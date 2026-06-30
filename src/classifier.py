"""
LLM 端点分类器 — 将端点分为 data_driven (YAML驱动) 和 need_code (需代码编排)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.llm_client import LLMClient
from src.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = "你是一个 API 测试架构分析师。请严格按照 JSON 格式返回结果，不要输出任何解释文字。"


def build_classification_prompt(endpoints_by_tag: dict[str, list[dict[str, Any]]]) -> str:
    """构建端点分类的 LLM Prompt。"""
    endpoints_text = ""
    total = 0
    for tag, eps in endpoints_by_tag.items():
        endpoints_text += f"\n## {tag}\n"
        for ep in eps:
            total += 1
            deprecated = " [DEPRECATED]" if ep.get("deprecated") else ""
            endpoints_text += (
                f"  - {ep['method']} {ep['path']}"
                f" | operationId: {ep['operation_id']}"
                f" | summary: {ep['summary']}"
                f"{deprecated}\n"
            )

    return f"""你是一个资深接口自动化测试架构师。请对以下 {total} 个 Spotify API 端点进行分类，
判断每个端点适合「YAML 数据驱动」还是「需要代码编排」。

{endpoints_text}

## 分类标准

### data_driven（YAML 驱动）
满足以下所有条件：
1. HTTP GET 方法（只读操作）
2. 不修改服务端状态（无副作用）
3. 不需要前置 setup（不依赖其他端点的创建操作）
4. 不需要后置 cleanup（不用撤销/恢复数据）
5. 单次请求即可验证，不涉及多步链路

### need_code（需要代码编排）
满足以下任一条件：
1. HTTP POST/PUT/PATCH/DELETE 方法（有写操作）
2. 会修改服务端状态（save/remove/follow/unfollow/add/delete 等）
3. 测试需要 setup 前置 → action → verify → teardown 链路
4. 与其他端点存在前后依赖关系（如: 先创建资源再校验再删除）
5. 需要动态生成测试数据（参数值依赖前一步返回结果）

## 输出要求

只输出一个 JSON 对象，不要有任何解释文字：

```json
{{
  "data_driven": [
    {{
      "tag": "Albums",
      "method": "GET",
      "path": "/albums/{{id}}",
      "operation_id": "get-an-album",
      "reason": "只读查询，无副作用，单次请求即可"
    }}
  ],
  "need_code": [
    {{
      "tag": "Albums",
      "method": "PUT",
      "path": "/me/albums",
      "operation_id": "save-albums-user",
      "reason": "PUT 写操作，修改用户状态，需要 cleanup 恢复"
    }}
  ]
}}
```

注意：
- reason 字段用中文简述分类理由，15字以内
- 每个端点都必须在两个数组之一中出现
- 只输出 JSON，不要 Markdown 标记
"""


def classify_endpoints(
    endpoints_by_tag: dict[str, list[dict[str, Any]]],
    client: LLMClient | None = None,
    output_path: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """调用 LLM 对端点进行分类。

    Args:
        endpoints_by_tag: 按 tag 分组的端点
        client: LLM 客户端
        output_path: 输出路径

    Returns:
        {"data_driven": [...], "need_code": [...]}
    """
    if client is None:
        client = LLMClient()

    total = sum(len(eps) for eps in endpoints_by_tag.values())
    logger.info("共 %d 个端点，%d 个标签", total, len(endpoints_by_tag))

    prompt = build_classification_prompt(endpoints_by_tag)

    # 保存 prompt 供调试
    prompts_dir = Path("prompts")
    prompts_dir.mkdir(exist_ok=True)
    (prompts_dir / "prompt_classify.txt").write_text(prompt, encoding="utf-8")
    logger.debug("Prompt 已保存: prompts/prompt_classify.txt")

    result = client.chat_json(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
    )

    output_path = output_path or "endpoint_classification.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    dd_count = len(result.get("data_driven", []))
    nc_count = len(result.get("need_code", []))
    logger.info("分类完成: data_driven=%d, need_code=%d", dd_count, nc_count)

    if result.get("need_code"):
        logger.info("需要代码编排的端点:")
        for ep in result["need_code"]:
            logger.info("  %s %s → %s", ep["method"], ep["path"], ep.get("reason", ""))

    return result
