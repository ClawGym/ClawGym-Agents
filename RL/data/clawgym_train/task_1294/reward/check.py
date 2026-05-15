import json
import os
import sys
import csv
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from collections import OrderedDict

def safe_read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_float_maybe(s):
    try:
        if isinstance(s, (int, float)):
            return float(s)
        s = str(s).strip()
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return None

def approx_equal(a, b, tol=5e-4):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def quantize_two_decimals(value):
    d = Decimal(str(value))
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def last_nonempty_line(text):
    if text is None:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else None

def count_words(text):
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text))

def split_paragraphs(text):
    if not text:
        return []
    parts = re.split(r"\n\s*\n+", text.strip())
    return [p for p in parts if p.strip()]

def find_section(text, header_substring_ci):
    if not text:
        return None, None
    # Find start index of header by case-insensitive search
    m = re.search(re.escape(header_substring_ci), text, flags=re.IGNORECASE)
    if not m:
        return None, None
    start = m.start()
    end = len(text)
    # Heuristic: next heading line starting with non-space and contains ':' or '#'
    # Keep simple: next occurrence of a line that looks like a heading marker (### or starts with a word and colon)
    after = text[m.end():]
    heading_matches = list(re.finditer(r"\n(?=[^\s].{0,80}\n)", after))
    # We will just take end = len(text)
    return start, end

