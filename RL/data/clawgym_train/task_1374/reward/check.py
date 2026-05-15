import sys
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path) -> Any:
    try:
        return json.loads(_safe_read_text(path))
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> List[Dict[str, Any]] or None:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> List[Dict[str, str]] or None:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_date(date_str: str) -> Any:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _is_yes(val: str) -> bool:
    return isinstance(val, str) and val.strip().upper() == "YES"


def _is_no(val: str) -> bool:
    return isinstance(val, str) and val.strip().upper() == "NO"


def _parse_int(val: str) -> Any:
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s == "":
            return None
        if "." in s:
            f = float(s)
            if abs(f - int(f)) < 1e-9:
                return int(f)
            return None
        return int(s)
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Dict[str, Any] or None:
    deals_path = workspace / "input" / "deals.csv"
    rules_path = workspace / "input" / "compliance_rules.json"
    commitments_path = workspace / "input" / "existing_commitments.json"

    deals_rows = _safe_read_csv_dicts(deals_path)
    rules = _safe_load_json(rules_path)
    commitments = _safe_load_json(commitments_path)

    if deals_rows is None or rules is None or commitments is None:
        return None

    mandatory_fields = [
        "deal_id",
        "partner_name",
        "category",
        "territories",
        "start_date",
        "end_date",
        "exclusivity",
        "usage_rights_months_after_end",
    ]

    valid_deals = []
    invalid_rows_info = []
    for idx, row in enumerate(deals_rows, start=2):  # header at row 1
        missing_or_blank = any((row.get(f) is None or str(row.get(f)).strip() == "") for f in mandatory_fields)
        if missing_or_blank:
            invalid_rows_info.append((idx, row.get("deal_id") or ""))
            continue

        sd = _parse_date(row["start_date"].strip())
        ed = _parse_date(row["end_date"].strip())
        if sd is None or ed is None:
            invalid_rows_info.append((idx, row.get("deal_id") or ""))
            continue

        if not (_is_yes(row["exclusivity"]) or _is_no(row["exclusivity"])):
            invalid_rows_info.append((idx, row.get("deal_id") or ""))
            continue

        urm = _parse_int(row["usage_rights_months_after_end"])
        if urm is None:
            invalid_rows_info.append((idx, row.get("deal_id") or ""))
            continue

        territories_raw = row.get("territories", "")
        territories = [t.strip() for t in territories_raw.split(";") if t.strip() != ""]
        if not territories:
            invalid_rows_info.append((idx, row.get("deal_id") or ""))
            continue

        valid_deals.append({
            "row_number": idx,
            "deal_id": row["deal_id"].strip(),
            "partner_name": row["partner_name"].strip(),
            "category": row["category"].strip(),
            "territories": territories,
            "start_date": sd,
            "end_date": ed,
            "exclusivity": _is_yes(row["exclusivity"]),
            "alcohol_marketing": _is_yes(row.get("alcohol_marketing", "")),
            "gambling_marketing": _is_yes(row.get("gambling_marketing", "")),
            "health_warning_required": _is_yes(row.get("health_warning_required", "")),
            "usage_rights_months_after_end": urm,
        })

    territory_restrictions = rules.get("territory_restrictions", {})
    usage_max = rules.get("usage_rights", {}).get("max_post_term_months")
    violation_types = rules.get("violation_types", {})
    enforce_exclusivity = rules.get("exclusivity", {}).get("enforce_unique_active_exclusivity_by_category", False)

    exclusives = commitments.get("exclusives", []) if isinstance(commitments.get("exclusives", []), list) else []

    def _territory_disallows_gambling(t: str) -> bool:
        info = territory_restrictions.get(t, {})
        return bool(info.get("disallow_gambling_marketing"))

    def _uk_requires_health_warning() -> bool:
        info = territory_restrictions.get("UK", {})
        return bool(info.get("alcohol_requires_health_warning"))

    def _dates_overlap(a_start, a_end, b_start, b_end) -> bool:
        return not (a_end < b_start or b_end < a_start)

    expected_violations = []
    for deal in valid_deals:
        if deal["gambling_marketing"]:
            if any(_territory_disallows_gambling(t) for t in deal["territories"]):
                vt = violation_types.get("gambling_in_restricted_territory", {})
                expected_violations.append({
                    "deal_id": deal["deal_id"],
                    "rule": "gambling_in_restricted_territory",
                    "severity": vt.get("severity"),
                    "weight": vt.get("weight"),
                })

        if deal["alcohol_marketing"]:
            if "UK" in deal["territories"] and _uk_requires_health_warning():
                if not deal["health_warning_required"]:
                    vt = violation_types.get("alcohol_missing_health_warning", {})
                    expected_violations.append({
                        "deal_id": deal["deal_id"],
                        "rule": "alcohol_missing_health_warning",
                        "severity": vt.get("severity"),
                        "weight": vt.get("weight"),
                    })

        if enforce_exclusivity and deal["exclusivity"]:
            for ex in exclusives:
                try:
                    if not ex.get("exclusivity", False):
                        continue
                    if str(ex.get("category", "")).strip() != deal["category"]:
                        continue
                    ex_sd = _parse_date(str(ex.get("start_date", "")).strip())
                    ex_ed = _parse_date(str(ex.get("end_date", "")).strip())
                    if ex_sd is None or ex_ed is None:
                        continue
                    if _dates_overlap(deal["start_date"], deal["end_date"], ex_sd, ex_ed):
                        vt = violation_types.get("exclusivity_conflict", {})
                        expected_violations.append({
                            "deal_id": deal["deal_id"],
                            "rule": "exclusivity_conflict",
                            "severity": vt.get("severity"),
                            "weight": vt.get("weight"),
                        })
                        break
                except Exception:
                    continue

        if isinstance(usage_max, int):
            if deal["usage_rights_months_after_end"] > usage_max:
                vt = violation_types.get("usage_rights_exceed_limit", {})
                expected_violations.append({
                    "deal_id": deal["deal_id"],
                    "rule": "usage_rights_exceed_limit",
                    "severity": vt.get("severity"),
                    "weight": vt.get("weight"),
                })

    summary = []
    vio_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    for v in expected_violations:
        vio_by_deal.setdefault(v["deal_id"], []).append(v)

    for deal in valid_deals:
        vlist = vio_by_deal.get(deal["deal_id"], [])
        crit = sum(1 for v in vlist if v["severity"] == "critical")
        maj = sum(1 for v in vlist if v["severity"] == "major")
        minor = sum(1 for v in vlist if v["severity"] == "minor")
        risk = sum(int(v["weight"]) for v in vlist if isinstance(v["weight"], int))
        summary.append({
            "deal_id": deal["deal_id"],
            "partner_name": deal["partner_name"],
            "critical_count": crit,
            "major_count": maj,
            "minor_count": minor,
            "risk_score": risk,
        })

    violated = [row for row in summary if row["risk_score"] > 0]
    violated_sorted = sorted(
        violated,
        key=lambda r: (-r["risk_score"], -r["critical_count"], -r["major_count"], r["deal_id"])
    )
    high_risk_top5 = violated_sorted[:5]

    return {
        "valid_deals": valid_deals,
        "invalid_rows_info": invalid_rows_info,
        "expected_violations": expected_violations,
        "expected_summary": summary,
        "expected_high_risk": high_risk_top5,
    }


