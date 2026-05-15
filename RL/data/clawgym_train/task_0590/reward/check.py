import json
import os
import sys
import csv
from datetime import datetime, date, timedelta

# Workspace root handling
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_date_yyyy_mm_dd(path):
    txt = read_text(path)
    if not txt:
        return None
    s = txt.strip()
    try:
        # Expect YYYY-MM-DD
        dt = datetime.strptime(s, "%Y-%m-%d").date()
        return dt
    except Exception:
        return None

def compute_tone_for_2026(d):
    # Tones cycle 1..13. Given calendar in supporting skill:
    # 2026-01-01 is Tone 10 (Planetary). We map from that anchor.
    # tone(d) = ((10 - 1 + delta_days) % 13) + 1
    if not isinstance(d, date):
        return None, None
    anchor = date(2026, 1, 1)
    delta = (d - anchor).days
    if delta < 0 or d.year != 2026:
        # Only defined for 2026 per provided calendar
        # We still compute modularly for robustness
        pass
    idx = ((10 - 1 + (delta % 13)) % 13) + 1
    tone_names = {
        1: "Magnetic",
        2: "Lunar",
        3: "Electric",
        4: "Self-Existing",
        5: "Overtone",
        6: "Rhythmic",
        7: "Resonant",
        8: "Galactic",
        9: "Solar",
        10: "Planetary",
        11: "Spectral",
        12: "Crystal",
        13: "Cosmic",
    }
    return idx, tone_names.get(idx, None)

def try_import_yaml():
    try:
        import yaml  # type: ignore
        return yaml
    except Exception:
        return None

def parse_simple_yaml(text):
    # Minimal YAML parser for basic mappings/lists with string scalars and nested dicts.
    # Supports keys with ":" and lists with "- ". Quotes around values are stripped.
    lines = text.splitlines()
    # Preprocess: remove comments (simple) and keep indentation
    tokens = []
    for ln in lines:
        if not ln.strip():
            continue
        # Remove inline comments only if not inside quotes (very simple heuristic)
        s = ln
        # Keep full line; comments starting with '#' at start of line will be ignored
        if s.lstrip().startswith("#"):
            continue
        tokens.append(ln.rstrip("\n"))
    if not tokens:
        return None
    root = None
    stack = []  # list of tuples (indent, container)
    pending_key_stack = []  # track last key awaiting nested content at each mapping level

    def current_container():
        return stack[-1][1] if stack else None

    def top_indent():
        return stack[-1][0] if stack else -1

    i = 0
    n = len(tokens)
    while i < n:
        line = tokens[i]
        indent = len(line) - len(line.lstrip(" "))
        content = line[indent:]
        # adjust stack for current indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
            if pending_key_stack:
                pending_key_stack.pop()
        if content.startswith("- "):
            # list item
            parent = current_container()
            if parent is None:
                # create a root list
                parent = []
                root = parent
                stack.append((indent - 2 if indent >= 2 else 0, parent))
                pending_key_stack.append(None)
            if not isinstance(parent, list):
                # If parent is a dict with a pending key expecting a list, create it
                if isinstance(parent, dict):
                    # try to use last pending key
                    # Not reliable; fallback: create last key as list if possible
                    pk = pending_key_stack[-1] if pending_key_stack else None
                    if pk and (parent.get(pk) is None or isinstance(parent.get(pk), (list, dict))):
                        if not isinstance(parent.get(pk), list):
                            parent[pk] = []
                        parent = parent[pk]
                        # push the list as new context
                        stack.append((indent - 2 if indent >= 2 else 0, parent))
                        pending_key_stack.append(None)
                    else:
                        # cannot resolve structure; create anonymous list context
                        # Wrap root-level list
                        lst = []
                        if root is None:
                            root = lst
                        parent = lst
                        stack.append((indent - 2 if indent >= 2 else 0, parent))
                        pending_key_stack.append(None)
                else:
                    # Unexpected
                    pass
            # Now parse list item value
            after = content[2:].strip()
            if after == "":
                # An empty list item (treat as None)
                parent.append(None)
                # push context? Not needed
                i += 1
                continue
            # If after looks like "key: value" mapping on same line
            if ":" in after:
                # Handle "key: value" or "key:"
                key, val = after.split(":", 1)
                key = key.strip()
                val = val.strip()
                item = {}
                if val != "":
                    # scalar value
                    sval = val
                    if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                        sval = sval[1:-1]
                    item[key] = sval
                    parent.append(item)
                    # This item may have further nested keys on following lines with greater indent
                    # Push this item context for subsequent lines
                    stack.append((indent, item))
                    pending_key_stack.append(None)
                else:
                    # value is empty; next lines define nested mapping or list
                    item[key] = None
                    parent.append(item)
                    # Lookahead to decide container type for key
                    j = i + 1
                    next_nonempty = None
                    while j < n:
                        ln2 = tokens[j]
                        ind2 = len(ln2) - len(ln2.lstrip(" "))
                        cnt2 = ln2[ind2:]
                        if cnt2.strip() == "" or cnt2.lstrip().startswith("#"):
                            j += 1
                            continue
                        if ind2 > indent:
                            next_nonempty = cnt2
                        break
                    # Create appropriate container
                    if next_nonempty and next_nonempty.startswith("- "):
                        item[key] = []
                    else:
                        item[key] = {}
                    # push item and then the newly created container as current context
                    stack.append((indent, item))
                    pending_key_stack.append(None)
                    # push the nested container
                    stack.append((indent + 2, item[key]))
                    pending_key_stack.append(None)
                i += 1
                continue
            else:
                # scalar list item
                sval = after
                if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                    sval = sval[1:-1]
                parent.append(sval)
                i += 1
                continue
        else:
            # mapping entry "key: value" or "key:"
            if ":" not in content:
                # Unrecognized line; skip
                i += 1
                continue
            key, val = content.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Ensure a parent mapping exists for this indent
            parent = current_container()
            if parent is None:
                parent = {}
                root = parent
                stack.append((indent - 2 if indent >= 2 else 0, parent))
                pending_key_stack.append(None)
            if isinstance(parent, list):
                # Convert list context to a new dict item and use that as mapping parent
                new_item = {}
                parent.append(new_item)
                parent = new_item
                # push new dict context
                stack.append((indent - 2 if indent >= 2 else 0, parent))
                pending_key_stack.append(None)
            if not isinstance(parent, dict):
                # Cannot handle other types
                i += 1
                continue
            if val != "":
                sval = val
                if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                    sval = sval[1:-1]
                parent[key] = sval
                # Reset pending key at this level
                if pending_key_stack:
                    pending_key_stack[-1] = None
                i += 1
                continue
            else:
                # No immediate value; decide container type by lookahead
                j = i + 1
                next_nonempty = None
                next_indent = None
                while j < n:
                    ln2 = tokens[j]
                    ind2 = len(ln2) - len(ln2.lstrip(" "))
                    cnt2 = ln2[ind2:]
                    if cnt2.strip() == "" or cnt2.lstrip().startswith("#"):
                        j += 1
                        continue
                    next_nonempty = cnt2
                    next_indent = ind2
                    break
                if next_nonempty and next_indent is not None and next_indent > indent and next_nonempty.startswith("- "):
                    parent[key] = []
                else:
                    parent[key] = {}
                # push mapping context and nested container
                stack.append((indent, parent))
                pending_key_stack.append(key)
                stack.append((indent + 2, parent[key]))
                pending_key_stack.append(None)
                i += 1
                continue
    return root

