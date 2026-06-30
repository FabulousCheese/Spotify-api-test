"""
YAML 数据驱动测试通用框架。

读取 test_data/ 目录下的所有 .yaml 文件，自动生成参数化测试。
新增测试用例只需编辑 YAML，无需修改此文件。

YAML 格式示例（test_data/albums.yaml）:

  endpoints:
    - path: /albums/{id}
      method: GET
      operation_id: get-an-album
      cases:
        - name: valid_album
          description: 正向：有效专辑ID
          path_params:
            id: "4aawyAB9vmqN3uQ7FjRGTy"
          query_params:
            market: US
          expect:
            status: 200
            body_fields: [album_type, artists, id, name]
            body_types:
              artists: list
              popularity: int
"""
import json
import yaml
import allure
import pytest
import requests
from pathlib import Path

TEST_DATA_DIR = Path(__file__).parent.parent / "test_data"

# 这些端点需要用户 token（Authorization Code flow），Client Credentials 无权访问
REQUIRE_USER_TOKEN = {
    # 用户专属端点（需要 Authorization Code flow）
    "/me/albums",
    "/me/albums/contains",
    "/me/following",
    "/me/following/contains",
    "/browse/new-releases",
    # 需要特定 scope，Client Credentials 返回 403
    "/artists/{id}/top-tracks",
    "/artists/{id}/related-artists",
    # 已废弃
    "/albums",      # get-multiple-albums (deprecated)
    "/artists",     # get-multiple-artists (deprecated)
}

TYPE_MAP = {
    "str": str, "string": str,
    "int": int, "integer": int,
    "float": float, "number": float,
    "list": list, "array": list,
    "dict": dict, "object": dict,
    "bool": bool, "boolean": bool,
}


def _load_all_yaml_cases() -> list[dict]:
    """从 test_data/ 下所有 YAML 文件加载测试用例"""
    cases = []
    if not TEST_DATA_DIR.exists():
        return cases

    for yaml_file in sorted(TEST_DATA_DIR.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        for endpoint in data.get("endpoints", []):
            for case in endpoint.get("cases", []):
                # 把端点信息附带到每个 case 上，供测试函数使用
                case["_endpoint"] = endpoint
                # 合并文件名前缀到 name，方便定位
                case["name"] = f"[{yaml_file.stem}] {case.get('name', 'unnamed')}"
                cases.append(case)
    return cases


_ALL_CASES = _load_all_yaml_cases()


def _id_func(case: dict) -> str:
    """测试名称：截取 name 防止过长"""
    name = case.get("name", "unnamed")
    return name if len(name) <= 60 else name[:57] + "..."


@pytest.mark.parametrize("case", _ALL_CASES, ids=_id_func)
def test_data_driven(base_url, auth_token, case):
    """
    通用数据驱动测试。

    从 YAML 读取 endpoint + case 定义，自动：
      1. 替换路径参数 → 构造 URL
      2. 拼接 query 参数
      3. 发起请求
      4. 断言 status code
      5. 断言返回体字段存在性
      6. 断言返回体字段类型
    """
    endpoint = case["_endpoint"]

    # 跳过需要用户 token 的端点
    if endpoint["path"] in REQUIRE_USER_TOKEN and not case.get("skip_auth"):
        pytest.skip(f"需要用户 token（Client Credentials 无权访问）")

    # ── Allure 动态元数据 ──
    allure.dynamic.title(case.get("name", "unnamed"))
    allure.dynamic.feature(endpoint.get("tag", endpoint["path"]))
    allure.dynamic.story(case.get("description", case.get("name", "")))
    allure.dynamic.tag(endpoint.get("method", "GET"))

    # ── 1. 构造 URL（替换路径参数） ──
    url = f"{base_url}{endpoint['path']}"
    path_params = case.get("path_params", {})
    for key, value in path_params.items():
        url = url.replace(f"{{{key}}}", str(value))

    # ── 2. 构造 query 参数 ──
    query_params = case.get("query_params", {})

    # ── 3. 构造请求头 ──
    if case.get("skip_auth"):
        headers = {}
    elif case.get("auth_header"):
        headers = {"Authorization": case["auth_header"]}
    else:
        headers = {"Authorization": f"Bearer {auth_token}"}

    # ── 4. 发起请求 ──
    method = endpoint.get("method", "GET")
    resp = requests.request(
        method,
        url,
        params=query_params or None,
        headers=headers,
        timeout=30,
    )

    # ── 5. 断言 status code ──
    expected_status = case["expect"].get("status")
    if expected_status is not None:
        if isinstance(expected_status, list):
            assert resp.status_code in expected_status, (
                f"[{case['name']}] 状态码 {resp.status_code} 不在期望范围 {expected_status}"
            )
        else:
            assert resp.status_code == expected_status, (
                f"[{case['name']}] 期望 {expected_status}，实际 {resp.status_code}"
            )

    # ── Allure 附加请求/响应详情 ──
    allure.attach(
        f"{method} {url}\n\nQuery: {query_params or 'N/A'}\n\nHeaders: {json.dumps({k: v[:20]+'...' if len(v)>20 else v for k, v in headers.items()}, indent=2)}",
        "Request",
        allure.attachment_type.TEXT,
    )
    allure.attach(
        f"Status: {resp.status_code}\n\nBody:\n{resp.text[:2000]}",
        "Response",
        allure.attachment_type.TEXT,
    )

    # ── 6. 断言返回体（仅成功响应才校验） ──
    if resp.status_code < 400 and resp.text:
        body = resp.json()

        # 6a. 字段存在性
        body_fields = case["expect"].get("body_fields", [])
        for field in body_fields:
            assert field in body, (
                f"[{case['name']}] 返回体缺少字段: {field}"
            )

        # 6b. 字段类型（支持点号路径访问嵌套字段，如 "artists.items.id"）
        body_types = case["expect"].get("body_types", {})
        if body_types and resp.status_code < 400:
            for field_path, expected_type in body_types.items():
                parts = field_path.split(".")
                current = body
                try:
                    for part in parts:
                        current = current[part] if isinstance(current, dict) else current[int(part)]
                except (KeyError, IndexError, TypeError, ValueError):
                    # 嵌套字段不存在，跳过类型检查
                    continue

                python_type = TYPE_MAP.get(expected_type, str)
                assert isinstance(current, python_type), (
                    f"[{case['name']}] 字段 {field_path} 类型期望 {expected_type}，"
                    f"实际 {type(current).__name__}"
                )

        # 6c. 精确值断言（可选）
        body_values = case["expect"].get("body_values", {})
        for field, expected_value in body_values.items():
            assert field in body, (
                f"[{case['name']}] 返回体缺少字段: {field}"
            )
            assert body[field] == expected_value, (
                f"[{case['name']}] 字段 {field} 期望 {expected_value}，"
                f"实际 {body[field]}"
            )
