"""
读取 extracted_endpoints.json + open-api-schema.yaml，
展开 $ref 引用，构建 Prompt，调用 LLM 生成 pytest 测试用例。

用法：
  1. 配置 .env 文件中的 LLM_API_KEY（DeepSeek）
  2. 批量生成（默认模式）：    python generate_tests.py
  3. 单接口调试：              python generate_tests.py --single "/albums"
  4. 有状态端点的链路测试：    python generate_tests.py --mode stateful
"""

import json
import os
import sys
import yaml
from typing import Any

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 未安装，依赖手动 export 环境变量

# ============================================================
# 配置
# ============================================================

YAML_PATH = "open-api-schema.yaml"
JSON_PATH = "extracted_endpoints.json"
CLASSIFY_PATH = "endpoint_classification.json"
OUTPUT_DIR = "tests"

# DeepSeek API 默认配置（可在 .env 中覆盖）
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-your-deepseek-key-here")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# 单接口调试模式：指定一个 path，只生成这个接口的用例
SINGLE_ENDPOINT = os.getenv("SINGLE_ENDPOINT", None)

# 是否跳过 required=false 的可选参数（少即是多，简化 Prompt）
SKIP_OPTIONAL_PARAMS = True

# schema 展开最大深度，防止无限递归
MAX_RESOLVE_DEPTH = 3


# ============================================================
# 第1步：$ref 展开工具
# ============================================================

class RefResolver:
    """解析 OpenAPI 中的 $ref 引用"""

    def __init__(self, spec: dict):
        self.spec = spec
        self._cache = {}

    def resolve(self, obj: Any, depth: int = 0) -> Any:
        """递归展开 $ref，返回展开后的对象"""
        if depth > MAX_RESOLVE_DEPTH:
            return "...(嵌套太深，已截断)"

        if isinstance(obj, dict):
            # 如果对象只有一个 $ref 键，直接替换
            if list(obj.keys()) == ["$ref"]:
                ref_path = obj["$ref"]
                return self._resolve_ref(ref_path, depth)

            # 否则递归处理每个值
            result = {}
            for key, value in obj.items():
                result[key] = self.resolve(value, depth)
            return result

        if isinstance(obj, list):
            return [self.resolve(item, depth) for item in obj]

        return obj

    def _resolve_ref(self, ref_path: str, depth: int) -> Any:
        """根据 $ref 路径查找定义并展开"""
        if ref_path in self._cache:
            return self.resolve(self._cache[ref_path], depth + 1)

        if not ref_path.startswith("#/"):
            return {"_error": f"外部引用暂不支持: {ref_path}"}

        parts = ref_path[2:].split("/")
        current = self.spec
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return {"_error": f"无法解析路径: {ref_path}"}

        if current is None:
            return {"_error": f"未找到定义: {ref_path}"}

        self._cache[ref_path] = current
        return self.resolve(current, depth + 1)


# ============================================================
# 第2步：从 YAML + JSON 构建端点的完整信息
# ============================================================

def build_endpoint_info(ep: dict, resolver: RefResolver) -> dict:
    """对一个端点做完整的 $ref 展开，返回供 LLM 可读的信息"""

    # 展开参数
    params_resolved = []
    for p in ep.get("parameters", []):
        resolved = resolver.resolve(p)

        # 如果参数是可选且开启了跳过开关，则忽略
        if SKIP_OPTIONAL_PARAMS and not resolved.get("required", False):
            continue

        # 提取关键字段
        params_resolved.append({
            "name": resolved.get("name", "?"),
            "in": resolved.get("in", "?"),
            "required": resolved.get("required", False),
            "type": resolved.get("schema", {}).get("type", "?"),
            "description": resolved.get("schema", {}).get("description", resolved.get("description", "")),
            "example": resolved.get("schema", {}).get("example", None),
            "default": resolved.get("schema", {}).get("default", None),
            "enum": resolved.get("schema", {}).get("enum", None),
        })

    # 展开返回值（只取关键的200/201/204 成功响应 + 常见错误码）
    responses_resolved = {}
    for status_code, resp in ep.get("responses", {}).items():
        resolved = resolver.resolve(resp)
        # 提取 schema（如有）
        schema_info = None
        if "content" in resolved:
            for content_type, content_body in resolved.get("content", {}).items():
                if "schema" in content_body:
                    schema_info = content_body["schema"]
                break

        responses_resolved[status_code] = {
            "description": resolved.get("description", ""),
            "schema": schema_info,
        }

    return {
        "method": ep["method"],
        "path": ep["path"],
        "operation_id": ep["operation_id"],
        "summary": ep["summary"],
        "deprecated": ep.get("deprecated", False),
        "parameters": params_resolved,
        "responses": responses_resolved,
    }


