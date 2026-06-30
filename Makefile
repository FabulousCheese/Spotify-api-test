# Spotify API 测试框架 Makefile
# 用法: make <target>

.PHONY: all extract classify generate-data generate-stateful validate test clean help unit report allure-serve audit coverage fix

# ── 完整流水线 ──
all: extract classify generate-data generate-stateful validate test

# ── 快速执行（跳过 LLM 生成） ──
fast: validate test

# ── 单步操作 ──
extract:
	python cli.py extract

classify:
	python cli.py classify

generate-data:
	python cli.py generate --mode data-driven

generate-stateful:
	python cli.py generate --mode stateful

validate:
	python cli.py run --fast --dry-run

test:
	python cli.py run --fast

# ── 单元测试 ──
unit:
	python -m pytest tests/unit/ -v

# ── 类型检查 ──
typecheck:
	mypy src/

# ── 清理 ──
clean:
	rm -rf tests/__pycache__ tests/.pytest_cache .pytest_cache
	rm -rf tests/unit/__pycache__
	rm -rf reports/allure-results/ reports/allure-report/
	rm -rf reports/
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# ── Allure 报告 ──
allure-serve:
	@if [ ! -d reports/allure-results ]; then \
		echo "请先执行测试: make test"; \
		exit 1; \
	fi
	cp -f environment.xml reports/allure-results/ 2>/dev/null || true
	allure serve reports/allure-results

report:
	@if [ ! -d reports/allure-results ]; then \
		echo "请先执行测试: make test"; \
		exit 1; \
	fi
	cp -f environment.xml reports/allure-results/ 2>/dev/null || true
	allure generate reports/allure-results -o reports/allure-report --clean
	@echo "报告已生成: reports/allure-report/index.html"
	allure open reports/allure-report

# ── 审计 & 覆盖率 ──
audit:
	python cli.py audit

coverage:
	python cli.py coverage

fix:
	python cli.py fix

fix-dry:
	python cli.py fix --dry-run

# ── 帮助 ──
help:
	@echo "Spotify API 测试框架"
	@echo ""
	@echo "  make all            完整流水线（提取→分类→生成→验证→执行）"
	@echo "  make fast           快速执行（跳过LLM生成）"
	@echo ""
	@echo "  make extract        提取端点"
	@echo "  make classify       LLM 分类"
	@echo "  make generate-data  生成 YAML 测试数据"
	@echo "  make generate-stateful  生成有状态测试"
	@echo "  make validate       只校验不执行"
	@echo "  make test           执行测试"
	@echo ""
	@echo "  make unit           框架自测"
	@echo "  make typecheck      类型检查"
	@echo "  make clean          清理缓存和报告"
	@echo ""
	@echo "  make allure-serve   生成并打开 Allure 报告（一键）"
	@echo "  make report         生成 Allure HTML 到 reports/allure-report"
	@echo ""
	@echo "  make audit          双角色交叉审计（独立审计师审查测试质量）"
	@echo "  make coverage       端点覆盖率统计"
	@echo "  make fix            根据审计报告自动修复 🤖 类问题"
	@echo "  make fix-dry        预览修复内容（不实际修改）"
