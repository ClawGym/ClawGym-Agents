import json
import csv
import sys
import ast
import re
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_yaml(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    data = {}
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
                val = val[1:-1]
            vlow = val.lower()
            if vlow in ("true", "false"):
                data[key] = vlow == "true"
            else:
                try:
                    data[key] = int(val)
                except Exception:
                    data[key] = val
        return data
    except Exception:
        return None


def _parse_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _parse_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f", ""):
        return False
    return False


def _parse_date_ymd(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        parts = s.strip().split("-")
        if len(parts) != 3:
            return None
        y, m, d = [int(p) for p in parts]
        return date(y, m, d)
    except Exception:
        return None


def _parse_iso8601_z(s: str) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    st = s.strip()
    try:
        if st.endswith("Z"):
            st = st[:-1] + "+00:00"
        return datetime.fromisoformat(st)
    except Exception:
        return None


def _format_violation_codes(codes: List[str]) -> str:
    def key_func(code: str) -> int:
        try:
            return int(code.lstrip("R"))
        except Exception:
            return 999
    return ";".join(sorted(set(codes), key=key_func))


def _severity_for_codes(codes: List[str]) -> str:
    high = {"R1", "R2", "R4"}
    medium = {"R3"}
    low = {"R5"}
    code_set = set(codes)
    if code_set & high:
        return "High"
    if code_set & medium:
        return "Medium"
    if code_set & low:
        return "Low"
    return "Low"


def _severity_sort_key(sev: str) -> int:
    order = {"High": 0, "Medium": 1, "Low": 2}
    return order.get(sev, 3)


def _detect_persists_consent_version(handler_text: str) -> bool:
    # Try AST parsing to detect STORED_FIELDS list contents
    try:
        tree = ast.parse(handler_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                # handle multiple targets (unlikely here, but robust)
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "STORED_FIELDS":
                        val = node.value
                        fields = []
                        if isinstance(val, ast.List):
                            for elt in val.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    fields.append(elt.value)
                                elif isinstance(elt, ast.Str):
                                    fields.append(elt.s)
                        elif isinstance(val, ast.Tuple):
                            for elt in val.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    fields.append(elt.value)
                                elif isinstance(elt, ast.Str):
                                    fields.append(elt.s)
                        # Persist only if 'consent_text_version' is in the stored fields
                        return "consent_text_version" in fields
        # Fallback to regex if AST didn't find assignment
    except Exception:
        pass
    try:
        m = re.search(r"STORED_FIELDS\s*=\s*\[(.*?)\]", handler_text, re.S)
        if m:
            content = m.group(1)
            items = re.findall(r"['\"]([^'\"]+)['\"]", content)
            return "consent_text_version" in items
    except Exception:
        pass
    return False


def _compute_expected_from_inputs(workspace: Path) -> Optional[dict]:
    signup_csv = workspace / "input" / "data" / "signups.csv"
    consent_json = workspace / "input" / "data" / "consent_texts.json"
    config_yaml = workspace / "input" / "config" / "app_config.yaml"
    handler_py = workspace / "input" / "app" / "signup_handler.py"

    rows = _parse_csv_dicts(signup_csv)
    consent = _load_json(consent_json)
    config = _load_yaml(config_yaml)
    handler_text = _read_text(handler_py)

    if rows is None or consent is None or config is None or handler_text is None:
        return None

    version_ids = set()
    try:
        versions = consent.get("versions", [])
        for v in versions:
            vid = v.get("id")
            if isinstance(vid, str) and vid:
                version_ids.add(vid)
    except Exception:
        pass

    total_records = len(rows)

    expected_config = {}
    expected_config["require_double_opt_in_ok"] = bool(config.get("require_double_opt_in", False))
    expected_config["eu_age_gate_ok"] = bool(config.get("enforce_eu_age_limit", False))
    try:
        ret_days = int(config.get("retention_days_unengaged", 0))
    except Exception:
        ret_days = 0
    expected_config["retention_days_unengaged_ok"] = ret_days <= 365
    unsubscribe_url = str(config.get("unsubscribe_url", "") or "")
    expected_config["unsubscribe_url_present"] = bool(unsubscribe_url.strip())
    expected_config["log_ip_enabled"] = bool(config.get("log_ip", False))

    persists = _detect_persists_consent_version(handler_text)

    expected_records = []
    for r in rows:
        user_id = r.get("user_id", "")
        email = r.get("email", "")
        region = r.get("region", "")
        birthdate = r.get("birthdate", "")
        signup_source = r.get("signup_source", "")
        event_name = r.get("event_name", "")
        consent_checkbox = _parse_bool(r.get("consent_checkbox"))
        consent_text_version = (r.get("consent_text_version") or "").strip()
        consent_timestamp = (r.get("consent_timestamp") or "").strip()
        double_opt_in_confirmed = _parse_bool(r.get("double_opt_in_confirmed"))
        unsubscribed = _parse_bool(r.get("unsubscribed"))
        unsub_timestamp = (r.get("unsub_timestamp") or "").strip()

        codes = []

        if not (consent_checkbox and bool(consent_timestamp)):
            codes.append("R1")

        if not double_opt_in_confirmed:
            codes.append("R2")

        if not consent_text_version or consent_text_version not in version_ids:
            codes.append("R3")

        if region == "EU":
            ts = _parse_iso8601_z(consent_timestamp)
            bd = _parse_date_ymd(birthdate)
            if ts is not None and bd is not None:
                consent_dt = ts.date()
                years = consent_dt.year - bd.year - ((consent_dt.month, consent_dt.day) < (bd.month, bd.day))
                if years < 16:
                    codes.append("R4")

        if unsubscribed and not unsub_timestamp:
            codes.append("R5")

        if codes:
            sev = _severity_for_codes(codes)
            expected_records.append({
                "user_id": user_id,
                "email": email,
                "region": region,
                "signup_source": signup_source,
                "event_name": event_name,
                "violation_codes": _format_violation_codes(codes),
                "severity": sev,
                "notes": "",
                "consent_timestamp": consent_timestamp,
            })

    def sort_key(rec: Dict[str, Any]):
        sev_key = _severity_sort_key(rec["severity"])
        dt = _parse_iso8601_z(rec.get("consent_timestamp", ""))
        # use a tuple: (severity order, 0 for present timestamp to sort above missing, negative timestamp for desc,
        #               1 for missing timestamp sorts last)
        if dt is not None:
            return (sev_key, 0, -dt.timestamp())
        else:
            return (sev_key, 1, 0)

    expected_records_sorted = sorted(expected_records, key=sort_key)

    high = sum(1 for r in expected_records_sorted if r["severity"] == "High")
    med = sum(1 for r in expected_records_sorted if r["severity"] == "Medium")
    low = sum(1 for r in expected_records_sorted if r["severity"] == "Low")
    stats = {
        "total_records": total_records,
        "total_violations": len(expected_records_sorted),
        "high_severity": high,
        "medium_severity": med,
        "low_severity": low,
    }

    totals_by_source: Dict[str, int] = {}
    violations_by_source: Dict[str, int] = {}
    for r in rows:
        ss = r.get("signup_source", "")
        totals_by_source[ss] = totals_by_source.get(ss, 0) + 1
    violating_ids = {r["user_id"] for r in expected_records_sorted}
    for r in rows:
        ss = r.get("signup_source", "")
        if r.get("user_id") in violating_ids:
            violations_by_source[ss] = violations_by_source.get(ss, 0) + 1
        else:
            violations_by_source.setdefault(ss, violations_by_source.get(ss, 0))

    agg = []
    for ss, total in totals_by_source.items():
        v = violations_by_source.get(ss, 0)
        rate = (v / total) if total > 0 else 0.0
        agg.append({
            "signup_source": ss,
            "total_records": total,
            "violation_count": v,
            "violation_rate": rate,
        })
    agg_sorted = sorted(agg, key=lambda x: (-x["violation_rate"], -x["total_records"], x["signup_source"]))

    return {
        "expected_config": expected_config,
        "expected_persists": persists,
        "expected_records": expected_records_sorted,
        "expected_stats": stats,
        "expected_agg": agg_sorted,
    }


def _parse_json_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        st = s
        if st.endswith("Z"):
            st = st[:-1] + "+00:00"
        _ = datetime.fromisoformat(st)
        return True
    except Exception:
        return False


def _load_audit_summary(path: Path) -> Optional[dict]:
    return _load_json(path)


def _validate_config_checks(summary: dict, expected_config: dict) -> bool:
    try:
        config_checks = summary.get("config_checks", {})
        required_keys = [
            "require_double_opt_in_ok",
            "eu_age_gate_ok",
            "retention_days_unengaged_ok",
            "unsubscribe_url_present",
            "log_ip_enabled",
        ]
        for k in required_keys:
            if k not in config_checks:
                return False
            entry = config_checks[k]
            if not isinstance(entry, dict):
                return False
            if "pass" not in entry or "message" not in entry:
                return False
            if bool(entry["pass"]) != bool(expected_config.get(k, False)):
                return False
            if not isinstance(entry["message"], str) or not entry["message"].strip():
                return False
        return True
    except Exception:
        return False


def _validate_code_checks(summary: dict, expected_persists: bool) -> bool:
    try:
        code_checks = summary.get("code_checks", {})
        if "persists_consent_text_version" not in code_checks:
            return False
        entry = code_checks["persists_consent_text_version"]
        if not isinstance(entry, dict):
            return False
        if "pass" not in entry or "message" not in entry:
            return False
        if bool(entry["pass"]) != bool(expected_persists):
            return False
        if not isinstance(entry["message"], str) or not entry["message"].strip():
            return False
        return True
    except Exception:
        return False


def _validate_stats(summary: dict, expected_stats: dict) -> bool:
    try:
        stats = summary.get("stats", {})
        if not isinstance(stats, dict):
            return False
        for k in ["total_records", "total_violations", "high_severity", "medium_severity", "low_severity"]:
            if k not in stats:
                return False
            if int(stats[k]) != int(expected_stats[k]):
                return False
        gen_at = summary.get("generated_at")
        if not _parse_json_datetime(gen_at):
            return False
        return True
    except Exception:
        return False


def _validate_non_compliant_csv(path: Path, expected_records: List[dict]) -> bool:
    rows = _parse_csv_dicts(path)
    if rows is None:
        return False
    expected_headers = [
        "user_id",
        "email",
        "region",
        "signup_source",
        "event_name",
        "violation_codes",
        "severity",
        "notes",
        "consent_timestamp",
    ]
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return False
            if header != expected_headers:
                return False
    except Exception:
        return False

    if len(rows) != len(expected_records):
        return False

    for row, exp in zip(rows, expected_records):
        for key in ["user_id", "email", "region", "signup_source", "event_name", "consent_timestamp"]:
            rv = row.get(key, "")
            ev = exp.get(key, "")
            if (rv or "") != (ev or ""):
                return False
        rv_codes = (row.get("violation_codes") or "").strip()
        if rv_codes != exp["violation_codes"]:
            return False
        if (row.get("severity") or "").strip() != exp["severity"]:
            return False
        if "notes" not in row:
            return False
    return True


def _validate_source_risk_csv(path: Path, expected_agg: List[dict]) -> bool:
    rows = _parse_csv_dicts(path)
    if rows is None:
        return False
    expected_headers = [
        "signup_source",
        "total_records",
        "violation_count",
        "violation_rate",
    ]
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return False
            if header != expected_headers:
                return False
    except Exception:
        return False

    if len(rows) != len(expected_agg):
        return False

    for row, exp in zip(rows, expected_agg):
        if (row.get("signup_source") or "") != exp["signup_source"]:
            return False
        try:
            tr = int(row.get("total_records", ""))
            vc = int(row.get("violation_count", ""))
            vr = float(row.get("violation_rate", ""))
        except Exception:
            return False
        if tr != int(exp["total_records"]):
            return False
        if vc != int(exp["violation_count"]):
            return False
        if abs(vr - float(exp["violation_rate"])) > 1e-9:
            return False
    return True


def _check_tools_script(workspace: Path) -> Dict[str, bool]:
    tool_path = workspace / "tools" / "audit.py"
    exists = tool_path.exists() and tool_path.is_file()
    refs_ok = False
    if exists:
        text = _read_text(tool_path) or ""
        needed_refs = [
            str(Path("input") / "data" / "signups.csv"),
            str(Path("input") / "data" / "consent_texts.json"),
            str(Path("input") / "config" / "app_config.yaml"),
            str(Path("input") / "app" / "signup_handler.py"),
            str(Path("out") / "audit_summary.json"),
            str(Path("out") / "non_compliant_records.csv"),
            str(Path("out") / "source_risk_ranked.csv"),
        ]
        refs_ok = all(ref in text for ref in needed_refs)
    return {"exists": exists, "refs_ok": refs_ok}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tools_script_present": 0.0,
        "tools_script_references_inputs": 0.0,
        "audit_summary_present": 0.0,
        "config_checks_correct": 0.0,
        "code_checks_correct": 0.0,
        "stats_correct": 0.0,
        "non_compliant_records_present_and_correct": 0.0,
        "source_risk_ranked_present_and_correct": 0.0,
    }

    tool_checks = _check_tools_script(workspace)
    if tool_checks["exists"]:
        scores["tools_script_present"] = 1.0
    if tool_checks["refs_ok"]:
        scores["tools_script_references_inputs"] = 1.0

    expected = _compute_expected_from_inputs(workspace)
    out_dir = workspace / "out"
    audit_summary_path = out_dir / "audit_summary.json"
    non_compliant_csv_path = out_dir / "non_compliant_records.csv"
    source_risk_csv_path = out_dir / "source_risk_ranked.csv"

    summary = _load_audit_summary(audit_summary_path) if audit_summary_path.exists() else None
    if summary is not None:
        scores["audit_summary_present"] = 1.0

    if expected is None:
        return scores

    if summary is not None:
        if _validate_config_checks(summary, expected["expected_config"]):
            scores["config_checks_correct"] = 1.0
        if _validate_code_checks(summary, expected["expected_persists"]):
            scores["code_checks_correct"] = 1.0
        if _validate_stats(summary, expected["expected_stats"]):
            scores["stats_correct"] = 1.0

    if non_compliant_csv_path.exists() and non_compliant_csv_path.is_file():
        if _validate_non_compliant_csv(non_compliant_csv_path, expected["expected_records"]):
            scores["non_compliant_records_present_and_correct"] = 1.0

    if source_risk_csv_path.exists() and source_risk_csv_path.is_file():
        if _validate_source_risk_csv(source_risk_csv_path, expected["expected_agg"]):
            scores["source_risk_ranked_present_and_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()