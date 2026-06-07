# Spotify API 自动化测试框架

基于 **OpenAPI 规范 + LLM（DeepSeek）** 的接口自动化测试方案。从 7500+ 行 YAML 规范自动生成 pytest 测试用例，支持纯数据驱动与有状态链路两种模式。

## 架构

```
open-api-schema.yaml  (Spotify OpenAPI 3.0, 70+ 端点)
        │
        ▼
  extract_api.py       ─── 解析 → $ref 展开 → 按 tag 分组去重
        │
        ▼
  classify_endpoints.py ─── LLM 分类 → data_driven (13) / need_code (4)
        │
        ├──────────────────────┐
        ▼                      ▼
  generate_data_yaml.py   generate_tests.py --mode stateful
  (生成 YAML 测试数据)    (生成链路测试代码)
        │                      │
        ▼                      ▼
  test_data_driven.py     test_stateful_workflows.py
  (通用框架，永不该)       (SETUP→ACTION→VERIFY→CLEANUP)
        │                      │
        └──────────┬───────────┘
                   ▼
            run_pipeline.py    ─── 编排执行 + JUnit 报告
                   │
                   ▼
            Jenkins / GitHub Actions
```

## 快速开始

### 安装

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 配置 `.env`

```ini
# Spotify API 凭证（https://developer.spotify.com/dashboard）
ClientId=your_client_id
Secret=your_client_secret

# DeepSeek API Key（https://platform.deepseek.com/api_keys）
LLM_API_KEY=sk-your-key-here
LLM_API_BASE=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

### 一行跑通

```bash
python run_pipeline.py --fast
```

`--fast` 跳过 LLM 生成步骤，直接执行已有测试。首次使用或修改了 YAML 规范后，跑完整流水线：

```bash
python run_pipeline.py
```

---

## 使用指南

### 方式一：流水线（推荐）

```bash
python run_pipeline.py              # 完整：提取→分类→生成→验证→执行→报告
python run_pipeline.py --fast       # 快速：只执行已有测试
python run_pipeline.py --skip-llm   # 跳过 LLM 调用，用已有文件
python run_pipeline.py --dry-run    # 只收集用例，不执行
```

### 方式二：Makefile

```bash
make all       # 完整流水线
make fast      # 快速测试
make test      # 只执行测试
make clean     # 清理缓存和报告
```

### 方式三：单步执行

```bash
# 第一步：从 OpenAPI 提取端点
python extract_api.py              # → extracted_endpoints.json

# 第二步：LLM 分类（data_driven / need_code）
python classify_endpoints.py       # → endpoint_classification.json

# 第三步 A：生成 YAML 数据驱动用例
python generate_data_yaml.py       # → test_data/*.yaml

# 第三步 B：生成有状态链路用例
python generate_tests.py --mode stateful  # → tests/test_stateful_workflows.py

# 第四步：单接口调试
python generate_tests.py --single "/albums/{id}"   # 生成单个接口的测试
python generate_tests.py --single "/albums"        # 调试另一个

# 第五步：执行测试
pytest tests/ -v
```

### 添加新的测试用例

**数据驱动端点** —— 编辑 YAML，代码不动：

```yaml
# test_data/albums.yaml
- name: test_boundary_id_length
  description: 边界：超长ID
  path_params:
    id: "a" * 500
  query_params: {}
  expect:
    status: [400, 403, 404]
```

**有状态端点** —— 重新让 LLM 生成：

```bash
python generate_tests.py --mode stateful
```

---

## 项目结构

```
├── open-api-schema.yaml           # Spotify OpenAPI 3.0 规范（输入）
│
├── extract_api.py                 # ① 解析 YAML → 按 tag 分组去重
├── classify_endpoints.py          # ② LLM 分类：data_driven vs need_code
├── generate_data_yaml.py          # ③ LLM 生成 YAML 测试数据
├── generate_tests.py              # ③ LLM 生成 pytest 代码（含 --mode stateful）
├── run_pipeline.py                # ④ 流水线编排
│
├── extracted_endpoints.json       # 中间产物：提取的端点
├── endpoint_classification.json   # 中间产物：分类结果
│
├── test_data/                     # YAML 测试数据（只改这里就能加用例）
│   ├── albums.yaml
│   └── artists.yaml
│
├── tests/                         # 测试代码
│   ├── conftest.py                # 公共 fixture（token 获取、base_url）
│   ├── test_data_driven.py        # ★ 通用 YAML 驱动框架（永不该）
│   ├── test_stateful_workflows.py # 有状态链路测试
│   └── test_*.py                  # LLM 生成的独立测试
│
├── prompts/                       # 调试用的 LLM Prompt 存档
├── reports/                       # 测试报告（JUnit XML + JSON）
├── requirements.txt
├── Makefile
└── Jenkinsfile
```

---

## Jenkins 集成

项目已内置 `Jenkinsfile`，配置三步：

1. **添加凭据**：在 Jenkins Credentials 中添加 `deepseek-api-key`、`spotify-client-id`、`spotify-client-secret`
2. **创建 Pipeline Job**：指向仓库 + `Jenkinsfile`
3. **构建**：Jenkins 自动解析 `reports/junit_*.xml` 生成趋势图

```groovy
// 生产环境用 --fast（省钱），定时任务用完整模式
sh 'python run_pipeline.py --fast'
```

---

## 技术栈

| 组件 | 用途 |
|---|---|
| Python 3.12+ | 主语言 |
| pytest + requests | 测试框架 |
| PyYAML | OpenAPI / YAML 解析 |
| DeepSeek API (OpenAI 兼容) | LLM 生成 |
| JUnit XML | Jenkins 集成 |
| python-dotenv | 凭据管理 |

## 核心设计决策

- **$ref 递归展开**：OpenAPI 规范大量使用 `$ref` 引用，LLM 无法直接理解。实现了 3 层深度的递归解析引擎
- **废弃端点处理**：`deprecated: true` 的端点只生成 2 个冒烟用例，不浪费测试资源
- **状态码保守断言**：异常场景用 `[400, 403, 404]` 数组而非单一值，适配 API 实现差异
- **YAML 永不该**：`test_data_driven.py` 通过 `glob("*.yaml")` + `@pytest.mark.parametrize` 实现新增用例零代码改动
- **清理保证**：有状态测试用 `try/finally` 确保异常时也会执行 cleanup
