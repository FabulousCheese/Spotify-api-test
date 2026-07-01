"""
Spotify API 自动化测试框架 — 统一 CLI 入口。

用法:
  python cli.py extract              # 提取端点
  python cli.py classify             # LLM 分类
  python cli.py generate --mode data-driven   # 生成 YAML 测试数据
  python cli.py generate --mode stateful      # 生成有状态链路测试
  python cli.py generate --single "/albums/{id}"  # 单接口调试
  python cli.py run --fast           # 快速执行已有测试
  python cli.py run --skip-llm       # 跳过 LLM 生成
  python cli.py run --dry-run        # 只收集用例不执行
  python cli.py review               # LLM 专家审查（--force 强制执行）
  python cli.py review --fix         # 审查后运行 audit + auto_fix
  python cli.py pipeline             # 完整流水线
  python cli.py report               # 生成 Allure HTML 报告并打开浏览器
  python cli.py audit                # 双角色交叉审计测试数据质量
  python cli.py fix                  # 根据审计报告自动修复问题
  python cli.py coverage             # 端点覆盖率统计
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

from src.logger import setup_logging, get_logger


def cmd_extract(args: argparse.Namespace) -> int:
    """提取端点 → extracted_endpoints.json"""
    from src.extractor import extract_endpoints

    logger = get_logger("extract")
    logger.info("开始提取端点...")
    extract_endpoints(target_tags=args.tags.split(",") if args.tags else None)
    logger.info("提取完成")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    """LLM 分类端点 → endpoint_classification.json"""
    from src.classifier import classify_endpoints
    from src.llm_client import LLMClient
    from src.config import get_config

    logger = get_logger("classify")
    cfg = get_config()

    if not cfg.has_llm:
        logger.error("未设置 LLM_API_KEY，请检查 .env 文件")
        return 1

    with open(cfg.extracted_path, encoding="utf-8") as f:
        endpoints = json.load(f)

    client = LLMClient()
    classify_endpoints(endpoints, client)
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """生成测试用例 (YAML 数据 / 有状态代码)"""
    from src.llm_client import LLMClient
    from src.config import get_config

    logger = get_logger("generate")
    cfg = get_config()

    if not cfg.has_llm:
        logger.error("未设置 LLM_API_KEY")
        return 1

    client = LLMClient()

    if args.mode == "data-driven":
        from src.yaml_generator import generate_yaml_cases

        if not Path(cfg.classify_path).exists():
            logger.error("未找到 %s，请先运行 classify", cfg.classify_path)
            return 1

        with open(cfg.classify_path, encoding="utf-8") as f:
            classify_data = json.load(f)

        dd_endpoints = classify_data.get("data_driven", [])
        logger.info("共 %d 个 data_driven 端点", len(dd_endpoints))

        if args.single:
            dd_endpoints = [ep for ep in dd_endpoints if ep["path"] == args.single]
            if not dd_endpoints:
                logger.error("未找到路径: %s", args.single)
                return 1

        generate_yaml_cases(dd_endpoints, client=client)
        return 0

    elif args.mode == "stateful":
        from src.test_generator import generate_stateful_tests

        if not Path(cfg.classify_path).exists():
            logger.error("未找到 %s", cfg.classify_path)
            return 1

        with open(cfg.classify_path, encoding="utf-8") as f:
            classify_data = json.load(f)

        need_code = classify_data.get("need_code", [])
        generate_stateful_tests(need_code, client=client)
        return 0

    else:
        logger.error("未知模式: %s (可选: data-driven, stateful)", args.mode)
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """执行测试 + 生成报告"""
    from src.pipeline import Pipeline

    logger = get_logger("run")

    pipeline = Pipeline(
        skip_llm=args.skip_llm,
        fast=args.fast,
        dry_run=args.dry_run,
    )

    if args.fast:
        pipeline.step_coverage()
        pipeline.step_execute_data_driven()
        pipeline.step_execute_stateful()
        pipeline.step_report()
        _write_ci_result(pipeline)
        if _generate_allure_report(logger) and not args.no_open:
            _serve_allure_report()
        return 0

    if not args.skip_llm:
        pipeline.step_extract()
        pipeline.step_classify()
        pipeline.step_generate_yaml()
        pipeline.step_generate_stateful()
        pipeline.step_audit()
        pipeline.step_coverage()

    pipeline.step_validate()

    if not args.dry_run:
        pipeline.step_execute_data_driven()
        pipeline.step_execute_stateful()

    failed = pipeline.step_report()

    # CI 兼容：写入 ci_result.txt
    _write_ci_result(pipeline)
    return failed


def cmd_audit(args: argparse.Namespace) -> int:
    """双角色交叉审计 — 独立审计师审查测试数据质量"""
    from src.auditor import audit_yaml_cases, audit_stateful_code, save_audit_report
    from src.llm_client import LLMClient
    from src.config import get_config

    logger = get_logger("audit")
    cfg = get_config()

    if not cfg.has_llm:
        logger.error("未设置 LLM_API_KEY")
        return 1

    client = LLMClient()
    logger.info("开始双角色交叉审计...")
    yaml_result = audit_yaml_cases(client=client)
    code_result = audit_stateful_code(client=client)
    save_audit_report(yaml_result, code_result)

    logger.info("YAML 质量评分: %d/100", yaml_result.get("score", 0))
    logger.info("代码质量评分: %d/100", code_result.get("score", 0))
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """端点覆盖率统计"""
    from src.coverage import compute_coverage, save_coverage_report

    logger = get_logger("coverage")
    coverage = compute_coverage()
    save_coverage_report(coverage)

    logger.info("=" * 40)
    logger.info("端点覆盖率: %.1f%% (%d/%d)",
                coverage["rate"], coverage["covered"], coverage["total"])
    logger.info("  YAML 数据驱动: %d 端点", coverage.get("yaml_sources", 0))
    logger.info("  有状态链路: %d 端点", coverage.get("code_sources", 0))

    uncovered = coverage.get("uncovered", [])
    if uncovered:
        logger.info("  未覆盖 (%d):", len(uncovered))
        for ep in uncovered:
            logger.info("    %s", ep)

    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    """根据审计报告自动修复标记为可自动修复的问题"""
    from src.auditor import auto_fix
    from src.llm_client import LLMClient
    from src.config import get_config

    logger = get_logger("fix")
    cfg = get_config()

    report_path = "reports/audit_report.json"
    if not Path(report_path).exists():
        logger.error("未找到审计报告，请先运行: python cli.py audit")
        return 1

    if not cfg.has_llm:
        logger.error("未设置 LLM_API_KEY")
        return 1

    client = LLMClient()

    if args.dry_run:
        logger.info("预览模式 — 不会实际修改文件")

    result = auto_fix(
        audit_report_path=report_path,
        client=client,
        dry_run=args.dry_run,
    )

    if result.get("error"):
        return 1

    fixed = result.get("fixed", 0)
    skipped = result.get("skipped", 0)
    failed = result.get("failed", 0)

    logger.info("=" * 40)
    logger.info("修复结果: 🤖 自动修复 %d 个, 👤 跳过 %d 个 (需人工), ❌ 失败 %d 个",
                fixed, skipped, failed)
    if result.get("files_changed"):
        logger.info("修改的文件: %s", ", ".join(result["files_changed"]))
        logger.info("备份文件: %s", ", ".join(f + ".bak" for f in result["files_changed"]))
        logger.info("恢复命令: cp test_data/*.bak test_data/ && rm test_data/*.bak")

    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """LLM 专家审查 & 自动改进"""
    from src.reviewer import review_and_improve, run_tests
    from src.llm_client import LLMClient
    from src.config import get_config

    logger = get_logger("review")
    cfg = get_config()

    if not cfg.has_llm:
        logger.error("未设置 LLM_API_KEY")
        return 1

    logger.info("执行测试...")
    result = run_tests()
    logger.info("初次结果: %d passed, %d failed (%.1f%%)",
                result["passed"], result["failed"], result["pass_rate"])

    if not args.force and result["pass_rate"] >= cfg.pass_threshold:
        logger.info("通过率已达 %.1f%%，无需审查（使用 --force 强制执行）", result["pass_rate"])
        _save_review_log("success", [])
        return 0

    if args.force:
        logger.info("强制启动 LLM 专家审查（通过率 %.1f%%）", result["pass_rate"])
    else:
        logger.info("通过率 %.1f%% < %.0f%%，启动 LLM 专家审查", result["pass_rate"], cfg.pass_threshold)
    client = LLMClient()
    ok = review_and_improve(result, client, max_retries=args.max_retries)

    if args.auto_fix:
        logger.info("运行 audit + auto_fix 精确修复...")
        from src.auditor import audit_yaml_cases, audit_stateful_code, save_audit_report, auto_fix
        yaml_result = audit_yaml_cases(client=client)
        code_result = audit_stateful_code(client=client)
        save_audit_report(yaml_result, code_result)
        fix_result = auto_fix(client=client)
        logger.info("fix: 🤖 fixed=%d, 👤 skipped=%d, ❌ failed=%d",
                    fix_result.get("fixed", 0), fix_result.get("skipped", 0),
                    fix_result.get("failed", 0))

    return 0 if ok else 1


def cmd_report(args: argparse.Namespace) -> int:
    """生成 Allure HTML 报告并打开。"""
    logger = get_logger("report")
    if not _generate_allure_report(logger):
        return 1
    if not args.no_open:
        _serve_allure_report()
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    """完整流水线: extract → classify → generate → validate → execute → report"""
    logger = get_logger("pipeline")

    # 复用 cmd_run 逻辑（跳过 --fast 的快捷路径）
    args.fast = False
    return cmd_run(args)


# ── 辅助函数 ──

def _generate_allure_report(logger: Any) -> bool:
    """生成 Allure HTML 报告。返回是否成功。"""
    import shutil
    allure_results = Path("reports/allure-results")
    allure_report = Path("reports/allure-report")

    if not allure_results.exists() or not list(allure_results.glob("*.json")):
        logger.warning("无 Allure 结果文件，跳过 HTML 报告生成")
        return False

    env_src = Path("environment.xml")
    if env_src.exists():
        shutil.copy(env_src, allure_results / "environment.xml")

    logger.info("生成 Allure HTML 报告...")
    result = subprocess.run(
        ["allure", "generate", str(allure_results), "-o", str(allure_report), "--clean"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info("Allure 报告: %s", (allure_report / "index.html").resolve())
        return True
    logger.warning("Allure 报告生成失败（是否已安装 allure CLI？）")
    return False


def _serve_allure_report() -> None:
    """启动本地 HTTP 服务打开 Allure 报告，避免 file:// 协议的 500 问题。"""
    import socket
    import webbrowser
    from http.server import HTTPServer, SimpleHTTPRequestHandler

    report_dir = Path("reports/allure-report").resolve()
    if not (report_dir / "index.html").exists():
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, directory=str(report_dir), **kwargs)

    url = f"http://127.0.0.1:{port}"
    webbrowser.open(url)
    print(f"Allure 报告: {url}")
    print("按 Ctrl+C 停止服务")

    server = HTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def _write_ci_result(pipeline: Any) -> None:
    """输出 CI 兼容的结果文件。"""
    logger = get_logger("cli")
    passed = sum(1 for s in pipeline.steps_result
                 if "PASS" in str(s.get("status", "")))
    failed = sum(1 for s in pipeline.steps_result
                 if "FAIL" in str(s.get("status", "")))
    skipped = sum(1 for s in pipeline.steps_result
                  if "SKIP" in str(s.get("status", "")))

    Path("reports").mkdir(exist_ok=True)
    content = f"{passed} {skipped} {failed}"
    (Path("reports") / "ci_result.txt").write_text(content, encoding="utf-8")
    logger.info("CI 结果: %s", content)


