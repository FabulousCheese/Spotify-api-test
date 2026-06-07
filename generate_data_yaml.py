"""
根据 endpoint_classification.json 中的 data_driven 端点，
调用 LLM 为每个端点生成 YAML 测试用例文件。
"""
import json
import os
import sys
import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from openai import OpenAI

# 复用 generate_tests 里的 RefResolver
from generate_tests import RefResolver, build_endpoint_info, SKIP_OPTIONAL_PARAMS

SPEC_PATH = "open-api-schema.yaml"
CLASSIFY_PATH = "endpoint_classification.json"
OUTPUT_DIR = "test_data"

LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")


def load_data_driven_endpoints() -> list[dict]:
    """读取分类结果，提取 data_driven 端点"""
    with open(CLASSIFY_PATH) as f:
        data = json.load(f)
    return data.get("data_driven", [])


def build_yaml_generation_prompt(
    ep_class: dict,
    ep_full: dict,
) -> str:
    """
    为单个端点构建 YAML 生成 Prompt。
    ep_class: 来自 endpoint_classification.json
    ep_full:  来自 build_endpoint_info 的展开后信息
    """

    params_text = ""
    for p in ep_full["parameters"]:
        required_mark = "必填" if p["required"] else "可选"
        params_text += (
            f"  - `{p['name']}` ({p['in']}, {p['type']}) [{required_mark}]"
        )
        if p.get("example"):
            params_text += f" | 示例: {p['example']}"
        if p.get("enum"):
            params_text += f" | 可选值: {p['enum']}"
        if p.get("description"):
            desc = p["description"][:150].replace("\n", " ")
            params_text += f" | {desc}"
        params_text += "\n"

    responses_text = ""
    for status, resp in ep_full["responses"].items():
        responses_text += f"  - `{status}`: {resp['description']}\n"
        if resp.get("schema"):
            schema_str = json.dumps(resp["schema"], indent=4, ensure_ascii=False)
            if len(schema_str) > 600:
                schema_str = schema_str[:600] + "\n    ...(已截断)"
            responses_text += f"    schema:\n{schema_str}\n"

    deprecated_note = ""
    if ep_full.get("deprecated"):
        deprecated_note = "\n⚠️ 此端点已废弃，只生成 1 个正向测试 + 1 个鉴权测试即可。"

    prompt = f"""你是 API 测试数据工程师。请为以下端点生成 YAML 格式的测试用例。

## 端点信息
- method: {ep_full['method']}
- path: {ep_full['path']}
- operation_id: {ep_full['operation_id']}
- summary: {ep_full['summary']}
{deprecated_note}

## 参数定义
{params_text}

## 返回值
{responses_text}

## YAML 输出格式

只输出一个完整的 YAML 块，用 ```yaml 包裹。**必须严格按照以下结构**：

```yaml
endpoints:
  - path: {ep_full['path']}
    method: {ep_full['method']}
    operation_id: {ep_full['operation_id']}
    cases:
      - name: valid_case             # 正向用例
        description: 正向：xxx
        path_params:
          id: "4aawyAB9vmqN3uQ7FjRGTy"  # TODO: 需替换为真实可用ID
        query_params: {{}}
        expect:
          status: 200
          body_fields: [id, name, type, uri]
          body_types:
            id: string
            name: string
            type: string
            artists: list

      - name: missing_required       # 异常：缺必填参数
        description: 异常：缺少必填参数
        path_params: {{}}
        query_params: {{}}
        expect:
          status: [400, 403, 404]

      - name: invalid_param          # 异常：无效参数值
        description: 异常：无效的id值
        path_params:
          id: "invalid_id_123"
        query_params: {{}}
        expect:
          status: [400, 403, 404]

      - name: no_token               # 鉴权：无token（必须有 skip_auth: true）
        description: 鉴权：无认证token
        skip_auth: true              # ← 必须写这个字段！
        path_params:
          id: "4aawyAB9vmqN3uQ7FjRGTy"
        query_params: {{}}
        expect:
          status: 401

      - name: invalid_token          # 鉴权：无效token（必须有 auth_header）
        description: 鉴权：无效token
        auth_header: "Bearer invalid_token_12345"  # ← 必须写这个字段！
        path_params:
          id: "4aawyAB9vmqN3uQ7FjRGTy"
        query_params: {{}}
        expect:
          status: 401
```

## 严格规则（必须遵守）

### 用例数量（每个 endpoint）
- **正常端点**: 最多 5 个用例
  - 1 个正向（核心字段）
  - 1 个异常（缺必填参数）
  - 1 个异常（无效参数值，如有字符串ID则测试）
  - 2 个鉴权（skip_auth + invalid_token）
- **deprecated 端点**: 最多 2 个用例（1正向 + 1鉴权skip_auth）
- **禁止生成**: rate_limited（429）、expired_token、forbidden_access 用例

### body_fields 规则
- 只列出核心标识字段（id, name, type, uri, href 等），最多 5 个
- **不要**列出文档标注 deprecated 的字段（如 label, popularity, genres）
- 数组端点只列容器字段（如 albums, artists, items, tracks）

### body_types 规则
- 基础类型用小写: string / int / float / bool / list / object
- 嵌套类型用点号: `album.artists` → list, `track.id` → string
- 每个 endpoint 最多 5 个 type 断言

### 鉴权用例规则（最严格）
- `no_token` 用例：**必须在 case 中添加 `skip_auth: true` 字段**，缺了这个字段就等于带 token 请求，测试会失败
- `invalid_token` 用例：**必须在 case 中添加 `auth_header: "Bearer invalid_token_12345"` 字段**
- 这两个字段是 YAML 字段名，不是注释，必须出现在 case 的 dict 中

### status 规则
- 成功统一用单一值: `200` / `204`
- 异常统一用数组: `[400, 403, 404]`
- 401 鉴权用单一值: `401`
- **禁止用 `429`**

### 边界测试规则
- 仅当参数有明确的 min/max 限制（如 limit: 1-50）时才加边界用例
- 边界用例最多 2 个（最小值 + 最大值）
```
"""
    return prompt