def parse_yaml(text):
    # Try PyYAML if available, else fallback
    y = try_import_yaml()
    if y:
        try:
            return y.safe_load(text)
        except Exception:
            pass
    try:
        return parse_simple_yaml(text)
    except Exception:
        return None

def extract_percentage_line(text, prefix):
    # Returns float percentage value if line starting with prefix exists
    # e.g., "Gross Margin: 72.5%"
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            # Extract number before % from the remainder
            rest = line.strip()[len(prefix):].strip()
            # rest like "72.5%"
            num = ""
            for ch in rest:
                if (ch.isdigit() or ch in ".-"):
                    num += ch
                elif ch == "%":
                    break
                elif ch == " ":
                    continue
                else:
                    # Unexpected char
                    continue
            try:
                return float(num)
            except Exception:
                return None
    return None

def compute_expected_margins(csv_path):
    # Aggregate for period == 2026Q1
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rev = 0.0
            cogs = 0.0
            ebit = 0.0
            net = 0.0
            for row in reader:
                period = (row.get("period") or "").strip()
                if period != "2026Q1":
                    continue
                def parse_float(v):
                    try:
                        return float(v)
                    except Exception:
                        return 0.0
                rev += parse_float(row.get("revenue", 0))
                cogs += parse_float(row.get("cogs", 0))
                ebit += parse_float(row.get("ebit", 0))
                net += parse_float(row.get("net_income", 0))
            if rev <= 0:
                return None
            gross_margin = ((rev - cogs) / rev) * 100.0
            op_margin = (ebit / rev) * 100.0
            net_margin = (net / rev) * 100.0
            # Round to 1 decimal place for comparison target
            gm_r = round(gross_margin, 1)
            om_r = round(op_margin, 1)
            nm_r = round(net_margin, 1)
            return gm_r, om_r, nm_r
    except Exception:
        return None

