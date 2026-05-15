import json
import os
import sys

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    txt = read_text(path)
    if txt is None:
        return None
    # Normalize newlines
    return txt.splitlines()

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def find_section_ranges(lines, headers):
    # returns dict header -> (start_index, end_index)
    # header must match line.strip() == header (case-sensitive)
    positions = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s in headers:
            positions.append((s, i))
    ranges = {}
    header_order = [h for h in headers if any(h == pos[0] for pos in positions)]
    # map positions by header
    header_to_index = {h: i for (h, i) in positions}
    for idx, h in enumerate(headers):
        if h not in header_to_index:
            continue
        start = header_to_index[h] + 1  # content starts after header line
        # find next header position
        next_pos = None
        for j in range(header_to_index[h] + 1, len(lines)):
            if lines[j].strip() in headers:
                next_pos = j
                break
        end = next_pos if next_pos is not None else len(lines)
        ranges[h] = (start, end)
    return ranges

def count_bullets(section_lines):
    count = 0
    for line in section_lines:
        ls = line.lstrip()
        if ls.startswith('-') or ls.startswith('*'):
            count += 1
    return count

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Read canonical hash from input/arkos_canon.json
canon_path = os.path.join(input_dir, "arkos_canon.json")
canon_json = load_json(canon_path)
lygo_hash = None
if isinstance(canon_json, dict):
    h = canon_json.get("lygo_mint_sha256")
    if isinstance(h, str):
        lygo_hash = h

checks = {
    "arkos_blueprint_exists": False,
    "arkos_blueprint_headers_ok": False,
    "arkos_intent_words_ok": False,
    "arkos_constraints_words_ok": False,
    "arkos_blueprint_words_ok": False,
    "arkos_observed_inferred_unknown_present": False,
    "arkos_failure_modes_bullets_ok": False,
    "arkos_receipts_anchor_ok": False,
    "arkos_includes_sha256": False,

    "risk_register_exists": False,
    "risk_register_header_ok": False,
    "risk_register_rows_ok": False,
    "risk_register_has_security_or_ethics": False,

    "refactor_plan_exists": False,
    "refactor_plan_header_ok": False,
    "refactor_plan_rows_ok": False,
    "refactor_plan_header_tab_delimited": False,

    "verification_receipts_exists": False,
    "verification_receipts_valid_json": False,
    "verification_receipts_min_items": False,
    "verification_receipts_schema_ok": False,
    "verification_receipts_has_hash_evidence": False,
    "verification_receipts_has_drill_or_rollback": False,
}

# 1) arkos_blueprint.md checks
arkos_path = os.path.join(output_dir, "arkos_blueprint.md")
arkos_lines = read_lines(arkos_path)
if arkos_lines is not None:
    checks["arkos_blueprint_exists"] = True
    arkos_text = "\n".join(arkos_lines)

    headers = [
        "1) Intent",
        "2) Constraints",
        "3) Blueprint",
        "4) Failure modes",
        "5) Refactor path",
        "6) Receipts",
    ]
    has_all_headers = all(any(line.strip() == h for line in arkos_lines) for h in headers)
    checks["arkos_blueprint_headers_ok"] = has_all_headers

    section_ranges = find_section_ranges(arkos_lines, headers)

    # Intent words: 'intent' and 'preserve' (case-insensitive) within Intent section body
    intent_ok = False
    if "1) Intent" in section_ranges:
        s, e = section_ranges["1) Intent"]
        intent_text = "\n".join(arkos_lines[s:e]).lower()
        if ("intent" in intent_text) and ("preserve" in intent_text):
            intent_ok = True
    checks["arkos_intent_words_ok"] = intent_ok

    # Constraints words: 'ethics' and 'security' (case-insensitive) within Constraints section
    constraints_ok = False
    if "2) Constraints" in section_ranges:
        s, e = section_ranges["2) Constraints"]
        ct_text = "\n".join(arkos_lines[s:e]).lower()
        if ("ethics" in ct_text) and ("security" in ct_text):
            constraints_ok = True
    checks["arkos_constraints_words_ok"] = constraints_ok

    # Blueprint words: 'modules' and 'interfaces' (case-insensitive) within Blueprint section
    blueprint_words_ok = False
    if "3) Blueprint" in section_ranges:
        s, e = section_ranges["3) Blueprint"]
        bp_text = "\n".join(arkos_lines[s:e]).lower()
        if ("modules" in bp_text) and ("interfaces" in bp_text):
            blueprint_words_ok = True
    checks["arkos_blueprint_words_ok"] = blueprint_words_ok

    # Observed/Inferred/Unknown anywhere in file (case-sensitive as specified)
    oiuk_ok = ("Observed" in arkos_text) and ("Inferred" in arkos_text) and ("Unknown" in arkos_text)
    checks["arkos_observed_inferred_unknown_present"] = oiuk_ok

    # Failure modes: at least 5 bullet lines between Failure modes and next header
    failure_ok = False
    if "4) Failure modes" in section_ranges:
        s, e = section_ranges["4) Failure modes"]
        bullets = count_bullets(arkos_lines[s:e])
        if bullets >= 5:
            failure_ok = True
    checks["arkos_failure_modes_bullets_ok"] = failure_ok

    # Receipts section includes ARKOS_OMEGA_FRAME
    receipts_anchor_ok = False
    if "6) Receipts" in section_ranges:
        s, e = section_ranges["6) Receipts"]
        receipts_text = "\n".join(arkos_lines[s:e])
        if "ARKOS_OMEGA_FRAME" in receipts_text:
            receipts_anchor_ok = True
    checks["arkos_receipts_anchor_ok"] = receipts_anchor_ok

    # arkos includes SHA-256 from input anywhere in file
    includes_hash_ok = False
    if isinstance(lygo_hash, str) and len(lygo_hash) > 0:
        if lygo_hash in arkos_text:
            includes_hash_ok = True
    checks["arkos_includes_sha256"] = includes_hash_ok

