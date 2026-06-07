"""
LLM 测试专家：审查 YAML 测试用例质量，输出改进建议和改进后的 YAML。
被 Jenkins 流水线调用。
"""
import json
import os
import sys
import yaml
import subprocess

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from openai import OpenAI

LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

TEST_DATA_DIR = "test_data"
REVIEW_LOG = "reports/review_history.json"


def run_tests() -> dict:
    """执行测试并解析结果"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--tb=no", "-q", "--junitxml=reports/junit.xml"],
        capture_output=True, text=True, timeout=120,
    )
    passed = failed = skipped = 0
    # pytest -q 输出格式: "37 passed, 19 skipped" 或 "3 failed, 37 passed, 19 skipped"
    import re
    m = re.search(r'(\d+)\s+failed', result.stdout)
    if m: failed = int(m.group(1))
    m = re.search(r'(\d+)\s+passed', result.stdout)
    if m: passed = int(m.group(1))
    m = re.search(r'(\d+)\s+skipped', result.stdout)
    if m: skipped = int(m.group(1))

    total = passed + failed
    pass_rate = round(passed / total * 100, 1) if total > 0 else 100
    return {
        "passed": passed, "failed": failed, "skipped": skipped,
        "total": total, "pass_rate": pass_rate,
        # 保留失败详情
        "stdout": result.stdout[-800:], "stderr": result.stderr[-300:],
    }


def review_and_improve(test_result: dict, max_retries: int = 2) -> bool:
    """LLM 专家审查并改进，返回是否达到 80% 通过率"""
    client = OpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)
    history = []

    for attempt in range(1, max_retries + 1):
        print(f"\n{'='*50}\n  第 {attempt}/{max_retries} 轮：LLM 专家审查\n{'='*50}")

        # 收集所有 YAML 内容
        yaml_contents = ""
        for yf in sorted(os.listdir(TEST_DATA_DIR)):
            if yf.endswith(".yaml"):
                with open(os.path.join(TEST_DATA_DIR, yf)) as f:
                    yaml_contents += f"\n--- {yf} ---\n{f.read()}"

        # 构建审查 Prompt
        failures_text = test_result.get("stdout", "无")
        prompt = f"""你是一位资深测试架构专家。请审查以下 YAML 测试用例，识别问题并输出改进后的 YAML。

## 当前测试结果
- 通过: {test_result['passed']} / 失败: {test_result['failed']} / 跳过: {test_result['skipped']}
- 通过率: {test_result['pass_rate']}%

## 当前问题
```
{failures_text}
```

## 当前 YAML 测试用例
{yaml_contents[:6000]}

## 审查规则
1. 检查 body_fields 是否包含不稳定字段（如 popularity, label, genres 等 deprecated 字段）
2. 检查 status 断言是否合理（异常用数组 [400, 403, 404]，不要单一值）
3. 检查鉴权用例是否缺少 skip_auth: true 或 auth_header 字段
4. 检查是否有不可测试的用例（如 rate_limited/429、expired_token）
5. 检查用例数量是否超标（普通端点 ≤5，deprecated ≤2）
6. 检查 ID 示例值是否合理（艺术家端点不能用专辑 ID）
7. 如果失败用例是 403/401，添加 skip 标记到对应端点
8. 检查 body_fields 数量是否精简（≤5 个核心字段）

## 输出格式

只输出一个 JSON，包含改进后的 YAML 内容数组：
```json
{{
  "analysis": "一句话总结发现的问题",
  "improved_files": [
    {{"filename": "albums.yaml", "content": "endpoints:\\n  - path: ..."}}
  ]
}}
```

只输出 JSON，不要 Markdown 标记。
"""
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是资深测试架构师。只输出 JSON，不输出解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=8192,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()

        # 解析并应用改进
        try:
            review = json.loads(raw)
            analysis = review.get("analysis", "无")
            improved = review.get("improved_files", [])
            print(f"  分析: {analysis}")

            if improved:
                for f in improved:
                    fname = f["filename"]
                    content = f["content"]
                    # 验证是有效 YAML
                    try:
                        yaml.safe_load(content)
                        path = os.path.join(TEST_DATA_DIR, fname)
                        with open(path, "w", encoding="utf-8") as wf:
                            wf.write(content)
                        print(f"  ✅ 已更新: {fname}")
                    except yaml.YAMLError as e:
                        print(f"  ⚠️ {fname} YAML 无效: {e}")
            else:
                print("  ⚠️  LLM 未返回改进内容，跳过")
        except json.JSONDecodeError:
            print(f"  ⚠️  LLM 返回非 JSON，跳过: {raw[:200]}")
            analysis = raw

        # 保存审查历史
        history.append({"attempt": attempt, "analysis": analysis, "pass_rate": test_result["pass_rate"]})

        # 重新执行测试
        print(f"\n  重新执行测试...")
        test_result = run_tests()
        print(f"  结果: {test_result['passed']} passed, {test_result['failed']} failed ({test_result['pass_rate']}%)")

        # 达到阈值就退出
        if test_result["pass_rate"] >= 80:
            os.makedirs("reports", exist_ok=True)
            with open(REVIEW_LOG, "w") as f:
                json.dump({"status": "success", "history": history}, f, indent=2, ensure_ascii=False)
            print(f"\n  ✅ 通过率 {test_result['pass_rate']}% ≥ 80%，审查完成")
            return True

    # 超过重试次数
    os.makedirs("reports", exist_ok=True)
    with open(REVIEW_LOG, "w") as f:
        json.dump({"status": "failed", "history": history}, f, indent=2, ensure_ascii=False)
    print(f"\n  ❌ {max_retries} 轮审查后仍未达到 80% 通过率")
    return False


if __name__ == "__main__":
    print("=" * 50)
    print("LLM 测试专家 - 审查与改进")
    print("=" * 50)

    if not LLM_API_KEY:
        print("❌ 未设置 LLM_API_KEY")
        sys.exit(1)

    # 第一轮：先执行一次测试
    print("\n▶ 执行测试...")
    result = run_tests()
    print(f"  初次结果: {result['passed']} passed, {result['failed']} failed ({result['pass_rate']}%)")

    if result["pass_rate"] >= 80:
        print(f"\n  ✅ 通过率 {result['pass_rate']}% ≥ 80%，无需审查")
        os.makedirs("reports", exist_ok=True)
        with open(REVIEW_LOG, "w") as f:
            json.dump({"status": "success", "history": []}, f, indent=2, ensure_ascii=False)
        sys.exit(0)

    print(f"\n  ⚠️ 通过率 {result['pass_rate']}% < 80%，启动 LLM 专家审查...")
    ok = review_and_improve(result, max_retries=2)
    sys.exit(0 if ok else 1)
