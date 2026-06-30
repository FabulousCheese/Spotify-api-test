"""RefResolver 单元测试 — $ref 解析、嵌套、截断、错误处理。"""

import pytest

from src.ref_resolver import RefResolver, build_endpoint_info


class TestBasicResolve:
    """基本 $ref 解析"""

    def test_simple_ref_resolve(self, minimal_spec):
        """$ref 指向简单类型应该被替换为内联定义"""
        resolver = RefResolver(minimal_spec)
        # ArtistId schema: {"type": "string", "example": "..."}
        result = resolver.resolve({"$ref": "#/components/schemas/ArtistId"})
        assert result == {"type": "string", "example": "0TnOYISbd1XYRBk9myaseg"}

    def test_object_ref_resolve(self, minimal_spec):
        """$ref 指向 object schema 应该递归展开"""
        resolver = RefResolver(minimal_spec)
        result = resolver.resolve({"$ref": "#/components/schemas/AlbumObject"})
        assert result["type"] == "object"
        assert result["properties"]["id"]["type"] == "string"
        # artists.items 是 $ref → ArtistObject，应该被递归展开
        artists_items = result["properties"]["artists"]["items"]
        assert artists_items["type"] == "object"
        assert "name" in artists_items["properties"]

    def test_nested_ref_resolve(self, minimal_spec):
        """嵌套 $ref（三层：AlbumObject → ArtistObject → ExternalUrls）"""
        resolver = RefResolver(minimal_spec)
        result = resolver.resolve({"$ref": "#/components/schemas/AlbumObject"})
        artist_props = result["properties"]["artists"]["items"]["properties"]
        # external_urls 是 $ref，应该被展开
        ext_urls = artist_props["external_urls"]
        assert ext_urls["type"] == "object"
        assert "spotify" in ext_urls["properties"]

    def test_response_ref_resolve(self, minimal_spec):
        """$ref 指向 responses 定义"""
        resolver = RefResolver(minimal_spec)
        result = resolver.resolve({"$ref": "#/components/responses/Unauthorized"})
        assert result["description"] == "Unauthorized"
        assert "application/json" in result["content"]


class TestCacheAndDedup:
    """缓存和去重"""

    def test_cache_reuse(self, minimal_spec):
        """同一个 $ref 多次解析应该命中缓存"""
        resolver = RefResolver(minimal_spec)
        # 两次解析同一个 ref
        resolver.resolve({"$ref": "#/components/schemas/ArtistId"})
        assert "#/components/schemas/ArtistId" in resolver._cache

        # 第二次应该直接从缓存读取
        result = resolver.resolve({"$ref": "#/components/schemas/ArtistId"})
        assert result == {"type": "string", "example": "0TnOYISbd1XYRBk9myaseg"}


class TestDepthLimit:
    """深度限制"""

    def test_depth_limit_truncation(self, minimal_spec):
        """循环引用超过 max_depth 应该截断"""
        resolver = RefResolver(minimal_spec, max_depth=2)
        result = resolver.resolve({"$ref": "#/components/schemas/CircularA"})
        # 应该包含截断提示
        props = result.get("properties", {})
        child = props.get("child", {})
        child_props = child.get("properties", {})
        parent = child_props.get("parent", {})
        # parent 再次指向 CircularA，但因为深度限制应该被截断
        assert isinstance(parent, str) and "截断" in parent

    def test_default_max_depth(self, minimal_spec):
        """默认深度限制从 config 读取（在测试环境为3）"""
        resolver = RefResolver(minimal_spec)
        assert resolver.max_depth == 3


class TestErrorHandling:
    """错误处理"""

    def test_external_ref(self, minimal_spec):
        """外部引用返回错误信息"""
        resolver = RefResolver(minimal_spec)
        result = resolver.resolve({"$ref": "https://example.com/schema.json"})
        assert result["_error"] == "暂不支持外部引用: https://example.com/schema.json"

    def test_invalid_path(self, minimal_spec):
        """无效路径返回错误信息"""
        resolver = RefResolver(minimal_spec)
        result = resolver.resolve({"$ref": "#/components/does_not_exist"})
        assert "_error" in result
        assert "未找到定义" in result["_error"]

    def test_broken_path(self, minimal_spec):
        """路径中间不匹配"""
        resolver = RefResolver(minimal_spec)
        result = resolver.resolve({"$ref": "#/invalid/schemas/ArtistId"})
        assert "_error" in result


class TestBuildEndpointInfo:
    """build_endpoint_info 函数"""

    def test_basic_endpoint_info(self, minimal_spec):
        """基本端点信息构建"""
        resolver = RefResolver(minimal_spec)
        ep = {
            "method": "GET",
            "path": "/artists/{id}",
            "operation_id": "get-an-artist",
            "summary": "Get an artist",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"$ref": "#/components/schemas/ArtistId"},
                }
            ],
            "responses": {
                "200": {
                    "description": "Successful",
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/ArtistObject",
                            }
                        }
                    },
                },
            },
        }

        info = build_endpoint_info(ep, resolver)
        assert info["method"] == "GET"
        assert info["path"] == "/artists/{id}"
        assert len(info["parameters"]) == 1
        assert info["parameters"][0]["name"] == "id"
        assert info["parameters"][0]["type"] == "string"
        assert "200" in info["responses"]

    def test_skip_optional_params(self, minimal_spec):
        """可选参数被跳过时不应出现在结果中"""
        resolver = RefResolver(minimal_spec)
        ep = {
            "method": "GET",
            "path": "/artists/{id}",
            "operation_id": "get-an-artist",
            "summary": "Get an artist",
            "parameters": [
                {
                    "name": "market",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                },
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
            "responses": {},
        }

        info = build_endpoint_info(ep, resolver)
        param_names = [p["name"] for p in info["parameters"]]
        assert "id" in param_names
        assert "market" not in param_names  # 可选参数被跳过

    def test_no_params(self, minimal_spec):
        """无参数端点"""
        resolver = RefResolver(minimal_spec)
        ep = {
            "method": "GET",
            "path": "/albums/{id}",
            "operation_id": "get-an-album",
            "summary": "Get an album",
            "parameters": [],
            "responses": {},
        }

        info = build_endpoint_info(ep, resolver)
        assert info["parameters"] == []
