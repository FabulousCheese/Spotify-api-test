"""
OpenAPI $ref 引用递归解析引擎。

Spotify 的 OpenAPI 规范大量使用 $ref 来复用 schema 定义，LLM 无法理解。
本模块将所有引用展开为内联定义，最多展开深度由 Config.max_resolve_depth 控制。
"""

from __future__ import annotations

from typing import Any

from src.config import get_config

DEFAULT_MAX_DEPTH = 3


class RefResolver:
    """递归解析 OpenAPI 规范中的 `$ref` 引用。"""

    def __init__(self, spec: dict[str, Any], max_depth: int | None = None) -> None:
        self.spec = spec
        self.max_depth = max_depth or get_config().max_resolve_depth or DEFAULT_MAX_DEPTH
        self._cache: dict[str, Any] = {}

    def resolve(self, obj: Any, depth: int = 0) -> Any:
        """递归展开所有 $ref 引用为内联定义。

        Args:
            obj: 待展开的对象 (dict/list/str/...)
            depth: 当前递归深度

        Returns:
            展开后的对象。超深度时返回截断提示字符串。
        """
        if depth > self.max_depth:
            return f"...(嵌套太深，已截断 at depth {depth})"

        if isinstance(obj, dict):
            # dict 只有一个 $ref 键 → 直接替换
            if list(obj.keys()) == ["$ref"]:
                return self._resolve_ref(obj["$ref"], depth)
            return {k: self.resolve(v, depth) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self.resolve(item, depth) for item in obj]

        return obj

    def _resolve_ref(self, ref_path: str, depth: int) -> Any:
        """根据 $ref 路径在 spec 中查找并递归展开。"""
        if ref_path in self._cache:
            return self.resolve(self._cache[ref_path], depth + 1)

        if not ref_path.startswith("#/"):
            return {"_error": f"暂不支持外部引用: {ref_path}"}

        parts = ref_path[2:].split("/")
        current: Any = self.spec
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return {"_error": f"无法解析路径: {ref_path} at /{part}"}

        if current is None:
            return {"_error": f"未找到定义: {ref_path}"}

        self._cache[ref_path] = current
        return self.resolve(current, depth + 1)


def build_endpoint_info(ep: dict[str, Any], resolver: RefResolver) -> dict[str, Any]:
    """对单个端点做完整 $ref 展开，提取 LLM 可读的结构化信息。

    Args:
        ep: 原始端点字典 (来自 extracted_endpoints.json)
        resolver: RefResolver 实例

    Returns:
        包含 method/path/operation_id/summary/deprecated/parameters/responses 的 dict
    """
    cfg = get_config()

    params_resolved: list[dict[str, Any]] = []
    for p in ep.get("parameters", []):
        resolved = resolver.resolve(p)

        if cfg.skip_optional_params and not resolved.get("required", False):
            continue

        schema = resolved.get("schema", {})
        params_resolved.append({
            "name": resolved.get("name", "?"),
            "in": resolved.get("in", "?"),
            "required": resolved.get("required", False),
            "type": schema.get("type", "?"),
            "description": schema.get("description", resolved.get("description", "")),
            "example": schema.get("example", None),
            "default": schema.get("default", None),
            "enum": schema.get("enum", None),
        })

    responses_resolved: dict[str, dict[str, Any]] = {}
    for status_code, resp in ep.get("responses", {}).items():
        resolved = resolver.resolve(resp)
        schema_info = None
        if "content" in resolved:
            for _ct, content_body in resolved.get("content", {}).items():
                if "schema" in content_body:
                    schema_info = content_body["schema"]
                break
        responses_resolved[status_code] = {
            "description": resolved.get("description", ""),
            "schema": schema_info,
        }

    return {
        "method": ep["method"],
        "path": ep["path"],
        "operation_id": ep["operation_id"],
        "summary": ep.get("summary", ""),
        "deprecated": ep.get("deprecated", False),
        "parameters": params_resolved,
        "responses": responses_resolved,
    }