def _parse_number(val: str) -> Any:
    try:
        s = str(val).strip()
        if s == "":
            return None
        if "." in s:
            f = float(s)
            if abs(f - int(f)) < 1e-9:
                return int(f)
            return f
        return int(s)
    except Exception:
        try:
            return float(val)
        except Exception:
            return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "violations_jsonl_exists_and_parseable": 0.0,
        "violations_match_expected": 0.0,
        "violations_messages_present": 0.0,
        "summary_csv_matches_expected": 0.0,
        "high_risk_ranked_correct": 0.0,
        "validation_log_exists_and_error_lines": 0.0,
        "import_errors_csv_matches_log": 0.0,
        "import_errors_contains_expected_row": 0.0,
        "summary_excludes_malformed_rows": 0.0,
    }

    out_dir = workspace / "output"
    violations_path = out_dir / "violations.jsonl"
    summary_path = out_dir / "summary.csv"
    highrisk_path = out_dir / "high_risk_ranked.csv"
    log_path = out_dir / "validation.log"
    import_errors_path = out_dir / "import_errors.csv"

    expected = _compute_expected(workspace)

    vlist = None
    if violations_path.exists():
        vlist = _safe_load_jsonl(violations_path)
        if isinstance(vlist, list):
            scores["violations_jsonl_exists_and_parseable"] = 1.0

    if expected is not None and isinstance(vlist, list):
        from collections import Counter

        expected_pairs = [(v["deal_id"], v["rule"]) for v in expected["expected_violations"]]
        expected_counter = Counter(expected_pairs)

        actual_pairs = []
        severity_ok = True
        weight_ok = True
        messages_present = True

        rules = _safe_load_json(workspace / "input" / "compliance_rules.json") or {}
        vtypes = (rules.get("violation_types") or {}) if isinstance(rules, dict) else {}

        for item in vlist:
            if not isinstance(item, dict):
                severity_ok = False
                weight_ok = False
                messages_present = False
                continue
            deal_id = item.get("deal_id")
            rule = item.get("rule")
            actual_pairs.append((deal_id, rule))
            msg = item.get("message")
            if not isinstance(msg, str) or msg.strip() == "":
                messages_present = False
            vt = vtypes.get(rule, {})
            exp_sev = vt.get("severity")
            exp_w = vt.get("weight")
            if item.get("severity") != exp_sev:
                severity_ok = False
            if item.get("weight") != exp_w:
                weight_ok = False

        actual_counter = Counter(actual_pairs)

        if actual_counter == expected_counter and severity_ok and weight_ok:
            scores["violations_match_expected"] = 1.0
        else:
            scores["violations_match_expected"] = 0.0

        if messages_present and len(vlist) > 0:
            scores["violations_messages_present"] = 1.0
        else:
            scores["violations_messages_present"] = 0.0

    if summary_path.exists():
        rows = _safe_read_csv_dicts(summary_path)
        if rows is not None and isinstance(rows, list):
            if expected is not None:
                actual_map = {}
                cols_ok = True
                required_cols = ["deal_id", "partner_name", "critical_count", "major_count", "minor_count", "risk_score"]
                for r in rows:
                    if any(c not in r for c in required_cols):
                        cols_ok = False
                    deal_id = r.get("deal_id", "").strip()
                    if deal_id:
                        actual_map[deal_id] = r
                exp_map = {d["deal_id"]: d for d in expected["expected_summary"]}
                structure_ok = cols_ok and set(actual_map.keys()) == set(exp_map.keys())
                values_ok = True
                for did, exp in exp_map.items():
                    act = actual_map.get(did)
                    if act is None:
                        values_ok = False
                        break
                    if str(act.get("partner_name", "")).strip() != exp["partner_name"]:
                        values_ok = False
                        break
                    try:
                        act_crit = int(_parse_number(act.get("critical_count")))
                        act_maj = int(_parse_number(act.get("major_count")))
                        act_min = int(_parse_number(act.get("minor_count")))
                        act_risk = int(_parse_number(act.get("risk_score")))
                    except Exception:
                        values_ok = False
                        break
                    if not (act_crit == exp["critical_count"] and act_maj == exp["major_count"] and act_min == exp["minor_count"] and act_risk == exp["risk_score"]):
                        values_ok = False
                        break
                if structure_ok and values_ok:
                    scores["summary_csv_matches_expected"] = 1.0

                malformed_ids = set()
                for rn, did in expected["invalid_rows_info"]:
                    if did:
                        malformed_ids.add(did)
                ids_in_summary = {r.get("deal_id", "").strip() for r in rows}
                if not malformed_ids:
                    if len(rows) == len(expected["expected_summary"]):
                        scores["summary_excludes_malformed_rows"] = 1.0
                else:
                    if not (ids_in_summary & malformed_ids):
                        scores["summary_excludes_malformed_rows"] = 1.0

    if highrisk_path.exists():
        rows = _safe_read_csv_dicts(highrisk_path)
        if rows is not None and isinstance(rows, list) and expected is not None:
            required_cols = ["deal_id", "partner_name", "risk_score", "critical_count", "major_count", "minor_count"]
            cols_ok = all(all(c in r for c in required_cols) for r in rows)
            actual = []
            ok_numeric = True
            for r in rows:
                try:
                    actual.append({
                        "deal_id": r.get("deal_id", "").strip(),
                        "partner_name": r.get("partner_name", "").strip(),
                        "risk_score": int(_parse_number(r.get("risk_score"))),
                        "critical_count": int(_parse_number(r.get("critical_count"))),
                        "major_count": int(_parse_number(r.get("major_count"))),
                        "minor_count": int(_parse_number(r.get("minor_count"))),
                    })
                except Exception:
                    ok_numeric = False
                    break
            exp = expected["expected_high_risk"]
            exp_norm = [{
                "deal_id": e["deal_id"],
                "partner_name": e["partner_name"],
                "risk_score": e["risk_score"],
                "critical_count": e["critical_count"],
                "major_count": e["major_count"],
                "minor_count": e["minor_count"],
            } for e in exp]
            if cols_ok and ok_numeric and len(actual) == len(exp_norm) and actual == exp_norm:
                scores["high_risk_ranked_correct"] = 1.0

    error_lines = []
    if log_path.exists():
        content = _safe_read_text(log_path)
        if content:
            lines = content.splitlines()
            for line in lines:
                if line.startswith("ERROR:"):
                    error_lines.append(line)
            if len(error_lines) >= 1:
                scores["validation_log_exists_and_error_lines"] = 1.0

    if import_errors_path.exists() and error_lines:
        csv_rows = _safe_read_csv_dicts(import_errors_path)
        if csv_rows is not None:
            required_cols = ["row_number", "deal_id", "error_message"]
            cols_ok = all(all(c in r for c in required_cols) for r in csv_rows)
            from collections import Counter
            log_messages = [l[len("ERROR:"):].strip() for l in error_lines]
            log_counter = Counter(log_messages)
            csv_messages = [str(r.get("error_message", "")).strip() for r in csv_rows]
            csv_counter = Counter(csv_messages)
            if cols_ok and csv_counter == log_counter:
                scores["import_errors_csv_matches_log"] = 1.0

            has_expected = False
            for r in csv_rows:
                rn = str(r.get("row_number", "")).strip()
                did = str(r.get("deal_id", "")).strip()
                try:
                    rn_int = int(_parse_number(rn))
                except Exception:
                    rn_int = None
                if rn_int == 9 and did == "D008":
                    has_expected = True
                    break
            if has_expected:
                scores["import_errors_contains_expected_row"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()