# ============================================================
# 第3步：构建 Prompt
# ============================================================

def build_prompt(tag: str, endpoints: list[dict]) -> str:
    """为一组端点构建 LLM Prompt（改进版）"""
    endpoints_text = ""

    for i, ep in enumerate(endpoints, 1):
        # 废弃标记
        deprecated_note = ""
        if ep.get("deprecated"):
            deprecated_note = " ⚠️【已废弃-仅生成基础冒烟测试】"

        endpoints_text += f"""
---
### 端点{i}: {ep['method']} {ep['path']}{deprecated_note}
- **operationId**: `{ep['operation_id']}`
- **summary**: {ep['summary']}
- **deprecated**: {ep.get('deprecated', False)}

**参数**:
"""
        if ep["parameters"]:
            for p in ep["parameters"]:
                required_mark = "[必填]" if p["required"] else "[可选]"
                enum_hint = f" 可选值: {p['enum']}" if p.get("enum") else ""
                example_hint = f" 示例: {p['example']}" if p.get("example") else ""
                default_hint = f" 默认: {p['default']}" if p.get("default") else ""
                endpoints_text += (
                    f"  - `{p['name']}` ({p['in']}, {p['type']}) {required_mark}"
                )
                hints = " ".join(h for h in [enum_hint, example_hint, default_hint] if h)
                if hints:
                    endpoints_text += f"\n    {hints}"
                if p.get("description"):
                    endpoints_text += f"\n    说明: {p['description'][:200]}"
                endpoints_text += "\n"
        else:
            endpoints_text += "  (无参数)\n"

        endpoints_text += "\n**返回值**:\n"
        for status, resp in ep["responses"].items():
            endpoints_text += f"  - `{status}`: {resp['description']}\n"
            if resp.get("schema"):
                schema_str = json.dumps(resp["schema"], indent=6, ensure_ascii=False)
                if len(schema_str) > 800:
                    schema_str = schema_str[:800] + "\n      ...(已截断)"
                endpoints_text += f"    返回体结构:\n{schema_str}\n"

    prompt = f"""你是一个资深 Python 自动化测试工程师。请根据以下 Spotify Web API 端点定义，
为「{tag}」类别的接口生成 pytest 测试用例。

{endpoints_text}
---
## 生成要求

### 1. 测试文件结构
- 文件名: `test_{tag.lower()}.py`
- 使用 `pytest` + `requests` 库
- **不要在本文件中定义 `base_url` 和 `auth_token` fixture**
  它们已在 `conftest.py` 中定义为 session 级 fixture，直接通过函数参数引用即可
- import 写法: `import conftest  # noqa: F401`

### 2. 类命名规范
- 格式: `Test{{operationId驼峰形式}}`
- 坏例子: `TestGetGetMultipleAlbums`（重复了 Get）
- 好例子: `TestGetMultipleAlbums`、`TestSaveAlbumsUser`

### 3. 测试用例范围（每个端点）

#### 正向测试
- 使用参数示例值构造请求，断言成功状态码 (200/201/204)
- 注意: YAML中的 `example` 是文档示例，不是保证可用的真实数据
- 直接在代码中用注释标明: `# TODO: 替换为真实测试数据`
- 返回体断言：用 `isinstance(body["xxx"], list)` / `isinstance(body["xxx"], dict)` 做类型检查
  **不要**用 `len(data["albums"]) == N` 这种严格数量相等（API 可能返回不同数量）

#### 异常测试
- 缺少必填参数: 断言 `status_code in [400, 403, 404]`（不同 API 返回不同，不做单一值断言）
- 无效参数值: 断言 `status_code in [400, 403, 404]`

#### 鉴权测试
- 不传 token: 断言 `response.status_code == 401`
- 无效 token: 断言 `response.status_code == 401`
- 对 401 响应: 还需断言返回体含 `error` 字段

#### 边界测试
- 仅当参数有明确的 limit/offset 且有 min/max 说明时才生成边界用例
- limit≥1、limit≤N、limit=0（越界）三种

### 4. 废弃端点特殊处理
- 如果端点标注 `deprecated: true`，**只生成 1 个正向测试和 1 个鉴权测试**
- 不生成异常测试、边界测试、参数化测试
- 在类 docstring 中标注: `(deprecated)`

### 5. 代码风格
- 使用 `@pytest.mark.parametrize` 做数据驱动
- 每个函数写简短中文 docstring 说明测试目的
- 不要 import 不在代码中使用的库
- 只输出 Python 代码，不要输出解释文字
- 用 ```python 和 ``` 包裹代码
"""
    return prompt