def contains_all_substrings(text, subs, case_insensitive=True):
    if text is None:
        return False
    t = text.lower() if case_insensitive else text
    for s in subs:
        s2 = s.lower() if case_insensitive else s
        if s2 not in t:
            return False
    return True

# Initialize checks
checks = {
    "has_SOUL": False,
    "soul_sections_ok": False,
    "has_IDENTITY": False,
    "has_AGENTS": False,
    "agents_sections_ok": False,
    "agents_lifecycle_ok": False,
    "has_USER": False,
    "has_HEARTBEAT": False,
    "heartbeat_sections_ok": False,
    "has_MEMORY": False,
    "has_TEAM": False,
    "team_sections_ok": False,
    "has_handoff": False,
    "handoff_yaml_ok": False,
    "handoff_required_fields": False,
    "has_cron": False,
    "cron_yaml_ok": False,
    "cron_jobs_ok": False,
    "cron_notes_tone_ok": False,
    "has_report": False,
    "report_lines_ok": False,
    "report_benchmark_ok": False,
    "report_findings_ok": False,
    "report_recommendations_ok": False,
    "report_values_match": False
}

# Paths
soul_path = os.path.join(output_dir, "SOUL.md")
identity_path = os.path.join(output_dir, "IDENTITY.md")
agents_path = os.path.join(output_dir, "AGENTS.md")
user_path = os.path.join(output_dir, "USER.md")
heartbeat_path = os.path.join(output_dir, "HEARTBEAT.md")
memory_path = os.path.join(output_dir, "MEMORY.md")
team_path = os.path.join(output_dir, "TEAM.md")
handoff_path = os.path.join(output_dir, "handoffs", "example_handoff.yaml")
cron_path = os.path.join(output_dir, "ops", "cron.yaml")
report_path = os.path.join(output_dir, "reports", "margin_report.md")

# Check existence
if os.path.isfile(soul_path):
    checks["has_SOUL"] = True
    soul_txt = read_text(soul_path) or ""
    if contains_all_substrings(soul_txt, ["Anti-Patterns", "Boundaries"], case_insensitive=False):
        checks["soul_sections_ok"] = True
else:
    soul_txt = ""

if os.path.isfile(identity_path):
    checks["has_IDENTITY"] = True

if os.path.isfile(agents_path):
    checks["has_AGENTS"] = True
    agents_txt = read_text(agents_path) or ""
    # Sections: safety, memory, communication, heartbeats (labels)
    if contains_all_substrings(agents_txt, ["safety", "memory", "communication", "heartbeats"], case_insensitive=True):
        checks["agents_sections_ok"] = True
    # Lifecycle states explicitly include substrings
    lifecycle_required = ["INBOX", "ASSIGNED", "IN PROGRESS", "REVIEW", "DONE"]
    if contains_all_substrings(agents_txt, lifecycle_required, case_insensitive=False):
        checks["agents_lifecycle_ok"] = True
else:
    agents_txt = ""

if os.path.isfile(user_path):
    checks["has_USER"] = True

if os.path.isfile(heartbeat_path):
    checks["has_HEARTBEAT"] = True
    hb_txt = read_text(heartbeat_path) or ""
    if ("Quiet Hours" in hb_txt) and ("HEARTBEAT_OK" in hb_txt):
        checks["heartbeat_sections_ok"] = True
else:
    hb_txt = ""

if os.path.isfile(memory_path):
    checks["has_MEMORY"] = True

if os.path.isfile(team_path):
    checks["has_TEAM"] = True
    team_txt = read_text(team_path) or ""
    if contains_all_substrings(team_txt, ["Hub-and-Spoke", "Orchestrator", "Builder", "Reviewer", "Researcher", "Ops"], case_insensitive=False):
        checks["team_sections_ok"] = True
else:
    team_txt = ""

