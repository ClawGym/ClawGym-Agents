import json
import os
import re
import sys
from datetime import datetime
import csv

def read_text(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def slugify(name):
    if name is None:
        return None
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s

def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def parse_csv(p, delimiter=","):
    rows = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for r in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()})
        return rows
    except Exception:
        return None

def is_number_str(val):
    if val is None:
        return False
    try:
        float(str(val).strip().replace(",", ""))
        return True
    except Exception:
        return False

def to_number(val):
    try:
        s = str(val).strip()
        s = s.replace(",", "")
        if s.endswith("%"):
            num = float(s[:-1].strip())
            return num / 100.0
        return float(s)
    except Exception:
        return None

def parse_simple_yaml_map(yaml_text):
    """
    Very simple YAML-like parser for two-level maps.
    Supports:
    key: value
    key:
      subkey: value
    Lists:
    key:
      - item1
      - item2
    Returns dict with nested dicts or lists. Values coerced to float/bool/None if simple.
    """
    if yaml_text is None:
        return None
    lines = [ln.rstrip("\n\r") for ln in yaml_text.splitlines()]
    data = {}
    i = 0
    def parse_value(v):
        v = v.strip()
        if v == "" or v.lower() in ("null", "none"):
            return None
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        # try number
        if is_number_str(v):
            return to_number(v)
        # strip quotes
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        return v

    while i < len(lines):
        line = lines[i]
        if not line or line.strip().startswith("#"):
            i += 1
            continue
        if re.match(r"^\s", line):
            # unexpected indentation at top-level; skip
            i += 1
            continue
        if ":" in line:
            key, rest = line.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            if rest != "":
                data[key] = parse_value(rest)
                i += 1
                continue
            # block under key
            i += 1
            # determine if list or map
            block_items = []
            block_map = {}
            is_list = None
            while i < len(lines):
                sub = lines[i]
                if not sub.strip():
                    i += 1
                    continue
                if re.match(r"^\S", sub):
                    break
                if re.match(r"^\s*-\s+", sub):
                    if is_list is None:
                        is_list = True
                    m = re.match(r"^\s*-\s+(.*)$", sub)
                    val = parse_value(m.group(1)) if m else None
                    block_items.append(val)
                    i += 1
                else:
                    if is_list is None:
                        is_list = False
                    # expect "  subkey: value" or indented
                    sub = sub.lstrip()
                    if ":" in sub:
                        skey, srest = sub.split(":", 1)
                        skey = skey.strip()
                        srest = srest.strip()
                        if srest != "":
                            block_map[skey] = parse_value(srest)
                            i += 1
                        else:
                            # multi-line under this subkey (list or further map), we will capture simple list
                            i += 1
                            # capture nested list values (e.g., - a, - b)
                            sub_items = []
                            while i < len(lines):
                                deeper = lines[i]
                                if not deeper.strip():
                                    i += 1
                                    continue
                                if re.match(r"^\s{4,}-\s+", deeper):
                                    m2 = re.match(r"^\s{4,}-\s+(.*)$", deeper)
                                    sub_items.append(parse_value(m2.group(1)) if m2 else None)
                                    i += 1
                                elif re.match(r"^\s{2,}\S", deeper):
                                    # another subkey
                                    break
                                else:
                                    break
                            block_map[skey] = sub_items
                    else:
                        i += 1
            data[key] = block_items if is_list else block_map
        else:
            i += 1
    return data

def extract_frontmatter_and_body(md_text):
    if md_text is None:
        return None, None
    lines = md_text.splitlines()
    if len(lines) < 3 or not lines[0].strip().startswith("---"):
        return None, md_text
    fm_lines = []
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip().startswith("---"):
            end_idx = idx
            break
        fm_lines.append(lines[idx])
    if end_idx is None:
        return None, md_text
    fm_text = "\n".join(fm_lines)
    body = "\n".join(lines[end_idx+1:])
    fm = parse_simple_yaml_map(fm_text)
    return fm, body

