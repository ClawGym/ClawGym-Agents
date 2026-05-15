import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, InvalidOperation

def dcast(x):
    try:
        return Decimal(str(x))
    except InvalidOperation:
        return None

def decimal_equal(a: Decimal, b: Decimal) -> bool:
    if a is None or b is None:
        return False
    return a == b

def round_one_decimal_variants(x: Decimal):
    if x is None:
        return None, None
    return (x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
            x.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN))

def last_non_empty_line(s: str):
    lines = [ln for ln in s.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else ""

def parse_item_lines(md_text: str):
    # Pattern for item lines like:
    # - Food name: 300 cal, 10g protein, 54g carbs, 5g fat
    pattern = re.compile(
        r'^\s*-\s+(.*?):\s*([0-9]+)\s*cal,\s*([0-9]+(?:\.[0-9]+)?)g\s*protein,\s*([0-9]+(?:\.[0-9]+)?)g\s*carbs,\s*([0-9]+(?:\.[0-9]+)?)g\s*fat\s*$',
        re.MULTILINE)
    items = []
    for m in pattern.finditer(md_text):
        name = m.group(1).strip()
        cal = int(m.group(2))
        protein = Decimal(m.group(3))
        carbs = Decimal(m.group(4))
        fat = Decimal(m.group(5))
        items.append({
            "name": name,
            "calories": cal,
            "protein": protein,
            "carbs": carbs,
            "fat": fat
        })
    return items

def sum_items(items):
    total_cal = sum(i["calories"] for i in items)
    total_protein = sum(i["protein"] for i in items) if items else Decimal("0")
    total_carbs = sum(i["carbs"] for i in items) if items else Decimal("0")
    total_fat = sum(i["fat"] for i in items) if items else Decimal("0")
    return {
        "calories": total_cal,
        "protein": total_protein,
        "carbs": total_carbs,
        "fat": total_fat
    }

def parse_daily_totals_section(md_text: str):
    lines = md_text.splitlines()
    totals_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == "## Daily Totals":
            totals_idx = idx
            break
    if totals_idx is None:
        return None
    # Expect next lines to contain "Calories: <int>" and then "Protein: ... | Carbs: ... | Fat: ..."
    calories = None
    protein = None
    carbs = None
    fat = None
    cal_pattern = re.compile(r'^\s*Calories:\s*([0-9]+)\s*$')
    macros_pattern = re.compile(
        r'^\s*Protein:\s*([0-9]+(?:\.[0-9]+)?)g\s*\|\s*Carbs:\s*([0-9]+(?:\.[0-9]+)?)g\s*\|\s*Fat:\s*([0-9]+(?:\.[0-9]+)?)g\s*$'
    )
    # Search in next few lines (up to 10)
    for j in range(totals_idx + 1, min(len(lines), totals_idx + 11)):
        m1 = cal_pattern.match(lines[j])
        if m1:
            try:
                calories = int(m1.group(1))
            except ValueError:
                calories = None
            continue
        m2 = macros_pattern.match(lines[j])
        if m2:
            try:
                protein = Decimal(m2.group(1))
                carbs = Decimal(m2.group(2))
                fat = Decimal(m2.group(3))
            except InvalidOperation:
                protein = carbs = fat = None
            continue
    if calories is None or protein is None or carbs is None or fat is None:
        return None
    return {
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat
    }

def parse_micronutrients_section(md_text: str):
    # Extract section under "## Micronutrients Notable" until next "## " or EOF
    lines = md_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## Micronutrients Notable":
            start = i + 1
            break
    if start is None:
        return ""
    buf = []
    for j in range(start, len(lines)):
        ln = lines[j]
        if ln.startswith("## "):
            break
        buf.append(ln)
    return "\n".join(buf)

def check_keywords_in_section(section_text: str, required_keywords):
    section_lower = section_text.lower()
    for kw in required_keywords:
        if kw.lower() not in section_lower:
            return False
    return True

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def compare_daily_totals(md_text):
    items = parse_item_lines(md_text)
    sums = sum_items(items)
    totals_section = parse_daily_totals_section(md_text)
    if totals_section is None:
        return False, sums
    ok = True
    ok = ok and (sums["calories"] == totals_section["calories"])
    ok = ok and decimal_equal(sums["protein"], totals_section["protein"])
    ok = ok and decimal_equal(sums["carbs"], totals_section["carbs"])
    ok = ok and decimal_equal(sums["fat"], totals_section["fat"])
    return ok, sums

def add_decimal(a: Decimal, b: Decimal) -> Decimal:
    return (a if a is not None else Decimal("0")) + (b if b is not None else Decimal("0"))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected output paths
    day10_path = os.path.join(output_dir, "nutrition", "daily", "2024-03", "2024-03-10.md")
    day11_path = os.path.join(output_dir, "nutrition", "daily", "2024-03", "2024-03-11.md")
    day12_path = os.path.join(output_dir, "nutrition", "daily", "2024-03", "2024-03-12.md")
    weekly_path = os.path.join(output_dir, "nutrition", "weekly", "2024-03-10_to_2024-03-12.json")

    checks = {
        # Presence
        "has_daily_2024_03_10": False,
        "has_daily_2024_03_11": False,
        "has_daily_2024_03_12": False,
        "has_weekly_json": False,
        # Anchors
        "anchors_2024_03_10": False,
        "anchors_2024_03_11": False,
        "anchors_2024_03_12": False,
        # Daily totals consistency
        "totals_match_2024_03_10": False,
        "totals_match_2024_03_11": False,
        "totals_match_2024_03_12": False,
        # Micronutrients sections
        "micros_2024_03_10": False,
        "micros_2024_03_11": False,
        "micros_2024_03_12": False,
        # Weekly JSON checks
        "weekly_json_keys_present": False,
        "weekly_daily_totals_match": False,
        "weekly_totals_match": False,
        "weekly_averages_match": False,
        "weekly_avg_vs_targets_match": False
    }

    # Read daily files if exist
    day10_text = read_text(day10_path)
    day11_text = read_text(day11_path)
    day12_text = read_text(day12_path)

    if day10_text is not None:
        checks["has_daily_2024_03_10"] = True
    if day11_text is not None:
        checks["has_daily_2024_03_11"] = True
    if day12_text is not None:
        checks["has_daily_2024_03_12"] = True

    # Anchors: exact lines present
    if day10_text:
        anchors_ok = True
        a1 = "- Oats 80g: 300 cal, 10g protein, 54g carbs, 5g fat"
        a2 = "- Salmon 200g: 400 cal, 40g protein, 0g carbs, 25g fat"
        anchors_ok = anchors_ok and (a1 in day10_text)
        anchors_ok = anchors_ok and (a2 in day10_text)
        checks["anchors_2024_03_10"] = anchors_ok

    if day11_text:
        a = "- Walnut 30g: 196 cal, 4.6g protein, 3.9g carbs, 18.3g fat"
        checks["anchors_2024_03_11"] = (a in day11_text)

    if day12_text:
        a = "- Sardines 100g: 208 cal, 25g protein, 0g carbs, 11.5g fat"
        checks["anchors_2024_03_12"] = (a in day12_text)

    # Totals consistency
    day10_sums = None
    day11_sums = None
    day12_sums = None

    if day10_text:
        ok10, sums10 = compare_daily_totals(day10_text)
        checks["totals_match_2024_03_10"] = ok10
        day10_sums = sums10
    if day11_text:
        ok11, sums11 = compare_daily_totals(day11_text)
        checks["totals_match_2024_03_11"] = ok11
        day11_sums = sums11
    if day12_text:
        ok12, sums12 = compare_daily_totals(day12_text)
        checks["totals_match_2024_03_12"] = ok12
        day12_sums = sums12

    # Micronutrients presence under section
    # Required keywords per day
    req10 = ["Vitamin D", "Omega-3", "Vitamin C", "Potassium"]
    req11 = ["Vitamin C", "Iron", "Vitamin D", "Omega-3", "Calcium"]
    req12 = ["Vitamin D", "Omega-3", "Vitamin C", "Potassium", "Calcium"]

    if day10_text:
        sec = parse_micronutrients_section(day10_text)
        checks["micros_2024_03_10"] = check_keywords_in_section(sec, req10)
    if day11_text:
        sec = parse_micronutrients_section(day11_text)
        checks["micros_2024_03_11"] = check_keywords_in_section(sec, req11)
    if day12_text:
        sec = parse_micronutrients_section(day12_text)
        checks["micros_2024_03_12"] = check_keywords_in_section(sec, req12)

    # Load weekly JSON
    weekly = load_json_file(weekly_path)
    if isinstance(weekly, dict):
        checks["has_weekly_json"] = True

    if weekly and all([day10_sums is not None, day11_sums is not None, day12_sums is not None]):
        # Keys present check
        keys_ok = True
        # targets
        t = weekly.get("targets")
        if not (isinstance(t, dict) and all(k in t for k in ["calories", "protein_g", "carbs_g", "fat_g"])):
            keys_ok = False
        # daily_totals
        dt = weekly.get("daily_totals")
        if not (isinstance(dt, dict) and all(k in dt for k in ["2024-03-10", "2024-03-11", "2024-03-12"])):
            keys_ok = False
        # weekly_totals, averages, average_vs_targets
        for k in ["weekly_totals", "averages", "average_vs_targets"]:
            v = weekly.get(k)
            if not (isinstance(v, dict) and all(x in v for x in ["calories", "protein_g", "carbs_g", "fat_g"])):
                keys_ok = False
        checks["weekly_json_keys_present"] = keys_ok

        # Daily totals match check
        if keys_ok:
            def dt_match(day_key, sums):
                v = dt.get(day_key, {})
                try:
                    c = dcast(v.get("calories"))
                    p = dcast(v.get("protein_g"))
                    cb = dcast(v.get("carbs_g"))
                    f = dcast(v.get("fat_g"))
                except Exception:
                    return False
                # calories from sums is int; cast to Decimal for compare
                return (c == Decimal(sums["calories"])) and \
                       decimal_equal(p, sums["protein"]) and \
                       decimal_equal(cb, sums["carbs"]) and \
                       decimal_equal(f, sums["fat"])

            daily_ok = dt_match("2024-03-10", day10_sums) and \
                       dt_match("2024-03-11", day11_sums) and \
                       dt_match("2024-03-12", day12_sums)
            checks["weekly_daily_totals_match"] = daily_ok

            # Weekly totals match
            if daily_ok:
                wt = weekly.get("weekly_totals", {})
                wt_c = dcast(wt.get("calories"))
                wt_p = dcast(wt.get("protein_g"))
                wt_cb = dcast(wt.get("carbs_g"))
                wt_f = dcast(wt.get("fat_g"))

                comp_c = Decimal(day10_sums["calories"] + day11_sums["calories"] + day12_sums["calories"])
                comp_p = day10_sums["protein"] + day11_sums["protein"] + day12_sums["protein"]
                comp_cb = day10_sums["carbs"] + day11_sums["carbs"] + day12_sums["carbs"]
                comp_f = day10_sums["fat"] + day11_sums["fat"] + day12_sums["fat"]

                weekly_totals_ok = (wt_c == comp_c) and decimal_equal(wt_p, comp_p) and decimal_equal(wt_cb, comp_cb) and decimal_equal(wt_f, comp_f)
                checks["weekly_totals_match"] = weekly_totals_ok

                # Averages match (accepting either HALF_UP or HALF_EVEN rounding)
                av = weekly.get("averages", {})
                av_c = dcast(av.get("calories"))
                av_p = dcast(av.get("protein_g"))
                av_cb = dcast(av.get("carbs_g"))
                av_f = dcast(av.get("fat_g"))

                if weekly_totals_ok:
                    three = Decimal("3")
                    comp_av_c_halfup, comp_av_c_halfeven = round_one_decimal_variants(comp_c / three)
                    comp_av_p_halfup, comp_av_p_halfeven = round_one_decimal_variants(comp_p / three)
                    comp_av_cb_halfup, comp_av_cb_halfeven = round_one_decimal_variants(comp_cb / three)
                    comp_av_f_halfup, comp_av_f_halfeven = round_one_decimal_variants(comp_f / three)

                    avg_ok = ((av_c == comp_av_c_halfup) or (av_c == comp_av_c_halfeven)) and \
                             ((av_p == comp_av_p_halfup) or (av_p == comp_av_p_halfeven)) and \
                             ((av_cb == comp_av_cb_halfup) or (av_cb == comp_av_cb_halfeven)) and \
                             ((av_f == comp_av_f_halfup) or (av_f == comp_av_f_halfeven))
                    checks["weekly_averages_match"] = avg_ok

                    # average_vs_targets: averages - targets rounded to 1 decimal (accept either rounding mode)
                    avt = weekly.get("average_vs_targets", {})
                    avt_c = dcast(avt.get("calories"))
                    avt_p = dcast(avt.get("protein_g"))
                    avt_cb = dcast(avt.get("carbs_g"))
                    avt_f = dcast(avt.get("fat_g"))

                    tgt = weekly.get("targets", {})
                    tgt_c = dcast(tgt.get("calories"))
                    tgt_p = dcast(tgt.get("protein_g"))
                    tgt_cb = dcast(tgt.get("carbs_g"))
                    tgt_f = dcast(tgt.get("fat_g"))

                    if avg_ok and None not in (tgt_c, tgt_p, tgt_cb, tgt_f, av_c, av_p, av_cb, av_f, avt_c, avt_p, avt_cb, avt_f):
                        # Averages already rounded to 1 decimal; compute difference and round to 1 decimal
                        diff_c_halfup, diff_c_halfeven = round_one_decimal_variants(av_c - tgt_c)
                        diff_p_halfup, diff_p_halfeven = round_one_decimal_variants(av_p - tgt_p)
                        diff_cb_halfup, diff_cb_halfeven = round_one_decimal_variants(av_cb - tgt_cb)
                        diff_f_halfup, diff_f_halfeven = round_one_decimal_variants(av_f - tgt_f)

                        avg_vs_targets_ok = ((avt_c == diff_c_halfup) or (avt_c == diff_c_halfeven)) and \
                                            ((avt_p == diff_p_halfup) or (avt_p == diff_p_halfeven)) and \
                                            ((avt_cb == diff_cb_halfup) or (avt_cb == diff_cb_halfeven)) and \
                                            ((avt_f == diff_f_halfup) or (avt_f == diff_f_halfeven))
                        checks["weekly_avg_vs_targets_match"] = avg_vs_targets_ok

    # Compute reward
    # Baseline: if none of the required output files exist, reward = 0.0
    required_paths = [day10_path, day11_path, day12_path, weekly_path]
    any_required_exists = any(os.path.isfile(p) for p in required_paths)
    if not any_required_exists:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    try:
        reward = float(max(0.0, min(1.0, reward)))
    except Exception:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()