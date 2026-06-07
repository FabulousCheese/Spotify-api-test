# Spotify API 测试流水线 Makefile
# 用法: make <target>

.PHONY: all extract classify generate-yaml generate-stateful validate test fast clean help

# ── 完整流水线 ──
all: extract classify generate-yaml generate-stateful validate test

# ── 快速执行（跳过 LLM 生成） ──
fast: validate test

# ── 单步操作 ──
extract:
	python extract_api.py

classify:
	python classify_endpoints.py

generate-yaml:
	python generate_data_yaml.py

generate-stateful:
	python generate_tests.py --mode stateful

validate:
	python run_pipeline.py --fast --dry-run

test:
	python run_pipeline.py --fast

# ── 清理 ──
clean:
	rm -rf tests/__pycache__ tests/.pytest_cache .pytest_cache
	rm -rf reports/

# ── 帮助 ──
help:
	@echo "Spotify API 测试流水线"
	@echo ""
	@echo "  make all            完整流水线（提取→分类→生成→验证→执行）"
	@echo "  make fast           快速执行（跳过LLM生成，只跑已有测试）"
	@echo ""
	@echo "  make extract        只提取端点"
	@echo "  make classify       只做LLM分类"
	@echo "  make generate-yaml  只生成YAML测试数据"
	@echo "  make generate-stateful  只生成有状态测试"
	@echo "  make validate       只校验不执行"
	@echo "  make test           只执行测试"
	@echo "  make clean          清理缓存"
