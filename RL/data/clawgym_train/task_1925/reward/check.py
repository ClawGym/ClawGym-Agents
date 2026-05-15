import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def file_nonempty(path):
    if not os.path.isfile(path):
        return False
    try:
        return os.path.getsize(path) > 0
    except Exception:
        return False

def has_substring_ci(text, needle):
    if text is None:
        return False
    return needle.lower() in text.lower()

def digits_only(s):
    return re.sub(r"\D", "", s or "")

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def csv_read_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            return list(reader)
    except Exception:
        return None

def check_fire_escape(path):
    if not file_nonempty(path):
        return False
    content = read_text(path)
    if content is None or not content.strip():
        return False
    checks = [
        "two exits" in content.lower(),
        "meeting point:" in content.lower(),
        "smoke detector" in content.lower(),
        ("drill" in content.lower()) or ("practice" in content.lower()),
    ]
    return all(checks)

def check_communication_plan(path, workspace_root):
    data = load_json(path)
    if not isinstance(data, dict):
        return False
    required_keys = ["out_of_area_contact", "meeting_points", "communication_methods", "wallet_cards_file"]
    if not all(k in data for k in required_keys):
        return False

    # out_of_area_contact
    oac = data.get("out_of_area_contact")
    if not isinstance(oac, dict):
        return False
    name = oac.get("name")
    phone = oac.get("phone")
    if not isinstance(name, str) or not name.strip():
        return False
    if not isinstance(phone, str) or len(digits_only(phone)) < 10:
        return False

    # meeting_points
    mp = data.get("meeting_points")
    if not isinstance(mp, dict):
        return False
    for key in ["home", "neighborhood", "out_of_area"]:
        val = mp.get(key)
        if not isinstance(val, str) or not val.strip():
            return False

    # communication_methods
    cm = data.get("communication_methods")
    if not isinstance(cm, list) or len(cm) == 0 or not all(isinstance(x, str) and x.strip() for x in cm):
        return False

    # wallet_cards_file
    wcf = data.get("wallet_cards_file")
    if wcf != "output/cards/emergency_cards.csv":
        return False
    cards_path = os.path.join(workspace_root, wcf)
    if not file_nonempty(cards_path):
        return False

    return True

def check_emergency_cards(path):
    if not file_nonempty(path):
        return False
    rows = csv_read_rows(path)
    if not rows or len(rows) < 5:
        return False
    header = [h.strip() for h in rows[0]]
    required = [
        "name",
        "role",
        "phone_primary",
        "phone_secondary",
        "out_of_area_contact_name",
        "out_of_area_contact_phone",
        "meeting_point_home",
        "meeting_point_neighborhood",
        "meeting_point_out_of_area",
    ]
    header_lower = [h.lower() for h in header]
    if not all(col in header_lower for col in required):
        return False
    # Check no "TBD" anywhere
    for row in rows:
        for cell in row:
            if cell is not None and "tbd" in cell.lower():
                return False
    return True

def check_document_kit(path):
    if not file_nonempty(path):
        return False
    content = read_text(path)
    if content is None or not content.strip():
        return False
    lc = content.lower()
    # Required mentions
    has_ids = "government-issued id" in lc  # covers ids/id
    has_insurance = "insurance policies" in lc
    has_medical_records = "medical records" in lc
    has_cash = "cash" in lc
    has_digital_or_encrypted = ("digital" in lc) or ("encrypted" in lc)
    # Pet records: look for 'pet' and 'record' in content (anywhere)
    has_pet_records = ("pet" in lc) and ("record" in lc)
    return all([has_ids, has_insurance, has_medical_records, has_cash, has_digital_or_encrypted, has_pet_records])

def check_go_bags(path):
    if not file_nonempty(path):
        return False
    rows = csv_read_rows(path)
    if not rows or len(rows) < 2:
        return False
    header = [h.strip() for h in rows[0]]
    header_lower = [h.lower() for h in header]
    required = ["owner", "category", "item", "qty", "notes"]
    if not all(col in header_lower for col in required):
        return False
    # Determine column indices
    idx_owner = header_lower.index("owner")
    idx_item = header_lower.index("item")
    idx_notes = header_lower.index("notes")
    owners_found = {"Nora": False, "Luis": False, "Eli": False, "Rosa": False}
    has_insulin = False
    has_n95 = False
    has_pet_or_cat = False

    for row in rows[1:]:
        if len(row) < max(idx_owner, idx_item, idx_notes) + 1:
            continue
        owner = row[idx_owner]
        item = row[idx_item]
        notes = row[idx_notes]
        for k in owners_found.keys():
            if isinstance(owner, str) and k in owner:
                owners_found[k] = True
        text_fields = " ".join([item or "", notes or ""]).lower()
        if "insulin" in text_fields:
            has_insulin = True
        if "n95" in text_fields:
            has_n95 = True
        if ("pet" in text_fields) or ("cat" in text_fields):
            has_pet_or_cat = True

    return all(list(owners_found.values()) + [has_insulin, has_n95, has_pet_or_cat])

