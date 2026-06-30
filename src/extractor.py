"""
端点提取器 — 解析 OpenAPI YAML 规范，按 tag 分组、去重，输出 JSON。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from src.config import get_config
from src.logger import get_logger

logger = get_logger(__name__)

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def extract_endpoints(
    spec_path: str | None = None,
    target_tags: list[str] | None = None,
    output_path: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """从 OpenAPI 规范中提取端点，按 tag 分组去重。

    Args:
        spec_path: YAML 规范文件路径，默认从 config 读取
        target_tags: 目标 tag 列表
        output_path: JSON 输出路径

    Returns:
        {tag_name: [endpoint_dict, ...]} 的字典
    """
    cfg = get_config()
    spec_path = spec_path or cfg.spec_path
    target_tags = target_tags or ["Albums", "Artists"]
    output_path = output_path or cfg.extracted_path

    with open(spec_path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path, methods in spec.get("paths", {}).items():
        for method, detail in methods.items():
            if method not in HTTP_METHODS:
                continue
            for tag in detail.get("tags", []):
                by_tag[tag].append({
                    "method": method.upper(),
                    "path": path,
                    "operation_id": detail.get("operationId"),
                    "summary": detail.get("summary", "").strip(),
                    "deprecated": detail.get("deprecated", False),
                    "parameters": detail.get("parameters", []),
                    "responses": detail.get("responses", {}),
                })

    result: dict[str, list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()

    for tag in target_tags:
        deduped: list[dict[str, Any]] = []
        for ep in by_tag.get(tag, []):
            op_id = ep["operation_id"]
            if op_id in seen_ids:
                logger.info("跳过重复: %s %s (operationId: %s)", ep["method"], ep["path"], op_id)
                continue
            seen_ids.add(op_id)
            deduped.append(ep)

        result[tag] = deduped
        logger.info("%s: %d 个端点", tag, len(deduped))
        for ep in deduped:
            logger.debug("  %s %s — %s", ep["method"], ep["path"], ep["summary"])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("端点列表已保存: %s (共 %d 个端点)", output_path, len(seen_ids))

    return result
