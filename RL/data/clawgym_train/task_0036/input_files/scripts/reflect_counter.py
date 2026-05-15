import sys, os, re, json

def count_terms(text):
    terms = ["intuition", "introspection", "insight"]
    counts = {}
    for term in terms:
        counts[term] = len(re.findall(r"\\b" + term + r"\\b", text, flags=re.IGNORECASE))
    return counts

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("Error: missing directory argument\n")
        sys.exit(2)
    dir_path = sys.argv[1]
    if not os.path.isdir(dir_path):
        sys.stderr.write(f"Error: directory not found: {dir_path}\n")
        sys.exit(2)

    md_files = sorted([f for f in os.listdir(dir_path) if f.endswith('.md')])
    per_file = {}
    totals = {"intuition": 0, "introspection": 0, "insight": 0}

    for fname in md_files:
        fpath = os.path.join(dir_path, fname)
        with open(fpath, 'r', encoding='utf-8') as fp:
            text = fp.read()
        c = count_terms(text)
        per_file[fname] = c
        for k in totals:
            totals[k] += c[k]

    result = {
        "files": per_file,
        "totals": totals,
        "source_dir": os.path.abspath(dir_path)
    }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")

    # Attempt to read optional file to trigger a benign warning if absent
    opt = os.path.join(dir_path, 'late_addition.md')
    try:
        with open(opt, 'r', encoding='utf-8') as _:
            pass
    except FileNotFoundError:
        sys.stderr.write(f"Warning: optional file {opt} not found; proceeding without it.\n")
        sys.stderr.flush()

    sys.exit(0)