def parse_alerts_yaml(text):
    # Expect:
    # warranty_expiring_soon:
    #   - slug1
    # lending_overdue:
    #   - slug2
    if text is None:
        return None
    lines = text.splitlines()
    result = {"warranty_expiring_soon": [], "lending_overdue": []}
    current = None
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("warranty_expiring_soon:"):
            current = "warranty_expiring_soon"
            continue
        if stripped.startswith("lending_overdue:"):
            current = "lending_overdue"
            continue
        if current and re.match(r"^- ", stripped):
            item = stripped[2:].strip()
            # trim quotes
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]
            result[current].append(item)
        elif re.match(r"^\S", ln):
            current = None
    return result

def money_from_text(text):
    # Extract first number with optional $ and commas; return float or None
    if text is None:
        return None
    m = re.search(r"(\$|€|£)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2})?)", text)
    if not m:
        return None
    num = m.group(2).replace(",", "")
    try:
        return float(num)
    except Exception:
        return None

def parse_preferences_threshold(md_text):
    # Look for a line with "insurance" and a number like $500. Default 500.
    if md_text is None:
        return 500.0
    # try to find "insurance threshold" or "threshold"
    for ln in md_text.splitlines():
        if re.search(r"insurance", ln, re.I):
            val = money_from_text(ln)
            if val is not None:
                return float(val)
    # fallback: any money-like number
    val2 = money_from_text(md_text)
    if val2 is not None:
        return float(val2)
    return 500.0

def years_between(d1, d2):
    # returns fractional years
    return (d2 - d1).days / 365.25

def compute_depreciation(purchase_price, purchase_date, today, rule):
    """
    rule may include:
      - rate, annual_rate, rate_per_year: as fraction (0.2) or percent (20 or '20%')
      - lifespan_years or years: as number of years
      - salvage_floor or salvage_min: fraction of purchase_price (<=1) or absolute amount (>1) or 0..1
      - method: 'straight_line' (assumed)
    Straight-line: value = purchase_price * max(1 - rate*years_elapsed, 0) or purchase_price * (1 - years_elapsed/lifespan)
    Apply salvage floor if present. Clamp between 0 and purchase_price.
    Round to 2 decimals done by caller.
    """
    if purchase_price is None or purchase_date is None or today is None:
        return None
    years = max(0.0, years_between(purchase_date, today))
    rate = None
    lifespan = None
    salvage = None
    if not rule:
        rule = {}
    # extract rate
    for key in ("annual_rate", "rate_per_year", "rate"):
        if key in rule and rule[key] is not None:
            val = rule[key]
            if isinstance(val, str) and val.strip().endswith("%"):
                try:
                    rate = float(val.strip().rstrip("%")) / 100.0
                except Exception:
                    pass
            else:
                try:
                    rate = float(val)
                    if rate > 1.0:  # treat as percent given without symbol
                        rate = rate / 100.0
                except Exception:
                    pass
            break
    for key in ("lifespan_years", "years"):
        if key in rule and rule[key] is not None:
            try:
                lifespan = float(rule[key])
            except Exception:
                pass
            break
    for key in ("salvage_floor", "salvage_min", "salvage"):
        if key in rule and rule[key] is not None:
            try:
                s = float(rule[key])
                salvage = s
            except Exception:
                # try percent string
                try:
                    s = str(rule[key]).strip()
                    if s.endswith("%"):
                        salvage = float(s[:-1]) / 100.0
                except Exception:
                    pass
            break
    # compute straight-line
    value = purchase_price
    if lifespan is not None and lifespan > 0:
        value = purchase_price * max(0.0, 1.0 - (years / lifespan))
    elif rate is not None and rate >= 0:
        value = purchase_price * max(0.0, 1.0 - rate * years)
    # Apply salvage
    if salvage is not None:
        # if salvage <= 1, interpret as fraction of purchase price
        if salvage <= 1.0:
            floor_val = purchase_price * salvage
        else:
            floor_val = salvage
        value = max(value, floor_val)
    # Clamp between 0 and purchase_price
    value = min(max(value, 0.0), purchase_price)
    return value

