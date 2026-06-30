"""
端点覆盖率统计 — 对比 OpenAPI 全部端点 vs 已生成测试用例，输出覆盖率报告。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.logger import get_logger

logger = get_logger(__name__)


def compute_coverage(
    extracted_path: str = "extracted_endpoints.json",
    test_data_dir: str = "test_data",
    stateful_test_path: str = "tests/test_stateful_workflows.py",
) -> dict[str, Any]:
    """计算端点测试覆盖率。

    从三个来源汇总：
    1. extracted_endpoints.json — OpenAPI 提取的全部端点
    2. test_data/*.yaml — YAML 数据驱动测试覆盖的端点
    3. tests/test_stateful_workflows.py — 有状态链路测试覆盖的端点

    Returns:
        {"total": 70, "covered": 55, "rate": 78.6, "uncovered": [...], "details": {...}}
    """
    # ── 1. 全部端点 ──
    all_endpoints: list[dict[str, Any]] = []
    extracted_file = Path(extracted_path)
    if extracted_file.exists():
        with open(extracted_file, encoding="utf-8") as f:
            data = json.load(f)
        for tag, eps in data.items():
            for ep in eps:
                ep["_tag"] = tag
                all_endpoints.append(ep)

    total = len(all_endpoints)
    if total == 0:
        logger.warning("未找到提取的端点: %s", extracted_path)
        return {"total": 0, "covered": 0, "rate": 0, "uncovered": [], "details": {}}

    # 用 (method, path) 作为唯一标识
    covered_keys: set[tuple[str, str]] = set()

    # ── 2. YAML 数据驱动 ──
    yaml_endpoints: list[str] = []
    data_dir = Path(test_data_dir)
    for yf in sorted(data_dir.glob("*.yaml")):
        try:
            content = yaml.safe_load(yf.read_text(encoding="utf-8"))
            for ep in content.get("endpoints", []):
                key = (ep.get("method", "GET").upper(), ep["path"])
                covered_keys.add(key)
                yaml_endpoints.append(f"{key[0]} {key[1]}")
        except yaml.YAMLError:
            pass

    # ── 3. 有状态测试代码 ──
    code_endpoints: list[str] = []
    stateful_file = Path(stateful_test_path)
    if stateful_file.exists():
        import re
        content = stateful_file.read_text(encoding="utf-8")
        for m in re.finditer(r'requests\.(get|put|post|delete|patch)\(\s*f?"([^"]+)"', content, re.IGNORECASE):
            method = m.group(1).upper()
            path = m.group(2)
            key = (method, path)
            covered_keys.add(key)
            code_endpoints.append(f"{key[0]} {key[1]}")

    # ── 4. 计算覆盖率 ──
    uncovered: list[str] = []
    details: dict[str, dict[str, Any]] = {}

    for ep in all_endpoints:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "")
        key = (method, path)
        endpoint_str = f"{method} {path}"

        if key in covered_keys:
            details[endpoint_str] = {"status": "covered", "tag": ep.get("_tag", ""), "source": "yaml" if endpoint_str in yaml_endpoints else "code"}
        else:
            details[endpoint_str] = {"status": "uncovered", "tag": ep.get("_tag", "")}
            uncovered.append(endpoint_str)

    covered = sum(1 for d in details.values() if d["status"] == "covered")
    rate = round(covered / total * 100, 1) if total > 0 else 0

    logger.info("端点覆盖率: %d/%d = %.1f%%", covered, total, rate)

    if uncovered:
        logger.info("未覆盖端点 (%d):", len(uncovered))
        for ep in uncovered[:10]:
            logger.info("  %s", ep)
        if len(uncovered) > 10:
            logger.info("  ... 还有 %d 个", len(uncovered) - 10)

    return {
        "total": total,
        "covered": covered,
        "rate": rate,
        "uncovered": uncovered,
        "yaml_sources": len(set(yaml_endpoints)),
        "code_sources": len(set(code_endpoints)),
        "details": details,
    }


def save_coverage_report(
    coverage: dict[str, Any],
    output_dir: str = "reports",
) -> str:
    """保存覆盖率报告到 reports/。"""
    reports_dir = Path(output_dir)
    reports_dir.mkdir(exist_ok=True)

    filepath = reports_dir / "coverage_report.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(coverage, f, indent=2, ensure_ascii=False)

    logger.info("覆盖率报告已保存: %s", filepath)
    return str(filepath)
