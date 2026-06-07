"""
读取 extracted_endpoints.json，调用 LLM 对每个端点进行分类：
  - data_driven: 可用 YAML 驱动的纯读写端点
  - need_code:   需要代码编排的有状态/链路端点
"""
import json
import os
import yaml
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from openai import OpenAI

JSON_PATH = "extracted_endpoints.json"
YAML_PATH = "open-api-schema.yaml"

LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")


def load_endpoints():
    with open(JSON_PATH) as f:
        return json.load(f)


def build_classification_prompt(endpoints_by_tag: dict) -> str:
    """构建端点分类 Prompt"""

    # 构造端点清单文本
    endpoints_text = ""
    total = 0
    for tag, eps in endpoints_by_tag.items():
        endpoints_text += f"\n## {tag}\n"
        for ep in eps:
            total += 1
            deprecated = " [DEPRECATED]" if ep.get("deprecated") else ""
            endpoints_text += (
                f"  - {ep['method']} {ep['path']}"
                f" | operationId: {ep['operation_id']}"
                f" | summary: {ep['summary']}"
                f"{deprecated}\n"
            )

    prompt = f"""你是一个资深接口自动化测试架构师。请对以下 {total} 个 Spotify API 端点进行分类，
判断每个端点适合「YAML 数据驱动」还是「需要代码编排」。

{endpoints_text}

## 分类标准

### data_driven（YAML 驱动）
满足以下所有条件：
1. HTTP GET 方法（只读操作）
2. 不修改服务端状态（无副作用）
3. 不需要前置 setup（不依赖其他端点的创建操作）
4. 不需要后置 cleanup（不用撤销/恢复数据）
5. 单次请求即可验证，不涉及多步链路

### need_code（需要代码编排）
满足以下任一条件：
1. HTTP POST/PUT/PATCH/DELETE 方法（有写操作）
2. 会修改服务端状态（save/remove/follow/unfollow/add/delete 等）
3. 测试需要 setup 前置 → action → verify → teardown 链路
4. 与其他端点存在前后依赖关系（如: 先创建资源再校验再删除）
5. 需要动态生成测试数据（参数值依赖前一步返回结果）

## 输出要求

只输出一个 JSON 对象，不要有任何解释文字：

```json
{{
  "data_driven": [
    {{
      "tag": "Albums",
      "method": "GET",
      "path": "/albums/{{id}}",
      "operation_id": "get-an-album",
      "reason": "只读查询，无副作用，单次请求即可"
    }}
  ],
  "need_code": [
    {{
      "tag": "Albums",
      "method": "PUT",
      "path": "/me/albums",
      "operation_id": "save-albums-user",
      "reason": "PUT 写操作，修改用户状态，需要 cleanup 恢复"
    }}
  ]
}}
```

注意：
- reason 字段用中文简述分类理由，15字以内
- 每个端点都必须在两个数组之一中出现
- 只输出 JSON，不要 Markdown 标记
"""
    return prompt


def call_llm(prompt: str) -> dict:
    """调用 LLM 获取分类结果"""
    client = OpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)
    print(f"  → 调用 {LLM_MODEL} ...")

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是一个 API 测试架构分析师。请严格按照 JSON 格式返回结果，不要输出任何解释文字。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content.strip()

    # 清理可能的 markdown 包裹
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3]

    return json.loads(raw)


def main():
    print("=" * 60)
    print("API 端点分类器 (YAML驱动 vs 代码编排)")
    print("=" * 60)

    if not LLM_API_KEY:
        print("❌ 请在 .env 中设置 LLM_API_KEY")
        sys.exit(1)

    endpoints_by_tag = load_endpoints()
    total = sum(len(eps) for eps in endpoints_by_tag.values())
    print(f"共 {total} 个端点，{len(endpoints_by_tag)} 个标签")

    prompt = build_classification_prompt(endpoints_by_tag)

    # 保存 prompt
    os.makedirs("prompts", exist_ok=True)
    with open("prompts/prompt_classify.txt", "w", encoding="utf-8") as f:
        f.write(prompt)
    print("✓ Prompt 已保存: prompts/prompt_classify.txt")

    result = call_llm(prompt)

    # 保存分类结果
    output_path = "endpoint_classification.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # 统计
    dd = len(result.get("data_driven", []))
    nc = len(result.get("need_code", []))
    print(f"\n分类结果:")
    print(f"  data_driven (YAML驱动): {dd} 个")
    print(f"  need_code   (代码编排): {nc} 个")
    print(f"  已保存: {output_path}")

    # 打印 need_code 清单
    if result.get("need_code"):
        print(f"\n需要代码编排的端点:")
        for ep in result["need_code"]:
            print(f"  {ep['method']} {ep['path']}")
            print(f"    → {ep.get('reason', '')}")

    print(f"\n{'=' * 60}")
    print("完成！")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
