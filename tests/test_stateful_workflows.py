import pytest
import requests
from conftest import base_url, auth_token  # noqa: F401


class TestAlbumLifecycle:
    """专辑收藏生命周期测试"""

    @pytest.fixture
    def test_album_id(self):
        """返回一个已知的专辑ID"""
        # TODO: 替换为真实可用ID
        return "4aawyAB9vmqN3uQ7FjRGTy"

    @pytest.mark.skip(reason="需要用户token (user-library-modify scope)")
    def test_album_lifecycle(self, base_url, auth_token, test_album_id):
        """正向链路：收藏→验证→取消→验证"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        album_id = test_album_id

        try:
            # ACTION: 收藏专辑
            put_resp = requests.put(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            assert put_resp.status_code == 200, f"收藏专辑失败: {put_resp.status_code}"

            # VERIFY: 验证已收藏
            contains_resp = requests.get(
                f"{base_url}/me/albums/contains",
                params={"ids": album_id},
                headers=headers
            )
            assert contains_resp.status_code == 200
            assert contains_resp.json() == [True], "专辑应处于已收藏状态"
        finally:
            # CLEANUP: 取消收藏
            delete_resp = requests.delete(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            assert delete_resp.status_code == 200, f"取消收藏失败: {delete_resp.status_code}"

            # 验证已取消
            final_check = requests.get(
                f"{base_url}/me/albums/contains",
                params={"ids": album_id},
                headers=headers
            )
            assert final_check.status_code == 200
            assert final_check.json() == [False], "专辑应处于未收藏状态"

    @pytest.mark.skip(reason="需要用户token (user-library-modify scope)")
    def test_album_idempotent_put(self, base_url, auth_token, test_album_id):
        """幂等测试：重复执行PUT收藏专辑"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        album_id = test_album_id

        try:
            # 第一次PUT
            resp1 = requests.put(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            assert resp1.status_code == 200

            # 第二次PUT（幂等）
            resp2 = requests.put(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )
            assert resp2.status_code == 200, "幂等PUT应返回200"
        finally:
            # 清理
            requests.delete(
                f"{base_url}/me/albums",
                params={"ids": album_id},
                headers=headers
            )

    def test_album_unauthorized(self, base_url, test_album_id):
        """鉴权测试：不传token执行PUT收藏"""
        resp = requests.put(
            f"{base_url}/me/albums",
            params={"ids": test_album_id}
        )
        assert resp.status_code == 401, f"无token应返回401，实际: {resp.status_code}"

    @pytest.mark.parametrize("invalid_id", [
        "invalid_album_id_12345",
        "0000000000000000000000",
        ""
    ])
    def test_album_invalid_id(self, base_url, auth_token, invalid_id):
        """无效参数测试：传入无效专辑ID"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = requests.put(
            f"{base_url}/me/albums",
            params={"ids": invalid_id},
            headers=headers
        )
        assert resp.status_code in [400, 403, 404], \
            f"无效ID应返回400/403/404，实际: {resp.status_code}"


class TestFollowLifecycle:
    """关注艺术家生命周期测试"""

    @pytest.fixture
    def test_artist_id(self):
        """返回一个已知的艺术家ID"""
        # TODO: 替换为真实可用ID
        return "0TnOYISbd1XYRBk9myaseg"

    @pytest.mark.skip(reason="需要用户token (user-follow-modify scope)")
    def test_follow_lifecycle(self, base_url, auth_token, test_artist_id):
        """正向链路：关注→验证→取消→验证"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        artist_id = test_artist_id

        try:
            # ACTION: 关注艺术家
            put_resp = requests.put(
                f"{base_url}/me/following",
                params={"type": "artist", "ids": artist_id},
                headers=headers
            )
            assert put_resp.status_code == 204, f"关注艺术家失败: {put_resp.status_code}"

            # VERIFY: 验证已关注
            contains_resp = requests.get(
                f"{base_url}/me/following/contains",
                params={"type": "artist", "ids": artist_id},
                headers=headers
            )
            assert contains_resp.status_code == 200
            assert contains_resp.json() == [True], "艺术家应处于已关注状态"
        finally:
            # CLEANUP: 取消关注
            delete_resp = requests.delete(
                f"{base_url}/me/following",
                params={"type": "artist", "ids": artist_id},
                headers=headers
            )
            assert delete_resp.status_code == 204, f"取消关注失败: {delete_resp.status_code}"

            # 验证已取消
            final_check = requests.get(
                f"{base_url}/me/following/contains",
                params={"type": "artist", "ids": artist_id},
                headers=headers
            )
            assert final_check.status_code == 200
            assert final_check.json() == [False], "艺术家应处于未关注状态"

    @pytest.mark.skip(reason="需要用户token (user-follow-modify scope)")
    def test_follow_idempotent_put(self, base_url, auth_token, test_artist_id):
        """幂等测试：重复执行PUT关注艺术家"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        artist_id = test_artist_id

        try:
            # 第一次PUT
            resp1 = requests.put(
                f"{base_url}/me/following",
                params={"type": "artist", "ids": artist_id},
                headers=headers
            )
            assert resp1.status_code == 204

            # 第二次PUT（幂等）
            resp2 = requests.put(
                f"{base_url}/me/following",
                params={"type": "artist", "ids": artist_id},
                headers=headers
            )
            assert resp2.status_code == 204, "幂等PUT应返回204"
        finally:
            # 清理
            requests.delete(
                f"{base_url}/me/following",
                params={"type": "artist", "ids": artist_id},
                headers=headers
            )

    def test_follow_unauthorized(self, base_url, test_artist_id):
        """鉴权测试：不传token执行PUT关注"""
        resp = requests.put(
            f"{base_url}/me/following",
            params={"type": "artist", "ids": test_artist_id}
        )
        assert resp.status_code == 401, f"无token应返回401，实际: {resp.status_code}"

    @pytest.mark.parametrize("invalid_id", [
        "invalid_artist_id_12345",
        "0000000000000000000000",
        ""
    ])
    def test_follow_invalid_id(self, base_url, auth_token, invalid_id):
        """无效参数测试：传入无效艺术家ID"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = requests.put(
            f"{base_url}/me/following",
            params={"type": "artist", "ids": invalid_id},
            headers=headers
        )
        assert resp.status_code in [400, 403, 404], \
            f"无效ID应返回400/403/404，实际: {resp.status_code}"