def generate_yaml_for_tag(tag: str, endpoints: list[dict], resolver: RefResolver, client: OpenAI):
    """为同一 tag 下的所有 data_driven 端点生成一个 YAML 文件（合并到一个 ``endpoints`` 列表中）"""
    all_endpoints = []

    for ep_class in endpoints:
        ep_raw = {
            "method": ep_class["method"],
            "path": ep_class["path"],
            "operation_id": ep_class["operation_id"],
            "summary": ep_class.get("summary", ""),
            "parameters": [],
            "responses": {},
        }

        # 从 spec 中查找端点参数定义
        for path, methods in resolver.spec.get("paths", {}).items():
            if path == ep_class["path"]:
                for method_name, detail in methods.items():
                    if method_name.upper() == ep_class["method"].upper():
                        ep_raw["parameters"] = detail.get("parameters", [])
                        ep_raw["responses"] = detail.get("responses", {})
                        ep_raw["deprecated"] = detail.get("deprecated", False)
                        ep_raw["summary"] = detail.get("summary", "").strip()
                        break
                break

        ep_full = build_endpoint_info(ep_raw, resolver)

        print(f"  → 生成 {ep_class['method']} {ep_class['path']} ...")
        prompt = build_yaml_generation_prompt(ep_class, ep_full)

        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "你是 API 测试数据工程师，严格按照 YAML 格式输出，不要输出任何解释文字。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4096,
        )
        raw = response.choices[0].message.content.strip()

        # 提取 YAML 内容
        if "```yaml" in raw:
            raw = raw.split("```yaml", 1)[1]
            if "```" in raw:
                raw = raw.split("```", 1)[0]
        elif "```" in raw:
            raw = raw.split("```", 1)[1]
            if "```" in raw:
                raw = raw.split("```", 1)[0]

        # 解析 YAML，取 endpoints 列表里的元素
        try:
            parsed = yaml.safe_load(raw)
            if isinstance(parsed, dict) and "endpoints" in parsed:
                all_endpoints.extend(parsed["endpoints"])
            else:
                all_endpoints.append(parsed)
        except yaml.YAMLError:
            all_endpoints.append({"path": ep_class["path"], "method": ep_class["method"], "_raw": raw})

    # 合并为一个 endpoints 列表
    combined = yaml.dump(
        {"endpoints": all_endpoints},
        indent=2,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )

    filepath = os.path.join(OUTPUT_DIR, f"{tag.lower()}.yaml")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(combined)
    print(f"  ✓ 已保存: {filepath}")


def main():
    print("=" * 60)
    print("YAML 测试数据生成器 (data_driven 端点)")
    print("=" * 60)

    if not LLM_API_KEY:
        print("❌ 请在 .env 中设置 LLM_API_KEY")
        sys.exit(1)

    # 加载分类结果
    dd_endpoints = load_data_driven_endpoints()
    print(f"共 {len(dd_endpoints)} 个 data_driven 端点")

    # 加载 YAML spec
    with open(SPEC_PATH) as f:
        spec = yaml.safe_load(f)
    resolver = RefResolver(spec)

    client = OpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)

    # 按 tag 分组
    from collections import defaultdict
    by_tag = defaultdict(list)
    for ep in dd_endpoints:
        by_tag[ep["tag"]].append(ep)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for tag, eps in by_tag.items():
        print(f"\n📦 处理 {tag} ({len(eps)} 个端点)")
        generate_yaml_for_tag(tag, eps, resolver, client)

    print(f"\n{'=' * 60}")
    print("完成！")
    print(f"YAML 文件已保存到: {OUTPUT_DIR}/")
    print(f"\n运行: python -m pytest tests/test_data_driven.py -v")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
