import os, re, json, sys

PATTERNS = [
    (re.compile(r"http://[^\s\"']+"), "plaintext_http"),
    (re.compile(r"\bAPI_KEY\b\s*=\s*['\"]([^'\"]+)['\"]"), "api_key_literal"),
    (re.compile(r"\bsk_[A-Za-z0-9]{5,}\b"), "secret_like"),
]

MANIFEST_TRACKING_RE = re.compile(r"com\\.[^"]*analytics[^"]*", re.IGNORECASE)
MANIFEST_AD_RE = re.compile(r"com\\.[^"]*ad[^"]*", re.IGNORECASE)

ALLOWED_EXTS = {".json", ".asset", ".cs", ".txt", ".yaml", ".yml"}

def scan_file(path, relpath):
    findings = []
    is_manifest = relpath.replace("\\", "/").endswith("Packages/manifest.json")
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, start=1):
                text = line.rstrip("\n")
                # General patterns
                for rx, kind in PATTERNS:
                    for m in rx.finditer(text):
                        findings.append({
                            "path": relpath,
                            "line": i,
                            "type": kind,
                            "match": m.group(0)
                        })
                # Manifest-specific lightweight checks
                if is_manifest:
                    for m in MANIFEST_TRACKING_RE.finditer(text):
                        findings.append({
                            "path": relpath,
                            "line": i,
                            "type": "tracking_package",
                            "match": m.group(0)
                        })
                    for m in MANIFEST_AD_RE.finditer(text):
                        findings.append({
                            "path": relpath,
                            "line": i,
                            "type": "ad_like_package",
                            "match": m.group(0)
                        })
    except Exception as e:
        findings.append({
            "path": relpath,
            "line": None,
            "type": "read_error",
            "match": str(e)
        })
    return findings

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 tools/scan.py <input_dir> <output_json>", file=sys.stderr)
        sys.exit(2)
    root = sys.argv[1]
    out_path = sys.argv[2]
    all_findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in ALLOWED_EXTS:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, start=os.path.dirname(root)) if os.path.isabs(root) else os.path.relpath(full)
                all_findings.extend(scan_file(full, rel))
    with open(out_path, "w", encoding="utf-8") as out:
        json.dump(all_findings, out, indent=2)

if __name__ == "__main__":
    main()