# Handoff YAML
handoff_obj = None
if os.path.isfile(handoff_path):
    checks["has_handoff"] = True
    handoff_txt = read_text(handoff_path) or ""
    handoff_obj = parse_yaml(handoff_txt) if handoff_txt else None
    if isinstance(handoff_obj, dict):
        checks["handoff_yaml_ok"] = True
        ho = handoff_obj.get("handoff") if isinstance(handoff_obj.get("handoff"), (dict,)) else None
        if isinstance(ho, dict):
            req_keys_present = True
            for k in ["from", "to", "task_id", "artifacts", "verification", "next_action"]:
                if k not in ho:
                    req_keys_present = False
                    break
            # artifacts must be list with at least one item having path
            artifacts_ok = False
            if req_keys_present:
                arts = ho.get("artifacts")
                if isinstance(arts, list) and len(arts) >= 1:
                    for it in arts:
                        if isinstance(it, dict) and "path" in it:
                            artifacts_ok = True
                            break
            # verification.command exists
            ver_ok = False
            if req_keys_present:
                ver = ho.get("verification")
                if isinstance(ver, dict) and "command" in ver:
                    ver_ok = True
            checks["handoff_required_fields"] = bool(req_keys_present and artifacts_ok and ver_ok)
    else:
        checks["handoff_yaml_ok"] = False

# Cron YAML
cron_obj = None
cron_txt = ""
if os.path.isfile(cron_path):
    checks["has_cron"] = True
    cron_txt = read_text(cron_path) or ""
    cron_obj = parse_yaml(cron_txt) if cron_txt else None
    if cron_obj is not None:
        checks["cron_yaml_ok"] = True
        # Find jobs (either list at root, or under key 'jobs')
        jobs = []
        if isinstance(cron_obj, list):
            jobs = [j for j in cron_obj if isinstance(j, dict)]
        elif isinstance(cron_obj, dict):
            if isinstance(cron_obj.get("jobs"), list):
                jobs = [j for j in cron_obj.get("jobs") if isinstance(j, dict)]
            else:
                # Also consider dict values that are job dicts in a mapping
                for v in cron_obj.values():
                    if isinstance(v, list):
                        jobs.extend([j for j in v if isinstance(j, dict)])
        # Count jobs that have schedule, payload, delivery
        job_count = 0
        notes_fields = []
        for j in jobs:
            if isinstance(j.get("schedule"), str) and isinstance(j.get("payload"), dict) and isinstance(j.get("delivery"), dict):
                job_count += 1
                if "notes" in j:
                    notes_fields.append(j.get("notes"))
        if job_count >= 2 and ("announce" in cron_txt):
            checks["cron_jobs_ok"] = True
        # Check notes mention the derived tone
        in_date_path = os.path.join(input_dir, "date.txt")
        d = read_date_yyyy_mm_dd(in_date_path)
        tone_idx, tone_name = compute_tone_for_2026(d) if d else (None, None)
        tone_ok = False
        if notes_fields:
            for n in notes_fields:
                if not isinstance(n, str):
                    continue
                if tone_idx is not None and (("Tone {}".format(tone_idx)) in n or (tone_name and tone_name in n)):
                    tone_ok = True
                    break
        # Additionally, for specific date 2026-05-24 accept either "Tone 10" or "Planetary"
        if d == date(2026, 5, 24):
            # Relax to accept if any notes mention Tone 10 or Planetary
            for n in notes_fields:
                if isinstance(n, str) and (("Tone 10" in n) or ("Planetary" in n)):
                    tone_ok = True
                    break
        checks["cron_notes_tone_ok"] = tone_ok

# Margin report
if os.path.isfile(report_path):
    checks["has_report"] = True
    report_txt = read_text(report_path) or ""
    gm_val = extract_percentage_line(report_txt, "Gross Margin:")
    om_val = extract_percentage_line(report_txt, "Operating Margin:")
    nm_val = extract_percentage_line(report_txt, "Net Margin:")
    if (gm_val is not None) and (om_val is not None) and (nm_val is not None):
        checks["report_lines_ok"] = True
    if "vs Industry Benchmark" in report_txt:
        checks["report_benchmark_ok"] = True
    if "TOP 3 FINDINGS:" in report_txt:
        checks["report_findings_ok"] = True
    if "RECOMMENDATIONS:" in report_txt:
        checks["report_recommendations_ok"] = True
    # Compare to expected values from CSV
    csv_path = os.path.join(input_dir, "company_financials.csv")
    expected = compute_expected_margins(csv_path)
    if expected and checks["report_lines_ok"]:
        egm, eom, enm = expected
        tol = 0.2  # percentage points
        if abs(gm_val - egm) <= tol and abs(om_val - eom) <= tol and abs(nm_val - enm) <= tol:
            checks["report_values_match"] = True

# Compute reward
total_checks = len(checks)
passed = sum(1 for v in checks.values() if v)
reward = passed / total_checks if total_checks > 0 else 0.0

# No-op baseline: if output dir missing or empty, ensure reward is exactly 0.0
if (not os.path.isdir(output_dir)) or (len([name for name in os.listdir(output_dir)]) == 0):
    reward = 0.0

result = {"reward": round(reward, 6)}
result.update(checks)

print(json.dumps(result))