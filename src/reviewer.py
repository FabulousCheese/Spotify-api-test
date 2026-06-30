"""
LLM 测试专家 — 审查 YAML 测试用例质量，自动改进直至通过率达到阈值。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from src.llm_client import LLMClient
from src.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = "你是资深测试架构师。只输出 JSON，不输出解释。"


def run_tests() -> dict[str, Any]:
    """执行测试并解析结果，返回统计信息。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--tb=no", "-q",
         "--junitxml=reports/junit.xml"],
        capture_output=True, text=True, timeout=120,
    )
    passed = failed = skipped = 0
    m = re.search(r'(\d+)\s+failed', result.stdout)
    if m:
        failed = int(m.group(1))
    m = re.search(r'(\d+)\s+passed', result.stdout)
    if m:
        passed = int(m.group(1))
    m = re.search(r'(\d+)\s+skipped', result.stdout)
    if m:
        skipped = int(m.group(1))

    total = passed + failed
    pass_rate = round(passed / total * 100, 1) if total > 0 else 100
    return {
        "passed": passed, "failed": failed, "skipped": skipped,
        "total": total, "pass_rate": pass_rate,
        "stdout": result.stdout[-800:], "stderr": result.stderr[-300:],
    }


def review_and_improve(
    test_result: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    max_retries: int = 2,
    test_data_dir: str = "test_data",
) -> bool:
    """LLM 专家审查测试用例质量，自动改进直至达到 80% 通过率。

    Args:
        test_result: 初始测试结果 (不传则先执行一次)
        client: LLM 客户端
        max_retries: 最大审查轮数
        test_data_dir: YAML 测试数据目录

    Returns:
        是否达到通过率阈值
    """
    if client is None:
        client = LLMClient()

    if test_result is None:
        test_result = run_tests()

    history: list[dict[str, Any]] = []

    for attempt in range(1, max_retries + 1):
        logger.info("=" * 40)
        logger.info("第 %d/%d 轮 LLM 专家审查", attempt, max_retries)

        yaml_contents = ""
        data_dir = Path(test_data_dir)
        for yf in sorted(data_dir.glob("*.yaml")):
            yaml_contents += f"\n--- {yf.name} ---\n{yf.read_text(encoding='utf-8')}"

        prompt = f"""你是一位资深测试架构专家。请审查以下 YAML 测试用例，识别问题并输出改进后的 YAML。

## 当前测试结果
- 通过: {test_result['passed']} / 失败: {test_result['failed']} / 跳过: {test_result['skipped']}
- 通过率: {test_result['pass_rate']}%

## 当前问题
```
{test_result.get('stdout', '无')}
```

## 当前 YAML 测试用例
{yaml_contents[:6000]}

## 审查规则
1. body_fields 是否包含不稳定字段（如 popularity, label, genres 等 deprecated 字段）
2. status 断言是否合理（异常用数组 [400, 403, 404]）
3. 鉴权用例是否缺少 skip_auth: true 或 auth_header 字段
4. 是否有不可测试的用例（如 rate_limited/429）
5. 用例数量是否超标（普通端点 ≤5，deprecated ≤2）
6. ID 示例值是否合理
7. 如果失败用例是 403/401，添加 skip 标记

## 输出格式
只输出一个 JSON：
```json
{{
  "analysis": "一句话总结",
  "improved_files": [
    {{"filename": "albums.yaml", "content": "endpoints:\\n  - path: ..."}}
  ]
}}
```
"""
        review_data = client.chat_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=8192,
        )

        analysis = review_data.get("analysis", "无")
        improved = review_data.get("improved_files", [])
        logger.info("分析: %s", analysis)

        for f in improved:
            fname = f["filename"]
            content = f["content"]
            try:
                yaml.safe_load(content)
                (data_dir / fname).write_text(content, encoding="utf-8")
                logger.info("已更新: %s", fname)
            except yaml.YAMLError as e:
                logger.warning("%s YAML 无效: %s", fname, e)

        history.append({
            "attempt": attempt, "analysis": analysis,
            "pass_rate": test_result["pass_rate"],
        })

        logger.info("重新执行测试...")
        test_result = run_tests()
        logger.info("结果: %d passed, %d failed (%.1f%%)",
                    test_result["passed"], test_result["failed"],
                    test_result["pass_rate"])

        if test_result["pass_rate"] >= 80:
            _save_history(history, status="success")
            logger.info("通过率 %.1f%% ≥ 80%%，审查完成", test_result["pass_rate"])
            return True

    _save_history(history, status="failed")
    logger.warning("%d 轮审查后仍未达到 80%% 通过率", max_retries)
    return False


def _save_history(history: list[dict[str, Any]], status: str) -> None:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / "review_history.json").write_text(
        json.dumps({"status": status, "history": history}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
