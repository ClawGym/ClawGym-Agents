import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    result: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
            val = val[1:-1]
        result[key] = val
    return result


def _parse_date_str(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _discover_engagement_logs(logs_dir: Path) -> Dict[int, Path]:
    mapping: Dict[int, Path] = {}
    if not logs_dir.exists():
        return mapping
    for p in logs_dir.glob("*.json"):
        m = re.search(r"donor_(\d+)\.json$", p.name)
        if m:
            try:
                donor_id = int(m.group(1))
                mapping[donor_id] = p
            except Exception:
                continue
    return mapping


def _compute_expected_scores(workspace: Path) -> Optional[Dict[int, Dict[str, Any]]]:
    donors_csv = workspace / "input" / "donors.csv"
    asof_yaml = workspace / "input" / "config" / "as_of.yaml"
    logs_dir = workspace / "input" / "engagement_logs"

    headers, donor_rows = _safe_read_csv_dicts(donors_csv)
    if headers is None or donor_rows is None:
        return None
    cfg = _parse_simple_yaml(asof_yaml)
    if cfg is None or "as_of_date" not in cfg:
        return None
    as_of_date = _parse_date_str(str(cfg["as_of_date"]))
    if as_of_date is None:
        return None

    logs_map = _discover_engagement_logs(logs_dir)
    expected: Dict[int, Dict[str, Any]] = {}

    for row in donor_rows:
        try:
            donor_id = int(str(row.get("donor_id", "")).strip())
        except Exception:
            return None
        full_name = row.get("full_name", "")
        email = row.get("email", "")
        preferred_channel = row.get("preferred_channel", "")
        base_score = 0.0
        last_activity: Optional[date] = None
        had_log = False

        if donor_id in logs_map:
            log_path = logs_map[donor_id]
            data = _safe_load_json(log_path)
            if isinstance(data, list):
                had_log = True
                for ev in data:
                    if not isinstance(ev, dict):
                        return None
                    ev_type = str(ev.get("event_type", "")).strip().lower()
                    ev_date_str = str(ev.get("date", "")).strip()
                    ev_date = _parse_date_str(ev_date_str)
                    if ev_date is None:
                        return None
                    if last_activity is None or ev_date > last_activity:
                        last_activity = ev_date
                    if ev_type == "donation":
                        amt = ev.get("amount", 0)
                        try:
                            amt_val = float(amt)
                        except Exception:
                            amt_val = 0.0
                        base_score += (amt_val / 100.0)
                    elif ev_type == "event_signup":
                        base_score += 2.0
                    elif ev_type == "volunteer_shift":
                        base_score += 3.0
                    elif ev_type == "email_open":
                        base_score += 0.5
                    else:
                        base_score += 0.0

        total_score = 0.0
        days_since: Optional[int] = None
        recency_bonus = 0.0
        if had_log and last_activity is not None:
            days = (as_of_date - last_activity).days
            days_since = days
            if days <= 30:
                recency_bonus = 5.0
            elif days <= 90:
                recency_bonus = 3.0
            elif days <= 180:
                recency_bonus = 1.0
            else:
                recency_bonus = 0.0
            total_score = base_score + recency_bonus
        else:
            total_score = 0.0

        if not had_log:
            tier = "No Data"
            last_activity_str = ""
            days_since_str = ""
        else:
            last_activity_str = last_activity.isoformat() if last_activity is not None else ""
            days_since_str = str(days_since) if days_since is not None else ""
            if days_since is not None and days_since > 180:
                tier = "Lapsed"
            else:
                if total_score >= 12.0:
                    tier = "Major Prospect"
                elif total_score >= 6.0:
                    tier = "Cultivation"
                else:
                    tier = "Re-engage"

        expected[donor_id] = {
            "donor_id": donor_id,
            "full_name": full_name,
            "email": email,
            "preferred_channel": preferred_channel,
            "total_score": float(total_score),
            "last_activity_date": last_activity_str,
            "days_since_last_activity": days_since_str,
            "classification_tier": tier,
        }

    return expected


def _sort_top5_from_expected(expected: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for v in expected.values():
        last_date = _parse_date_str(v.get("last_activity_date", "")) if v.get("last_activity_date") else None
        items.append({
            **v,
            "_last_date_obj": last_date,
        })

    def sort_key(d: Dict[str, Any]) -> Tuple[Any, ...]:
        total = float(d.get("total_score", 0.0))
        last_date_obj: Optional[date] = d.get("_last_date_obj")
        is_blank = 1 if last_date_obj is None else 0
        neg_ord = 0
        if last_date_obj is not None:
            neg_ord = -last_date_obj.toordinal()
        donor_id = int(d.get("donor_id", 0))
        return (-total, is_blank, neg_ord, donor_id)

    items.sort(key=sort_key)
    return items[:5]


def _read_student_top5(workspace: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    path = workspace / "output" / "top5.csv"
    return _safe_read_csv_dicts(path)


def _read_student_donor_scores(workspace: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    path = workspace / "output" / "donor_scores.csv"
    return _safe_read_csv_dicts(path)


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _check_email_scoring_summary(text: str) -> float:
    t = text.lower()
    donation_ok = ("donation" in t) and (re.search(r"amount\s*/\s*100", t) is not None)
    es_ok = (("event signup" in t) or ("event-signup" in t)) and (re.search(r"(\+?\s*2\b)|(\b2 points\b)", t) is not None)
    vol_ok = ("volunteer" in t) and (re.search(r"(\+?\s*3\b)|(\b3 points\b)", t) is not None)
    open_ok = (("email open" in t) or ("email-open" in t)) and (re.search(r"0\.5", t) is not None)
    has_30 = "30" in t
    has_90 = "90" in t
    has_180 = "180" in t
    has_plus5 = re.search(r"\+?\s*5\b", t) is not None
    has_plus3 = re.search(r"\+?\s*3\b", t) is not None
    has_plus1 = re.search(r"\+?\s*1\b", t) is not None
    recency_ok = (("recency" in t) or ("bonus" in t)) and has_30 and has_90 and has_180 and has_plus5 and has_plus3 and has_plus1
    return 1.0 if (donation_ok and es_ok and vol_ok and open_ok and recency_ok) else 0.0


def _extract_count_for_tier(text: str, tier: str) -> Optional[int]:
    lines = text.splitlines()
    for line in lines:
        if tier.lower() in line.lower():
            m = re.search(r"(-?\d+)", line)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
    return None


def _normalize_score_variants(score: float) -> List[str]:
    variants = set()
    variants.add(f"{score}")
    variants.add(f"{score:.1f}")
    variants.add(f"{score:.2f}")
    trimmed = re.sub(r"(?<=\d)\.0+$", "", f"{score:.6f}")
    trimmed = re.sub(r"(\.\d*?)0+$", r"\1", trimmed)
    if trimmed.endswith("."):
        trimmed = trimmed[:-1]
    variants.add(trimmed)
    return list(variants)


def _check_email_top5_bullets(text: str, top5_rows: List[Dict[str, str]]) -> float:
    lines = [ln.strip() for ln in text.splitlines()]
    bullet_lines = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
    if len(bullet_lines) == 0:
        return 0.0

    for row in top5_rows:
        name = row.get("full_name", "")
        channel = row.get("preferred_channel", "")
        sc = row.get("total_score", "")
        try:
            sc_val = float(sc)
        except Exception:
            return 0.0
        found = False
        score_variants = _normalize_score_variants(sc_val)
        for bl in bullet_lines:
            if name.lower() in bl.lower() and channel.lower() in bl.lower():
                if any(v in bl for v in score_variants):
                    found = True
                    break
        if not found:
            return 0.0
    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "donor_scores_columns": 0.0,
        "donor_scores_row_coverage": 0.0,
        "donor_scores_values_correct": 0.0,
        "top5_columns": 0.0,
        "top5_correct_vs_inputs": 0.0,
        "top5_consistent_with_donor_scores": 0.0,
        "email_exists": 0.0,
        "email_scoring_summary_present": 0.0,
        "email_classification_counts_correct": 0.0,
        "email_top5_bullets_complete": 0.0,
    }

    expected = _compute_expected_scores(workspace)

    ds_headers, ds_rows = _read_student_donor_scores(workspace)
    required_ds_cols = [
        "donor_id",
        "full_name",
        "email",
        "preferred_channel",
        "total_score",
        "last_activity_date",
        "days_since_last_activity",
        "classification_tier",
    ]

    if ds_headers is not None:
        scores["donor_scores_columns"] = 1.0 if ds_headers == required_ds_cols else 0.0
    else:
        scores["donor_scores_columns"] = 0.0

    if ds_rows is not None and expected is not None:
        try:
            ids_in_ds = set()
            for row in ds_rows:
                did = _parse_int(row.get("donor_id", ""))
                ids_in_ds.add(did)
            expected_ids = set(expected.keys())
            if ids_in_ds == expected_ids and len(ds_rows) == len(expected_ids):
                scores["donor_scores_row_coverage"] = 1.0
            else:
                scores["donor_scores_row_coverage"] = 0.0
        except Exception:
            scores["donor_scores_row_coverage"] = 0.0
    else:
        scores["donor_scores_row_coverage"] = 0.0

    if ds_rows is not None and expected is not None and ds_headers == required_ds_cols:
        all_match = True
        for row in ds_rows:
            did = _parse_int(row.get("donor_id", ""))
            if did is None or did not in expected:
                all_match = False
                break
            exp = expected[did]
            if row.get("full_name", "") != exp["full_name"]:
                all_match = False
                break
            if row.get("email", "") != exp["email"]:
                all_match = False
                break
            if row.get("preferred_channel", "") != exp["preferred_channel"]:
                all_match = False
                break
            s_val = _parse_float(row.get("total_score", ""))
            if s_val is None or not _float_eq(s_val, float(exp["total_score"])):
                all_match = False
                break
            if row.get("last_activity_date", "") != exp["last_activity_date"]:
                all_match = False
                break
            if row.get("days_since_last_activity", "") != exp["days_since_last_activity"]:
                all_match = False
                break
            if row.get("classification_tier", "") != exp["classification_tier"]:
                all_match = False
                break
        scores["donor_scores_values_correct"] = 1.0 if all_match else 0.0
    else:
        scores["donor_scores_values_correct"] = 0.0

    t5_headers, t5_rows = _read_student_top5(workspace)
    required_t5_cols = [
        "donor_id",
        "full_name",
        "email",
        "preferred_channel",
        "total_score",
        "classification_tier",
    ]
    if t5_headers is not None:
        scores["top5_columns"] = 1.0 if t5_headers == required_t5_cols else 0.0
    else:
        scores["top5_columns"] = 0.0

    if t5_rows is not None and expected is not None and t5_headers == required_t5_cols:
        expected_top5 = _sort_top5_from_expected(expected)
        exp_len = min(5, len(expected))
        if len(t5_rows) != exp_len:
            scores["top5_correct_vs_inputs"] = 0.0
        else:
            ok = True
            for i, row in enumerate(t5_rows):
                exp_row = expected_top5[i]
                if _parse_int(row.get("donor_id", "")) != int(exp_row["donor_id"]):
                    ok = False
                    break
                if row.get("full_name", "") != exp_row["full_name"]:
                    ok = False
                    break
                if row.get("email", "") != exp_row["email"]:
                    ok = False
                    break
                if row.get("preferred_channel", "") != exp_row["preferred_channel"]:
                    ok = False
                    break
                sval = _parse_float(row.get("total_score", ""))
                if sval is None or not _float_eq(sval, float(exp_row["total_score"])):
                    ok = False
                    break
                if row.get("classification_tier", "") != exp_row["classification_tier"]:
                    ok = False
                    break
            scores["top5_correct_vs_inputs"] = 1.0 if ok else 0.0
    else:
        scores["top5_correct_vs_inputs"] = 0.0

    if t5_rows is not None and ds_rows is not None and t5_headers == required_t5_cols and ds_headers == required_ds_cols:
        enriched: List[Dict[str, Any]] = []
        for r in ds_rows:
            did = _parse_int(r.get("donor_id", ""))
            if did is None:
                continue
            total = _parse_float(r.get("total_score", "0")) or 0.0
            lad_str = r.get("last_activity_date", "")
            lad = _parse_date_str(lad_str) if lad_str else None
            enriched.append({
                "donor_id": did,
                "full_name": r.get("full_name", ""),
                "email": r.get("email", ""),
                "preferred_channel": r.get("preferred_channel", ""),
                "total_score": total,
                "classification_tier": r.get("classification_tier", ""),
                "_last_date_obj": lad,
            })

        def key_fn(d: Dict[str, Any]) -> Tuple[Any, ...]:
            total = float(d.get("total_score", 0.0))
            last_date_obj: Optional[date] = d.get("_last_date_obj")
            is_blank = 1 if last_date_obj is None else 0
            neg_ord = 0
            if last_date_obj is not None:
                neg_ord = -last_date_obj.toordinal()
            donor_id = int(d.get("donor_id", 0))
            return (-total, is_blank, neg_ord, donor_id)

        enriched.sort(key=key_fn)
        expected_from_ds = enriched[:min(5, len(enriched))]
        consistent = True
        if len(t5_rows) != len(expected_from_ds):
            consistent = False
        else:
            for i, row in enumerate(t5_rows):
                exp_row = expected_from_ds[i]
                if _parse_int(row.get("donor_id", "")) != int(exp_row["donor_id"]):
                    consistent = False
                    break
                if row.get("full_name", "") != exp_row["full_name"]:
                    consistent = False
                    break
                if row.get("email", "") != exp_row["email"]:
                    consistent = False
                    break
                if row.get("preferred_channel", "") != exp_row["preferred_channel"]:
                    consistent = False
                    break
                sval = _parse_float(row.get("total_score", ""))
                if sval is None or not _float_eq(sval, float(exp_row["total_score"])):
                    consistent = False
                    break
                if row.get("classification_tier", "") != exp_row["classification_tier"]:
                    consistent = False
                    break
        scores["top5_consistent_with_donor_scores"] = 1.0 if consistent else 0.0
    else:
        scores["top5_consistent_with_donor_scores"] = 0.0

    email_path = workspace / "output" / "email_fundraising_committee.md"
    email_text = _safe_read_text(email_path)
    scores["email_exists"] = 1.0 if email_text is not None else 0.0

    if email_text is not None:
        scores["email_scoring_summary_present"] = _check_email_scoring_summary(email_text)
    else:
        scores["email_scoring_summary_present"] = 0.0

    if email_text is not None and expected is not None:
        tiers = ["No Data", "Lapsed", "Major Prospect", "Cultivation", "Re-engage"]
        expected_counts: Dict[str, int] = {t: 0 for t in tiers}
        for v in expected.values():
            expected_counts[v["classification_tier"]] += 1
        ok_counts = True
        for t in tiers:
            cnt_in_text = _extract_count_for_tier(email_text, t)
            if cnt_in_text is None or cnt_in_text != expected_counts[t]:
                ok_counts = False
                break
        scores["email_classification_counts_correct"] = 1.0 if ok_counts else 0.0
    else:
        scores["email_classification_counts_correct"] = 0.0

    if email_text is not None and t5_rows is not None and t5_headers == required_t5_cols:
        scores["email_top5_bullets_complete"] = _check_email_top5_bullets(email_text, t5_rows)
    else:
        scores["email_top5_bullets_complete"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()