def check_evacuation_routes(path):
    data = load_json(path)
    if not isinstance(data, dict):
        return False
    # Keys
    if "routes" not in data or "destinations" not in data or "avoid" not in data:
        return False
    routes = data.get("routes")
    if not isinstance(routes, dict):
        return False
    for key in ["primary", "alternate", "backup"]:
        r = routes.get(key)
        if not isinstance(r, dict):
            return False
        name = r.get("name")
        desc = r.get("description")
        if not (isinstance(name, str) and name.strip()) or not (isinstance(desc, str) and desc.strip()):
            return False
    # Destinations
    dests = data.get("destinations")
    if not isinstance(dests, list) or len(dests) < 2:
        return False
    types = set()
    for d in dests:
        if isinstance(d, dict) and isinstance(d.get("type"), str):
            types.add(d.get("type"))
    if "friend_or_relative" not in types:
        return False
    if not (("public_shelter" in types) or ("hotel" in types)):
        return False
    # Avoid list
    avoid = data.get("avoid")
    if not isinstance(avoid, list) or len(avoid) == 0:
        return False
    avoid_strs = [str(a).lower() for a in avoid]
    if not any(("low-water" in a) or ("flood" in a) for a in avoid_strs):
        return False
    return True

def check_utility_shutoffs(path):
    if not file_nonempty(path):
        return False
    content = read_text(path)
    if content is None or not content.strip():
        return False
    lc = content.lower()
    has_gas = "gas" in lc
    has_water = "water" in lc
    has_electric = "electric" in lc
    has_label = "label" in lc
    has_wrench = "wrench" in lc
    return all([has_gas, has_water, has_electric, has_label, has_wrench])

def check_special_needs(path):
    if not file_nonempty(path):
        return False
    content = read_text(path)
    if content is None or not content.strip():
        return False
    lc = content.lower()
    has_insulin = "insulin" in lc
    has_cooling = ("cooler" in lc) or ("ice pack" in lc) or ("ice packs" in lc)
    has_mobility = ("mobility" in lc) or ("cane" in lc) or ("stairs" in lc)
    has_helper_phrase = "designated helper" in lc
    return all([has_insulin, has_cooling, has_mobility, has_helper_phrase])

def check_reminders(path):
    data = load_json(path)
    if not isinstance(data, dict):
        return False
    for key in ["fire_drill", "go_bag_rotation", "annual_review"]:
        entry = data.get(key)
        if not isinstance(entry, dict):
            return False
        note = entry.get("note")
        due = entry.get("due_date")
        if not (isinstance(note, str) and note.strip()):
            return False
        if not (isinstance(due, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", due or "")):
            return False
    return True

def check_assumptions(path):
    return file_nonempty(path)

def check_no_placeholders(plan_dir, cards_dir):
    # Ensure no file under these directories contains "TBD" (case-insensitive)
    allowed_exts = {".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".xml", ".html", ".py"}
    for d in [plan_dir, cards_dir]:
        if not os.path.isdir(d):
            # If directory missing, we consider placeholder check fail-safe: do not pass since required files are elsewhere failing anyway
            return False
        for root, dirs, files in os.walk(d):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in allowed_exts:
                    fpath = os.path.join(root, fname)
                    text = read_text(fpath)
                    if text is None:
                        continue
                    if "tbd" in text.lower():
                        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    # Prepare expected paths
    fire_escape_path = os.path.join(output_dir, "plan", "fire_escape.md")
    comm_plan_path = os.path.join(output_dir, "plan", "communication_plan.json")
    cards_csv_path = os.path.join(output_dir, "cards", "emergency_cards.csv")
    doc_kit_path = os.path.join(output_dir, "plan", "document_kit_checklist.md")
    go_bags_path = os.path.join(output_dir, "plan", "go_bags.csv")
    evac_routes_path = os.path.join(output_dir, "plan", "evacuation_routes.json")
    utility_path = os.path.join(output_dir, "plan", "utility_shutoffs.md")
    special_needs_path = os.path.join(output_dir, "plan", "special_needs.md")
    reminders_path = os.path.join(output_dir, "schedule", "reminders.json")
    assumptions_path = os.path.join(output_dir, "plan", "assumptions.md")

    checks = {
        "fire_escape_ok": False,
        "communication_plan_ok": False,
        "emergency_cards_ok": False,
        "document_kit_ok": False,
        "go_bags_ok": False,
        "evac_routes_ok": False,
        "utility_shutoffs_ok": False,
        "special_needs_ok": False,
        "reminders_ok": False,
        "assumptions_ok": False,
        "no_placeholders_ok": False,
    }

    # Perform checks
    checks["fire_escape_ok"] = check_fire_escape(fire_escape_path)
    checks["communication_plan_ok"] = check_communication_plan(comm_plan_path, workspace_root)
    checks["emergency_cards_ok"] = check_emergency_cards(cards_csv_path)
    checks["document_kit_ok"] = check_document_kit(doc_kit_path)
    checks["go_bags_ok"] = check_go_bags(go_bags_path)
    checks["evac_routes_ok"] = check_evacuation_routes(evac_routes_path)
    checks["utility_shutoffs_ok"] = check_utility_shutoffs(utility_path)
    checks["special_needs_ok"] = check_special_needs(special_needs_path)
    checks["reminders_ok"] = check_reminders(reminders_path)
    checks["assumptions_ok"] = check_assumptions(assumptions_path)
    # Placeholder check must scan output/plan and output/cards
    plan_dir = os.path.join(output_dir, "plan")
    cards_dir = os.path.join(output_dir, "cards")
    checks["no_placeholders_ok"] = check_no_placeholders(plan_dir, cards_dir)

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Ensure no-op baseline: if output dir missing or empty of required artifacts, reward stays 0.0
    # This is already satisfied since no checks pass if files are missing.
    result = {"reward": round(reward, 4)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()