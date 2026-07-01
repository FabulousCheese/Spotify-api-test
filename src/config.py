"""
集中配置管理 — 从 .env 文件和环境变量加载，全项目单一入口。
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass
class Config:
    """全项目配置，从环境变量/.env 加载，提供合理默认值。"""

    # ── Spotify API 凭据 ──
    spotify_client_id: str = field(
        default_factory=lambda: os.getenv("ClientId", "")
    )
    spotify_client_secret: str = field(
        default_factory=lambda: os.getenv("Secret", "")
    )

    # ── LLM 配置 ──
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )
    llm_api_base: str = field(
        default_factory=lambda: os.getenv("LLM_API_BASE", "https://api.deepseek.com")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "deepseek-v4-pro")
    )

    # ── OpenAPI 解析 ──
    max_resolve_depth: int = 3
    skip_optional_params: bool = True

    # ── 路径 ──
    spec_path: str = "open-api-schema.yaml"
    extracted_path: str = "extracted_endpoints.json"
    classify_path: str = "endpoint_classification.json"
    test_data_dir: str = "test_data"
    tests_dir: str = "tests"
    prompts_dir: str = "prompts"
    reports_dir: str = "reports"

    # ── 测试 ──
    base_url: str = "https://api.spotify.com/v1"
    pass_threshold: float = 80.0

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def has_spotify(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_client_secret)


@lru_cache
def get_config() -> Config:
    """获取全局唯一配置实例（单例）。"""
    return Config()
