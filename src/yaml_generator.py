"""
YAML 测试数据生成器 — 为 data_driven 端点调用 LLM 生成 YAML 测试用例文件。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.llm_client import LLMClient
from src.logger import get_logger
from src.ref_resolver import RefResolver, build_endpoint_info

logger = get_logger(__name__)

SYSTEM_PROMPT = "你是 API 测试数据工程师，严格按照 YAML 格式输出，不要输出任何解释文字。"


def build_yaml_generation_prompt(ep_class: dict[str, Any], ep_full: dict[str, Any]) -> str:
    """为单个端点构建 YAML 生成 Prompt。"""
    params_text = ""
    for p in ep_full["parameters"]:
        required_mark = "必填" if p["required"] else "可选"
        params_text += f"  - `{p['name']}` ({p['in']}, {p['type']}) [{required_mark}]"
        if p.get("example"):
            params_text += f" | 示例: {p['example']}"
        if p.get("enum"):
            params_text += f" | 可选值: {p['enum']}"
        if p.get("description"):
            desc = str(p["description"])[:150].replace("\n", " ")
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

    return f"""你是 API 测试数据工程师。请为以下端点生成 YAML 格式的测试用例。

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
      - name: valid_case
        description: 正向：xxx
        path_params:
          id: "4aawyAB9vmqN3uQ7FjRGTy"
        query_params: {{}}
        expect:
          status: 200
          body_fields: [id, name, type, uri]
          body_types:
            id: string
            name: string

      - name: missing_required
        description: 异常：缺少必填参数
        path_params: {{}}
        query_params: {{}}
        expect:
          status: [400, 403, 404]

      - name: invalid_param
        description: 异常：无效的id值
        path_params:
          id: "invalid_id_123"
        query_params: {{}}
        expect:
          status: [400, 403, 404]

      - name: no_token
        description: 鉴权：无认证token
        skip_auth: true
        path_params:
          id: "4aawyAB9vmqN3uQ7FjRGTy"
        query_params: {{}}
        expect:
          status: 401

      - name: invalid_token
        description: 鉴权：无效token
        auth_header: "Bearer invalid_token_12345"
        path_params:
          id: "4aawyAB9vmqN3uQ7FjRGTy"
        query_params: {{}}
        expect:
          status: 401
```

## 严格规则

- 正常端点最多 5 个用例，deprecated 端点最多 2 个
- body_fields 最多 5 个核心字段
- 成功状态码用单一值，异常用数组 [400, 403, 404]
- 鉴权用例必须加 skip_auth: true 或 auth_header 字段
- 禁止生成 429 rate_limited 用例
- 只输出 YAML，不输出解释
"""


def generate_yaml_for_tag(
    tag: str,
    endpoints: list[dict[str, Any]],
    resolver: RefResolver,
    client: LLMClient,
    output_dir: str = "test_data",
) -> None:
    """为同一 tag 下的所有 data_driven 端点生成一个合并的 YAML 文件。"""
    all_endpoints: list[dict[str, Any]] = []

    for ep_class in endpoints:
        ep_raw: dict[str, Any] = {
            "method": ep_class["method"],
            "path": ep_class["path"],
            "operation_id": ep_class["operation_id"],
            "summary": ep_class.get("summary", ""),
            "parameters": [],
            "responses": {},
        }

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

        logger.info("生成 %s %s ...", ep_class["method"], ep_class["path"])
        prompt = build_yaml_generation_prompt(ep_class, ep_full)

        raw_yaml = client.chat_yaml(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4096,
        )

        try:
            parsed = yaml.safe_load(raw_yaml)
            if isinstance(parsed, dict) and "endpoints" in parsed:
                all_endpoints.extend(parsed["endpoints"])
            else:
                all_endpoints.append(parsed)
        except yaml.YAMLError:
            all_endpoints.append({
                "path": ep_class["path"],
                "method": ep_class["method"],
                "_raw": raw_yaml,
            })

    combined = yaml.dump(
        {"endpoints": all_endpoints},
        indent=2,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True)
    filepath = out_dir / f"{tag.lower()}.yaml"
    if filepath.exists():
        backup = filepath.with_suffix(f".yaml.bak.{datetime.now():%Y%m%d_%H%M%S}")
        filepath.rename(backup)
        logger.info("已备份: %s", backup)
    filepath.write_text(combined, encoding="utf-8")
    logger.info("已保存: %s", filepath)


def generate_yaml_cases(
    data_driven_endpoints: list[dict[str, Any]],
    spec: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    output_dir: str = "test_data",
    spec_path: str | None = None,
) -> None:
    """为所有 data_driven 端点生成 YAML 测试数据。

    Args:
        data_driven_endpoints: 来自 endpoint_classification.json 的 data_driven 列表
        spec: 已解析的 OpenAPI spec (可选，不传则从文件加载)
        client: LLM 客户端
        output_dir: YAML 输出目录
        spec_path: YAML 规范路径 (不传则从 config 读取)
    """
    from src.config import get_config

    if client is None:
        client = LLMClient()
    if spec is None:
        spec_path = spec_path or get_config().spec_path
        with open(spec_path, encoding="utf-8") as f:
            spec = yaml.safe_load(f)

    resolver = RefResolver(spec)

    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ep in data_driven_endpoints:
        by_tag[ep["tag"]].append(ep)

    for tag, eps in by_tag.items():
        logger.info("处理 %s (%d 个端点)", tag, len(eps))
        generate_yaml_for_tag(tag, eps, resolver, client, output_dir)

    logger.info("YAML 文件已保存到: %s/", output_dir)