def count_bullets(text):
    if not text:
        return 0
    cnt = 0
    for line in text.splitlines():
        if re.match(r"^\s*(-|\*|\d+\.)\s+", line):
            cnt += 1
    return cnt

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = OrderedDict()

    # Expected ground-truth values (derived from provided dataset description)
    years = [2019, 2020, 2021, 2022, 2023, 2024]
    category_elec = "Electronics (HS85)"
    category_text = "Textiles (HS61+62)"
    expected_aggregates = {
        category_elec: {
            2019: 300000.0, 2020: 320000.0, 2021: 360000.0,
            2022: 390000.0, 2023: 410000.0, 2024: 430000.0
        },
        category_text: {
            2019: 220000.0, 2020: 210000.0, 2021: 230000.0,
            2022: 240000.0, 2023: 235000.0, 2024: 238000.0
        },
    }
    # Metrics expected (tolerances applied)
    expected_metrics = {
        "electronics": {
            "cagr_2019_2024": 0.0744,
            "growth_2023_2024_pct": 0.04878,
            "top3_share_2024_excl_other": 0.82432
        },
        "textiles": {
            "cagr_2019_2024": 0.0157,
            "growth_2023_2024_pct": 0.01277,
            "top3_share_2024_excl_other": 0.85638
        }
    }
    metrics_tolerance = 5e-4

    # Top destinations 2024 expected
    # Electronics (HS85): EU 122000; USA 105000; ASEAN 78000; Japan 37000; South Korea 28000; non-Other total = 370000.
    # Shares: 32.97, 28.38, 21.08, 10.00, 7.57
    expected_top_elec = [
        ("EU", 122000.0, Decimal("32.97")),
        ("USA", 105000.0, Decimal("28.38")),
        ("ASEAN", 78000.0, Decimal("21.08")),
        ("Japan", 37000.0, Decimal("10.00")),
        ("South Korea", 28000.0, Decimal("7.57")),
    ]
    expected_top_elec_total_non_other = 370000.0

    # Textiles (HS61+62): EU 85500; USA 68000; ASEAN 24300; Japan 17800; South Korea 12000; non-Other total = 207600.
    # Shares: 41.19, 32.76, 11.71, 8.57, 5.78
    expected_top_text = [
        ("EU", 85500.0, Decimal("41.19")),
        ("USA", 68000.0, Decimal("32.76")),
        ("ASEAN", 24300.0, Decimal("11.71")),
        ("Japan", 17800.0, Decimal("8.57")),
        ("South Korea", 12000.0, Decimal("5.78")),
    ]
    expected_top_text_total_non_other = 207600.0

    # 1) Check output/aggregates.csv
    agg_path = os.path.join(output_dir, "aggregates.csv")
    checks["has_aggregates_file"] = os.path.isfile(agg_path)
    checks["aggregates_header_ok"] = False
    checks["aggregates_12_rows"] = False
    checks["aggregates_categories_ok"] = False
    checks["aggregates_sorted"] = False
    checks["aggregates_values_correct"] = False

    if checks["has_aggregates_file"]:
        try:
            with open(agg_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                checks["aggregates_header_ok"] = header == ["year", "category", "exports_usd_millions"]
                data_rows = rows[1:]
                checks["aggregates_12_rows"] = len(data_rows) == 12
                # Parse data
                parsed = []
                categories_found = set()
                year_cat_counts = {}
                sorted_ok = True
                prev = None
                for r in data_rows:
                    if len(r) != 3:
                        parsed = []
                        break
                    y = None
                    try:
                        y = int(str(r[0]).strip())
                    except Exception:
                        parsed = []
                        break
                    cat = r[1].strip()
                    val = parse_float_maybe(r[2])
                    if val is None:
                        parsed = []
                        break
                    parsed.append((y, cat, val))
                    categories_found.add(cat)
                    year_cat_counts.setdefault(y, 0)
                    year_cat_counts[y] += 1
                    if prev is not None:
                        if (y < prev[0]) or (y == prev[0] and cat < prev[1] is False and cat != prev[1]):
                            # We need strict lexicographic sort: by year asc then category alphabetically.
                            pass
                    prev = (y, cat)

                # Check categories
                checks["aggregates_categories_ok"] = categories_found == {category_elec, category_text}

                # Check each year has exactly two rows
                has_all_years = all(year_cat_counts.get(y, 0) == 2 for y in years)
                # Check sorting explicitly
                if parsed:
                    sorted_parsed = sorted(parsed, key=lambda t: (t[0], t[1]))
                    checks["aggregates_sorted"] = parsed == sorted_parsed

                # Check values
                values_ok = True
                if parsed and has_all_years and checks["aggregates_categories_ok"]:
                    # Compare with expected with tolerance 0.1
                    for (y, cat, val) in parsed:
                        if cat == category_elec:
                            exp = expected_aggregates[category_elec].get(y)
                        elif cat == category_text:
                            exp = expected_aggregates[category_text].get(y)
                        else:
                            values_ok = False
                            break
                        if exp is None or abs(val - exp) > 0.1:
                            values_ok = False
                            break
                else:
                    values_ok = False
                checks["aggregates_values_correct"] = values_ok
        except Exception:
            pass

    # 2) Check output/metrics.json
    metrics_path = os.path.join(output_dir, "metrics.json")
    checks["has_metrics_json"] = os.path.isfile(metrics_path)
    checks["metrics_schema_ok"] = False
    checks["metrics_electronics_cagr_ok"] = False
    checks["metrics_electronics_growth_ok"] = False
    checks["metrics_electronics_top3_ok"] = False
    checks["metrics_textiles_cagr_ok"] = False
    checks["metrics_textiles_growth_ok"] = False
    checks["metrics_textiles_top3_ok"] = False

    if checks["has_metrics_json"]:
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            # Schema: keys 'electronics' and 'textiles', with numeric fields
            schema_ok = (
                isinstance(metrics, dict) and
                "electronics" in metrics and "textiles" in metrics and
                isinstance(metrics["electronics"], dict) and isinstance(metrics["textiles"], dict)
            )
            if schema_ok:
                def has_numeric_fields(obj):
                    keys = ["cagr_2019_2024", "growth_2023_2024_pct", "top3_share_2024_excl_other"]
                    for k in keys:
                        if k not in obj:
                            return False
                        if not isinstance(obj[k], (int, float)):
                            return False
                    return True
                schema_ok = has_numeric_fields(metrics["electronics"]) and has_numeric_fields(metrics["textiles"])
            checks["metrics_schema_ok"] = schema_ok

            if checks["metrics_schema_ok"]:
                me = metrics["electronics"]
                mt = metrics["textiles"]
                checks["metrics_electronics_cagr_ok"] = approx_equal(me["cagr_2019_2024"], expected_metrics["electronics"]["cagr_2019_2024"], metrics_tolerance)
                checks["metrics_electronics_growth_ok"] = approx_equal(me["growth_2023_2024_pct"], expected_metrics["electronics"]["growth_2023_2024_pct"], metrics_tolerance)
                checks["metrics_electronics_top3_ok"] = approx_equal(me["top3_share_2024_excl_other"], expected_metrics["electronics"]["top3_share_2024_excl_other"], metrics_tolerance)
                checks["metrics_textiles_cagr_ok"] = approx_equal(mt["cagr_2019_2024"], expected_metrics["textiles"]["cagr_2019_2024"], metrics_tolerance)
                checks["metrics_textiles_growth_ok"] = approx_equal(mt["growth_2023_2024_pct"], expected_metrics["textiles"]["growth_2023_2024_pct"], metrics_tolerance)
                checks["metrics_textiles_top3_ok"] = approx_equal(mt["top3_share_2024_excl_other"], expected_metrics["textiles"]["top3_share_2024_excl_other"], metrics_tolerance)
        except Exception:
            pass

    # 3) Check output/top_destinations_2024.csv
    top_path = os.path.join(output_dir, "top_destinations_2024.csv")
    checks["has_top_dest_file"] = os.path.isfile(top_path)
    checks["top_dest_header_ok"] = False
    checks["top_dest_10_rows"] = False
    checks["top_dest_categories_ok"] = False
    checks["top_dest_ranks_ok"] = False
    checks["top_dest_values_ok"] = False
    checks["top_dest_shares_ok"] = False

    if checks["has_top_dest_file"]:
        try:
            with open(top_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                checks["top_dest_header_ok"] = header == ["category", "rank", "destination", "value_usd_millions", "share_percent_excl_other"]
                data = rows[1:]
                checks["top_dest_10_rows"] = len(data) == 10
                # Parse and validate
                # Separate by category
                cat_rows = {category_elec: [], category_text: []}
                categories_ok = True
                for r in data:
                    if len(r) != 5:
                        categories_ok = False
                        break
                    cat = r[0].strip()
                    if cat not in cat_rows:
                        categories_ok = False
                        break
                    cat_rows[cat].append(r)
                checks["top_dest_categories_ok"] = categories_ok and all(len(cat_rows[c]) == 5 for c in cat_rows)

                ranks_ok = False
                values_ok = False
                shares_ok = False
                if checks["top_dest_categories_ok"]:
                    # Order within each category by rank
                    ranks_ok = True
                    for cat, rows_cat in cat_rows.items():
                        ranks = []
                        for r in rows_cat:
                            try:
                                ranks.append(int(str(r[1]).strip()))
                            except Exception:
                                ranks_ok = False
                                break
                        if ranks != list(range(1, 6)):
                            ranks_ok = False
                            break

                    # Values and shares
                    values_ok = True
                    shares_ok = True
                    # Electronics
                    for idx, r in enumerate(cat_rows[category_elec], start=1):
                        dest = r[2].strip()
                        val = parse_float_maybe(r[3])
                        share_str = r[4].strip()
                        share_val = parse_float_maybe(share_str)
                        exp_dest, exp_val, exp_share = expected_top_elec[idx - 1]
                        if dest != exp_dest or val is None or abs(val - exp_val) > 0.1:
                            values_ok = False
                        # Compute expected with Decimal to enforce 2 decimals
                        denom = expected_top_elec_total_non_other
                        exp_share_calc = quantize_two_decimals((Decimal(str(exp_val)) / Decimal(str(denom))) * Decimal("100"))
                        # exp_share already given; cross-check with calc (should match)
                        if exp_share != exp_share_calc:
                            # Should not happen, but ensure robustness
                            exp_share = exp_share_calc
                        if share_val is None:
                            shares_ok = False
                        else:
                            got = quantize_two_decimals(share_val)
                            if got != exp_share:
                                shares_ok = False

                    # Textiles
                    for idx, r in enumerate(cat_rows[category_text], start=1):
                        dest = r[2].strip()
                        val = parse_float_maybe(r[3])
                        share_str = r[4].strip()
                        share_val = parse_float_maybe(share_str)
                        exp_dest, exp_val, exp_share = expected_top_text[idx - 1]
                        if dest != exp_dest or val is None or abs(val - exp_val) > 0.1:
                            values_ok = False
                        denom = expected_top_text_total_non_other
                        exp_share_calc = quantize_two_decimals((Decimal(str(exp_val)) / Decimal(str(denom))) * Decimal("100"))
                        if exp_share != exp_share_calc:
                            exp_share = exp_share_calc
                        if share_val is None:
                            shares_ok = False
                        else:
                            got = quantize_two_decimals(share_val)
                            if got != exp_share:
                                shares_ok = False

                checks["top_dest_ranks_ok"] = ranks_ok
                checks["top_dest_values_ok"] = values_ok
                checks["top_dest_shares_ok"] = shares_ok
        except Exception:
            pass

    # 4) Check output/summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    checks["has_summary_md"] = os.path.isfile(summary_path)
    checks["summary_length_ok"] = False
    checks["summary_contains_phrases_ok"] = False
    checks["summary_has_methodology_section"] = False
    checks["summary_has_implications_section"] = False
    checks["summary_paragraphs_ok"] = False
    checks["summary_implications_bullets_ok"] = False

    summary_text = None
    if checks["has_summary_md"]:
        summary_text = safe_read(summary_path)
        if summary_text is None:
            summary_text = ""
        word_count = count_words(summary_text)
        checks["summary_length_ok"] = (250 <= word_count <= 600)
        # Phrase checks (case-sensitive as specified)
        phrase_ok = (
            ("General Administration of Customs of China" in summary_text) and
            ("HS 85" in summary_text) and
            (("HS 61" in summary_text) or ("HS 62" in summary_text))
        )
        checks["summary_contains_phrases_ok"] = phrase_ok
        # Methodology heading presence (case-insensitive search for 'Methodology' or 'Methodology & Assumptions')
        checks["summary_has_methodology_section"] = bool(re.search(r"methodology", summary_text, flags=re.IGNORECASE))
        # Implications heading presence (case-insensitive)
        checks["summary_has_implications_section"] = bool(re.search(r"implications\s*for\s*2025\s*planning", summary_text, flags=re.IGNORECASE))
        # Paragraphs count
        paragraphs = split_paragraphs(summary_text)
        checks["summary_paragraphs_ok"] = len(paragraphs) >= 3
        # Bullets in implications section
        sec_start, sec_end = find_section(summary_text, "Implications for 2025 planning")
        bullets_ok = False
        if sec_start is not None:
            sec_text = summary_text[sec_start:sec_end]
            bullets_count = count_bullets(sec_text)
            bullets_ok = bullets_count >= 3
        checks["summary_implications_bullets_ok"] = bullets_ok

    # 5) Steps files
    steps_dir = os.path.join(output_dir, "steps")
    plan_path = os.path.join(steps_dir, "plan.md")
    draft_path = os.path.join(steps_dir, "draft.md")
    critique_path = os.path.join(steps_dir, "critique.md")
    refine_path = os.path.join(steps_dir, "refine.md")

    checks["has_steps_plan"] = os.path.isfile(plan_path)
    checks["has_steps_draft"] = os.path.isfile(draft_path)
    checks["has_steps_critique"] = os.path.isfile(critique_path)
    checks["has_steps_refine"] = os.path.isfile(refine_path)

    checks["plan_min_length_ok"] = False
    checks["draft_min_length_ok"] = False
    checks["critique_min_length_ok"] = False
    checks["refine_min_length_ok"] = False
    checks["plan_has_numbered_list"] = False
    checks["critique_has_keywords"] = False
    checks["refine_matches_summary_length"] = False
    checks["refine_contains_phrases"] = False

    plan_text = safe_read(plan_path) if checks["has_steps_plan"] else ""
    draft_text = safe_read(draft_path) if checks["has_steps_draft"] else ""
    critique_text = safe_read(critique_path) if checks["has_steps_critique"] else ""
    refine_text = safe_read(refine_path) if checks["has_steps_refine"] else ""

    if checks["has_steps_plan"] and plan_text is not None:
        checks["plan_min_length_ok"] = len(plan_text.strip()) >= 100
        # Numbered list starting with 1. or 1)
        has_numbered = any(re.match(r"^\s*1[.)]\s", line) for line in plan_text.splitlines())
        checks["plan_has_numbered_list"] = has_numbered

    if checks["has_steps_draft"] and draft_text is not None:
        checks["draft_min_length_ok"] = len(draft_text.strip()) >= 100

    if checks["has_steps_critique"] and critique_text is not None:
        checks["critique_min_length_ok"] = len(critique_text.strip()) >= 100
        checks["critique_has_keywords"] = bool(re.search(r"\b(improve|clarify)\b", critique_text, flags=re.IGNORECASE))

    if checks["has_steps_refine"] and refine_text is not None:
        checks["refine_min_length_ok"] = len(refine_text.strip()) >= 100
        # Compare length with summary within ±20%
        if summary_text is not None:
            s_len = len(summary_text.strip())
            r_len = len(refine_text.strip())
            if s_len > 0:
                lower = 0.8 * s_len
                upper = 1.2 * s_len
                checks["refine_matches_summary_length"] = (lower <= r_len <= upper)
        # Contains key phrases
        checks["refine_contains_phrases"] = (
            ("General Administration of Customs of China" in refine_text) and
            ("HS 85" in refine_text)
        )

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Enforce no-op baseline: if output folder missing or empty required artifacts, reward 0.0
    # If none of the main deliverables exist, set reward to 0.0
    main_any_exists = any(os.path.isfile(p) for p in [
        agg_path, metrics_path, top_path, summary_path, plan_path, draft_path, critique_path, refine_path
    ])
    if not main_any_exists:
        reward = 0.0

    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = bool(v)
    print(json.dumps(result))

if __name__ == "__main__":
    main()