def _save_review_log(status: str, history: list[dict[str, Any]]) -> None:
    Path("reports").mkdir(exist_ok=True)
    (Path("reports") / "review_history.json").write_text(
        json.dumps({"status": status, "history": history}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── CLI 构建 ──

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spotify-test",
        description="Spotify API 自动化测试框架 — LLM 驱动, 数据驱动, CI 就绪",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--quiet", "-q", action="store_true", help="安静模式")

    sub = parser.add_subparsers(dest="command", help="可用命令")

    # extract
    p_extract = sub.add_parser("extract", help="从 OpenAPI 规范提取端点")
    p_extract.add_argument("--tags", type=str, help="目标 tag，逗号分隔 (默认: Albums,Artists)")

    # classify
    sub.add_parser("classify", help="LLM 分类端点 (data_driven / need_code)")

    # generate
    p_gen = sub.add_parser("generate", help="LLM 生成测试用例")
    p_gen.add_argument("--mode", type=str, default="data-driven",
                       choices=["data-driven", "stateful"],
                       help="生成模式 (默认: data-driven)")
    p_gen.add_argument("--single", type=str, help="单接口调试: 指定路径如 /albums/{id}")

    # run
    p_run = sub.add_parser("run", help="执行测试")
    p_run.add_argument("--fast", action="store_true", help="快速模式: 只执行已有测试")
    p_run.add_argument("--skip-llm", action="store_true", help="跳过 LLM 生成步骤")
    p_run.add_argument("--dry-run", action="store_true", help="只收集用例不执行")
    p_run.add_argument("--no-open", action="store_true", help="不自动打开浏览器查看报告")

    # review
    p_review = sub.add_parser("review", help="LLM 专家审查 & 自动改进")
    p_review.add_argument("--max-retries", type=int, default=2, help="最大审查轮数 (默认: 2)")
    p_review.add_argument("--force", action="store_true", help="强制执行审查，即使通过率已达阈值")
    p_review.add_argument("--fix", action="store_true", dest="auto_fix", help="审查结束后运行 audit + auto_fix 精确修复")

    # pipeline
    sub.add_parser("pipeline", help="完整流水线 (extract→classify→generate→validate→execute)")

    # report
    p_report = sub.add_parser("report", help="生成 Allure HTML 报告并打开")
    p_report.add_argument("--no-open", action="store_true", help="不自动打开浏览器")

    # audit
    sub.add_parser("audit", help="双角色交叉审计（独立审计师审查测试质量）")

    # coverage
    sub.add_parser("coverage", help="端点覆盖率统计")

    # fix
    p_fix = sub.add_parser("fix", help="根据审计报告自动修复 🤖 类问题")
    p_fix.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    setup_logging(verbose=args.verbose)
    logger = get_logger("cli")

    if args.quiet:
        import logging
        logging.getLogger().setLevel(logging.WARNING)

    commands: dict[str, Callable[[argparse.Namespace], int]] = {
        "extract": cmd_extract,
        "classify": cmd_classify,
        "generate": cmd_generate,
        "run": cmd_run,
        "review": cmd_review,
        "pipeline": cmd_pipeline,
        "report": cmd_report,
        "audit": cmd_audit,
        "coverage": cmd_coverage,
        "fix": cmd_fix,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            return handler(args)
        except Exception as e:
            logger.exception("命令 '%s' 执行失败: %s", args.command, e)
            return 1
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
