"""
LLM 调用封装 — 统一 OpenAI-compatible API 调用，内置重试。
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.config import get_config
from src.logger import get_logger

logger = get_logger(__name__)


def _extract_json(raw: str) -> dict[str, Any]:
    """从 LLM 返回文本中提取 JSON（处理 markdown 包裹的情况）。"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    import typing
    return typing.cast(dict[str, Any], json.loads(text))


def _extract_yaml(raw: str) -> str:
    """从 LLM 返回文本中提取 YAML 块。"""
    text = raw.strip()
    if "```yaml" in text:
        text = text.split("```yaml", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]
    return text.strip()


def _extract_python(raw: str) -> str:
    """从 LLM 返回文本中提取 Python 代码块。"""
    text = raw.strip()
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


class LLMClient:
    """封装 OpenAI-compatible LLM 调用，带自动重试。"""

    def __init__(self) -> None:
        cfg = get_config()
        self._model = cfg.llm_model
        self._client = OpenAI(base_url=cfg.llm_api_base, api_key=cfg.llm_api_key)

    @property
    def model(self) -> str:
        return self._model

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=lambda retry_state: logger.warning(
            "LLM 调用重试 %d/3: %s", retry_state.attempt_number, retry_state.outcome
        ),
    )
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """发送请求到 LLM，返回原始文本响应。"""
        logger.debug("→ 调用 %s (max_tokens=%d)", self._model, max_tokens)

        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format

        response = self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        logger.debug("← LLM 返回 %d 字符", len(content))
        return content

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """发送请求并解析为 JSON。"""
        raw = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return _extract_json(raw)

    def chat_yaml(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """发送请求并提取 YAML 内容。"""
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return _extract_yaml(raw)

    def chat_python(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> str:
        """发送请求并提取 Python 代码。"""
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return _extract_python(raw)
