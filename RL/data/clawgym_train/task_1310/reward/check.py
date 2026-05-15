import json
import csv
import sys
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    lines = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        lines.append(obj)
                    else:
                        return None
                except Exception:
                    return None
        return lines
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _simple_yaml_load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        # Detect list item lines (indented and starts with "- ")
        if current_list_key is not None:
            if re.match(r"^\s*-\s+", raw_line):
                val = re.sub(r"^\s*-\s+", "", raw_line).strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                data[current_list_key].append(val)
                continue
            else:
                current_list_key = None
        if raw_line.strip().endswith(":"):
            key = raw_line.split(":", 1)[0].strip()
            data[key] = []
            current_list_key = key
            continue
        if ":" in raw_line:
            key, val = raw_line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if re.fullmatch(r"-?\d+", val):
                try:
                    data[key] = int(val)
                    continue
                except Exception:
                    pass
            data[key] = val
        else:
            continue
    return data


def _compute_expected(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    apps_path = workspace / "input" / "pesticide_applications.csv"
    harvest_path = workspace / "input" / "harvest_schedule.csv"
    products_path = workspace / "input" / "inventory" / "products.csv"
    policy_path = workspace / "input" / "policy_rules.yaml"
    training_path = workspace / "input" / "worker_training.jsonl"

    apps = _safe_load_csv(apps_path)
    harvests = _safe_load_csv(harvest_path)
    products = _safe_load_csv(products_path)
    policy = _simple_yaml_load(policy_path)
    training_records = _safe_load_jsonl(training_path)

    if any(x is None for x in [apps, harvests, products, policy, training_records]):
        return None

    prod_map: Dict[str, Dict[str, Any]] = {}
    for row in products:
        name = row.get("product_name", "").strip()
        ai = row.get("active_ingredient", "").strip()
        try:
            phi_days = int(row.get("PHI_days", "").strip())
        except Exception:
            return None
        try:
            max_per_season = int(row.get("max_applications_per_season", "").strip())
        except Exception:
            return None
        prod_map[name] = {
            "active_ingredient": ai,
            "PHI_days": phi_days,
            "max_applications_per_season": max_per_season,
        }

    allowed = policy.get("allowed_active_ingredients", [])
    if not isinstance(allowed, list):
        return None
    try:
        training_within_days = int(policy.get("require_training_within_days"))
    except Exception:
        return None
    season_start_str = policy.get("season_start_date")
    season_end_str = policy.get("season_end_date")
    if not isinstance(season_start_str, str) or not isinstance(season_end_str, str):
        return None
    season_start = _parse_date(season_start_str)
    season_end = _parse_date(season_end_str)
    if not season_start or not season_end:
        return None

    harvest_by_field: Dict[str, List[date]] = {}
    for row in harvests:
        fid = row.get("field_id", "").strip()
        hd = _parse_date(row.get("harvest_date", "").strip())
        if not fid or not hd:
            return None
        harvest_by_field.setdefault(fid, []).append(hd)
    for fid in list(harvest_by_field.keys()):
        harvest_by_field[fid].sort()

    training_map: Dict[str, List[date]] = {}
    for rec in training_records:
        wn = rec.get("worker_name")
        td = rec.get("training_date")
        if not isinstance(wn, str) or not isinstance(td, str):
            return None
        d = _parse_date(td)
        if not d:
            return None
        training_map.setdefault(wn.strip(), []).append(d)
    for wn in list(training_map.keys()):
        training_map[wn].sort()

    parsed_apps = []
    for row in apps:
        ad = _parse_date(row.get("date", "").strip())
        if not ad:
            return None
        if ad < season_start or ad > season_end:
            continue
        fid = row.get("field_id", "").strip()
        crop = row.get("crop", "").strip()
        prod = row.get("product_name", "").strip()
        applicator = row.get("applicator_name", "").strip()
        if not (fid and crop and prod and applicator):
            return None
        if prod not in prod_map:
            return None
        parsed_apps.append({
            "date": ad,
            "field_id": fid,
            "crop": crop,
            "product_name": prod,
            "applicator_name": applicator,
        })

    parsed_apps.sort(key=lambda x: (x["date"], x["field_id"], x["product_name"]))

    violations: List[Dict[str, Any]] = []

    counts_by_field_product: Dict[tuple, int] = {}
    for app in parsed_apps:
        ad = app["date"]
        fid = app["field_id"]
        crop = app["crop"]
        prod = app["product_name"]
        applicator = app["applicator_name"]
        prod_info = prod_map[prod]
        ai = prod_info["active_ingredient"]
        phi_days = prod_info["PHI_days"]
        max_per_season = prod_info["max_applications_per_season"]

        if ai not in allowed:
            violations.append({
                "violation_type": "not_allowed_active_ingredient",
                "application_date": ad.isoformat(),
                "field_id": fid,
                "crop": crop,
                "product_name": prod,
                "active_ingredient": ai,
                "rule_reference": "policy_rules.yaml",
                "details": "",
                "severity": "critical",
            })

        hdates = harvest_by_field.get(fid, [])
        next_harvest: Optional[date] = None
        for h in hdates:
            if h >= ad:
                next_harvest = h
                break
        if next_harvest is not None:
            diff_days = (next_harvest - ad).days
            if diff_days < phi_days:
                violations.append({
                    "violation_type": "phi_violation",
                    "application_date": ad.isoformat(),
                    "field_id": fid,
                    "crop": crop,
                    "product_name": prod,
                    "active_ingredient": ai,
                    "rule_reference": "policy_rules.yaml",
                    "details": "",
                    "severity": "major",
                })

        key = (fid, prod)
        counts_by_field_product[key] = counts_by_field_product.get(key, 0) + 1
        if counts_by_field_product[key] > max_per_season:
            violations.append({
                "violation_type": "max_applications_exceeded",
                "application_date": ad.isoformat(),
                "field_id": fid,
                "crop": crop,
                "product_name": prod,
                "active_ingredient": ai,
                "rule_reference": "inventory/products.csv",
                "details": "",
                "severity": "minor",
            })

        trainings = training_map.get(applicator, [])
        within = False
        for td in trainings:
            if td <= ad and (ad - td).days <= training_within_days:
                within = True
                break
        if not within:
            violations.append({
                "violation_type": "training_outdated_or_missing",
                "application_date": ad.isoformat(),
                "field_id": fid,
                "crop": crop,
                "product_name": prod,
                "active_ingredient": ai,
                "rule_reference": "policy_rules.yaml",
                "details": "",
                "severity": "major",
            })

    return violations


def _multiset_tuples(violations: List[Dict[str, Any]]) -> Dict[tuple, int]:
    counts: Dict[tuple, int] = {}
    for v in violations:
        key = (
            v.get("violation_type"),
            v.get("application_date"),
            v.get("field_id"),
            v.get("crop"),
            v.get("product_name"),
            v.get("active_ingredient"),
            v.get("rule_reference"),
            v.get("severity"),
        )
        counts[key] = counts.get(key, 0) + 1
    return counts


def _parse_int_token_list(text: str) -> List[int]:
    return [int(m.group(0)) for m in re.finditer(r"\b\d+\b", text)]


def _has_number(text: str, n: int) -> bool:
    for val in _parse_int_token_list(text):
        if val == n:
            return True
    words_map = {
        0: "zero",
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
    }
    w = words_map.get(n)
    if w and re.search(r"\b" + re.escape(w) + r"\b", text, flags=re.IGNORECASE):
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "violations_json_parseable_and_schema": 0.0,
        "violations_json_matches_expected": 0.0,
        "summary_csv_structure_and_counts": 0.0,
        "email_under_150_words": 0.0,
        "email_includes_total_and_types_with_counts": 0.0,
        "email_includes_field_product_pair": 0.0,
        "repro_command_one_line_nonempty": 0.0,
    }

    expected = _compute_expected(workspace)

    violations_path = workspace / "output" / "compliance_violations.json"
    produced = _safe_load_json(violations_path)

    schema_ok = False
    produced_list: List[Dict[str, Any]] = []
    if isinstance(produced, list):
        required_keys = {"violation_type", "application_date", "field_id", "crop", "product_name", "active_ingredient", "rule_reference", "details", "severity"}
        schema_ok = True
        for item in produced:
            if not isinstance(item, dict):
                schema_ok = False
                break
            keys = set(item.keys())
            if keys != required_keys:
                schema_ok = False
                break
            if not isinstance(item.get("details"), str):
                schema_ok = False
                break
            ad = item.get("application_date")
            if not isinstance(ad, str) or _parse_date(ad) is None:
                schema_ok = False
                break
        if schema_ok:
            produced_list = produced
    if schema_ok:
        scores["violations_json_parseable_and_schema"] = 1.0

    if expected is not None and produced_list:
        expected_clean = []
        for e in expected:
            ec = dict(e)
            ec["details"] = ""
            expected_clean.append(ec)
        prod_clean = []
        for p in produced_list:
            pc = dict(p)
            pc["details"] = ""
            prod_clean.append(pc)
        exp_ms = _multiset_tuples(expected_clean)
        prod_ms = _multiset_tuples(prod_clean)
        if exp_ms == prod_ms:
            scores["violations_json_matches_expected"] = 1.0

    summary_csv_path = workspace / "output" / "compliance_summary.csv"
    summary_ok = False
    csv_rows = _safe_load_csv(summary_csv_path)
    if csv_rows is not None:
        try:
            with summary_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        if header == ["violation_type", "count"]:
            summary_counts: Dict[str, int] = {}
            try:
                for r in csv_rows:
                    vt = (r.get("violation_type") or "").strip()
                    ct_str = (r.get("count") or "").strip()
                    if not vt:
                        raise ValueError("empty type")
                    ct = int(ct_str)
                    summary_counts[vt] = ct
                summary_ok = True
            except Exception:
                summary_ok = False

            if summary_ok and produced_list:
                json_counts: Dict[str, int] = {}
                for v in produced_list:
                    vt = v["violation_type"]
                    json_counts[vt] = json_counts.get(vt, 0) + 1
                if summary_counts == json_counts:
                    scores["summary_csv_structure_and_counts"] = 1.0

    email_path = workspace / "output" / "compliance_summary_email.txt"
    email_text = _read_text(email_path) or ""
    if email_text:
        words = re.findall(r"\b\w+\b", email_text)
        if len(words) <= 150:
            scores["email_under_150_words"] = 1.0

        if expected is not None:
            total_expected = len(expected)
            counts_by_type: Dict[str, int] = {}
            for v in expected:
                vt = v["violation_type"]
                counts_by_type[vt] = counts_by_type.get(vt, 0) + 1
            total_ok = _has_number(email_text, total_expected)
            types_ok = True
            lines = email_text.splitlines()
            for vt, ct in counts_by_type.items():
                found_line = False
                for ln in lines:
                    if vt in ln:
                        if _has_number(ln, ct):
                            found_line = True
                            break
                if not found_line:
                    types_ok = False
                    break
            if total_ok and types_ok:
                scores["email_includes_total_and_types_with_counts"] = 1.0

        valid_pairs = [
            ("F1", "Entrust SC"),
            ("F2", "Champ WG"),
            ("F1", "Warrior II"),
            ("F3", "Entrust SC"),
        ]
        pair_ok = False
        for ln in email_text.splitlines():
            lnl = ln.lower()
            for fid, prod in valid_pairs:
                if fid.lower() in lnl and prod.lower() in lnl:
                    pair_ok = True
                    break
            if pair_ok:
                break
        if pair_ok:
            scores["email_includes_field_product_pair"] = 1.0

    repro_path = workspace / "output" / "repro_command.txt"
    repro_txt = _read_text(repro_path)
    if repro_txt is not None:
        lines = repro_txt.splitlines()
        if len(lines) == 1 and lines[0].strip():
            scores["repro_command_one_line_nonempty"] = 1.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()