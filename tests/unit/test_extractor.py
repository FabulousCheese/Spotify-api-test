"""Extractor 单元测试 — 端点提取、去重、tag过滤。"""

import json
import tempfile
from pathlib import Path

import yaml
import pytest

from src.extractor import extract_endpoints


@pytest.fixture
def temp_spec_file():
    """创建临时 OpenAPI 规范文件"""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0"},
        "paths": {
            "/artists/{id}": {
                "get": {
                    "operationId": "get-an-artist",
                    "summary": "Get an artist",
                    "tags": ["Artists"],
                },
            },
            "/albums/{id}": {
                "get": {
                    "operationId": "get-an-album",
                    "summary": "Get an album",
                    "tags": ["Albums"],
                },
            },
            "/albums/{id}/tracks": {
                "get": {
                    "operationId": "get-an-albums-tracks",
                    "summary": "Get album tracks",
                    "tags": ["Albums"],
                },
            },
            "/me/albums": {
                "put": {
                    "operationId": "save-albums-user",
                    "summary": "Save albums",
                    "tags": ["Albums"],
                },
                "delete": {
                    "operationId": "remove-albums-user",
                    "summary": "Remove albums",
                    "tags": ["Albums"],
                },
            },
            "/me/following": {
                "put": {
                    "operationId": "follow-artists-users",
                    "summary": "Follow artists",
                    "tags": ["Artists"],
                },
                "get": {
                    "operationId": "get-followed",
                    "summary": "Get followed artists",
                    "tags": ["Artists"],
                },
            },
            # 跨 tag 重复的端点
            "/artists/{id}/albums": {
                "get": {
                    "operationId": "get-an-artists-albums",
                    "summary": "Get artist albums",
                    "tags": ["Albums", "Artists"],
                },
            },
            # 不在目标 tag 中的端点
            "/tracks/{id}": {
                "get": {
                    "operationId": "get-a-track",
                    "summary": "Get a track",
                    "tags": ["Tracks"],
                },
            },
        },
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(spec, f)
        spec_path = f.name

    yield spec_path
    Path(spec_path).unlink(missing_ok=True)


class TestExtraction:
    """基本提取功能"""

    def test_extract_by_tags(self, temp_spec_file, tmp_path):
        """按 tag 分组提取端点"""
        output = str(tmp_path / "output.json")
        result = extract_endpoints(
            spec_path=temp_spec_file,
            target_tags=["Albums", "Artists"],
            output_path=output,
        )

        assert "Albums" in result
        assert "Artists" in result
        # Tracks 不在目标列表
        assert "Tracks" not in result

    def test_dedup_across_tags(self, temp_spec_file, tmp_path):
        """跨 tag 重复的端点只出现在第一个匹配 tag 中"""
        output = str(tmp_path / "output.json")
        result = extract_endpoints(
            spec_path=temp_spec_file,
            target_tags=["Albums", "Artists"],
            output_path=output,
        )

        # get-an-artists-albums 同时有 Albums 和 Artists tag
        # 因为 Albums 在 target_tags 里排第一，应该归入 Albums
        albums_ops = [ep["operation_id"] for ep in result["Albums"]]
        artists_ops = [ep["operation_id"] for ep in result["Artists"]]

        assert "get-an-artists-albums" in albums_ops
        assert "get-an-artists-albums" not in artists_ops

    def test_skips_non_http_methods(self, temp_spec_file, tmp_path):
        """非标准 HTTP 方法被跳过"""
        # 规范里只有 get/put/delete，没有 patch/post
        output = str(tmp_path / "output.json")
        result = extract_endpoints(
            spec_path=temp_spec_file,
            target_tags=["Albums", "Artists"],
            output_path=output,
        )

        all_ops = []
        for eps in result.values():
            for ep in eps:
                all_ops.append(ep["method"])
        assert all(m in ["GET", "PUT", "DELETE"] for m in all_ops)

    def test_output_file_written(self, temp_spec_file, tmp_path):
        """输出文件正确写入"""
        output = str(tmp_path / "output.json")
        extract_endpoints(
            spec_path=temp_spec_file,
            target_tags=["Albums"],
            output_path=output,
        )

        with open(output) as f:
            data = json.load(f)
        assert "Albums" in data
        assert len(data["Albums"]) > 0

    def test_single_tag_filter(self, temp_spec_file, tmp_path):
        """单 tag 过滤"""
        output = str(tmp_path / "output.json")
        result = extract_endpoints(
            spec_path=temp_spec_file,
            target_tags=["Albums"],
            output_path=output,
        )

        assert "Albums" in result
        assert "Artists" not in result

    def test_method_uppercase(self, temp_spec_file, tmp_path):
        """HTTP 方法统一转为大写"""
        output = str(tmp_path / "output.json")
        result = extract_endpoints(
            spec_path=temp_spec_file,
            target_tags=["Albums", "Artists"],
            output_path=output,
        )

        for eps in result.values():
            for ep in eps:
                assert ep["method"] == ep["method"].upper()
