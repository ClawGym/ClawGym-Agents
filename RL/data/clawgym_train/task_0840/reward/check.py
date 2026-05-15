import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _compute_baselines(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    groups: Dict[str, List[Dict[str, str]]] = {}
    for r in rows:
        pt = r.get("promotion_type", "").strip()
        if pt == "":
            # skip invalid rows
            continue
        groups.setdefault(pt, []).append(r)
    expected: Dict[str, Dict[str, int]] = {}
    for pt, items in groups.items():
        games = len(items)
        def avg(field: str) -> int:
            vals = []
            for it in items:
                try:
                    vals.append(float(it[field]))
                except Exception:
                    # Malformed value leads to failure by making values inconsistent
                    vals.append(float("nan"))
            try:
                av = sum(vals) / len(vals)
                return int(round(av))
            except Exception:
                return None  # type: ignore
        metrics = {
            "promotion_type": pt,
            "games": games,
            "avg_attendance": avg("attendance"),
            "avg_ticket_rev": avg("ticket_rev"),
            "avg_merch_rev": avg("merch_rev"),
            "avg_concessions_rev": avg("concessions_rev"),
            "avg_social_shares": avg("social_shares"),
        }
        expected[pt] = metrics  # type: ignore
    return expected


def _parse_packages_html(html: str) -> List[Dict[str, Any]]:
    # Simple regex-based extraction tailored to the provided structure
    packages: List[Dict[str, Any]] = []
    package_blocks = re.findall(r'<div\s+class="package"[^>]*>(.*?)</div>\s*', html, flags=re.DOTALL | re.IGNORECASE)
    for block in package_blocks:
        # name
        name_match = re.search(r'<h2>\s*(.*?)\s*</h2>', block, flags=re.DOTALL | re.IGNORECASE)
        price_match = re.search(r'<span\s+class="price">\s*\$?\s*([\d]+(?:\.\d+)?)\s*</span>', block, flags=re.DOTALL | re.IGNORECASE)
        benefits_match = re.search(r'<ul\s+class="benefits"\s*>\s*(.*?)</ul>', block, flags=re.DOTALL | re.IGNORECASE)
        addons_match = re.search(r'<ul\s+class="add-ons"\s*>\s*(.*?)</ul>', block, flags=re.DOTALL | re.IGNORECASE)
        if not name_match or not price_match or not benefits_match or not addons_match:
            # Skip malformed blocks
            continue
        name = _strip_html(name_match.group(1)).strip()
        try:
            price = float(price_match.group(1))
        except Exception:
            continue
        benefits = _extract_li_texts(benefits_match.group(1))
        add_ons = _extract_li_texts(addons_match.group(1))
        packages.append({
            "name": name,
            "base_price": price if price % 1 != 0 else int(price),
            "benefits": benefits,
            "add_ons": add_ons
        })
    return packages


def _strip_html(s: str) -> str:
    # Remove HTML tags
    return re.sub(r'<[^>]+>', '', s)


def _extract_li_texts(ul_inner_html: str) -> List[str]:
    items = re.findall(r'<li>\s*(.*?)\s*</li>', ul_inner_html, flags=re.DOTALL | re.IGNORECASE)
    texts = [_strip_html(it).strip() for it in items]
    return [t for t in texts if t != ""]


def _normalize_number_tokens(s: str) -> List[str]:
    # Returns normalized numeric tokens (without commas) found in a string
    tokens = re.findall(r'\d[\d,]*', s)
    norm = [t.replace(",", "") for t in tokens]
    return norm


def _number_appears_in_text(n: int, text: str) -> bool:
    plain = str(n)
    comma = f"{n:,}"
    return (plain in text) or (comma in text) or (plain in _normalize_number_tokens(text))


def _compare_baselines_csv(expected: Dict[str, Dict[str, int]], csv_rows: List[Dict[str, str]], header: List[str]) -> Tuple[bool, str]:
    required_header = ["promotion_type","games","avg_attendance","avg_ticket_rev","avg_merch_rev","avg_concessions_rev","avg_social_shares"]
    if header != required_header:
        return False, "Header does not match required columns or order."
    # Build map from csv rows
    got: Dict[str, Dict[str, int]] = {}
    seen_pts = set()
    for r in csv_rows:
        pt = r.get("promotion_type", "").strip()
        if pt == "":
            return False, "Missing promotion_type in a row."
        if pt in seen_pts:
            return False, "Duplicate promotion_type rows."
        try:
            row_vals = {
                "promotion_type": pt,
                "games": int(r.get("games", "")),
                "avg_attendance": int(r.get("avg_attendance", "")),
                "avg_ticket_rev": int(r.get("avg_ticket_rev", "")),
                "avg_merch_rev": int(r.get("avg_merch_rev", "")),
                "avg_concessions_rev": int(r.get("avg_concessions_rev", "")),
                "avg_social_shares": int(r.get("avg_social_shares", "")),
            }
        except Exception:
            return False, "Non-integer values found in baseline averages or games."
        got[pt] = row_vals
        seen_pts.add(pt)
    if set(got.keys()) != set(expected.keys()):
        return False, "Set of promotion_type values does not match expected."
    for pt, exp_vals in expected.items():
        row = got.get(pt)
        if not row:
            return False, f"Missing row for promotion_type={pt}"
        # Compare all numeric fields
        for key in ["games","avg_attendance","avg_ticket_rev","avg_merch_rev","avg_concessions_rev","avg_social_shares"]:
            if row.get(key) != exp_vals.get(key):
                return False, f"Mismatch for {pt} field {key}: got {row.get(key)} != expected {exp_vals.get(key)}"
    return True, ""


def _packages_list_to_map(packages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {p.get("name"): p for p in packages if isinstance(p, dict) and "name" in p}


def _compare_packages_json(expected: List[Dict[str, Any]], got: Any) -> Tuple[bool, str]:
    if not isinstance(got, list):
        return False, "packages.json is not a JSON array."
    exp_map = _packages_list_to_map(expected)
    got_map = _packages_list_to_map(got)
    if set(exp_map.keys()) != set(got_map.keys()):
        return False, "Set of package names does not match expected."
    for name, exp in exp_map.items():
        g = got_map.get(name)
        if not isinstance(g, dict):
            return False, f"Package {name} is not an object."
        # base_price must be number and equal
        if "base_price" not in g or not isinstance(g["base_price"], (int, float)):
            return False, f"Package {name} missing numeric base_price."
        # Normalize to int if whole
        exp_bp = exp["base_price"]
        got_bp = int(g["base_price"]) if int(g["base_price"]) == g["base_price"] else g["base_price"]
        if got_bp != exp_bp:
            return False, f"Package {name} base_price mismatch: got {got_bp} != expected {exp_bp}"
        # benefits and add_ons arrays
        for arr_key in ["benefits", "add_ons"]:
            if arr_key not in g or not isinstance(g[arr_key], list) or not all(isinstance(x, str) for x in g[arr_key]):
                return False, f"Package {name} missing {arr_key} string array."
            exp_list = exp[arr_key]
            got_list = g[arr_key]
            # Compare as sets (order-insensitive), after stripping spaces
            exp_set = {s.strip() for s in exp_list}
            got_set = {s.strip() for s in got_list}
            if exp_set != got_set:
                return False, f"Package {name} {arr_key} mismatch."
    return True, ""


def _find_last_section(text: str, header: str) -> Optional[str]:
    idx = text.rfind(header)
    if idx == -1:
        return None
    return text[idx:]


def _extract_between(text: str, start: str, end: Optional[str]) -> Optional[str]:
    sidx = text.find(start)
    if sidx == -1:
        return None
    if end is None:
        return text[sidx:]
    eidx = text.find(end, sidx + len(start))
    if eidx == -1:
        return text[sidx:]
    return text[sidx:eidx]


def _check_test_plan_section(plan_text: str, expected_family_concessions: int, expected_theme_merch: int, packages: Dict[str, Dict[str, Any]]) -> Tuple[bool, Dict[str, str]]:
    # Verify two tests within the section
    results: Dict[str, str] = {}
    ok = True

    test_a = _extract_between(plan_text, "Test A", "Test B")
    test_b = _extract_between(plan_text, "Test B", None)

    # We require both segments to exist
    if not test_a:
        ok = False
        results["test_a_spec_correct"] = "0.0"
    else:
        # Check package and add-on names
        pkg_name = "Family Pack"
        addon_name = "Concession Voucher ($15)"
        # Validate that extracted packages contain these (sanity)
        if pkg_name not in packages or addon_name not in set(packages[pkg_name]["add_ons"]):
            ok = False
        conds = []
        conds.append(pkg_name in test_a)
        conds.append(addon_name in test_a)
        # related promotion type
        conds.append("Family Pack" in test_a)
        # primary metric contains 'concessions'
        conds.append(re.search(r'concession', test_a, flags=re.IGNORECASE) is not None)
        # baseline value
        conds.append(_number_appears_in_text(expected_family_concessions, test_a))
        # success threshold +8%
        conds.append(re.search(r'\+?\s*8\s*%', test_a) is not None)
        if all(conds):
            results["test_a_spec_correct"] = "1.0"
        else:
            results["test_a_spec_correct"] = "0.0"
            ok = False

    if not test_b:
        ok = False
        results["test_b_spec_correct"] = "0.0"
    else:
        pkg_name_b = "Theme Night Bundle"
        addon_name_b = "Merch Discount (10%)"
        if pkg_name_b not in packages or addon_name_b not in set(packages[pkg_name_b]["add_ons"]):
            ok = False
        conds_b = []
        conds_b.append(pkg_name_b in test_b)
        conds_b.append(addon_name_b in test_b)
        # related promotion type "Theme Night"
        conds_b.append("Theme Night" in test_b)
        # primary metric contains 'merch'
        conds_b.append(re.search(r'merch', test_b, flags=re.IGNORECASE) is not None)
        # baseline value
        conds_b.append(_number_appears_in_text(expected_theme_merch, test_b))
        # success threshold +10%
        conds_b.append(re.search(r'\+?\s*10\s*%', test_b) is not None)
        if all(conds_b):
            results["test_b_spec_correct"] = "1.0"
        else:
            results["test_b_spec_correct"] = "0.0"
            ok = False

    # Check that the section starts with the proper header
    if not plan_text.lstrip().startswith("## Test Plan"):
        ok = False
        results["test_plan_section_appended"] = "0.0"
    else:
        results["test_plan_section_appended"] = "1.0" if ok else results.get("test_plan_section_appended", "0.0")

    return ok, results


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "baselines_csv_correct": 0.0,
        "packages_json_correct": 0.0,
        "test_plan_section_appended": 0.0,
        "test_a_spec_correct": 0.0,
        "test_b_spec_correct": 0.0,
        "tests_json_correct": 0.0,
        "test_plan_status_summary_valid": 0.0,
    }

    # Input paths
    input_csv_path = workspace / "input" / "past_engagement.csv"
    input_html_path = workspace / "input" / "ticket_packages.html"
    input_md_path = workspace / "input" / "fan_ideas.md"

    # Output paths
    out_baselines_csv = workspace / "output" / "baselines.csv"
    out_packages_json = workspace / "output" / "packages.json"
    out_tests_json = workspace / "output" / "tests.json"
    out_status_md = workspace / "output" / "test_plan_status.md"

    # Prepare expected baselines
    expected_baselines: Optional[Dict[str, Dict[str, int]]] = None
    if input_csv_path.exists():
        rows = _load_csv_dicts(input_csv_path)
        if rows is not None and len(rows) > 0:
            try:
                expected_baselines = _compute_baselines(rows)
            except Exception:
                expected_baselines = None
        else:
            expected_baselines = None

    # Prepare expected packages
    expected_packages_list: Optional[List[Dict[str, Any]]] = None
    if input_html_path.exists():
        html = _read_text(input_html_path)
        if html is not None:
            try:
                expected_packages_list = _parse_packages_html(html)
            except Exception:
                expected_packages_list = None

    # Check baselines.csv
    if expected_baselines is not None and out_baselines_csv.exists():
        parsed_out_rows = _load_csv_dicts(out_baselines_csv)
        if parsed_out_rows is not None:
            # Get header
            try:
                with out_baselines_csv.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader)
            except Exception:
                header = []
            ok, _msg = _compare_baselines_csv(expected_baselines, parsed_out_rows, header)
            scores["baselines_csv_correct"] = 1.0 if ok else 0.0
        else:
            scores["baselines_csv_correct"] = 0.0
    else:
        # Missing input to compute expected or output file
        scores["baselines_csv_correct"] = 0.0

    # Check packages.json
    if expected_packages_list is not None and out_packages_json.exists():
        got_packages = _load_json(out_packages_json)
        if got_packages is not None:
            ok, _msg = _compare_packages_json(expected_packages_list, got_packages)
            scores["packages_json_correct"] = 1.0 if ok else 0.0
        else:
            scores["packages_json_correct"] = 0.0
    else:
        scores["packages_json_correct"] = 0.0

    # For plan checks, we need expected baselines for specific tests and extracted packages
    expected_family_concessions = None
    expected_theme_merch = None
    if expected_baselines is not None:
        fam = expected_baselines.get("Family Pack")
        thm = expected_baselines.get("Theme Night")
        if fam and thm:
            expected_family_concessions = fam.get("avg_concessions_rev")
            expected_theme_merch = thm.get("avg_merch_rev")

    # Build map of expected packages by name
    expected_packages_map: Dict[str, Dict[str, Any]] = {}
    if expected_packages_list is not None:
        expected_packages_map = _packages_list_to_map(expected_packages_list)

    # Check input/fan_ideas.md appended Test Plan
    plan_text_full = None
    if input_md_path.exists():
        plan_text_full = _read_text(input_md_path)

    if plan_text_full is not None and expected_family_concessions is not None and expected_theme_merch is not None and expected_packages_map:
        last_section = _find_last_section(plan_text_full, "## Test Plan")
        if last_section is not None:
            ok, plan_scores = _check_test_plan_section(
                last_section,
                expected_family_concessions,
                expected_theme_merch,
                expected_packages_map
            )
            # Populate individual scores
            scores["test_plan_section_appended"] = float(plan_scores.get("test_plan_section_appended", "0.0"))
            scores["test_a_spec_correct"] = float(plan_scores.get("test_a_spec_correct", "0.0"))
            scores["test_b_spec_correct"] = float(plan_scores.get("test_b_spec_correct", "0.0"))
        else:
            scores["test_plan_section_appended"] = 0.0
            scores["test_a_spec_correct"] = 0.0
            scores["test_b_spec_correct"] = 0.0
    else:
        scores["test_plan_section_appended"] = 0.0
        scores["test_a_spec_correct"] = 0.0
        scores["test_b_spec_correct"] = 0.0

    # Check tests.json
    if out_tests_json.exists() and expected_family_concessions is not None and expected_theme_merch is not None:
        tests_data = _load_json(out_tests_json)
        valid = True
        if not isinstance(tests_data, list) or len(tests_data) != 2:
            valid = False
        else:
            # Find tests by add_on and package
            found_a = False
            found_b = False
            for t in tests_data:
                if not isinstance(t, dict):
                    valid = False
                    break
                required_fields = ["test_id","idea_name","target_package_name","add_on","related_promotion_type","primary_metric","baseline_avg","success_threshold_percent","notes"]
                if any(k not in t for k in required_fields):
                    valid = False
                    break
                # Check types
                if not isinstance(t["test_id"], str): valid = False
                if not isinstance(t["idea_name"], str): valid = False
                if not isinstance(t["target_package_name"], str): valid = False
                if not isinstance(t["add_on"], str): valid = False
                if not isinstance(t["related_promotion_type"], str): valid = False
                if not isinstance(t["primary_metric"], str): valid = False
                if not isinstance(t["baseline_avg"], (int, float)): valid = False
                if not isinstance(t["success_threshold_percent"], (int, float)): valid = False
                if not isinstance(t["notes"], str): valid = False
                if not valid:
                    break
                # Identify Test A
                if t["target_package_name"] == "Family Pack" and t["add_on"] == "Concession Voucher ($15)":
                    # related promotion type
                    if t["related_promotion_type"] != "Family Pack": valid = False
                    # primary metric must reference concessions
                    if re.search(r'concession', t["primary_metric"], flags=re.IGNORECASE) is None: valid = False
                    # baseline
                    if int(round(float(t["baseline_avg"]))) != expected_family_concessions: valid = False
                    # threshold
                    if int(round(float(t["success_threshold_percent"]))) != 8: valid = False
                    found_a = True
                # Identify Test B
                if t["target_package_name"] == "Theme Night Bundle" and t["add_on"] == "Merch Discount (10%)":
                    if t["related_promotion_type"] != "Theme Night": valid = False
                    if re.search(r'merch', t["primary_metric"], flags=re.IGNORECASE) is None: valid = False
                    if int(round(float(t["baseline_avg"]))) != expected_theme_merch: valid = False
                    if int(round(float(t["success_threshold_percent"]))) != 10: valid = False
                    found_b = True
            if not (found_a and found_b):
                valid = False
        scores["tests_json_correct"] = 1.0 if valid else 0.0
    else:
        scores["tests_json_correct"] = 0.0

    # Check test_plan_status.md
    if out_status_md.exists() and expected_baselines is not None and expected_packages_list is not None:
        status_text = _read_text(out_status_md) or ""
        valid_status = True
        # Must mention source files used (paths) and that fan_ideas.md was appended
        src_requirements = all(p in status_text for p in ["input/past_engagement.csv", "input/ticket_packages.html", "input/fan_ideas.md"])
        appended_mention = ("append" in status_text.lower() or "appended" in status_text.lower() or "updated" in status_text.lower()) and ("input/fan_ideas.md" in status_text)
        if not (src_requirements and appended_mention):
            valid_status = False
        # Must summarize baselines with rounded averages.
        # Require that all promotion types are mentioned
        for pt in expected_baselines.keys():
            if pt not in status_text:
                valid_status = False
                break
        # Require at least avg_attendance numbers for all types appear somewhere
        if valid_status:
            for pt, vals in expected_baselines.items():
                if not _number_appears_in_text(vals["avg_attendance"], status_text):
                    valid_status = False
                    break
        # Require the specific baselines used for tests to appear
        fam = expected_baselines.get("Family Pack", {})
        thm = expected_baselines.get("Theme Night", {})
        fam_conc = fam.get("avg_concessions_rev")
        thm_merch = thm.get("avg_merch_rev")
        if valid_status and (fam_conc is not None and thm_merch is not None):
            if not _number_appears_in_text(fam_conc, status_text):
                valid_status = False
            if not _number_appears_in_text(thm_merch, status_text):
                valid_status = False
        # Must list packages/add-ons discovered (at least names and add-ons of interest)
        pkg_names_ok = all(p.get("name") in status_text for p in expected_packages_list)
        addons_ok = ("Concession Voucher ($15)" in status_text) and ("Merch Discount (10%)" in status_text)
        if not (pkg_names_ok and addons_ok):
            valid_status = False
        # Must summarize two tests created with thresholds
        if not ("Test A" in status_text and "Test B" in status_text and re.search(r'\b8\s*%', status_text) and re.search(r'\b10\s*%', status_text)):
            valid_status = False
        scores["test_plan_status_summary_valid"] = 1.0 if valid_status else 0.0
    else:
        scores["test_plan_status_summary_valid"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()