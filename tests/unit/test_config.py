"""Config 单元测试 — 默认值、环境变量加载、单例。"""

import os
from unittest.mock import patch

from src.config import Config, get_config


class TestConfigDefaults:
    """默认值"""

    def test_default_values(self):
        """所有字段应该有合理默认值"""
        with patch.dict(os.environ, {}, clear=True):
            cfg = Config()
            assert cfg.spotify_client_id == ""
            assert cfg.spotify_client_secret == ""
            assert cfg.llm_api_key == ""
            assert cfg.llm_api_base == "https://api.deepseek.com"
            assert cfg.llm_model == "deepseek-v4-pro"
            assert cfg.max_resolve_depth == 3
            assert cfg.skip_optional_params is True
            assert cfg.base_url == "https://api.spotify.com/v1"
            assert cfg.pass_threshold == 80.0

    def test_has_llm_false_when_no_key(self):
        """未设置 API key 时 has_llm 返回 False"""
        with patch.dict(os.environ, {}, clear=True):
            cfg = Config()
            assert cfg.has_llm is False

    def test_has_llm_true_when_key_set(self):
        """设置了 API key 时 has_llm 返回 True"""
        with patch.dict(os.environ, {"LLM_API_KEY": "sk-test-key"}, clear=True):
            cfg = Config()
            assert cfg.has_llm is True

    def test_has_spotify_false_when_no_credentials(self):
        """未设置凭据时 has_spotify 返回 False"""
        with patch.dict(os.environ, {}, clear=True):
            cfg = Config()
            assert cfg.has_spotify is False

    def test_has_spotify_true_when_both_set(self):
        """凭据完整时 has_spotify 返回 True"""
        with patch.dict(os.environ, {
            "ClientId": "test-id",
            "Secret": "test-secret",
        }, clear=True):
            cfg = Config()
            assert cfg.has_spotify is True


class TestEnvLoading:
    """环境变量加载"""

    def test_load_from_env(self):
        """从环境变量覆盖默认值"""
        env = {
            "LLM_API_KEY": "sk-env-key",
            "LLM_API_BASE": "https://custom.api.com",
            "LLM_MODEL": "custom-model",
            "ClientId": "env-client-id",
            "Secret": "env-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = Config()
            assert cfg.llm_api_key == "sk-env-key"
            assert cfg.llm_api_base == "https://custom.api.com"
            assert cfg.llm_model == "custom-model"
            assert cfg.spotify_client_id == "env-client-id"
            assert cfg.spotify_client_secret == "env-secret"


class TestSingleton:
    """单例行为"""

    def test_get_config_returns_same_instance(self):
        """多次调用 get_config 应返回同一个实例"""
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_get_config_is_cached(self):
        """lru_cache 确保只创建一个实例"""
        # 清除缓存后获取
        get_config.cache_clear()
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2
