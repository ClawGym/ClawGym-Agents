import sys, csv, re, difflib, os

USAGE = "Usage: python tools/validate_quotes.py <synthesis.md> <sources.csv>"

def load_sources(csv_path):
    ids = set()
    excerpts = set()
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get('id', '').strip()
            ex = row.get('excerpt', '').strip()
            if sid:
                ids.add(sid)
            if ex:
                excerpts.add(ex)
    return ids, excerpts

def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(USAGE)
        sys.exit(2)

    synth_path = sys.argv[1]
    sources_path = sys.argv[2]

    if not os.path.exists(synth_path):
        print(f"ERROR: synthesis file not found: {synth_path}")
        sys.exit(1)
    if not os.path.exists(sources_path):
        print(f"ERROR: sources file not found: {sources_path}")
        sys.exit(1)

    ids, excerpts = load_sources(sources_path)
    text = read_text(synth_path)

    # Find direct quotes of length >= 10 characters inside double quotes
    quotes = re.findall(r'"([^"\n]{10,})"', text)

    # Find citations like [source:ID]
    cited_ids = re.findall(r'\[source:([A-Za-z0-9]+)\]', text)

    errors = []

    # Validate quotes exactly match an excerpt
    for q in quotes:
        q_clean = q.strip()
        if q_clean not in excerpts:
            # Suggest closest match by similarity
            closest = difflib.get_close_matches(q_clean, list(excerpts), n=1, cutoff=0.6)
            hint = f" Did you mean: \"{closest[0]}\"?" if closest else ""
            errors.append(f"ERROR: Unknown quote: \"{q_clean}\".{hint}")

    # Validate cited IDs exist
    for cid in cited_ids:
        if cid not in ids:
            errors.append(f"ERROR: Unknown source ID: {cid}")

    # Minimum requirements
    if len(quotes) < 2:
        errors.append("ERROR: Fewer than 2 direct quotes found.")
    if len(cited_ids) < 5:
        errors.append("ERROR: Fewer than 5 citations [source:ID] found.")

    # Summary
    print(f"Found {len(quotes)} direct quotes and {len(cited_ids)} citations.")
    if errors:
        for e in errors:
            print(e)
        sys.exit(1)
    else:
        print("OK: All quotes validated and citation counts satisfied.")
        sys.exit(0)
