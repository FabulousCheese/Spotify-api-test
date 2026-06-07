"""
Spotify API 自动化测试流水线。

流程: 提取端点 → LLM分类 → 生成用例 → 验证 → 执行 → 报告

用法:
  python run_pipeline.py              # 完整流水线
  python run_pipeline.py --skip-llm   # 跳过 LLM 调用（用已有文件）
  python run_pipeline.py --fast       # 只执行已有测试，跳过生成
  python run_pipeline.py --dry-run    # 只收集用例，不执行
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


class Pipeline:
    def __init__(self, skip_llm=False, fast=False, dry_run=False):
        self.skip_llm = skip_llm
        self.fast = fast
        self.dry_run = dry_run
        self.steps_result = []
        self.start_time = time.time()

    def run(self, step_name: str, cmd: list[str], cwd: str = ".") -> bool:
        """执行一个步骤，返回是否成功"""
        banner = f"\n{'='*60}\n▶ {step_name}\n{'='*60}"
        print(banner)

        t0 = time.time()
        result = subprocess.run(cmd, cwd=cwd, capture_output=False)  # 实时输出
        elapsed = time.time() - t0

        ok = result.returncode == 0
        status = "✅ PASS" if ok else f"❌ FAIL (exit={result.returncode})"
        self.steps_result.append({
            "step": step_name, "status": status, "elapsed": round(elapsed, 1),
        })
        print(f"\n  {status}  ({elapsed:.1f}s)")
        return ok

    # ── 步骤函数 ──

    def step_extract(self):
        """提取端点 → extracted_endpoints.json"""
        return self.run("提取端点", [sys.executable, "extract_api.py"])

    def step_classify(self):
        """LLM 分类 → endpoint_classification.json"""
        if self.skip_llm:
            print("  ⏭  跳过（--skip-llm）")
            return True
        return self.run("LLM 分类端点", [sys.executable, "classify_endpoints.py"])

    def step_generate_yaml(self):
        """LLM 生成 YAML 测试数据"""
        if self.skip_llm:
            print("  ⏭  跳过（--skip-llm）")
            return True
        return self.run("生成 YAML 测试数据", [sys.executable, "generate_data_yaml.py"])

    def step_generate_stateful(self):
        """LLM 生成有状态链路测试"""
        if self.skip_llm:
            print("  ⏭  跳过（--skip-llm）")
            return True
        return self.run(
            "生成有状态测试代码",
            [sys.executable, "generate_tests.py", "--mode", "stateful"],
        )

    def step_validate(self):
        """校验测试用例是否可被 pytest 收集"""
        # 1. YAML 语法校验
        print("\n  → 校验 YAML 文件...")
        for yf in Path("test_data").glob("*.yaml"):
            try:
                import yaml
                with open(yf) as f:
                    yaml.safe_load(f)
                print(f"    {yf.name} ✅")
            except Exception as e:
                print(f"    {yf.name} ❌ {e}")
                return self._mark_fail("YAML 校验", str(e), 0)

        # 2. pytest 收集校验
        return self.run(
            "pytest 收集校验",
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        )

    def step_execute_data_driven(self):
        """执行数据驱动测试"""
        return self.run(
            "数据驱动测试",
            [
                sys.executable, "-m", "pytest",
                "tests/test_data_driven.py",
                "-v", "--tb=short",
                "--junitxml=reports/junit_data_driven.xml",
            ],
        )

    def step_execute_stateful(self):
        """执行有状态链路测试"""
        return self.run(
            "有状态链路测试",
            [
                sys.executable, "-m", "pytest",
                "tests/test_stateful_workflows.py",
                "-v", "--tb=short",
                "--junitxml=reports/junit_stateful.xml",
            ],
        )

    def step_report(self):
        """生成汇总报告"""
        elapsed_total = time.time() - self.start_time
        passed = sum(1 for s in self.steps_result if "PASS" in s["status"])
        failed = sum(1 for s in self.steps_result if "FAIL" in s["status"])
        skipped = sum(1 for s in self.steps_result if "SKIP" in s["status"])

        report = {
            "pipeline": "Spotify API 测试流水线",
            "timestamp": datetime.now().isoformat(),
            "total_elapsed": round(elapsed_total, 1),
            "summary": f"{passed} passed, {failed} failed, {skipped} skipped",
            "steps": self.steps_result,
        }

        os.makedirs("reports", exist_ok=True)
        path = "reports/pipeline_report.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        banner = f"""
{'='*60}
  流水线完成
{'='*60}
  耗时: {elapsed_total:.1f}s
  结果: {passed} passed, {failed} failed, {skipped} skipped
"""
        for s in self.steps_result:
            banner += f"  {s['status']:20s}  {s['step']} ({s['elapsed']}s)\n"
        banner += f"{'='*60}"
        print(banner)
        return failed == 0

    def _mark_fail(self, step: str, msg: str, elapsed: float):
        self.steps_result.append({
            "step": step, "status": f"❌ FAIL ({msg})", "elapsed": elapsed,
        })
        return False


def main():
    skip_llm = "--skip-llm" in sys.argv
    fast = "--fast" in sys.argv
    dry_run = "--dry-run" in sys.argv

    pipeline = Pipeline(skip_llm=skip_llm, fast=fast, dry_run=dry_run)

    print("=" * 60)
    print("  Spotify API 自动化测试流水线")
    print(f"  模式: {'LLM跳过' if skip_llm else '完整'}"
          f"{' | 快速' if fast else ''}"
          f"{' | 干跑' if dry_run else ''}")
    print("=" * 60)

    if fast:
        # 快速模式：只执行已有测试
        pipeline.step_execute_data_driven()
        pipeline.step_execute_stateful()
        pipeline.step_report()
        return

    # 完整流程：提取 → 分类 → 生成 → 验证 → 执行 → 报告
    pipeline.step_extract()

    if not skip_llm:
        pipeline.step_classify()
        pipeline.step_generate_yaml()
        pipeline.step_generate_stateful()

    pipeline.step_validate()

    if not dry_run:
        pipeline.step_execute_data_driven()
        pipeline.step_execute_stateful()

    pipeline.step_report()


if __name__ == "__main__":
    main()