# ============================================================
# 第3B步：有状态端点专用 Prompt（--mode stateful）
# ============================================================

def build_stateful_prompt(endpoints_by_tag: dict) -> str:
    """为 need_code 端点构建链路测试 Prompt"""
    endpoints_text = ""
    total = 0

    # 定义工作流
    workflows = {}
    for tag, eps in endpoints_by_tag.items():
        for ep in eps:
            total += 1
            op_id = ep["operation_id"]
            reason = ep.get("reason", "")
            ep_info = f"- {ep['method']} {ep['path']} | operationId: {op_id} | reason: {reason}"
            endpoints_text += f"  {ep_info}\n"

            # 根据 operation_id 归类到工作流
            if "albums" in op_id or "album" in op_id:
                workflows.setdefault("album_lifecycle", []).append(ep)
            elif "follow" in op_id:
                workflows.setdefault("follow_lifecycle", []).append(ep)

    # 工作流描述
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

    prompt = f"""你是资深 Python 自动化测试工程师。以下 {total} 个 Spotify API 端点是**有状态写操作**，
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
- 在类中定义 `@pytest.fixture` 提供测试数据：
  - `test_album_id`: 返回一个已知 album ID（# TODO: 替换为真实可用ID）
  - `test_artist_id`: 返回一个已知 artist ID（# TODO: 替换为真实可用ID）
- `base_url` 和 `auth_token` 通过 conftest.py 注入，不要在本文件定义

### 3. 用例设计（每个工作流至少包含）
- **正向链路**: setup(无) → action(PUT) → verify(GET contains 返回 true) → cleanup(DELETE)
- **幂等测试**: 重复执行 PUT，断言不报错
- **鉴权测试**: 不传 token 执行 PUT，断言 401
- **无效参数**: 传入无效 ID，断言 [400, 403, 404]

### 4. 代码风格
- import conftest  # noqa: F401
- 每个测试函数有简短中文 docstring
- cleanup 用 try/finally 确保即使断言失败也执行
- 使用 `@pytest.mark.parametrize` 做数据驱动
- 状态码异常断言用 `in [400, 403, 404]`

### 5. 约束
- 只输出 Python 代码，不输出解释
- 用 ```python 和 ``` 包裹代码
"""
    return prompt


# ============================================================
# 第4步：调用 LLM
# ============================================================

def call_llm(prompt: str) -> str | None:
    """调用 OpenAI 兼容 API 生成测试代码"""
    try:
        from openai import OpenAI
    except ImportError:
        print("请先安装 openai: pip install openai")
        print("当前模式：仅输出 Prompt（不调用 LLM）")
        return None

    if LLM_API_KEY == "sk-your-key-here":
        print("⚠️  未设置 LLM_API_KEY 环境变量，仅输出 Prompt")
        return None

    client = OpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)
    print(f"  → 调用 LLM ({LLM_MODEL})...")

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "你是一个专业的 Python 自动化测试工程师。请严格按照要求生成 pytest 测试代码，只输出代码块。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=8192,
    )
    return response.choices[0].message.content


# ============================================================
# 第5步：解析并保存生成的代码
# ============================================================

