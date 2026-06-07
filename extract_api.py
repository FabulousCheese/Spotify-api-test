import json
import yaml
from collections import defaultdict

with open("open-api-schema.yaml") as f:
    spec = yaml.safe_load(f)

# 按 tag 分组
by_tag = defaultdict(list)

for path, methods in spec["paths"].items():
    for method, detail in methods.items():
        if method not in ["get", "post", "put", "delete", "patch"]:
            continue
        for tag in detail.get("tags", []):
            by_tag[tag].append({
                "method": method.upper(),
                "path": path,
                "operation_id": detail.get("operationId"),
                "summary": detail.get("summary", "").strip(),
                "deprecated": detail.get("deprecated", False),
                "parameters": detail.get("parameters", []),
                "responses": detail.get("responses", {}),
            })

# 只取 Albums 和 Artists，按 operation_id 去重（排前面的 tag 优先）
target_tags = ["Albums", "Artists"]
result = {}
seen_ids = set()

for tag in target_tags:
    deduped = []
    for ep in by_tag.get(tag, []):
        op_id = ep["operation_id"]
        if op_id in seen_ids:
            print(f"  [跳过重复] {ep['method']} {ep['path']} (operationId: {op_id}) 已归入其他 tag")
            continue
        seen_ids.add(op_id)
        deduped.append(ep)

    result[tag] = deduped
    print(f"\n=== {tag} ({len(deduped)} 个端点) ===")
    for ep in deduped:
        print(f"  {ep['method']} {ep['path']}")
        print(f"    operationId: {ep['operation_id']}")
        print(f"    summary: {ep['summary']}")

# 写入结果文件
with open("extracted_endpoints.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"\n结果已写入 extracted_endpoints.json")
