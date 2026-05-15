import json
import re
from pathlib import Path
from datetime import datetime

def fail(msg: str):
    print(f"VALIDATION FAILED: {msg}")
    raise SystemExit(1)

def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        fail(f"Cannot read JSON {path}: {e}")

def check_report():
    path = Path("output/system_report.json")
    if not path.exists():
        fail("output/system_report.json not found. Did you run the collector?")
    data = load_json(path)
    for key in ["system", "python", "cpu", "disk", "collected_at"]:
        if key not in data:
            fail(f"Missing top-level key: {key}")
    sys = data["system"]
    py = data["python"]
    cpu = data["cpu"]
    disk = data["disk"]
    for k in ["os_name", "kernel", "machine"]:
        if not isinstance(sys.get(k), str) or not sys.get(k):
            fail(f"system.{k} must be a non-empty string")
    if not isinstance(py.get("version"), str) or not py.get("version"):
        fail("python.version must be a non-empty string")
    if not isinstance(cpu.get("logical_cores"), int) or cpu["logical_cores"] < 0:
        fail("cpu.logical_cores must be a non-negative int")
    for k in ["total_bytes", "used_bytes", "free_bytes"]:
        if not isinstance(disk.get(k), int) or disk[k] < 0:
            fail(f"disk.{k} must be a non-negative int")
    if disk["used_bytes"] + disk["free_bytes"] != disk["total_bytes"]:
        fail("disk.used_bytes + disk.free_bytes must equal disk.total_bytes")
    try:
        datetime.fromisoformat(data["collected_at"])
    except Exception:
        fail("collected_at must be ISO-8601 parseable")
    return sys["os_name"], py["version"]

def check_blog(os_name: str, py_version: str):
    path = Path("blog/draft.md")
    if not path.exists():
        fail("blog/draft.md not found")
    text = path.read_text(encoding="utf-8")
    header = "## System note (auto-generated)"
    idx = text.find(header)
    if idx == -1:
        fail(f'Missing section header: "{header}" in blog/draft.md')
    after = text[idx + len(header):].lstrip("\n\r")
    lines = []
    for line in after.splitlines():
        if not line.strip():
            break
        if line.startswith("## "):
            break
        lines.append(line.strip())
    paragraph = " ".join(lines).strip()
    if not paragraph:
        fail("No paragraph found under the system note header")
    words = re.findall(r"\b\w+\b", paragraph)
    if len(words) > 60:
        fail(f"System note paragraph has {len(words)} words; must be 60 or fewer")
    if os_name not in paragraph:
        fail(f'System note must mention OS name "{os_name}"')
    if py_version not in paragraph:
        fail(f'System note must mention Python version "{py_version}"')
    if "{{" in paragraph or "}}" in paragraph:
        fail("System note still contains template placeholders")

def main():
    os_name, py_ver = check_report()
    check_blog(os_name, py_ver)
    print("OK: validation passed.")

if __name__ == "__main__":
    main()
