"""
测试质量审计师 — 独立角色交叉审查生成的测试用例。

与 reviewer.py 的关键区别：
- reviewer: 事后修复（执行失败后根据错误日志改 YAML）
- auditor:  事前审查（生成后立即用批判视角审查，不依赖执行结果）

同一 DeepSeek 模型，不同 system prompt 角色隔离，模拟双人交叉审查。
"""

from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.llm_client import LLMClient
from src.logger import get_logger

logger = get_logger(__name__)

# 审计师角色：批判、挑剔、不信任生成结果
SYSTEM_PROMPT = (
    "你是一位独立测试质量审计师，你的职责是严格审查他人编写的测试用例质量。"
    "你与测试用例作者是同事关系，你必须对他的产出保持质疑——默认认为存在隐藏问题，"
    "需要逐条验证。只输出 JSON，不输出解释。"
)


def audit_yaml_cases(
    test_data_dir: str = "test_data",
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """对 test_data/ 下的 YAML 用例进行独立交叉审查。

    审查维度：
    1. 断言合理性 — status/body_fields 是否符合端点行为
    2. 边界覆盖 — 是否遗漏关键异常场景
    3. 鉴权正确性 — skip_auth/auth_header 是否合理
    4. ID 示例值 — 路径参数样例是否真实可用
    5. 冗余检测 — 是否有可合并的重复用例

    Returns:
        {"score": 85, "risk": "low", "issues": [...], "suggestions": [...]}
    """
    if client is None:
        client = LLMClient()

    data_dir = Path(test_data_dir)
    yaml_files = sorted(data_dir.glob("*.yaml"))
    if not yaml_files:
        logger.warning("未找到 YAML 测试数据")
        return {"score": 0, "risk": "high", "issues": [], "suggestions": []}

    yaml_contents = ""
    for yf in yaml_files:
        yaml_contents += f"\n--- {yf.name} ---\n{yf.read_text(encoding='utf-8')}"

    prompt = f"""你是独立测试质量审计师。请对以下自动生成的 YAML 测试用例进行严格审查。

## 被审查的测试用例
{yaml_contents[:8000]}

## 审查清单（逐条检查，不可跳过）

### 1. 断言合理性
- status 期望值是否与该端点的实际行为一致？（只读 GET 通常是 200，鉴权缺失是 401）
- body_fields 是否包含不稳定字段（如 popularity、genres、label、followers 等经常变化的字段）？
- body_types 的类型声明是否正确？

### 2. 边界覆盖
- 每个端点是否覆盖了：正向用例、无效参数、缺失必填字段、鉴权失败？(至少 3-4 个)
- 对于带路径参数的端点，是否有多条 ID 不同的有效用例？

### 3. 鉴权正确性
- skip_auth: true 的用例是否预期 401（无 token 场景）？
- 依赖用户 token 的端点（/me/*）, 是否全部标记了 skip？

### 4. ID 示例值
- path_params 中的 ID 是否看起来像是真实的 Spotify ID（22 位 base62 编码）？
- 是否都是同一两个 ID 在复用？缺少多样性？

### 5. 冗余检测
- 多个端点是否使用了完全相同的 case 组合（只是路径不同）？
- 异常用例中 [400, 403, 404] 范围是否过宽？能否更精确？

## 输出格式
只输出一个 JSON：
```json
{{
  "score": 85,
  "risk": "low",
  "summary": "一句话结论",
  "issues": [
    {{"severity": "high|medium|low", "file": "文件名", "case": "用例名", "problem": "问题描述", "suggestion": "修复建议", "auto_fixable": true}}
  ],
  "suggestions": ["改进建议1", "改进建议2"]
}}
```

score: 0-100 (100=完美, <60=不合格, 60-79=需改进, 80-100=合格)
risk: "low"|"medium"|"high"
auto_fixable: true 表示可通过脚本/LLM 自动修复（如补充缺失字段、调整状态码范围）；false 表示需要人工判断（如 API 行为不确定、需确认业务逻辑）
"""

    logger.info("审计师开始交叉审查 %d 个 YAML 文件...", len(yaml_files))

    result = client.chat_json(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,  # 稍高温度增加审查多样性
        max_tokens=4096,
    )

    score = result.get("score", 0)
    risk = result.get("risk", "unknown")
    issues = result.get("issues", [])
    suggestions = result.get("suggestions", [])

    logger.info("审计完成: score=%d, risk=%s, issues=%d", score, risk, len(issues))
    for issue in issues:
        sev = issue.get("severity", "?")
        fixable = "🤖" if issue.get("auto_fixable") else "👤"
        logger.warning("  [%s] %s %s/%s: %s", sev, fixable, issue.get("file", "?"), issue.get("case", "?"), issue.get("problem", ""))

    return result


def audit_stateful_code(
    code_path: str = "tests/test_stateful_workflows.py",
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """对生成的有状态测试代码进行独立审查。

    Returns:
        {"score": 85, "issues": [...], "suggestions": [...]}
    """
    if client is None:
        client = LLMClient()

    code_file = Path(code_path)
    if not code_file.exists():
        logger.warning("未找到有状态测试代码: %s", code_path)
        return {"score": 0, "issues": [], "suggestions": []}

    code = code_file.read_text(encoding="utf-8")

    prompt = f"""你是独立测试质量审计师。请审查以下自动生成的 pytest 有状态链路测试代码。

## 被审查的代码
```python
{code[:6000]}
```

## 审查清单
1. try/finally cleanup 是否正确覆盖所有写操作路径？
2. 断言范围（如 `in [400, 403, 404]`）是否过于宽松？
3. fixture 中硬编码的测试 ID 是否合理？
4. skip 标记的条件是否正确？
5. 是否有竞态条件风险（如多测试共享状态的 cleanup 冲突）？

## 输出格式
只输出一个 JSON：
```json
{{
  "score": 80,
  "summary": "一句话结论",
  "issues": [
    {{"severity": "high|medium|low", "method": "方法名", "problem": "问题", "suggestion": "建议", "auto_fixable": false}}
  ],
  "suggestions": []
}}
```
"""

    logger.info("审计师开始审查有状态测试代码...")

    result = client.chat_json(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )

    score = result.get("score", 0)
    logger.info("代码审计完成: score=%d", score)
    return result


def save_audit_report(
    yaml_result: dict[str, Any],
    code_result: dict[str, Any],
    output_dir: str = "reports",
) -> str:
    """将审计报告序列化到 reports/ 目录。"""
    reports_dir = Path(output_dir)
    reports_dir.mkdir(exist_ok=True)

    report = {
        "auditor": "双角色交叉审查 (DeepSeek 审计师模式)",
        "timestamp": datetime.now().isoformat(),
        "yaml_audit": yaml_result,
        "code_audit": code_result,
    }

    filepath = reports_dir / "audit_report.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("审计报告已保存: %s", filepath)
    return str(filepath)


FIX_SYSTEM_PROMPT = (
    "你是一位测试数据修复专家。请根据审计师发现的问题，精确修复 YAML 测试数据。"
    "只修改问题相关的字段，保持其余内容不变。只输出 YAML，不输出解释。"
)


def auto_fix(
    audit_report_path: str = "reports/audit_report.json",
    client: LLMClient | None = None,
    test_data_dir: str = "test_data",
    dry_run: bool = False,
) -> dict[str, Any]:
    """读取审计报告，自动修复标记为 auto_fixable 的 YAML 问题。

    流程：
    1. 读取 audit_report.json，筛选 auto_fixable: true 的问题
    2. 备份原 YAML → .bak
    3. 对每个受影响的文件，LLM 逐条修复
    4. 校验修复后 YAML 语法
    5. 输出 diff

    Returns:
        {"fixed": 3, "skipped": 2, "files_changed": ["albums.yaml"], ...}
    """
    if client is None:
        client = LLMClient()

    report_path = Path(audit_report_path)
    if not report_path.exists():
        logger.error("未找到审计报告: %s，请先运行 audit", audit_report_path)
        return {"fixed": 0, "skipped": 0, "files_changed": [], "error": "no_report"}

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    yaml_audit = report.get("yaml_audit", {})
    all_issues = yaml_audit.get("issues", [])

    # 筛选 auto_fixable 问题
    fixable = [i for i in all_issues if i.get("auto_fixable")]
    manual = [i for i in all_issues if not i.get("auto_fixable")]

    if not fixable:
        logger.info("没有可自动修复的问题")
        if manual:
            logger.info("有 %d 个需人工处理的问题 (👤)", len(manual))
        return {"fixed": 0, "skipped": len(manual), "files_changed": []}

    logger.info("可自动修复: %d 个, 需人工: %d 个", len(fixable), len(manual))

    # 按文件分组
    by_file: dict[str, list[dict[str, Any]]] = {}
    for issue in fixable:
        fname = issue.get("file", "unknown.yaml")
        by_file.setdefault(fname, []).append(issue)

    data_dir = Path(test_data_dir)
    fixed_count = 0
    failed_count = 0
    changed_files: list[str] = []

    for fname, issues in by_file.items():
        filepath = data_dir / fname
        if not filepath.exists():
            logger.warning("文件不存在: %s，跳过", fname)
            failed_count += len(issues)
            continue

        original = filepath.read_text(encoding="utf-8")

        # 备份
        backup_path = filepath.with_suffix(".yaml.bak")
        if not dry_run:
            shutil.copy(filepath, backup_path)
        logger.info("已备份: %s", backup_path)

        # 构建修复 prompt
        issues_text = ""
        for idx, issue in enumerate(issues, 1):
            issues_text += (
                f"{idx}. [{issue.get('severity')}] {issue.get('case', '?')}\n"
                f"   问题: {issue.get('problem')}\n"
                f"   建议: {issue.get('suggestion')}\n\n"
            )

        prompt = f"""请修复以下 YAML 测试数据文件中的 {len(issues)} 个问题。

## 当前 YAML
```yaml
{original[:8000]}
```

## 需要修复的问题
{issues_text}

## 修复要求
1. 只修改上述问题，保持其他行完全不变
2. 禁止删除任何端点 (path/method 块) 或测试用例 (case 块)，只能修改其内部字段
3. 如果某端点不属于当前文件，禁止删除——该问题是分类阶段的责任，不在修复范围内
4. 确保修复后的 YAML 语法正确
5. 输出完整的修复后 YAML 文件，不要省略任何内容
6. 不要输出解释文字，只输出 YAML

只输出 YAML："""

        logger.info("LLM 修复 %s 中的 %d 个问题...", fname, len(issues))
        try:
            fixed_yaml = client.chat(
                messages=[
                    {"role": "system", "content": FIX_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=8192,
            )

            # 清理 LLM 输出的 markdown 标记
            fixed_yaml = _clean_yaml_output(fixed_yaml)

            # 校验语法
            try:
                yaml.safe_load(fixed_yaml)
            except yaml.YAMLError as e:
                logger.error("修复后的 YAML 语法错误: %s，保留原文件", e)
                failed_count += len(issues)
                continue

            if not dry_run:
                filepath.write_text(fixed_yaml, encoding="utf-8")

            # 输出 diff
            logger.info("─── %s diff ───", fname)
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                fixed_yaml.splitlines(keepends=True),
                fromfile=f"{fname}.bak",
                tofile=fname,
            )
            for line in diff:
                logger.info(line.rstrip())

            fixed_count += len(issues)
            changed_files.append(fname)
            logger.info("✅ %s: %d 个问题已修复", fname, len(issues))

        except Exception as e:
            logger.error("修复 %s 失败: %s", fname, e)
            failed_count += len(issues)

    # 校验修复后仍能收集用例
    if changed_files and not dry_run:
        logger.info("校验修复后用例收集...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("用例收集失败！可通过 .bak 文件恢复:\n%s",
                           result.stderr[-300:])
        else:
            logger.info("用例收集通过 ✅")

    summary = {
        "fixed": fixed_count,
        "skipped": len(manual),
        "failed": failed_count,
        "files_changed": changed_files,
        "manual_issues_remaining": len(manual),
    }

    logger.info("修复完成: fixed=%d, skipped=%d, failed=%d",
                fixed_count, len(manual), failed_count)
    if manual:
        logger.info("还有 %d 个 👤 问题需人工处理，见审计报告", len(manual))
    if changed_files:
        logger.info("备份文件: %s", ", ".join(f + ".bak" for f in changed_files))

    return summary


def _clean_yaml_output(text: str) -> str:
    """清理 LLM 输出中的 markdown 标记。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```yaml 和结尾 ```
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return text.strip() + "\n"
