"""
pytest 公共 fixture：鉴权 token、base_url
"""
import os
import sys
import pytest
import requests

# 确保能加载项目根目录的 .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    # 从 tests/ 的上级目录（项目根目录）加载 .env
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

SPOTIFY_CLIENT_ID = os.getenv("ClientId", "")
SPOTIFY_CLIENT_SECRET = os.getenv("Secret", "")


@pytest.fixture(scope="session")
def base_url():
    return "https://api.spotify.com/v1"


@pytest.fixture(scope="session")
def auth_token():
    """通过 Client Credentials 获取 Spotify access token"""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        pytest.skip("ClientId/Secret 未在 .env 中配置")

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.fail(f"获取 token 失败: {resp.status_code} {resp.text}")

    token = resp.json()["access_token"]
    return token
