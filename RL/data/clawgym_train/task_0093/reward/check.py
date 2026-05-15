import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(errors="ignore")
        except Exception:
            return None


def _safe_load_json(path: Path) -> Optional[Any]:
    txt = _safe_read_text(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def _list_all_input_files(workspace: Path) -> List[Path]:
    input_root = workspace / "input"
    if not input_root.exists() or not input_root.is_dir():
        return []
    return sorted([p for p in input_root.rglob("*") if p.is_file()])


def _contains_line_with_keywords(text: str, path_str: str, required_keywords: List[str]) -> bool:
    if text is None:
        return False
    lines = text.splitlines()
    for line in lines:
        if path_str in line:
            lowered = line.lower()
            if all(k.lower() in lowered for k in required_keywords):
                return True
    return False


def _any_text_contains(text: Optional[str], any_of: List[str]) -> bool:
    if not text:
        return False
    tl = text.lower()
    return any(tok.lower() in tl for tok in any_of)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "compliance_report_present": 0.0,
        "compliance_report_sections": 0.0,
        "student_privacy_csv_flagged": 0.0,
        "student_privacy_script_flagged": 0.0,
        "political_solicitation_flagged": 0.0,
        "missing_disclaimer_index_flagged": 0.0,
        "missing_disclaimer_syllabus_flagged": 0.0,
        "findings_tracking_analytics": 0.0,
        "findings_copyright_third_party": 0.0,
        "findings_configuration_site_structure": 0.0,
        "remediations_include_required_disclaimer_text": 0.0,
        "status_summary_blocker_language": 0.0,
        "dir_inventory_exists": 0.0,
        "dir_inventory_coverage": 0.0,
        "dir_inventory_classification_quality": 0.0,
        "dir_inventory_indicators_quality": 0.0,
        "deployment_email_exists": 0.0,
        "deployment_email_length_ok": 0.0,
        "deployment_email_mentions_staging_review": 0.0,
        "deployment_email_summarizes_fixes": 0.0,
        "deployment_email_recommends_pause": 0.0,
    }

    # Load input references
    input_files = _list_all_input_files(workspace)
    path_mkdocs = workspace / "input/site/mkdocs.yml"
    path_index = workspace / "input/site/pages/index.md"
    path_syllabus = workspace / "input/site/pages/syllabus.md"
    path_csv = workspace / "input/data/survey_responses.csv"
    path_script = workspace / "input/scripts/collect_responses.py"
    path_quotes = workspace / "input/site/assets/quotes.txt"
    path_policy = workspace / "input/policies/campus_political_activity_policy.md"
    path_email_draft = workspace / "input/email/deployment_request_draft.txt"

    mkdocs_text = _safe_read_text(path_mkdocs)
    index_text = _safe_read_text(path_index)
    syllabus_text = _safe_read_text(path_syllabus)
    csv_text = _safe_read_text(path_csv)
    script_text = _safe_read_text(path_script)
    quotes_text = _safe_read_text(path_quotes)
    policy_text = _safe_read_text(path_policy)
    email_draft_text = _safe_read_text(path_email_draft)

    # Outputs to grade
    path_report = workspace / "output/compliance_report.md"
    path_inventory = workspace / "output/dir_inventory.json"
    path_deploy_email = workspace / "output/deployment_request_email.txt"

    # compliance_report checks
    report_text = _safe_read_text(path_report)
    if report_text is not None:
        scores["compliance_report_present"] = 1.0

        # Sections check (case-insensitive presence)
        sections_ok = True
        for sect in ["Overview", "Findings by Category", "Recommended Remediations", "Status Summary"]:
            if sect.lower() not in report_text.lower():
                sections_ok = False
                break
        scores["compliance_report_sections"] = 1.0 if sections_ok else 0.0

        # Student privacy: CSV flagged with exact path and an offending substring
        csv_issue = False
        if "input/data/survey_responses.csv" in report_text:
            # Offending substrings: header fields or specific emails from CSV
            if any(s in report_text for s in ["name,email", "ana.ruiz@example.edu", "markc@personalmail.com"]):
                csv_issue = True
        scores["student_privacy_csv_flagged"] = 1.0 if csv_issue else 0.0

        # Student privacy: script flagged with exact path and offending substring
        script_issue = False
        if "input/scripts/collect_responses.py" in report_text:
            # Accept the NOTE line, fieldnames mention, or explicit "name"/"email" fields in a list
            if "NOTE: This script stores names and email addresses" in report_text:
                script_issue = True
            elif "fieldnames" in report_text and ("name" in report_text and "email" in report_text):
                script_issue = True
            elif '["response_id","name","email"' in report_text or '"name","email"' in report_text:
                script_issue = True
        scores["student_privacy_script_flagged"] = 1.0 if script_issue else 0.0

        # Political solicitation language in syllabus
        pol_issue = False
        if "input/site/pages/syllabus.md" in report_text and "Please consider supporting the Reform Now PAC" in report_text:
            pol_issue = True
        scores["political_solicitation_flagged"] = 1.0 if pol_issue else 0.0

        # Missing disclaimers for index and syllabus
        idx_disc = _contains_line_with_keywords(report_text, "input/site/pages/index.md", ["disclaimer", "missing"]) or _contains_line_with_keywords(report_text, "input/site/pages/index.md", ["disclaimer", "absent"]) or _contains_line_with_keywords(report_text, "input/site/pages/index.md", ["disclaimer", "lacks"])
        syl_disc = _contains_line_with_keywords(report_text, "input/site/pages/syllabus.md", ["disclaimer", "missing"]) or _contains_line_with_keywords(report_text, "input/site/pages/syllabus.md", ["disclaimer", "absent"]) or _contains_line_with_keywords(report_text, "input/site/pages/syllabus.md", ["disclaimer", "lacks"])
        scores["missing_disclaimer_index_flagged"] = 1.0 if idx_disc else 0.0
        scores["missing_disclaimer_syllabus_flagged"] = 1.0 if syl_disc else 0.0

        # Tracking/analytics ID in mkdocs config flagged
        analytics_flag = False
        if "input/site/mkdocs.yml" in report_text and "UA-TEST-12345" in report_text:
            analytics_flag = True
        scores["findings_tracking_analytics"] = 1.0 if analytics_flag else 0.0

        # Third-party quotes/copyright risk flagged
        copyright_flag = False
        if "input/site/assets/quotes.txt" in report_text and ("All rights reserved" in report_text or "The Daily Tribune (2020)" in report_text):
            copyright_flag = True
        scores["findings_copyright_third_party"] = 1.0 if copyright_flag else 0.0

        # Configuration/site structure issues (CSV linked directly in nav)
        config_nav_flag = False
        if "input/site/mkdocs.yml" in report_text and ("Data: ../data/survey_responses.csv" in report_text or "../data/survey_responses.csv" in report_text):
            config_nav_flag = True
        scores["findings_configuration_site_structure"] = 1.0 if config_nav_flag else 0.0

        # Recommended Remediations include required disclaimer text and concrete actions
        required_disclaimer_txt = 'The views expressed are those of the author and do not represent the University.'
        rem_ok = required_disclaimer_txt in report_text
        # Also require mention of analytics and PAC solicitation fixes to ensure completeness
        if rem_ok:
            if not (_any_text_contains(report_text, ["UA-TEST-12345", "google_analytics", "analytics"]) and _any_text_contains(report_text, ["PAC", "Reform Now", "solicit"])):
                rem_ok = False
        scores["remediations_include_required_disclaimer_text"] = 1.0 if rem_ok else 0.0

        # Status Summary includes blocker language
        status_ok = "status summary" in report_text.lower() and ("blocker" in report_text.lower())
        scores["status_summary_blocker_language"] = 1.0 if status_ok else 0.0

    # dir_inventory checks
    inventory = _safe_load_json(path_inventory)
    if inventory is not None and isinstance(inventory, list):
        scores["dir_inventory_exists"] = 1.0
        required_paths = [str(p.relative_to(workspace).as_posix()) for p in input_files]
        inv_paths: List[str] = []
        valid_structure = True
        valid_types = True
        allowed_types = {"markdown", "config", "code", "data", "text", "policy", "email"}
        for item in inventory:
            if not isinstance(item, dict):
                valid_structure = False
                break
            if not {"path", "file_type", "detected_indicators", "notes"}.issubset(set(item.keys())):
                valid_structure = False
                break
            inv_paths.append(item.get("path"))
            if item.get("file_type") not in allowed_types:
                valid_types = False
            if not isinstance(item.get("detected_indicators"), list):
                valid_structure = False
                break
            if not isinstance(item.get("notes"), str):
                valid_structure = False
                break

        coverage_ok = False
        if valid_structure:
            if len(inv_paths) == len(set(inv_paths)):
                try:
                    coverage_ok = set(inv_paths) == set(required_paths)
                except Exception:
                    coverage_ok = False
            else:
                coverage_ok = False
        scores["dir_inventory_coverage"] = 1.0 if coverage_ok else 0.0
        scores["dir_inventory_classification_quality"] = 1.0 if valid_types and valid_structure else 0.0

        indicators_ok = True
        if coverage_ok:
            path_to_inds = {item["path"]: item.get("detected_indicators", []) for item in inventory if isinstance(item, dict) and "path" in item}
            def has_any(path: str, tokens: List[str]) -> bool:
                inds = path_to_inds.get(path, [])
                return any(tok in inds for tok in tokens)

            mkdocs_rel = "input/site/mkdocs.yml"
            if mkdocs_rel in path_to_inds and not has_any(mkdocs_rel, ["ANALYTICS_ID"]):
                indicators_ok = False

            syl_rel = "input/site/pages/syllabus.md"
            if syl_rel in path_to_inds and (not has_any(syl_rel, ["POLITICAL_SOLICITATION"]) or not has_any(syl_rel, ["MISSING_DISCLAIMER"])):
                indicators_ok = False

            idx_rel = "input/site/pages/index.md"
            if idx_rel in path_to_inds and not has_any(idx_rel, ["MISSING_DISCLAIMER"]):
                indicators_ok = False

            csv_rel = "input/data/survey_responses.csv"
            if csv_rel in path_to_inds and (not has_any(csv_rel, ["EMAIL_ADDRESS"]) or not has_any(csv_rel, ["NAME_FIELD"])):
                indicators_ok = False

            script_rel = "input/scripts/collect_responses.py"
            if script_rel in path_to_inds and not has_any(script_rel, ["EMAIL_ADDRESS", "NAME_FIELD", "PII_COLLECTION", "PII_STORAGE"]):
                indicators_ok = False

            quotes_rel = "input/site/assets/quotes.txt"
            if quotes_rel in path_to_inds and not has_any(quotes_rel, ["THIRD_PARTY_QUOTE", "COPYRIGHT_RISK"]):
                indicators_ok = False
        else:
            indicators_ok = False
        scores["dir_inventory_indicators_quality"] = 1.0 if indicators_ok else 0.0

    # deployment_request_email checks
    dep_email_text = _safe_read_text(path_deploy_email)
    if dep_email_text is not None:
        scores["deployment_email_exists"] = 1.0
        words = re.findall(r"\b\w+\b", dep_email_text)
        scores["deployment_email_length_ok"] = 1.0 if 0 < len(words) <= 180 else 0.0
        staging_ok = ("staging" in dep_email_text.lower()) and ("review" in dep_email_text.lower())
        scores["deployment_email_mentions_staging_review"] = 1.0 if staging_ok else 0.0

        fixes_hits = 0
        if "analytic" in dep_email_text.lower() or "ua-test-12345" in dep_email_text.lower():
            fixes_hits += 1
        if "disclaimer" in dep_email_text.lower():
            fixes_hits += 1
        if "pac" in dep_email_text.lower() or "solicit" in dep_email_text.lower():
            fixes_hits += 1
        if any(k in dep_email_text.lower() for k in ["student", "pii", "names", "emails", "csv"]):
            fixes_hits += 1
        scores["deployment_email_summarizes_fixes"] = 1.0 if fixes_hits >= 3 else 0.0

        pause_ok = ("pause" in dep_email_text.lower()) or (("until" in dep_email_text.lower()) and ("blocker" in dep_email_text.lower() or "addressed" in dep_email_text.lower() or "resolved" in dep_email_text.lower()))
        scores["deployment_email_recommends_pause"] = 1.0 if pause_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()