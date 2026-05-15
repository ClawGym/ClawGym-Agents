import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(p: Path) -> Optional[dict]:
    try:
        txt = _read_text(p)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _parse_csv_baseline(p: Path) -> Optional[Tuple[int, float]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None
        row = rows[0]
        year = int(row["year"])
        share = float(row["renewables_share_percent"])
        return year, share
    except Exception:
        return None


def _parse_yaml_value(val: str) -> Any:
    sval = val.strip()
    if sval == "":
        return None
    # Try int
    try:
        iv = int(sval)
        return iv
    except Exception:
        pass
    # Try float
    try:
        fv = float(sval)
        return fv
    except Exception:
        pass
    # Otherwise return string as is
    return sval


def _parse_policy_yaml(p: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(p)
    if text is None:
        return None
    lines = text.splitlines()
    data: Dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if ":" in line:
            # Determine indentation and key/value
            indent = len(line) - len(line.lstrip(" "))
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            if val == "":
                # Possibly a nested mapping
                # Read following indented lines
                nested: Dict[Any, Any] = {}
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if not nxt.strip() or nxt.strip().startswith("#"):
                        i += 1
                        continue
                    nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                    if nxt_indent <= indent:
                        break
                    # Expect "key: value"
                    if ":" in nxt:
                        nk, nv = nxt.strip().split(":", 1)
                        nk_val = _parse_yaml_value(nk)
                        nv_val = _parse_yaml_value(nv)
                        nested[nk_val] = nv_val
                        i += 1
                    else:
                        # Not a k:v line; break
                        break
                data[key] = nested
                continue  # already advanced i in loop
            else:
                data[key] = _parse_yaml_value(val)
                i += 1
                continue
        else:
            i += 1
            continue
    return data


def _parse_retired_policy_md(p: Path) -> Dict[str, Any]:
    """
    Extracts:
    - claim_household_savings_2030_usd
    - optional target share and year, fee schedule (not required for grading)
    """
    results: Dict[str, Any] = {}
    text = _read_text(p) or ""
    # Claim: "... average household will save about $300/year by 2030."
    claim_match = re.search(r"average household .*?save.*?\$([0-9][0-9,]*(?:\.\d+)?)\s*/?year\s*by\s*2030", text, re.IGNORECASE | re.DOTALL)
    if not claim_match:
        # Try a more relaxed pattern
        claim_match = re.search(r"save.*?\$([0-9][0-9,]*(?:\.\d+)?)", text, re.IGNORECASE)
    if claim_match:
        claim_str = claim_match.group(1).replace(",", "")
        try:
            results["claim_household_savings_2030_usd"] = float(claim_str)
        except Exception:
            pass
    # Target share and year (optional parse)
    tgt_match = re.search(r"(\d{1,3})\s*%[^.\n]*?\bby\s+(\d{4})", text, re.IGNORECASE)
    if tgt_match:
        try:
            results["md_target_renewables_share_percent"] = float(tgt_match.group(1))
            results["md_target_year"] = int(tgt_match.group(2))
        except Exception:
            pass
    # Carbon fee schedule (optional)
    fee_match = re.search(r"Carbon fee:\s*Start\s+at\s*\$([0-9][0-9,]*(?:\.\d+)?)\s*/?ton\s+in\s+(\d{4}),\s*rising\s+to\s*\$([0-9][0-9,]*(?:\.\d+)?)\s*/?ton\s+by\s+(\d{4})", text, re.IGNORECASE)
    if fee_match:
        try:
            results["md_fee_start_usd"] = float(fee_match.group(1).replace(",", ""))
            results["md_fee_start_year"] = int(fee_match.group(2))
            results["md_fee_end_usd"] = float(fee_match.group(3).replace(",", ""))
            results["md_fee_end_year"] = int(fee_match.group(4))
        except Exception:
            pass
    return results


def _num_close(a: float, b: float, abs_tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= abs_tol
    except Exception:
        return False


def _extract_numbers(text: str) -> List[float]:
    if not text:
        return []
    nums: List[float] = []
    # Regex to capture numbers possibly with $ and commas and signs
    for m in re.finditer(r'(?P<sign>[-+])?\$?(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)', text):
        ns = m.group('num').replace(",", "")
        sign = m.group('sign') or ""
        try:
            val = float(sign + ns)
            nums.append(val)
        except Exception:
            continue
    return nums


def _find_value_in_text(text: str, expected: float, tol: float = 0.05) -> bool:
    nums = _extract_numbers(text)
    for n in nums:
        if _num_close(n, expected, abs_tol=tol):
            return True
    return False


def _get_section(text: str, heading: str) -> str:
    """
    Returns text content under the given heading (case-insensitive) until the next heading line
    that starts with '#' or a line with another known section title.
    """
    if not text:
        return ""
    lines = text.splitlines()
    start_idx = None
    pattern = re.compile(rf'^\s*#*+\s*{re.escape(heading)}\s*$', re.IGNORECASE)
    # Also allow lines that contain the heading phrase
    pattern_in = re.compile(rf'{re.escape(heading)}', re.IGNORECASE)
    for idx, line in enumerate(lines):
        if pattern.match(line) or pattern_in.search(line):
            start_idx = idx + 1
            break
    if start_idx is None:
        return ""
    # Find next heading
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        if re.match(r'^\s*#', lines[idx]):
            end_idx = idx
            break
        # If another section label line appears, stop (conservative)
        if re.search(r'Executive Summary|Details|Talking Points', lines[idx], re.IGNORECASE) and idx != start_idx:
            end_idx = idx
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_exist": 0.0,
        "assumption_map_parseable": 0.0,
        "assumption_map_fields_exact": 0.0,
        "baseline_values_correct": 0.0,
        "target_values_correct": 0.0,
        "required_annual_increase_correct": 0.0,
        "max_growth_value_correct": 0.0,
        "exceeds_max_growth_correct": 0.0,
        "computed_savings_correct": 0.0,
        "claim_savings_correct_vs_md": 0.0,
        "discrepancy_correct": 0.0,
        "memo_sections_present": 0.0,
        "memo_cites_sources_files": 0.0,
        "memo_numbers_match_json": 0.0,
        "talking_points_bullets_count_ok": 0.0,
        "email_content_completeness": 0.0,
    }

    # Input paths
    input_dir = workspace / "input"
    policy_yaml_path = input_dir / "policy_config.yaml"
    fee_model_path = input_dir / "fee_model.py"
    policy_md_path = input_dir / "retired_policy.md"
    baseline_csv_path = input_dir / "baseline_energy.csv"

    # Output paths
    analysis_json_path = workspace / "analysis" / "assumption_map.json"
    memo_path = workspace / "output" / "rebuttal_memo.md"
    email_path = workspace / "output" / "internal_email.txt"

    # Check outputs existence
    outputs_exist = analysis_json_path.exists() and memo_path.exists() and email_path.exists()
    scores["outputs_exist"] = 1.0 if outputs_exist else 0.0

    # Parse inputs
    cfg = _parse_policy_yaml(policy_yaml_path) or {}
    baseline = _parse_csv_baseline(baseline_csv_path)
    md_info = _parse_retired_policy_md(policy_md_path)

    # Compute expected values if possible
    expected: Dict[str, Any] = {}
    try:
        if baseline is not None:
            expected["baseline_year"] = baseline[0]
            expected["baseline_renewables_share_percent"] = baseline[1]
        if cfg:
            # Required top-level fields
            expected["target_renewables_share_percent"] = float(cfg.get("target_renewables_share_percent")) if cfg.get("target_renewables_share_percent") is not None else None
            expected["target_year"] = int(cfg.get("target_year")) if cfg.get("target_year") is not None else None
            expected["max_annual_growth_abs_percent"] = float(cfg.get("max_annual_growth_abs_percent")) if cfg.get("max_annual_growth_abs_percent") is not None else None
            # For net savings calculation
            use = cfg.get("avg_household_energy_use_mmbtu_annual")
            delta = cfg.get("cost_increase_per_mmbtu_from_fee_2030")
            rebate = cfg.get("efficiency_rebate_per_household_2030")
            if use is not None and delta is not None and rebate is not None:
                try:
                    computed_savings = float(rebate) - (float(use) * float(delta))
                    expected["computed_household_net_savings_2030_usd"] = computed_savings
                except Exception:
                    expected["computed_household_net_savings_2030_usd"] = None
        # Claim from MD
        if "claim_household_savings_2030_usd" in md_info:
            expected["claim_household_savings_2030_usd"] = float(md_info["claim_household_savings_2030_usd"])
        # Required annual increase and exceeds flag
        by = expected.get("baseline_year")
        bs = expected.get("baseline_renewables_share_percent")
        ty = expected.get("target_year")
        ts = expected.get("target_renewables_share_percent")
        if None not in (by, bs, ty, ts) and isinstance(by, int) and isinstance(ty, int):
            years = ty - by
            if years != 0:
                req_inc = (float(ts) - float(bs)) / years
                expected["required_annual_increase_pp"] = req_inc
            else:
                expected["required_annual_increase_pp"] = None
        if expected.get("required_annual_increase_pp") is not None and expected.get("max_annual_growth_abs_percent") is not None:
            expected["exceeds_max_growth"] = bool(expected["required_annual_increase_pp"] > expected["max_annual_growth_abs_percent"])
        # Discrepancy
        comp = expected.get("computed_household_net_savings_2030_usd")
        claim = expected.get("claim_household_savings_2030_usd")
        if comp is not None and claim is not None:
            # Deterministic rule: discrepancy = computed - claim
            expected["savings_discrepancy_usd"] = float(comp) - float(claim)
    except Exception:
        pass

    # Load analysis/assumption_map.json
    analysis = _load_json(analysis_json_path) if analysis_json_path.exists() else None
    if analysis is not None:
        scores["assumption_map_parseable"] = 1.0
        required_keys = {
            "baseline_year",
            "baseline_renewables_share_percent",
            "target_year",
            "target_renewables_share_percent",
            "required_annual_increase_pp",
            "max_annual_growth_abs_percent",
            "exceeds_max_growth",
            "claim_household_savings_2030_usd",
            "computed_household_net_savings_2030_usd",
            "savings_discrepancy_usd",
        }
        keys_set = set(analysis.keys())
        if keys_set == required_keys:
            scores["assumption_map_fields_exact"] = 1.0
        else:
            scores["assumption_map_fields_exact"] = 0.0

        # Validate baseline values
        try:
            by_ok = isinstance(analysis.get("baseline_year"), int) and expected.get("baseline_year") is not None and analysis["baseline_year"] == expected["baseline_year"]
            bs_ok = isinstance(analysis.get("baseline_renewables_share_percent"), (int, float)) and expected.get("baseline_renewables_share_percent") is not None and _num_close(analysis["baseline_renewables_share_percent"], expected["baseline_renewables_share_percent"])
            scores["baseline_values_correct"] = 1.0 if (by_ok and bs_ok) else 0.0
        except Exception:
            scores["baseline_values_correct"] = 0.0

        # Validate target values
        try:
            ty_ok = isinstance(analysis.get("target_year"), int) and expected.get("target_year") is not None and analysis["target_year"] == expected["target_year"]
            ts_ok = isinstance(analysis.get("target_renewables_share_percent"), (int, float)) and expected.get("target_renewables_share_percent") is not None and _num_close(analysis["target_renewables_share_percent"], expected["target_renewables_share_percent"])
            scores["target_values_correct"] = 1.0 if (ty_ok and ts_ok) else 0.0
        except Exception:
            scores["target_values_correct"] = 0.0

        # Required annual increase
        try:
            rai_ok = isinstance(analysis.get("required_annual_increase_pp"), (int, float)) and expected.get("required_annual_increase_pp") is not None and _num_close(analysis["required_annual_increase_pp"], expected["required_annual_increase_pp"])
            scores["required_annual_increase_correct"] = 1.0 if rai_ok else 0.0
        except Exception:
            scores["required_annual_increase_correct"] = 0.0

        # Max growth value
        try:
            mg_ok = isinstance(analysis.get("max_annual_growth_abs_percent"), (int, float)) and expected.get("max_annual_growth_abs_percent") is not None and _num_close(analysis["max_annual_growth_abs_percent"], expected["max_annual_growth_abs_percent"])
            scores["max_growth_value_correct"] = 1.0 if mg_ok else 0.0
        except Exception:
            scores["max_growth_value_correct"] = 0.0

        # Exceeds flag
        try:
            emg_ok = isinstance(analysis.get("exceeds_max_growth"), bool) and expected.get("exceeds_max_growth") is not None and analysis["exceeds_max_growth"] == expected["exceeds_max_growth"]
            scores["exceeds_max_growth_correct"] = 1.0 if emg_ok else 0.0
        except Exception:
            scores["exceeds_max_growth_correct"] = 0.0

        # Computed savings
        try:
            cs_ok = isinstance(analysis.get("computed_household_net_savings_2030_usd"), (int, float)) and expected.get("computed_household_net_savings_2030_usd") is not None and _num_close(analysis["computed_household_net_savings_2030_usd"], expected["computed_household_net_savings_2030_usd"])
            scores["computed_savings_correct"] = 1.0 if cs_ok else 0.0
        except Exception:
            scores["computed_savings_correct"] = 0.0

        # Claim savings vs markdown
        try:
            clm_ok = isinstance(analysis.get("claim_household_savings_2030_usd"), (int, float)) and expected.get("claim_household_savings_2030_usd") is not None and _num_close(analysis["claim_household_savings_2030_usd"], expected["claim_household_savings_2030_usd"])
            scores["claim_savings_correct_vs_md"] = 1.0 if clm_ok else 0.0
        except Exception:
            scores["claim_savings_correct_vs_md"] = 0.0

        # Discrepancy
        try:
            disc_ok = isinstance(analysis.get("savings_discrepancy_usd"), (int, float)) and expected.get("savings_discrepancy_usd") is not None and _num_close(analysis["savings_discrepancy_usd"], expected["savings_discrepancy_usd"])
            scores["discrepancy_correct"] = 1.0 if disc_ok else 0.0
        except Exception:
            scores["discrepancy_correct"] = 0.0
    else:
        # cannot parse or missing
        scores["assumption_map_parseable"] = 0.0
        scores["assumption_map_fields_exact"] = 0.0
        scores["baseline_values_correct"] = 0.0
        scores["target_values_correct"] = 0.0
        scores["required_annual_increase_correct"] = 0.0
        scores["max_growth_value_correct"] = 0.0
        scores["exceeds_max_growth_correct"] = 0.0
        scores["computed_savings_correct"] = 0.0
        scores["claim_savings_correct_vs_md"] = 0.0
        scores["discrepancy_correct"] = 0.0

    # Memo checks
    memo_text = _read_text(memo_path) if memo_path.exists() else None
    if memo_text is not None:
        # Sections present
        has_exec = re.search(r'Executive Summary', memo_text, re.IGNORECASE) is not None
        has_details = re.search(r'\bDetails\b', memo_text, re.IGNORECASE) is not None
        has_talking = re.search(r'Talking Points', memo_text, re.IGNORECASE) is not None
        scores["memo_sections_present"] = 1.0 if (has_exec and has_details and has_talking) else 0.0

        # Cites sources (file names)
        cites = all(name in memo_text for name in ["policy_config.yaml", "fee_model.py", "retired_policy.md", "baseline_energy.csv"])
        scores["memo_cites_sources_files"] = 1.0 if cites else 0.0

        # Numbers match JSON (if JSON loaded)
        json_ok = True
        if analysis is None:
            json_ok = False
        else:
            # Check presence of key figures
            # required_annual_increase_pp and max_annual_growth_abs_percent
            rai = analysis.get("required_annual_increase_pp")
            mg = analysis.get("max_annual_growth_abs_percent")
            cs = analysis.get("computed_household_net_savings_2030_usd")
            cl = analysis.get("claim_household_savings_2030_usd")
            disc = analysis.get("savings_discrepancy_usd")
            # Tolerant matching in memo text
            for val in [rai, mg, cs, cl, disc]:
                if not isinstance(val, (int, float)):
                    json_ok = False
                    break
            if json_ok:
                tol = 0.05
                if not _find_value_in_text(memo_text, rai, tol=tol):
                    json_ok = False
                if not _find_value_in_text(memo_text, mg, tol=tol):
                    json_ok = False
                if not _find_value_in_text(memo_text, cs, tol=tol):
                    json_ok = False
                if not _find_value_in_text(memo_text, cl, tol=tol):
                    json_ok = False
                if not _find_value_in_text(memo_text, disc, tol=tol):
                    json_ok = False
        scores["memo_numbers_match_json"] = 1.0 if json_ok else 0.0

        # Talking points bullets count 3-5 in that section
        tp_section = _get_section(memo_text, "Talking Points")
        bullet_lines = [ln for ln in tp_section.splitlines() if re.match(r'^\s*[-*]\s+', ln)]
        bullets_ok = 3 <= len(bullet_lines) <= 5
        scores["talking_points_bullets_count_ok"] = 1.0 if bullets_ok else 0.0
    else:
        scores["memo_sections_present"] = 0.0
        scores["memo_cites_sources_files"] = 0.0
        scores["memo_numbers_match_json"] = 0.0
        scores["talking_points_bullets_count_ok"] = 0.0

    # Email checks
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text is not None:
        # Addressed to Government Affairs team
        addressed = re.search(r'Government Affairs', email_text, re.IGNORECASE) is not None
        # Mentions where files are saved (paths)
        mentions_paths = all(s in email_text for s in ["analysis/assumption_map.json", "output/rebuttal_memo.md", "output/internal_email.txt"])
        # Contains the two headline findings numbers (at least the five numbers)
        headline_ok = False
        if analysis is not None:
            tol = 0.05
            need_vals = [
                analysis.get("required_annual_increase_pp"),
                analysis.get("max_annual_growth_abs_percent"),
                analysis.get("computed_household_net_savings_2030_usd"),
                analysis.get("claim_household_savings_2030_usd"),
                analysis.get("savings_discrepancy_usd"),
            ]
            if all(isinstance(v, (int, float)) for v in need_vals):
                headline_ok = all(_find_value_in_text(email_text, v, tol=tol) for v in need_vals)
        # Request for feedback by close of business tomorrow
        feedback_req = (re.search(r'feedback', email_text, re.IGNORECASE) is not None) and (
            re.search(r'close of business|COB', email_text, re.IGNORECASE) is not None
        ) and (re.search(r'tomorrow', email_text, re.IGNORECASE) is not None)
        scores["email_content_completeness"] = 1.0 if (addressed and mentions_paths and headline_ok and feedback_req) else 0.0
    else:
        scores["email_content_completeness"] = 0.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()