def save_generated_code(tag: str, raw_output: str, suffix: str = ""):
    """从 LLM 返回中提取 Python 代码并保存"""
    import re

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"test_{tag.lower()}{suffix}.py")

    # 提取 ```python ... ``` 代码块
    match = re.search(r"```python\s*\n(.*?)```", raw_output, re.DOTALL)
    if match:
        code = match.group(1).strip()
    else:
        # 兜底：尝试提取 ``` ... ```
        match = re.search(r"```\s*\n(.*?)```", raw_output, re.DOTALL)
        if match:
            code = match.group(1).strip()
        else:
            code = raw_output.strip()

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"  ✓ 已保存: {filepath}")


# ============================================================
# main
# ============================================================

def main():
    # 命令行参数解析
    single_path = SINGLE_ENDPOINT
    mode = "default"  # default | stateful
    if "--single" in sys.argv:
        idx = sys.argv.index("--single")
        if idx + 1 < len(sys.argv):
            single_path = sys.argv[idx + 1]
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]

    print("=" * 60)
    print("Spotify API 测试用例生成器")
    print(f"  模式: {mode}")
    if single_path:
        print(f"  [单接口] 只处理: {single_path}")
    print(f"  LLM: {LLM_MODEL} @ {LLM_API_BASE}")
    print(f"  跳过可选参数: {SKIP_OPTIONAL_PARAMS}")
    print("=" * 60)

    # 1. 加载
    with open(YAML_PATH) as f:
        spec = yaml.safe_load(f)
    with open(JSON_PATH) as f:
        data = json.load(f)

    resolver = RefResolver(spec)

    # ── stateful 模式：只处理 need_code 端点 ──
    if mode == "stateful":
        if not os.path.exists(CLASSIFY_PATH):
            print(f"❌ 未找到 {CLASSIFY_PATH}，请先运行 classify_endpoints.py")
            sys.exit(1)
        with open(CLASSIFY_PATH) as f:
            classify = json.load(f)
        need_code = classify.get("need_code", [])
        if not need_code:
            print("⚠️  没有 need_code 端点，跳过")
            return

        # 按 tag 分组
        from collections import defaultdict
        nc_by_tag = defaultdict(list)
        for ep in need_code:
            nc_by_tag[ep["tag"]].append(ep)

        prompt = build_stateful_prompt(dict(nc_by_tag))
        print(f"\n📦 有状态端点: {len(need_code)} 个")
        print(f"  ✓ Prompt 构建完成")

        # 保存 prompt
        os.makedirs("prompts", exist_ok=True)
        prompt_file = "prompts/prompt_stateful.txt"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"  ✓ Prompt 已保存: {prompt_file}")

        llm_output = call_llm(prompt)
        if llm_output:
            save_generated_code("stateful_workflows", llm_output)
        print(f"\n{'=' * 60}\n完成！\n{'=' * 60}")
        return

    # ── default 模式：原有逻辑 ──
    for tag, endpoints_raw in data.items():
        # 单接口模式：只保留匹配 path 的端点
        if single_path:
            endpoints_raw = [ep for ep in endpoints_raw if ep["path"] == single_path]
            if not endpoints_raw:
                continue

        print(f"\n📦 处理 {tag} ({len(endpoints_raw)} 个端点)")

        # 2. 展开 $ref
        endpoints = [build_endpoint_info(ep, resolver) for ep in endpoints_raw]
        print(f"  ✓ $ref 展开完成")

        # 3. 构建 Prompt
        prompt = build_prompt(tag, endpoints)

        # 保存 Prompt（方便调试）
        prompt_dir = "prompts"
        os.makedirs(prompt_dir, exist_ok=True)
        suffix = f"_{single_path.replace('/', '_')}" if single_path else ""
        prompt_file = os.path.join(prompt_dir, f"prompt_{tag.lower()}{suffix}.txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"  ✓ Prompt 已保存: {prompt_file}")

        # 4. 调用 LLM
        llm_output = call_llm(prompt)
        if llm_output:
            if single_path:
                save_generated_code(tag, llm_output,
                                    suffix=f"_{single_path.replace('/', '_')}")
            else:
                save_generated_code(tag, llm_output)
        else:
            print(f"  ⚠️  跳过 LLM 调用，Prompt 已保存到 prompts/ 目录")
            print(f"     请在 .env 中设置 LLM_API_KEY 后重新运行")

    print(f"\n{'=' * 60}")
    print("完成！")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