def parse_index_md(text, categories):
    if text is None:
        return None
    lines = text.splitlines()
    cat_counts = {}
    total_line = None
    for ln in lines:
        for cat in categories:
            # Look for the category name and a number in line
            if re.search(r"\b" + re.escape(cat) + r"\b", ln, re.I):
                m = re.search(r"([0-9]+)", ln)
                if m:
                    cat_counts[cat] = int(m.group(1))
        if "Total items" in ln:
            m2 = re.search(r"([0-9]+)", ln)
            if m2:
                total_line = int(m2.group(1))
    return {"category_counts": cat_counts, "total": total_line}

def extract_item_lines_with_values(md_text):
    if md_text is None:
        return []
    lines = md_text.splitlines()
    items = []
    for ln in lines:
        lns = ln.strip()
        if not lns:
            continue
        if lns.lower().startswith("category totals"):
            break
        # bullet or numbered or dash lines which likely contain item and amount
        if lns.startswith("-") or lns.startswith("*") or re.match(r"^\d+\.", lns):
            amt = money_from_text(lns)
            if amt is not None:
                items.append({"line": lns, "amount": amt})
    return items

def extract_overall_and_has_category_totals(md_text):
    overall = money_from_text(md_text or "")
    has_ct = False
    if md_text:
        has_ct = re.search(r"category totals", md_text, re.I) is not None
    return overall, has_ct

def round2(x):
    return round(float(x) + 1e-9, 2)

