import pytest
import requests
import allure
import conftest  # noqa: F401


@allure.feature("专辑收藏生命周期")
class TestAlbumLifecycle:
    """专辑收藏工作流测试"""

    @pytest.fixture(scope="class")
    def album_id(self):
        return "382ObEPsp2rxGrnsizN5TX"

    @pytest.fixture(scope="class")
    def invalid_album_ids(self):
        return ["invalid", "nonexistent"]

    @allure.story("正向链路")
    @pytest.mark.skip(reason="Token 缺少 user-library-modify scope，无法执行 PUT/DELETE")
    def test_album_save_lifecycle(self, base_url, auth_token, album_id):
        """
        正向链路：收藏 → 验证已收藏 → 取消收藏 → 验证已取消
        """
        allure.dynamic.title("专辑收藏正向生命周期测试")
        headers = {"Authorization": f"Bearer {auth_token}"}
        try:
            # ACTION: 收藏专辑
            resp_put = requests.put(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            assert resp_put.status_code == 200, f"收藏失败: {resp_put.status_code}"
            allure.attach(
                f"PUT /me/albums?ids={album_id} → {resp_put.status_code}",
                name="收藏请求",
                attachment_type=allure.attachment_type.TEXT
            )

            # VERIFY: 验证已收藏
            resp_contains = requests.get(
                f"{base_url}/me/albums/contains",
                params={"ids": album_id},
                headers=headers
            )
            assert resp_contains.status_code == 200
            data = resp_contains.json()
            # 响应示例： [true] 或 [false]
            assert isinstance(data, list) and len(data) == 1
            assert data[0] is True, f"期望收藏状态为 true, 实际: {data}"
            allure.attach(
                f"GET /me/albums/contains?ids={album_id} → {resp_contains.status_code}, body: {data}",
                name="验证收藏状态",
                attachment_type=allure.attachment_type.TEXT
            )
        finally:
            # CLEANUP: 取消收藏
            resp_delete = requests.delete(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            allure.attach(
                f"DELETE /me/albums?ids={album_id} → {resp_delete.status_code}",
                name="取消收藏(cleanup)",
                attachment_type=allure.attachment_type.TEXT
            )
            # 重新验证已取消
            resp_contains_after = requests.get(
                f"{base_url}/me/albums/contains",
                params={"ids": album_id},
                headers=headers
            )
            if resp_contains_after.status_code == 200:
                data_after = resp_contains_after.json()
                assert data_after[0] is False, f"取消后状态应为 false, 实际: {data_after}"

    @allure.story("幂等测试")
    @pytest.mark.skip(reason="Token 缺少 user-library-modify scope，无法执行 PUT/DELETE")
    def test_album_save_idempotent(self, base_url, auth_token, album_id):
        """
        幂等测试：重复 PUT 收藏专辑，断言不报错（200）
        """
        allure.dynamic.title("专辑收藏幂等性测试")
        headers = {"Authorization": f"Bearer {auth_token}"}
        try:
            resp1 = requests.put(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            assert resp1.status_code == 200, f"第一次PUT失败: {resp1.status_code}"
            allure.attach(
                f"第一次 PUT → {resp1.status_code}",
                name="幂等PUT-1",
                attachment_type=allure.attachment_type.TEXT
            )
            resp2 = requests.put(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            assert resp2.status_code == 200, f"第二次PUT失败: {resp2.status_code}"
            allure.attach(
                f"第二次 PUT → {resp2.status_code}",
                name="幂等PUT-2",
                attachment_type=allure.attachment_type.TEXT
            )
        finally:
            # 清理状态
            requests.delete(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )

    @allure.story("鉴权测试")
    def test_album_save_unauthorized(self, base_url, album_id):
        """
        鉴权测试：不传 Authorization token，期望 401
        """
        allure.dynamic.title("专辑收藏无鉴权测试")
        resp = requests.put(
            f"{base_url}/me/albums",
            params={"ids": album_id}
        )
        assert resp.status_code == 401, f"期望401, 实际{resp.status_code}"
        allure.attach(
            f"PUT 无token → {resp.status_code}",
            name="鉴权测试",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.story("无效参数测试")
    @pytest.mark.parametrize("invalid_id", ["invalid", "nonexistent"])
    def test_album_save_invalid_id(self, base_url, auth_token, invalid_id):
        """
        无效参数测试：传入无效的 album ID，期望 400/403/404
        """
        allure.dynamic.title(f"专辑收藏无效ID测试: {invalid_id}")
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = requests.put(
            f"{base_url}/me/albums",
            params={"ids": invalid_id},
            headers=headers
        )
        assert resp.status_code in [400, 403, 404], \
            f"期望400/403/404, 实际{resp.status_code}"
        allure.attach(
            f"PUT ids={invalid_id} → {resp.status_code}",
            name="无效ID测试",
            attachment_type=allure.attachment_type.TEXT
        )


@allure.feature("关注艺术家生命周期")
class TestFollowLifecycle:
    """关注艺术家工作流测试"""

    @pytest.fixture(scope="class")
    def artist_id(self):
        return "0TnOYISbd1XYRBk9myaseg"

    @pytest.fixture(scope="class")
    def invalid_artist_ids(self):
        return ["invalid", "nonexistent"]

    @allure.story("正向链路")
    @pytest.mark.skip(reason="Token 缺少 user-follow-modify scope，无法执行 PUT/DELETE")
    def test_follow_artist_lifecycle(self, base_url, auth_token, artist_id):
        """
        正向链路：关注 → 验证已关注 → 取消关注 → 验证已取消
        """
        allure.dynamic.title("关注艺术家正向生命周期测试")
        headers = {"Authorization": f"Bearer {auth_token}"}
        params_common = {"type": "artist", "ids": artist_id}

        try:
            # ACTION: 关注艺术家
            resp_put = requests.put(
                f"{base_url}/me/following",
                params=params_common,
                headers=headers
            )
            assert resp_put.status_code == 200, f"关注失败: {resp_put.status_code}"
            allure.attach(
                f"PUT /me/following?type=artist&ids={artist_id} → {resp_put.status_code}",
                name="关注请求",
                attachment_type=allure.attachment_type.TEXT
            )

            # VERIFY: 验证已关注
            resp_contains = requests.get(
                f"{base_url}/me/following/contains",
                params=params_common,
                headers=headers
            )
            assert resp_contains.status_code == 200
            data = resp_contains.json()
            # 响应示例： [true] 或 [false]
            assert isinstance(data, list) and len(data) == 1
            assert data[0] is True, f"期望关注状态为 true, 实际: {data}"
            allure.attach(
                f"GET /me/following/contains?type=artist&ids={artist_id} → {resp_contains.status_code}, body: {data}",
                name="验证关注状态",
                attachment_type=allure.attachment_type.TEXT
            )
        finally:
            # CLEANUP: 取消关注
            resp_delete = requests.delete(
                f"{base_url}/me/following",
                params=params_common,
                headers=headers
            )
            allure.attach(
                f"DELETE /me/following?type=artist&ids={artist_id} → {resp_delete.status_code}",
                name="取消关注(cleanup)",
                attachment_type=allure.attachment_type.TEXT
            )
            # 重新验证已取消
            resp_contains_after = requests.get(
                f"{base_url}/me/following/contains",
                params=params_common,
                headers=headers
            )
            if resp_contains_after.status_code == 200:
                data_after = resp_contains_after.json()
                assert data_after[0] is False, f"取消后状态应为 false, 实际: {data_after}"

    @allure.story("幂等测试")
    @pytest.mark.skip(reason="Token 缺少 user-follow-modify scope，无法执行 PUT/DELETE")
    def test_follow_artist_idempotent(self, base_url, auth_token, artist_id):
        """
        幂等测试：重复 PUT 关注艺术家，断言不报错（200）
        """
        allure.dynamic.title("关注艺术家幂等性测试")
        headers = {"Authorization": f"Bearer {auth_token}"}
        params = {"type": "artist", "ids": artist_id}

        try:
            resp1 = requests.put(
                f"{base_url}/me/following",
                params=params,
                headers=headers
            )
            assert resp1.status_code == 200, f"第一次PUT失败: {resp1.status_code}"
            allure.attach(
                f"第一次 PUT → {resp1.status_code}",
                name="幂等PUT-1",
                attachment_type=allure.attachment_type.TEXT
            )
            resp2 = requests.put(
                f"{base_url}/me/following",
                params=params,
                headers=headers
            )
            assert resp2.status_code == 200, f"第二次PUT失败: {resp2.status_code}"
            allure.attach(
                f"第二次 PUT → {resp2.status_code}",
                name="幂等PUT-2",
                attachment_type=allure.attachment_type.TEXT
            )
        finally:
            # 清理状态
            requests.delete(
                f"{base_url}/me/following",
                params=params,
                headers=headers
            )

    @allure.story("鉴权测试")
    def test_follow_artist_unauthorized(self, base_url, artist_id):
        """
        鉴权测试：不传 Authorization token，期望 401
        """
        allure.dynamic.title("关注艺术家无鉴权测试")
        params = {"type": "artist", "ids": artist_id}
        resp = requests.put(
            f"{base_url}/me/following",
            params=params
        )
        assert resp.status_code == 401, f"期望401, 实际{resp.status_code}"
        allure.attach(
            f"PUT 无token → {resp.status_code}",
            name="鉴权测试",
            attachment_type=allure.attachment_type.TEXT
        )

    @allure.story("无效参数测试")
    @pytest.mark.parametrize("invalid_id", ["invalid", "nonexistent"])
    def test_follow_artist_invalid_id(self, base_url, auth_token, invalid_id):
        """
        无效参数测试：传入无效的 artist ID，期望 400/403/404
        """
        allure.dynamic.title(f"关注艺术家无效ID测试: {invalid_id}")
        headers = {"Authorization": f"Bearer {auth_token}"}
        params = {"type": "artist", "ids": invalid_id}
        resp = requests.put(
            f"{base_url}/me/following",
            params=params,
            headers=headers
        )
        assert resp.status_code in [400, 403, 404], \
            f"期望400/403/404, 实际{resp.status_code}"
        allure.attach(
            f"PUT ids={invalid_id} → {resp.status_code}",
            name="无效ID测试",
            attachment_type=allure.attachment_type.TEXT
        )