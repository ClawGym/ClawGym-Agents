import json
import csv
import sys
import re
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl_safe(path: Path) -> Optional[List[dict]]:
    try:
        records = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records
    except Exception:
        return None


def _parse_csv_metrics(path: Path) -> Optional[Dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = [c.strip() for c in rows[0]]
    if len(header) != 2 or header[0] != "metric" or header[1] != "value":
        return None
    metrics = {}
    for r in rows[1:]:
        if not r:
            continue
        if len(r) < 2:
            return None
        metric = r[0].strip()
        value = r[1].strip()
        metrics[metric] = value
    return metrics


def _median(vals: List[float]) -> float:
    n = len(vals)
    if n == 0:
        return float("nan")
    s = sorted(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    else:
        return (s[mid - 1] + s[mid]) / 2.0


def _compute_expected_metrics(records: List[dict]) -> Dict[str, Any]:
    total_records = len(records)
    num_records_link_shared = 0
    num_records_shared_externally = 0
    num_records_with_phi_in_notes = 0
    external_domains = set()
    sodiums = []
    for rec in records:
        sodium = rec.get("sodium_mg")
        if isinstance(sodium, (int, float)):
            sodiums.append(float(sodium))
        if rec.get("share_via_link") is True:
            num_records_link_shared += 1
        shared_with = rec.get("shared_with", [])
        if isinstance(shared_with, list):
            extern = False
            for email in shared_with:
                if isinstance(email, str) and "@" in email:
                    domain = email.split("@", 1)[1].lower()
                    if domain != "clinic.org":
                        extern = True
                        external_domains.add(domain)
            if extern:
                num_records_shared_externally += 1
        notes = rec.get("notes")
        if isinstance(notes, str) and "mrn:" in notes.lower():
            num_records_with_phi_in_notes += 1

    sodium_threshold_mg = 1500
    num_records_over_sodium_threshold = sum(1 for v in sodiums if v > sodium_threshold_mg)
    mean_sodium_mg = mean(sodiums) if sodiums else 0.0
    median_sodium_mg = _median(sodiums) if sodiums else 0.0

    exposure = {
        "total_records": total_records,
        "num_records_shared_externally": num_records_shared_externally,
        "num_records_link_shared": num_records_link_shared,
        "unique_external_domains": sorted(external_domains),
        "num_records_with_phi_in_notes": num_records_with_phi_in_notes,
    }
    nutrition = {
        "sodium_threshold_mg": sodium_threshold_mg,
        "num_records_over_sodium_threshold": num_records_over_sodium_threshold,
        "mean_sodium_mg": mean_sodium_mg,
        "median_sodium_mg": median_sodium_mg,
    }
    return {"exposure": exposure, "nutrition": nutrition}


def _detect_config_risks(cfg_text: str) -> List[Dict[str, Any]]:
    text = cfg_text
    lower = text.lower()
    risks = []
    source = "input/config/app_settings.yaml"

    if re.search(r"\blink_sharing\s*:\s*true\b", lower):
        risks.append({
            "id": "link_sharing_enabled",
            "source": source,
            "patterns": ["link_sharing"]
        })
    if "allowed_domains" in lower:
        extern_domains = []
        for dom in ["gmail.com", "yahoo.com", "consultants.com", "outlook.com"]:
            if dom in lower:
                extern_domains.append(dom)
        if extern_domains:
            risks.append({
                "id": "external_domains_allowed",
                "source": source,
                "patterns": ["allowed_domains"] + extern_domains
            })
    if re.search(r"\bdefault_permission\s*:\s*edit\b", lower):
        risks.append({
            "id": "default_edit_permission",
            "source": source,
            "patterns": ["default_permission", "edit"]
        })
    m = re.search(r"\bretention_days\s*:\s*(\d+)\b", lower)
    if m:
        try:
            val = int(m.group(1))
            if val > 365:
                risks.append({
                    "id": "retention_gt_365",
                    "source": source,
                    "patterns": ["retention_days", str(val)]
                })
        except Exception:
            pass
    if "backup" in lower and re.search(r"\benabled\s*:\s*false\b", lower):
        risks.append({
            "id": "backups_disabled",
            "source": source,
            "patterns": ["backup", "enabled", "false"]
        })
    if re.search(r"\brequire_2fa\s*:\s*false\b", lower):
        risks.append({
            "id": "two_factor_disabled",
            "source": source,
            "patterns": ["require_2fa", "false"]
        })
    if re.search(r"\bdefault_password\s*:\s*['\"]?([^'\"]+)['\"]?", text):
        risks.append({
            "id": "default_weak_password",
            "source": source,
            "patterns": ["default_password"]
        })
    if re.search(r"\bnutrition_api_key\s*:\s*['\"]?([^'\"]+)['\"]?", text):
        risks.append({
            "id": "api_keys_present",
            "source": source,
            "patterns": ["nutrition_api_key", "api_keys"]
        })
    if re.search(r"\bpii_logging\s*:\s*true\b", lower):
        risks.append({
            "id": "pii_logging_enabled",
            "source": source,
            "patterns": ["pii_logging"]
        })

    return risks


def _detect_code_risks(code_text: str) -> List[Dict[str, Any]]:
    lower = code_text.lower()
    source = "input/scripts/export_meals.py"
    risks = []

    if "0o777" in code_text:
        risks.append({
            "id": "world_perms_0777",
            "source": source,
            "patterns": ["0o777"]
        })
    if "harcoded_db_password" in lower or "HARDCODED_DB_PASSWORD" in code_text:
        risks.append({
            "id": "hardcoded_password",
            "source": source,
            "patterns": ["HARDCODED_DB_PASSWORD"]
        })
    if "patient_dob" in code_text and "print" in code_text:
        risks.append({
            "id": "logs_pii",
            "source": source,
            "patterns": ["print", "patient_dob", "patient_name"]
        })
    if "NamedTemporaryFile" in code_text and "delete=False" in code_text:
        risks.append({
            "id": "insecure_tempfile",
            "source": source,
            "patterns": ["NamedTemporaryFile", "delete=False"]
        })
    if "os.chmod" in code_text and "DEFAULT_EXPORT_PERMISSIONS" in code_text:
        risks.append({
            "id": "chmod_world_perms",
            "source": source,
            "patterns": ["os.chmod", "DEFAULT_EXPORT_PERMISSIONS"]
        })

    return risks


def _issue_has_required_fields(item: dict) -> bool:
    required = ["source", "setting_or_pattern", "value_or_snippet", "risk", "severity", "recommendation"]
    for k in required:
        if k not in item:
            return False
        if not isinstance(item[k], str):
            return False
    if item["severity"] not in {"High", "Medium", "Low"}:
        return False
    return True


def _find_matching_issue(issues: List[dict], source: str, patterns: List[str]) -> bool:
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if issue.get("source") != source:
            continue
        combined = ""
        for fld in ("setting_or_pattern", "value_or_snippet", "risk"):
            v = issue.get(fld)
            if isinstance(v, str):
                combined += " " + v.lower()
        ok = True
        for p in patterns:
            if p.lower() not in combined:
                ok = False
                break
        if ok:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "findings_json_exists_and_parseable": 0.0,
        "findings_json_config_issues_coverage": 0.0,
        "findings_json_code_issues_coverage": 0.0,
        "findings_json_data_exposure_summary_correct": 0.0,
        "findings_json_nutrition_risk_summary_correct": 0.0,
        "aggregates_csv_exists_and_correct": 0.0,
        "risk_report_exists": 0.0,
        "risk_report_references_outputs": 0.0,
        "risk_report_includes_key_metrics": 0.0,
        "risk_report_has_min_recommendations": 0.0,
    }

    cfg_path = workspace / "input" / "config" / "app_settings.yaml"
    code_path = workspace / "input" / "scripts" / "export_meals.py"
    data_path = workspace / "input" / "data" / "meal_plans.jsonl"

    cfg_text = _read_text_safe(cfg_path) or ""
    code_text = _read_text_safe(code_path) or ""
    records = _load_jsonl_safe(data_path)

    expected_config_risks = _detect_config_risks(cfg_text) if cfg_text else []
    expected_code_risks = _detect_code_risks(code_text) if code_text else []
    expected_metrics = None
    if records is not None:
        expected_metrics = _compute_expected_metrics(records)

    findings_path = workspace / "outputs" / "security" / "findings.json"
    aggregates_path = workspace / "outputs" / "security" / "aggregates.csv"
    report_path = workspace / "outputs" / "security" / "risk_report.md"

    findings = _load_json_safe(findings_path)
    if isinstance(findings, dict):
        config_issues = findings.get("config_issues")
        code_issues = findings.get("code_issues")
        des = findings.get("data_exposure_summary")
        nrs = findings.get("nutrition_risk_summary")
        ok_struct = True
        if not isinstance(config_issues, list) or not isinstance(code_issues, list):
            ok_struct = False
        else:
            for arr in [config_issues, code_issues]:
                for item in arr:
                    if not isinstance(item, dict) or not _issue_has_required_fields(item):
                        ok_struct = False
                        break
                if not ok_struct:
                    break
        if not isinstance(des, dict) or not isinstance(nrs, dict):
            ok_struct = False
        if ok_struct:
            scores["findings_json_exists_and_parseable"] = 1.0

        if isinstance(config_issues, list) and expected_config_risks:
            covered = 0
            for r in expected_config_risks:
                if _find_matching_issue(config_issues, r["source"], r["patterns"]):
                    covered += 1
            if expected_config_risks:
                scores["findings_json_config_issues_coverage"] = covered / float(len(expected_config_risks))

        if isinstance(code_issues, list) and expected_code_risks:
            covered = 0
            for r in expected_code_risks:
                if _find_matching_issue(code_issues, r["source"], r["patterns"]):
                    covered += 1
            if expected_code_risks:
                scores["findings_json_code_issues_coverage"] = covered / float(len(expected_code_risks))

        if expected_metrics is not None and isinstance(des, dict):
            try:
                exp = expected_metrics["exposure"]
                ok = True
                for k in ["total_records", "num_records_shared_externally", "num_records_link_shared", "num_records_with_phi_in_notes"]:
                    if des.get(k) != exp[k]:
                        ok = False
                        break
                if ok:
                    u = des.get("unique_external_domains")
                    if not isinstance(u, list):
                        ok = False
                    else:
                        set_actual = set([str(x).lower() for x in u])
                        set_expected = set([str(x).lower() for x in exp["unique_external_domains"]])
                        if set_actual != set_expected:
                            ok = False
                if ok:
                    scores["findings_json_data_exposure_summary_correct"] = 1.0
            except Exception:
                pass

        if expected_metrics is not None and isinstance(nrs, dict):
            try:
                expn = expected_metrics["nutrition"]
                okn = True
                if nrs.get("sodium_threshold_mg") != expn["sodium_threshold_mg"]:
                    okn = False
                if nrs.get("num_records_over_sodium_threshold") != expn["num_records_over_sodium_threshold"]:
                    okn = False
                ms = nrs.get("mean_sodium_mg")
                md = nrs.get("median_sodium_mg")

                def _close(a: float, b: float, tol: float = 1e-6) -> bool:
                    try:
                        return abs(float(a) - float(b)) <= tol
                    except Exception:
                        return False

                if not _close(ms, expn["mean_sodium_mg"]):
                    okn = False
                if not _close(md, expn["median_sodium_mg"]):
                    okn = False
                if okn:
                    scores["findings_json_nutrition_risk_summary_correct"] = 1.0
            except Exception:
                pass

    metrics_csv = _parse_csv_metrics(aggregates_path)
    if metrics_csv is not None and expected_metrics is not None:
        exp_e = expected_metrics["exposure"]
        exp_n = expected_metrics["nutrition"]
        expected_numeric = {
            "total_records": exp_e["total_records"],
            "num_records_shared_externally": exp_e["num_records_shared_externally"],
            "num_records_link_shared": exp_e["num_records_link_shared"],
            "num_records_with_phi_in_notes": exp_e["num_records_with_phi_in_notes"],
            "sodium_threshold_mg": exp_n["sodium_threshold_mg"],
            "num_records_over_sodium_threshold": exp_n["num_records_over_sodium_threshold"],
            "mean_sodium_mg": exp_n["mean_sodium_mg"],
            "median_sodium_mg": exp_n["median_sodium_mg"],
        }
        okcsv = True
        for k, v in expected_numeric.items():
            if k not in metrics_csv:
                okcsv = False
                break
            val_str = metrics_csv[k]
            try:
                val_num = float(val_str)
                exp_num = float(v)
                tol = 1e-6
                if abs(val_num - exp_num) > tol:
                    okcsv = False
                    break
            except Exception:
                okcsv = False
                break
        if okcsv:
            scores["aggregates_csv_exists_and_correct"] = 1.0

    if report_path.exists():
        scores["risk_report_exists"] = 1.0
        report_text = _read_text_safe(report_path) or ""
        lower = report_text.lower()

        ref_ok = ("outputs/security/findings.json" in report_text and
                  "outputs/security/aggregates.csv" in report_text and
                  ("status update" in lower) and
                  ("next steps" in lower or "next-step" in lower))
        scores["risk_report_references_outputs"] = 1.0 if ref_ok else 0.0

        target_nums = ["7", "4", "2", "3", "1500", "1550"]
        present = sum(1 for t in target_nums if t in report_text)
        scores["risk_report_includes_key_metrics"] = 1.0 if present >= 5 else 0.0

        lines = report_text.splitlines()
        rec_count = 0
        for ln in lines:
            lns = ln.strip()
            if lns.startswith("- ") or lns.startswith("* ") or re.match(r"^\d+\.\s+", lns):
                rec_count += 1
        scores["risk_report_has_min_recommendations"] = 1.0 if rec_count >= 5 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()