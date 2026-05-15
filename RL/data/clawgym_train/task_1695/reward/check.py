import json
import csv
import sys
from pathlib import Path
from typing import List, Dict, Tuple


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_csv_dicts(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            headers = reader.fieldnames or []
            return headers, rows
    except Exception:
        return [], []


def _parse_law_bullet_lines(text: str) -> List[str]:
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- [") and "]" in s:
            lines.append(s)
    return lines


def _compute_expected_from_inputs(workspace: Path):
    pdpa_path = workspace / "input" / "law" / "pdpa_sl_excerpt.md"
    ea_path = workspace / "input" / "law" / "elections_act_excerpt.md"
    catalog_path = workspace / "input" / "project" / "dataset_catalog.json"

    pdpa_text = _read_text_safe(pdpa_path)
    ea_text = _read_text_safe(ea_path)
    catalog = _load_json_safe(catalog_path)

    if not catalog or "datasets" not in catalog or not isinstance(catalog["datasets"], list):
        return None

    expected_rows = []
    for ds in catalog["datasets"]:
        dataset_name = ds.get("dataset_name", "")
        retention_months = ds.get("retention_months")
        has_ethics_approval = bool(ds.get("has_ethics_approval", False))
        cross_border_transfer = bool(ds.get("cross_border_transfer", False))
        intended_publication = ds.get("intended_publication", "")
        fields = ds.get("fields", [])
        if not isinstance(fields, list):
            fields = []

        for field in fields:
            field_name = field.get("name", "")
            category = field.get("category", "")
            consent_obtained = bool(field.get("consent_obtained", False))

            requires_explicit_consent = "Yes" if category == "sensitive" else "No"

            pub_rules = []
            if intended_publication == "microdata" and field_name.lower() in {"vote_choice", "vote", "voted"}:
                pub_rules.append("EA-1")
            if intended_publication == "microdata" and dataset_name.lower().startswith("voter_roll"):
                if field_name.lower() in {"full_name", "address"}:
                    pub_rules.append("EA-2")

            publication_risk = ";".join([f"[{r}]" for r in sorted(pub_rules)]) if pub_rules else ""

            retention_risk = "Yes" if isinstance(retention_months, int) and retention_months > 24 and category in {"personal", "sensitive"} else "No"

            cross_border_risk = "Yes" if cross_border_transfer and category in {"personal", "sensitive"} else "No"

            triggered = []
            if category == "sensitive":
                triggered.append("PDPA-2")
            if retention_risk == "Yes":
                triggered.append("PDPA-3")
            if cross_border_risk == "Yes":
                triggered.append("PDPA-4")
            triggered.extend(pub_rules)
            triggered = sorted(set(triggered), key=lambda x: (x.split("-")[0], int(x.split("-")[1]) if x.split("-")[1].isdigit() else x.split("-")[1]))
            triggered_rules = ";".join(triggered)

            status = "Compliant"
            if "EA-1" in pub_rules:
                status = "Non-compliant"
            elif "EA-2" in pub_rules:
                status = "Non-compliant"
            elif category == "sensitive" and not consent_obtained and not has_ethics_approval:
                status = "Non-compliant"
            else:
                if retention_risk == "Yes" or cross_border_risk == "Yes":
                    status = "Needs review"

            rationales = []
            if category == "sensitive":
                if consent_obtained:
                    rationales.append("Sensitive data with explicit consent [PDPA-2]")
                elif has_ethics_approval:
                    rationales.append("Sensitive data with research derogation (ethics approval) [PDPA-2]")
                else:
                    rationales.append("Sensitive data lacks consent and no ethics approval [PDPA-2]")
            if retention_risk == "Yes":
                rationales.append("Retention exceeds 24 months for personal/sensitive data [PDPA-3]")
            if cross_border_risk == "Yes":
                rationales.append("Cross-border transfer requires safeguards/SCCs and register entry [PDPA-4]")
            if "EA-1" in pub_rules:
                rationales.append("Microdata could reveal how an individual voted [EA-1]")
            if "EA-2" in pub_rules:
                rationales.append("Voter roll microdata with names and addresses cannot be published [EA-2]")
            rationale = "; ".join(rationales)

            expected_rows.append({
                "dataset_name": dataset_name,
                "field_name": field_name,
                "category": category,
                "requires_explicit_consent": requires_explicit_consent,
                "publication_risk": publication_risk,
                "retention_risk": retention_risk,
                "cross_border_risk": cross_border_risk,
                "status": status,
                "triggered_rules": triggered_rules,
                "rationale": rationale,
            })

    total_fields = 0
    sensitive_fields = 0
    fields_missing_consent = 0
    ea_publication_risks = 0
    retention_risks = 0
    cross_border_risks = 0

    for ds in catalog["datasets"]:
        intended_publication = ds.get("intended_publication", "")
        retention_months = ds.get("retention_months")
        cross_border_transfer = bool(ds.get("cross_border_transfer", False))
        fields = ds.get("fields", [])
        if not isinstance(fields, list):
            continue
        for field in fields:
            total_fields += 1
            category = field.get("category", "")
            consent_obtained = bool(field.get("consent_obtained", False))
            name = field.get("name", "")

            if category == "sensitive":
                sensitive_fields += 1
                if not consent_obtained:
                    fields_missing_consent += 1

            if intended_publication == "microdata" and name.lower() in {"vote_choice", "vote", "voted"}:
                ea_publication_risks += 1
            if intended_publication == "microdata" and ds.get("dataset_name", "").lower().startswith("voter_roll") and name.lower() in {"full_name", "address"}:
                ea_publication_risks += 1

            if isinstance(retention_months, int) and retention_months > 24 and category in {"personal", "sensitive"}:
                retention_risks += 1

            if cross_border_transfer and category in {"personal", "sensitive"}:
                cross_border_risks += 1

    expected_summary = {
        "total_fields": total_fields,
        "sensitive_fields": sensitive_fields,
        "fields_missing_consent": fields_missing_consent,
        "ea_publication_risks": ea_publication_risks,
        "retention_risks": retention_risks,
        "cross_border_risks": cross_border_risks,
    }

    law_bullets = _parse_law_bullet_lines(pdpa_text) + _parse_law_bullet_lines(ea_text)

    return {
        "expected_rows": expected_rows,
        "expected_summary": expected_summary,
        "law_bullets": law_bullets,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "compliance_matrix_exists_and_header": 0.0,
        "compliance_matrix_row_count": 0.0,
        "compliance_matrix_values_match": 0.0,
        "triggered_rules_and_rationale_consistency": 0.0,
        "summary_json_exists_and_keys": 0.0,
        "summary_json_values_correct": 0.0,
        "meeting_notes_summary_counts_consistent": 0.0,
        "meeting_notes_risks_listed": 0.0,
        "meeting_notes_action_items_owners": 0.0,
        "email_subject_and_attachment": 0.0,
        "email_questions_and_rule_refs": 0.0,
        "email_verbatim_quotes": 0.0,
    }

    inputs = _compute_expected_from_inputs(workspace)
    compliance_path = workspace / "output" / "compliance_matrix.csv"
    summary_path = workspace / "output" / "summary.json"
    notes_path = workspace / "output" / "meeting_notes.md"
    email_path = workspace / "output" / "email_to_legal.txt"

    expected_header = [
        "dataset_name",
        "field_name",
        "category",
        "requires_explicit_consent",
        "publication_risk",
        "retention_risk",
        "cross_border_risk",
        "status",
        "triggered_rules",
        "rationale",
    ]
    headers, rows = _read_csv_dicts(compliance_path)
    if headers == expected_header:
        scores["compliance_matrix_exists_and_header"] = 1.0

    if inputs is not None and rows:
        expected_rows = inputs["expected_rows"]
        if len(rows) == len(expected_rows):
            scores["compliance_matrix_row_count"] = 1.0

        def key_fn(d):
            return (d.get("dataset_name", ""), d.get("field_name", ""))

        expected_map = {key_fn(r): r for r in expected_rows}
        actual_map = {key_fn(r): r for r in rows}

        all_keys_present = set(expected_map.keys()).issubset(set(actual_map.keys()))
        values_match = all_keys_present
        triggered_ok = all_keys_present
        if all_keys_present:
            for k, exp in expected_map.items():
                act = actual_map.get(k, {})
                for col in ["dataset_name", "field_name", "category", "requires_explicit_consent",
                            "publication_risk", "retention_risk", "cross_border_risk", "status"]:
                    if act.get(col, "") != exp.get(col, ""):
                        values_match = False
                        break
                exp_trig = exp.get("triggered_rules", "")
                if act.get("triggered_rules", "") != exp_trig:
                    triggered_ok = False
                else:
                    if exp_trig:
                        all_bracketed_present = True
                        for rid in exp_trig.split(";"):
                            if f"[{rid}]" not in act.get("rationale", ""):
                                all_bracketed_present = False
                                break
                        if not all_bracketed_present:
                            triggered_ok = False
        if values_match:
            scores["compliance_matrix_values_match"] = 1.0
        if triggered_ok:
            scores["triggered_rules_and_rationale_consistency"] = 1.0

    summary_data = _load_json_safe(summary_path)
    if isinstance(summary_data, dict):
        required_keys = ["total_fields", "sensitive_fields", "fields_missing_consent", "ea_publication_risks", "retention_risks", "cross_border_risks"]
        if all(k in summary_data and isinstance(summary_data[k], int) for k in required_keys):
            scores["summary_json_exists_and_keys"] = 1.0
        if inputs is not None:
            if all(summary_data.get(k) == inputs["expected_summary"].get(k) for k in required_keys):
                scores["summary_json_values_correct"] = 1.0

    notes_text = _read_text_safe(notes_path)
    if notes_text and summary_data and isinstance(summary_data, dict):
        counts_ok = True
        for k in ["total_fields", "sensitive_fields", "fields_missing_consent", "ea_publication_risks", "retention_risks", "cross_border_risks"]:
            val = summary_data.get(k)
            if val is None or str(val) not in notes_text:
                counts_ok = False
                break
        if counts_ok:
            scores["meeting_notes_summary_counts_consistent"] = 1.0

    if inputs is not None and notes_text:
        risk_items = []
        for r in inputs["expected_rows"]:
            if r["status"] in {"Non-compliant", "Needs review"}:
                cause_rules = []
                if r["status"] == "Non-compliant":
                    if "[EA-1]" in r["publication_risk"]:
                        cause_rules.append("EA-1")
                    if "[EA-2]" in r["publication_risk"]:
                        cause_rules.append("EA-2")
                    if "lacks consent" in r["rationale"] and "[PDPA-2]" in r["rationale"]:
                        cause_rules.append("PDPA-2")
                else:
                    if r["retention_risk"] == "Yes":
                        cause_rules.append("PDPA-3")
                    if r["cross_border_risk"] == "Yes":
                        cause_rules.append("PDPA-4")
                risk_items.append((r["dataset_name"], r["field_name"], set(cause_rules)))
        lines = [ln.strip() for ln in notes_text.splitlines()]
        listed_all = True
        for ds_name, field_name, cause_rules in risk_items:
            found_line = False
            for ln in lines:
                if ds_name in ln and field_name in ln:
                    has_all = True
                    for rid in cause_rules:
                        if f"[{rid}]" not in ln:
                            has_all = False
                            break
                    if has_all:
                        found_line = True
                        break
            if not found_line:
                listed_all = False
                break
        if listed_all:
            scores["meeting_notes_risks_listed"] = 1.0

        owner_keywords = ["PI", "Data Manager", "Legal Counsel"]
        bullet_lines = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
        owner_lines = [ln for ln in bullet_lines if any(owner in ln for owner in owner_keywords)]
        owners_present = all(any(owner in ln for ln in owner_lines) for owner in owner_keywords)
        if len(owner_lines) >= len(risk_items) and owners_present:
            scores["meeting_notes_action_items_owners"] = 1.0

    email_text = _read_text_safe(email_path)
    if email_text:
        lines = [ln.strip() for ln in email_text.splitlines() if ln.strip()]
        subject_lines = [ln for ln in lines if ln.lower().startswith("subject:")]
        subject_ok = False
        if subject_lines:
            subj = subject_lines[0].lower()
            if "sri lanka" in subj and "compliance" in subj:
                subject_ok = True
        attachment_ok = "output/compliance_matrix.csv" in email_text
        if subject_ok and attachment_ok:
            scores["email_subject_and_attachment"] = 1.0

        question_lines = [ln for ln in lines if "?" in ln and ("[PDPA-" in ln or "[EA-" in ln)]
        if len(question_lines) >= 3:
            scores["email_questions_and_rule_refs"] = 1.0

        if inputs is not None:
            bullets = inputs["law_bullets"]
            email_lines_set = set(lines)
            match_count = sum(1 for b in bullets if b in email_lines_set)
            if match_count >= 2:
                scores["email_verbatim_quotes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()