def kebab_case_pattern():
    return re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_inventory_dir": False,
        "has_category_dirs": False,
        "has_all_item_files": False,
        "valid_frontmatter": False,
        "depreciation_correct": False,
        "index_md_correct": False,
        "value_summary_correct": False,
        "for_insurance_correct_set": False,
        "for_insurance_sorted_desc": False,
        "alerts_yaml_correct": False,
        "moving_assignments_correct": False,
        "declutter_candidates_present": False,
        "lending_log_correct": False,
        "notes_length_high_value": False,
        "slugs_consistent": False,
        "has_required_files": False
    }

    # Load inputs
    items_json_path = os.path.join(input_dir, "items.json")
    depreciation_yaml_path = os.path.join(input_dir, "depreciation.yaml")
    move_plan_csv_path = os.path.join(input_dir, "move_plan.csv")
    lending_tsv_path = os.path.join(input_dir, "lending.tsv")
    today_txt_path = os.path.join(input_dir, "today.txt")
    preferences_md_path = os.path.join(input_dir, "preferences.md")

    items = read_json(items_json_path) or []
    dep_yaml_text = read_text(depreciation_yaml_path)
    dep_rules = parse_simple_yaml_map(dep_yaml_text) if dep_yaml_text else {}
    move_rows = parse_csv(move_plan_csv_path, delimiter=",") or []
    lending_rows = parse_csv(lending_tsv_path, delimiter="\t") or []
    today_str = read_text(today_txt_path) or ""
    today_date = parse_date(today_str.strip()) if today_str else None
    prefs_md = read_text(preferences_md_path) or ""
    insurance_threshold = parse_preferences_threshold(prefs_md)

    # Output paths
    inv_root = os.path.join(output_dir, "inventory")
    index_md_path = os.path.join(inv_root, "index.md")
    value_summary_json_path = os.path.join(inv_root, "value_summary.json")
    for_insurance_md_path = os.path.join(inv_root, "for-insurance.md")
    alerts_yaml_path = os.path.join(inv_root, "alerts.yaml")
    moving_json_path = os.path.join(inv_root, "moving", "box-assignments.json")
    declutter_csv_path = os.path.join(inv_root, "declutter_candidates.csv")
    lending_log_jsonl_path = os.path.join(inv_root, "lending_log.jsonl")

    # Basic existence
    if os.path.isdir(inv_root):
        checks["has_inventory_dir"] = True

    # Categories and expected files
    categories = []
    item_expect = []
    for it in items:
        name = it.get("name") or it.get("item_name")
        category = it.get("category")
        if category and category not in categories:
            categories.append(category)
        slug = slugify(name) if name else None
        if category and slug:
            item_expect.append((category, slug, name, it))

    # Category dirs
    cat_ok = True
    for cat in categories:
        cat_dir = os.path.join(inv_root, cat)
        if not os.path.isdir(cat_dir):
            cat_ok = False
            break
    if categories and cat_ok:
        checks["has_category_dirs"] = True

    # All item files exist and frontmatter parse
    fm_all_ok = True
    item_files_ok = True
    kebab_re = kebab_case_pattern()
    fm_by_slug = {}
    notes_by_slug = {}
    for (cat, slug, name, it) in item_expect:
        path = os.path.join(inv_root, cat, f"{slug}.md")
        if not os.path.isfile(path):
            item_files_ok = False
            continue
        md_text = read_text(path)
        fm, body = extract_frontmatter_and_body(md_text)
        if fm is None or body is None:
            fm_all_ok = False
            continue
        # required fields
        required_top = ["name", "category", "location", "purchase_date", "purchase_price", "current_estimated_value", "warranty"]
        has_required = all(k in fm for k in required_top)
        # warranty keys
        warr_ok = isinstance(fm.get("warranty"), dict) and all(k in fm["warranty"] for k in ["expires_on", "coverage", "registered"])
        # receipts optional but if present ensure vendor and number exist
        receipts_ok = True
        if "receipts" in fm and fm["receipts"] is not None:
            receipts_ok = isinstance(fm["receipts"], dict) and all(k in fm["receipts"] for k in ["vendor", "number"])
        if not (has_required and warr_ok and receipts_ok):
            fm_all_ok = False
        fm_by_slug[slug] = fm
        notes_by_slug[slug] = body.strip()
        # slug format check
        if not kebab_re.match(slug):
            fm_all_ok = False

    if item_files_ok and len(item_expect) > 0:
        checks["has_all_item_files"] = True
    if fm_all_ok and checks["has_all_item_files"]:
        checks["valid_frontmatter"] = True

    # Required files presence
    required_files_exist = all([
        os.path.isfile(index_md_path),
        os.path.isfile(value_summary_json_path),
        os.path.isfile(for_insurance_md_path),
        os.path.isfile(alerts_yaml_path),
        os.path.isfile(moving_json_path),
        os.path.isfile(declutter_csv_path),
        os.path.isfile(lending_log_jsonl_path),
    ])
    checks["has_required_files"] = required_files_exist

    # Depreciation correctness
    dep_ok = True
    if checks["valid_frontmatter"] and today_date is not None:
        for (cat, slug, name, it) in item_expect:
            fm = fm_by_slug.get(slug) or {}
            pp = fm.get("purchase_price")
            if pp is None:
                try:
                    pp = float(it.get("purchase_price", None))
                except Exception:
                    pp = None
            if pp is None:
                dep_ok = False
                break
            pd = fm.get("purchase_date") or it.get("purchase_date")
            pd_date = parse_date(pd) if isinstance(pd, str) else None
            rule = dep_rules.get(cat) if isinstance(dep_rules, dict) else None
            expected_val = compute_depreciation(float(pp), pd_date, today_date, rule)
            if expected_val is None:
                dep_ok = False
                break
            expected_val = round2(expected_val)
            cev = fm.get("current_estimated_value")
            if cev is None and "current_estimated_value" in it:
                try:
                    cev = float(it["current_estimated_value"])
                except Exception:
                    cev = None
            try:
                cev = float(cev)
            except Exception:
                dep_ok = False
                break
            if abs(round2(cev) - expected_val) > 0.01:
                dep_ok = False
                break
    else:
        dep_ok = False
    if dep_ok:
        checks["depreciation_correct"] = True

    # Index.md check
    index_ok = False
    if os.path.isfile(index_md_path) and checks["has_all_item_files"]:
        idx_text = read_text(index_md_path)
        parsed = parse_index_md(idx_text, categories)
        if parsed:
            # count items by category from files
            counts = {}
            for (cat, slug, name, it) in item_expect:
                counts[cat] = counts.get(cat, 0) + 1
            # verify each category present with correct count
            cats_ok = True
            for cat in categories:
                if parsed["category_counts"].get(cat) != counts.get(cat, 0):
                    cats_ok = False
                    break
            total_n = sum(counts.values())
            total_ok = parsed["total"] == total_n
            index_ok = cats_ok and total_ok
    checks["index_md_correct"] = index_ok

    # Value summary json
    vs_ok = False
    if os.path.isfile(value_summary_json_path) and checks["valid_frontmatter"]:
        vs = read_json(value_summary_json_path)
        if isinstance(vs, dict):
            per = {}
            for (cat, slug, name, it) in item_expect:
                fm = fm_by_slug.get(slug) or {}
                val = fm.get("current_estimated_value")
                try:
                    valf = float(val)
                except Exception:
                    valf = None
                if valf is None:
                    per = None
                    break
                per[cat] = round2(per.get(cat, 0.0) + valf)
            if per is not None:
                overall = round2(sum(per.values()))
                # value_summary expected: per-category totals and overall_total
                cats_match = True
                for cat, tot in per.items():
                    v = vs.get(cat)
                    try:
                        v = float(v)
                    except Exception:
                        cats_match = False
                        break
                    if abs(round2(v) - tot) > 0.01:
                        cats_match = False
                        break
                overall_ok = "overall_total" in vs and abs(round2(float(vs["overall_total"])) - overall) <= 0.01 if cats_match else False
                vs_ok = cats_match and overall_ok
    checks["value_summary_correct"] = vs_ok

    # For-insurance.md
    fi_ok_set = False
    fi_sorted_ok = False
    if os.path.isfile(for_insurance_md_path) and checks["valid_frontmatter"]:
        fi_text = read_text(for_insurance_md_path)
        # Determine expected items above threshold
        expected_items = []
        for (cat, slug, name, it) in item_expect:
            fm = fm_by_slug.get(slug) or {}
            val = fm.get("current_estimated_value")
            try:
                valf = float(val)
            except Exception:
                continue
            if valf >= insurance_threshold:
                expected_items.append({"slug": slug, "name": fm.get("name") or name, "category": cat, "value": round2(valf)})
        # Check presence
        miss = []
        lower_fi_text = fi_text.lower() if fi_text else ""
        for e in expected_items:
            s_present = (e["slug"] in lower_fi_text)
            n_present = (e["name"].lower() in lower_fi_text)
            if not (s_present or n_present):
                miss.append(e["slug"])
        overall_amount, has_cat_totals = extract_overall_and_has_category_totals(fi_text)
        # Recompute overall sum
        expected_overall = round2(sum(e["value"] for e in expected_items))
        overall_ok = overall_amount is not None and abs(round2(overall_amount) - expected_overall) <= 0.01
        fi_ok_set = (len(miss) == 0) and overall_ok and has_cat_totals
        # Sorted descending by values on item lines
        item_lines = extract_item_lines_with_values(fi_text)
        if item_lines:
            amt_list = [it["amount"] for it in item_lines]
            non_increasing = all(amt_list[i] >= amt_list[i+1] - 1e-9 for i in range(len(amt_list)-1))
            fi_sorted_ok = non_increasing
    checks["for_insurance_correct_set"] = fi_ok_set
    checks["for_insurance_sorted_desc"] = fi_sorted_ok

    # Alerts.yaml
    alerts_ok = False
    if os.path.isfile(alerts_yaml_path) and checks["valid_frontmatter"] and today_date is not None:
        alerts_text = read_text(alerts_yaml_path)
        alerts = parse_alerts_yaml(alerts_text)
        if alerts is not None:
            # warranty_expiring_soon: items with warranty.expires_on within 90 days
            expected_warranty = []
            for (cat, slug, name, it) in item_expect:
                fm = fm_by_slug.get(slug) or {}
                warr = fm.get("warranty") or {}
                exp = warr.get("expires_on")
                d = parse_date(exp) if isinstance(exp, str) else None
                if d is not None:
                    delta = (d - today_date).days
                    if 0 <= delta <= 90:
                        expected_warranty.append(slug)
            # lending_overdue: from lending.tsv due_back_on < today
            expected_overdue = []
            for r in lending_rows:
                item_name = r.get("item_name") or r.get("name")
                due_s = r.get("due_back_on") or r.get("due")
                due_d = parse_date(due_s) if due_s else None
                if item_name and due_d and today_date and due_d < today_date:
                    expected_overdue.append(slugify(item_name))
            # Compare sets (allow ordering differences)
            listed_w = set(alerts.get("warranty_expiring_soon", []))
            listed_l = set(alerts.get("lending_overdue", []))
            alerts_ok = set(expected_warranty) <= listed_w and set(expected_overdue) <= listed_l
    checks["alerts_yaml_correct"] = alerts_ok

    # Moving assignments
    moving_ok = False
    if os.path.isfile(moving_json_path) and checks["has_all_item_files"]:
        mv = read_json(moving_json_path)
        if isinstance(mv, dict):
            # Build expected mapping: box_label -> {new_room, slugs list}
            expected = {}
            for r in move_rows:
                item_name = r.get("item_name") or r.get("name")
                new_room = r.get("new_room")
                box_label = r.get("box_label")
                if not item_name or not box_label:
                    continue
                slug = slugify(item_name)
                if box_label not in expected:
                    expected[box_label] = {"new_room": new_room, "slugs": []}
                # if multiple rooms listed for same box, keep first non-empty
                if not expected[box_label]["new_room"] and new_room:
                    expected[box_label]["new_room"] = new_room
                expected[box_label]["slugs"].append(slug)
            ok = True
            for box, exp in expected.items():
                entry = mv.get(box)
                if entry is None:
                    ok = False
                    break
                if isinstance(entry, list):
                    slugs_list = entry
                    new_room = None
                elif isinstance(entry, dict):
                    # list may be under 'items', 'slugs', or 'item_slugs'
                    slugs_list = None
                    for k in ("items", "slugs", "item_slugs"):
                        if k in entry and isinstance(entry[k], list):
                            slugs_list = entry[k]
                            break
                    new_room = entry.get("new_room")
                else:
                    ok = False
                    break
                if slugs_list is None or not set(exp["slugs"]).issubset(set(slugs_list)):
                    ok = False
                    break
                if exp["new_room"] and new_room and (exp["new_room"] != new_room):
                    ok = False
                    break
            moving_ok = ok
    checks["moving_assignments_correct"] = moving_ok

    # Declutter candidates
    declutter_ok = False
    if os.path.isfile(declutter_csv_path) and checks["valid_frontmatter"] and today_date is not None:
        # compute expected slugs for last_used_date > 24 months (approx 730 days)
        expected_old = set()
        for (cat, slug, name, it) in item_expect:
            fm = fm_by_slug.get(slug) or {}
            lud = fm.get("last_used_date") or it.get("last_used_date")
            d = parse_date(lud) if isinstance(lud, str) else None
            if d is not None:
                if (today_date - d).days > 730:
                    expected_old.add(slug)
        # duplicates: group by normalized item name (lowercase)
        name_counts = {}
        for (cat, slug, name, it) in item_expect:
            key = (name or "").strip().lower()
            name_counts[key] = name_counts.get(key, 0) + 1
        expected_dups = set()
        for (cat, slug, name, it) in item_expect:
            if (name or "").strip().lower() and name_counts[(name or "").strip().lower()] > 2:
                expected_dups.add(slug)
        expected = expected_old.union(expected_dups)
        # Read CSV and check columns and inclusion
        rows = []
        try:
            with open(declutter_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()})
            cols = set(rows[0].keys()) if rows else set()
            cols_ok = {"item_slug", "reason", "suggested_action"}.issubset(cols)
            listed = set([r.get("item_slug", "") for r in rows])
            # suggested_action values
            actions_ok = all((r.get("suggested_action", "").lower() in ("donate", "sell")) for r in rows if "suggested_action" in r)
            declutter_ok = cols_ok and expected.issubset(listed) and actions_ok
        except Exception:
            declutter_ok = False
    checks["declutter_candidates_present"] = declutter_ok

    # Lending log
    lending_ok = False
    if os.path.isfile(lending_log_jsonl_path):
        # Build expected records
        expected = {}
        for r in lending_rows:
            item_name = r.get("item_name") or r.get("name")
            if not item_name:
                continue
            slug = slugify(item_name)
            due_s = r.get("due_back_on") or r.get("due")
            lent_on = r.get("lent_on")
            due_d = parse_date(due_s) if due_s else None
            status = None
            if today_date and due_d:
                status = "overdue" if due_d < today_date else "lent"
            expected[slug] = {
                "item_slug": slug,
                "lent_to": r.get("lent_to"),
                "lent_on": lent_on,
                "due_back_on": due_s,
                "status": status
            }
        try:
            with open(lending_log_jsonl_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip()]
            parsed = []
            for ln in lines:
                try:
                    parsed.append(json.loads(ln))
                except Exception:
                    parsed.append({})
            ok = True
            # Build map by slug
            by_slug = {rec.get("item_slug"): rec for rec in parsed if "item_slug" in rec}
            # Verify all expected present and fields match
            for slug, exp in expected.items():
                rec = by_slug.get(slug)
                if rec is None:
                    ok = False
                    break
                if exp["lent_to"] and rec.get("lent_to") != exp["lent_to"]:
                    ok = False
                    break
                if exp["lent_on"] and rec.get("lent_on") != exp["lent_on"]:
                    ok = False
                    break
                if exp["due_back_on"] and rec.get("due_back_on") != exp["due_back_on"]:
                    ok = False
                    break
                if exp["status"] and rec.get("status") != exp["status"]:
                    ok = False
                    break
            lending_ok = ok and (len(expected) == 0 or len(by_slug) >= len(expected))
        except Exception:
            lending_ok = False
    checks["lending_log_correct"] = lending_ok

    # Notes length for high-value items
    notes_ok = False
    if checks["valid_frontmatter"]:
        ok = True
        for (cat, slug, name, it) in item_expect:
            fm = fm_by_slug.get(slug) or {}
            pp = fm.get("purchase_price")
            try:
                ppv = float(pp)
            except Exception:
                ppv = None
            if ppv is not None and ppv >= 1000.0:
                note = (notes_by_slug.get(slug) or "").strip()
                # remove frontmatter if any residual; we already extracted body
                words = len(re.findall(r"\b\w+\b", note))
                if words < 80:
                    ok = False
                    break
        notes_ok = ok
    checks["notes_length_high_value"] = notes_ok

    # Slugs consistent across references and kebab-case
    slugs_ok = False
    if checks["has_all_item_files"]:
        known_slugs = set([slug for (_, slug, _, _) in item_expect])
        # moving JSON slugs
        move_slugs = set()
        mv = read_json(moving_json_path) if os.path.isfile(moving_json_path) else {}
        if isinstance(mv, dict):
            for v in mv.values():
                if isinstance(v, list):
                    move_slugs.update(v)
                elif isinstance(v, dict):
                    arr = None
                    for k in ("items", "slugs", "item_slugs"):
                        if isinstance(v.get(k), list):
                            arr = v[k]
                            break
                    if arr:
                        move_slugs.update(arr)
        # lending_log slugs
        lend_slugs = set()
        if os.path.isfile(lending_log_jsonl_path):
            try:
                with open(lending_log_jsonl_path, "r", encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            j = json.loads(ln)
                            if "item_slug" in j:
                                lend_slugs.add(j["item_slug"])
                        except Exception:
                            pass
            except Exception:
                pass
        kebab_re = kebab_case_pattern()
        all_ref_slugs = move_slugs.union(lend_slugs)
        format_ok = all(kebab_re.match(s or "") for s in known_slugs.union(all_ref_slugs))
        contained_ok = all((s in known_slugs) for s in all_ref_slugs)
        slugs_ok = format_ok and contained_ok
    checks["slugs_consistent"] = slugs_ok

    # Gate for baseline: if required artifacts missing, reward must be 0.0
    essential_ok = all([
        checks["has_inventory_dir"],
        checks["has_category_dirs"],
        checks["has_all_item_files"],
        checks["has_required_files"]
    ])

    # Compute reward as fraction of checks passed if essential_ok, else 0
    passed = sum(1 for v in checks.values() if v is True)
    total = len(checks)
    reward = 0.0
    if essential_ok:
        reward = passed / total if total > 0 else 0.0
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))
    else:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()