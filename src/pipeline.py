"""
流水线编排器 — 将 extract/classify/generate/validate/execute/report 串联执行。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.logger import get_logger

logger = get_logger(__name__)


class Pipeline:
    """测试流水线编排器，支持多种运行模式。"""

    def __init__(
        self,
        skip_llm: bool = False,
        fast: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.skip_llm = skip_llm
        self.fast = fast
        self.dry_run = dry_run
        self.steps_result: list[dict[str, Any]] = []
        self.start_time = time.time()

    def _run_step(self, step_name: str, cmd: list[str], cwd: str = ".") -> bool:
        """执行单个步骤。"""
        banner = f"\n{'=' * 60}\n▶ {step_name}\n{'=' * 60}"
        logger.info(banner)

        t0 = time.time()
        result = subprocess.run(cmd, cwd=cwd, capture_output=False)
        elapsed = time.time() - t0

        ok = result.returncode == 0
        status = "PASS" if ok else f"FAIL (exit={result.returncode})"
        self.steps_result.append({
            "step": step_name, "status": status, "elapsed": round(elapsed, 1),
        })
        logger.info("%s (%s) (%.1fs)", "✅" if ok else "❌", status, elapsed)
        return ok

    def step_extract(self) -> bool:
        return self._run_step("提取端点", [sys.executable, "cli.py", "extract"])

    def step_classify(self) -> bool:
        if self.skip_llm:
            logger.info("⏭ 跳过 (--skip-llm)")
            return True
        return self._run_step("LLM 分类端点", [sys.executable, "cli.py", "classify"])

    def step_generate_yaml(self) -> bool:
        if self.skip_llm:
            logger.info("⏭ 跳过 (--skip-llm)")
            return True
        return self._run_step(
            "生成 YAML 测试数据",
            [sys.executable, "cli.py", "generate", "--mode", "data-driven"],
        )

    def step_generate_stateful(self) -> bool:
        if self.skip_llm:
            logger.info("⏭ 跳过 (--skip-llm)")
            return True
        return self._run_step(
            "生成有状态测试代码",
            [sys.executable, "cli.py", "generate", "--mode", "stateful"],
        )

    def step_audit(self) -> bool:
        """双角色交叉审计：独立审计师审查生成的测试用例质量。"""
        if self.skip_llm:
            logger.info("⏭ 跳过 (--skip-llm)")
            return True

        return self._run_step_llm(
            "双角色交叉审计",
            self._do_audit,
        )

    def _do_audit(self) -> bool:
        from src.auditor import audit_yaml_cases, audit_stateful_code, save_audit_report

        yaml_result = audit_yaml_cases()
        code_result = audit_stateful_code()
        save_audit_report(yaml_result, code_result)

        yaml_score = yaml_result.get("score", 0)
        code_score = code_result.get("score", 0)

        if yaml_score < 60:
            logger.warning("YAML 质量评分 %d < 60，建议人工检查", yaml_score)
        if code_score < 60:
            logger.warning("代码质量评分 %d < 60，建议人工检查", code_score)

        return True  # 审计本身不阻塞流水线，只警告

    def step_coverage(self) -> bool:
        """端点覆盖率统计。"""
        return self._run_step_llm(
            "端点覆盖率统计",
            self._do_coverage,
        )

    def _do_coverage(self) -> bool:
        from src.coverage import compute_coverage, save_coverage_report

        coverage = compute_coverage()
        save_coverage_report(coverage)

        rate = coverage.get("rate", 0)
        uncovered_count = len(coverage.get("uncovered", []))
        logger.info("端点覆盖率: %.1f%% (%d/%d)", rate, coverage.get("covered", 0), coverage.get("total", 0))
        if uncovered_count > 0:
            logger.info("未覆盖端点: %d 个", uncovered_count)

        # 不阻塞流水线，只报告
        return True

    def _run_step_llm(self, step_name: str, func: Any) -> bool:
        """执行 Python 级别的步骤（非 subprocess）。"""
        banner = f"\n{'=' * 60}\n▶ {step_name}\n{'=' * 60}"
        logger.info(banner)

        t0 = time.time()
        try:
            ok = func()
        except Exception as e:
            logger.error("步骤异常: %s", e)
            ok = False

        elapsed = time.time() - t0
        status = "PASS" if ok else f"FAIL"
        self.steps_result.append({
            "step": step_name, "status": status, "elapsed": round(elapsed, 1),
        })
        logger.info("%s (%s) (%.1fs)", "✅" if ok else "❌", status, elapsed)
        return ok

    def step_validate(self) -> bool:
        """校验 YAML 语法 + pytest 收集。"""
        logger.info("→ 校验 YAML 文件...")
        for yf in Path("test_data").glob("*.yaml"):
            try:
                yaml.safe_load(yf.read_text(encoding="utf-8"))
                logger.info("  %s ✅", yf.name)
            except yaml.YAMLError as e:
                logger.error("  %s ❌ %s", yf.name, e)
                return False

        return self._run_step(
            "pytest 收集校验",
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        )

    def step_execute_data_driven(self) -> bool:
        # 清理旧的 allure 结果
        allure_dir = Path("reports/allure-results")
        if allure_dir.exists():
            shutil.rmtree(allure_dir)
        allure_dir.mkdir(parents=True, exist_ok=True)

        return self._run_step(
            "数据驱动测试",
            [
                sys.executable, "-m", "pytest",
                "tests/test_data_driven.py",
                "-v", "--tb=short",
                "--junitxml=reports/junit_data_driven.xml",
                "--alluredir=reports/allure-results",
            ],
        )

    def step_execute_stateful(self) -> bool:
        return self._run_step(
            "有状态链路测试",
            [
                sys.executable, "-m", "pytest",
                "tests/test_stateful_workflows.py",
                "-v", "--tb=short",
                "--junitxml=reports/junit_stateful.xml",
                "--alluredir=reports/allure-results",
            ],
        )

    def step_report(self) -> int:
        """生成汇总报告，返回失败数。"""
        elapsed_total = time.time() - self.start_time
        passed = sum(1 for s in self.steps_result if "PASS" in str(s["status"]))
        failed = sum(1 for s in self.steps_result if "FAIL" in str(s["status"]))
        skipped_count = sum(1 for s in self.steps_result if "SKIP" in str(s["status"]))

        report = {
            "pipeline": "Spotify API 测试流水线",
            "timestamp": datetime.now().isoformat(),
            "total_elapsed": round(elapsed_total, 1),
            "summary": f"{passed} passed, {failed} failed, {skipped_count} skipped",
            "steps": self.steps_result,
        }

        Path("reports").mkdir(exist_ok=True)
        report_path = "reports/pipeline_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # 复制 environment.xml 到 allure-results
        env_src = Path("environment.xml")
        allure_dir = Path("reports/allure-results")
        if env_src.exists():
            allure_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(env_src, allure_dir / "environment.xml")

        banner = "\n".join([
            f"{'=' * 60}",
            "  流水线完成",
            f"{'=' * 60}",
            f"  耗时: {elapsed_total:.1f}s",
            f"  结果: {passed} passed, {failed} failed, {skipped_count} skipped",
        ])
        for s in self.steps_result:
            banner += f"\n  {s['status']:20s}  {s['step']} ({s['elapsed']}s)"
        banner += f"\n{'=' * 60}"
        logger.info(banner)
        return failed
