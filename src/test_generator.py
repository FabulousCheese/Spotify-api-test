"""
pytest 测试代码生成器 — 为 need_code 端点生成有状态链路测试代码。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.llm_client import LLMClient
from src.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = "你是资深 Python 自动化测试工程师。请严格按照要求生成 pytest 测试代码，只输出代码块。"


def build_stateful_prompt(endpoints_by_tag: dict[str, list[dict[str, Any]]]) -> str:
    """为 need_code 端点构建链路测试 Prompt。"""
    endpoints_text = ""
    total = 0
    workflows: dict[str, list[dict[str, Any]]] = {}

    for tag, eps in endpoints_by_tag.items():
        for ep in eps:
            total += 1
            op_id = ep["operation_id"]
            reason = ep.get("reason", "")
            endpoints_text += (
                f"  - {ep['method']} {ep['path']}"
                f" | operationId: {op_id} | reason: {reason}\n"
            )

            if "albums" in op_id or "album" in op_id:
                workflows.setdefault("album_lifecycle", []).append(ep)
            elif "follow" in op_id:
                workflows.setdefault("follow_lifecycle", []).append(ep)

    workflow_text = ""
    if "album_lifecycle" in workflows:
        workflow_text += """
### 工作流 1：专辑收藏生命周期
```
准备: 取一个已知 album_id（如 "4aawyAB9vmqN3uQ7FjRGTy"）
PUT  /me/albums?ids={album_id}        → 收藏专辑
GET  /me/albums/contains?ids={album_id} → 验证收藏状态 [true]
DELETE /me/albums?ids={album_id}      → 取消收藏（cleanup）
GET  /me/albums/contains?ids={album_id} → 验证已取消 [false]
```
"""
    if "follow_lifecycle" in workflows:
        workflow_text += """
### 工作流 2：关注艺术家生命周期
```
准备: 取一个已知 artist_id（如 "0TnOYISbd1XYRBk9myaseg"）
PUT  /me/following?type=artist&ids={artist_id}      → 关注
GET  /me/following/contains?type=artist&ids={artist_id} → 验证已关注 [true]
DELETE /me/following?type=artist&ids={artist_id}   → 取消关注（cleanup）
GET  /me/following/contains?type=artist&ids={artist_id} → 验证已取消 [false]
```
"""

    return f"""你是资深 Python 自动化测试工程师。以下 {total} 个 Spotify API 端点是**有状态写操作**，
无法用纯数据驱动，需要代码级编排。请为它们生成 pytest 链路测试。

## 端点清单
{endpoints_text}
{workflow_text}
## 生成要求

### 1. 测试架构
- 文件名: `test_stateful_workflows.py`
- 按工作流分 TestClass：`TestAlbumLifecycle`、`TestFollowLifecycle`
- 每个工作流按 SETUP → ACTION → VERIFY → CLEANUP 的顺序组织

### 2. Fixture 设计
- 在类中定义 `@pytest.fixture` 提供测试数据
- `base_url` 和 `auth_token` 通过 conftest.py 注入，不要在本文件定义

### 3. 用例设计（每个工作流至少包含）
- 正向链路: setup(无) → action(PUT) → verify(GET contains 返回 true) → cleanup(DELETE)
- 幂等测试: 重复执行 PUT，断言不报错
- 鉴权测试: 不传 token 执行 PUT，断言 401
- 无效参数: 传入无效 ID，断言 [400, 403, 404]

### 4. 代码风格
- import conftest  # noqa: F401
- 每个测试函数有简短中文 docstring
- cleanup 用 try/finally 确保即使断言失败也执行
- 使用 `@pytest.mark.parametrize` 做数据驱动
- 状态码异常断言用 `in [400, 403, 404]`

### 5. Allure 报告集成
    - 导入 `import allure`
    - 类级别使用 `@allure.feature("{{类别名}}")`
    - 方法级别使用 `@allure.story("{{用例名}}")` + `allure.dynamic.title("{{中文标题}}")`
    - 关键请求处使用 `allure.attach()` 附加请求URL、方法、响应状态码

### 6. 约束
- 只输出 Python 代码，不输出解释
- 用 ```python 和 ``` 包裹代码
"""


def generate_stateful_tests(
    need_code_endpoints: list[dict[str, Any]],
    client: LLMClient | None = None,
    output_dir: str = "tests",
) -> None:
    """为 need_code 端点生成链路测试代码。

    Args:
        need_code_endpoints: 来自 endpoint_classification.json 的 need_code 列表
        client: LLM 客户端
        output_dir: 输出目录
    """
    if not need_code_endpoints:
        logger.warning("没有 need_code 端点，跳过")
        return

    if client is None:
        client = LLMClient()

    nc_by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ep in need_code_endpoints:
        nc_by_tag[ep["tag"]].append(ep)

    prompt = build_stateful_prompt(dict(nc_by_tag))
    logger.info("有状态端点: %d 个", len(need_code_endpoints))

    # 保存 prompt
    prompts_dir = Path("prompts")
    prompts_dir.mkdir(exist_ok=True)
    (prompts_dir / "prompt_stateful.txt").write_text(prompt, encoding="utf-8")

    code = client.chat_python(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=8192,
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True)
    filepath = out_dir / "test_stateful_workflows.py"
    if filepath.exists():
        backup = filepath.with_suffix(f".py.bak.{datetime.now():%Y%m%d_%H%M%S}")
        filepath.rename(backup)
        logger.info("已备份: %s", backup)
    filepath.write_text(code, encoding="utf-8")
    logger.info("已保存: %s", filepath)