# 2) risk_register.csv checks
risk_path = os.path.join(output_dir, "risk_register.csv")
risk_lines = read_lines(risk_path)
if risk_lines is not None:
    checks["risk_register_exists"] = True
    header_expected = "risk_id,description,impact,likelihood,mitigation,owner"
    header_ok = (risk_lines[0].strip() == header_expected)
    checks["risk_register_header_ok"] = header_ok
    rows_ok = (len(risk_lines) >= 6)
    checks["risk_register_rows_ok"] = rows_ok
    # at least one data row contains 'security' or 'ethic' (case-insensitive)
    has_sec_ethics = False
    for line in risk_lines[1:]:
        l = line.lower()
        if ("security" in l) or ("ethic" in l):
            has_sec_ethics = True
            break
    checks["risk_register_has_security_or_ethics"] = has_sec_ethics

# 3) refactor_plan.tsv checks
refactor_path = os.path.join(output_dir, "refactor_plan.tsv")
ref_lines = read_lines(refactor_path)
if ref_lines is not None:
    checks["refactor_plan_exists"] = True
    header_expected_tsv = "step_id\tdescription\teffort\towner\tdependencies"
    header_ok = (ref_lines[0].strip() == header_expected_tsv)
    checks["refactor_plan_header_ok"] = header_ok
    rows_ok = (len(ref_lines) >= 6)
    checks["refactor_plan_rows_ok"] = rows_ok
    # tab-delimited header
    header_tab_ok = ("\t" in ref_lines[0]) and (len(ref_lines[0].split("\t")) == 5)
    checks["refactor_plan_header_tab_delimited"] = header_tab_ok

# 4) verification_receipts.json checks
ver_path = os.path.join(output_dir, "verification_receipts.json")
ver_json = None
if os.path.isfile(ver_path):
    checks["verification_receipts_exists"] = True
    ver_json = load_json(ver_path)
    valid_json = isinstance(ver_json, list)
    checks["verification_receipts_valid_json"] = valid_json
    if valid_json:
        min_items_ok = len(ver_json) >= 5
        checks["verification_receipts_min_items"] = min_items_ok
        # schema: each object must have string fields: checkpoint, method, evidence
        schema_ok = True
        for item in ver_json:
            if not isinstance(item, dict):
                schema_ok = False
                break
            cp = item.get("checkpoint")
            md = item.get("method")
            ev = item.get("evidence")
            if not (isinstance(cp, str) and isinstance(md, str) and isinstance(ev, str)):
                schema_ok = False
                break
        checks["verification_receipts_schema_ok"] = schema_ok

        # at least one evidence contains the hash
        has_hash_ev = False
        if isinstance(lygo_hash, str) and len(lygo_hash) > 0:
            for item in ver_json:
                ev = item.get("evidence")
                if isinstance(ev, str) and (lygo_hash in ev):
                    has_hash_ev = True
                    break
        checks["verification_receipts_has_hash_evidence"] = has_hash_ev

        # at least one checkpoint or method includes 'drill' or 'rollback' (case-insensitive)
        has_drill_or_rb = False
        for item in ver_json:
            cp = item.get("checkpoint")
            md = item.get("method")
            cp_l = cp.lower() if isinstance(cp, str) else ""
            md_l = md.lower() if isinstance(md, str) else ""
            if ("drill" in cp_l) or ("rollback" in cp_l) or ("drill" in md_l) or ("rollback" in md_l):
                has_drill_or_rb = True
                break
        checks["verification_receipts_has_drill_or_rollback"] = has_drill_or_rb

# Compute reward
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)
reward = 0.0
if passed_checks > 0:
    reward = passed_checks / total_checks

# Ensure no-op baseline: if output/ is missing or empty (no files), reward must be 0.0
try:
    output_exists = os.path.isdir(output_dir)
    output_files = []
    if output_exists:
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                output_files.append(os.path.join(root, f))
    if (not output_exists) or (len(output_files) == 0):
        reward = 0.0
except Exception:
    reward = 0.0

# Clamp reward to [0,1]
if reward < 0.0:
    reward = 0.0
elif reward > 1.0:
    reward = 1.0

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))