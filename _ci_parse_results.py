"""Jenkins CI 辅助脚本：执行测试并输出 "passed skipped failed" """
import subprocess, sys, re, os

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "--tb=no", "-q", "--junitxml=reports/junit.xml"],
    capture_output=True, text=True, timeout=120,
)

m = re.search(r'(\d+)\s+passed', result.stdout)
passed = int(m.group(1)) if m else 0
m = re.search(r'(\d+)\s+skipped', result.stdout)
skipped = int(m.group(1)) if m else 0
m = re.search(r'(\d+)\s+failed', result.stdout)
failed = int(m.group(1)) if m else 0

# 输出到文件，Groovy 再读取
os.makedirs("reports", exist_ok=True)
with open("reports/ci_result.txt", "w") as f:
    f.write(f"{passed} {skipped} {failed}")

print(f"{passed} passed, {failed} failed, {skipped} skipped")
sys.exit(failed)  # Jenkins 检查退出码
