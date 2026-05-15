#!/usr/bin/env python3
import sys
import re

def load_required_sections(path):
    sections = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^\s*-\s*(.+?)\s*$', line)
            if m:
                sections.append(m.group(1).strip())
    return sections

def has_section(md_text, name):
    pattern = r'^\s*#+\s*' + re.escape(name) + r'\s*$'
    return re.search(pattern, md_text, flags=re.MULTILINE) is not None

def main():
    if len(sys.argv) != 3:
        sys.stderr.write("USAGE: python tools/validate_report.py <report.md> <checklist.yml>\n")
        sys.exit(2)
    md_path, y_path = sys.argv[1], sys.argv[2]
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            md = f.read()
    except Exception as e:
        sys.stderr.write(f"ERROR: cannot read report: {e}\n")
        sys.exit(2)
    try:
        sections = load_required_sections(y_path)
    except Exception as e:
        sys.stderr.write(f"ERROR: cannot read checklist: {e}\n")
        sys.exit(2)
    passes = 0
    fails = 0
    print("Validation start...")
    for s in sections:
        if has_section(md, s):
            print(f"CHECK: Section '{s}' ... PASS")
            passes += 1
        else:
            print(f"CHECK: Section '{s}' ... FAIL")
            sys.stderr.write(f"ERROR: missing section: {s}\n")
            fails += 1
    if "output/metrics.json" in md:
        print("CHECK: Metrics reference ... PASS")
        passes += 1
    else:
        print("CHECK: Metrics reference ... FAIL")
        sys.stderr.write("ERROR: metrics reference missing (expected to see 'output/metrics.json')\n")
        fails += 1
    print(f"SUMMARY: passes={passes}, fails={fails}")
    if fails > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
