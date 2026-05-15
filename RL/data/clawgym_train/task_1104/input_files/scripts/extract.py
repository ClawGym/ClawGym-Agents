import os, json, re

DATA_DIR = "data/pages"
KEYWORDS = ["rebate"]  # BUG: only rebate, case-sensitive filtering
REGION = "Greenfield County"

# NOTE: This is a quick-and-dirty parser and likely brittle.

def parse_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        html = f.read()
    programs = []
    blocks = re.findall(r'<div class="program">(.*?)</div>', html, flags=re.S)
    for b in blocks:
        name_m = re.search(r'<h2>([^<]+)</h2>', b)
        type_m = re.search(r'class="type">Type:\s*([^<]+)</p>', b)
        sponsor_m = re.search(r'class="sponsor">([^<]+)</p>', b)
        desc_m = re.search(r'class="desc">([^<]+)</p>', b)
        region_m = re.search(r'class="region">Eligible region:\s*([^<]+)</p>', b)
        if not name_m:
            continue
        ptype = type_m.group(1) if type_m else ""
        # BUG: case-sensitive substring match and only 'rebate'
        if not any(k in ptype for k in KEYWORDS):
            continue
        program = {
            "program_name": name_m.group(1).strip(),
            "sponsor": sponsor_m.group(1).strip() if sponsor_m else "",
            "program_type": ptype.strip(),
            "description": desc_m.group(1).strip() if desc_m else "",
            # BUG: fallback region is hardcoded constant
            "region": region_m.group(1).strip() if region_m else REGION
            # NOTE: no source_file field
        }
        programs.append(program)
    return programs

def main():
    all_programs = []
    # BUG: processes any filename containing ".html" substring and uses string concat for paths
    for fn in os.listdir(DATA_DIR):
        if ".html" in fn:
            all_programs.extend(parse_file(DATA_DIR + "/" + fn))
    os.makedirs("build", exist_ok=True)
    # BUG: only writes JSON to a hardcoded path; no CSV output
    with open("build/programs.json", "w", encoding="utf-8") as out:
        json.dump(all_programs, out, indent=2, ensure_ascii=False)
    print("Wrote", len(all_programs), "records to build/programs.json")

if __name__ == "__main__":
    main()
