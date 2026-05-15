import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_simple_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    text = safe_read_text(path)
    if text is None:
        return None

    lines = text.splitlines()
    signature_lines: List[str] = []
    allowed_vars: List[str] = []
    placeholder_style: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i]

        if re.match(r"^\s*signature:\s*\|\s*$", line):
            i += 1
            sig_block: List[str] = []
            while i < len(lines):
                next_line = lines[i]
                if re.match(r"^\s", next_line) or next_line.strip() == "":
                    sig_block.append(next_line)
                    i += 1
                    continue
                else:
                    break
            non_empty_sig = [l for l in sig_block if l.strip() != ""]
            if non_empty_sig:
                min_indent = min(len(re.match(r"^(\s*)", l).group(1)) for l in non_empty_sig)
            else:
                min_indent = 0
            for l in sig_block:
                if len(l) >= min_indent:
                    signature_lines.append(l[min_indent:])
                else:
                    signature_lines.append(l)
            continue

        if re.match(r"^\s*allowed_vars\s*:\s*$", line):
            i += 1
            while i < len(lines):
                lv = lines[i]
                m_item = re.match(r"^\s*-\s+(.+)$", lv)
                if m_item:
                    val = m_item.group(1).strip()
                    allowed_vars.append(val)
                    i += 1
                    continue
                if lv.strip() == "":
                    i += 1
                    continue
                break
            continue

        m_style = re.match(r"^\s*placeholder_style\s*:\s*(\S+)\s*$", line)
        if m_style:
            placeholder_style = m_style.group(1).strip()
            i += 1
            continue

        i += 1

    signature = "\n".join(signature_lines).strip("\n")
    return {
        "signature": signature,
        "allowed_vars": allowed_vars,
        "placeholder_style": placeholder_style,
    }


def find_placeholders(text: str) -> List[str]:
    return re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", text)


def parse_subject_and_body(text: str) -> Tuple[Optional[str], str]:
    lines = text.splitlines()
    subject_line = None
    body_lines: List[str] = []
    for i, line in enumerate(lines):
        if line.strip():
            if line.startswith("Subject:"):
                subject_line = line[len("Subject:"):].strip()
                body_lines = lines[i + 1 :]
            break
    body = "\n".join(body_lines).strip()
    return subject_line, body


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def detect_script_template_rules(path: Path) -> Dict[str, Any]:
    content = safe_read_text(path) or ""
    subject_first_line = 'line.startswith("Subject:")' in content
    placeholder_style = "jinja2" if "from jinja2 import Template" in content else "unknown"
    return {
        "subject_first_line": subject_first_line,
        "placeholder_style": placeholder_style,
    }


def content_ends_with_signature(content: str, signature: str) -> bool:
    sig_lines = [l.rstrip() for l in signature.splitlines()]
    content_lines = [l.rstrip() for l in content.rstrip().splitlines()]
    while content_lines and content_lines[-1] == "":
        content_lines.pop()
    if len(content_lines) < len(sig_lines):
        return False
    tail = content_lines[-len(sig_lines):]
    return tail == sig_lines


def remove_signature_from_content(content: str, signature: str) -> str:
    if not signature:
        return content
    sig_lines = [l.rstrip() for l in signature.splitlines()]
    content_lines = [l.rstrip() for l in content.rstrip().splitlines()]
    while content_lines and content_lines[-1] == "":
        content_lines.pop()
    if len(content_lines) >= len(sig_lines) and content_lines[-len(sig_lines):] == sig_lines:
        remaining = content_lines[: -len(sig_lines)]
        while remaining and remaining[-1] == "":
            remaining.pop()
        return "\n".join(remaining).strip()
    return content


def remove_subject_from_content(content: str) -> str:
    _, body = parse_subject_and_body(content)
    return body


def remove_placeholders(text: str) -> str:
    return re.sub(r"{{\s*([a-zA-Z0-9_]+)\s*}}", "", text)


def contains_plaintext_food_terms(text: str) -> bool:
    terms = [
        r"\blunch\b",
        r"\bfood\b",
        r"\bcare package\b",
        r"\bcare box\b",
        r"\bcookies\b",
        r"\bbite\b",
        r"\bmeal\b",
        r"\bsnack\b",
    ]
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in terms)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "revised_templates_exist": 0.0,
        "report_json_exists_and_well_formed": 0.0,
        "report_top_level_allowed_variables_match": 0.0,
        "report_script_rules_detected_correct": 0.0,
        "shipper_subject_line_correct": 0.0,
        "family_subject_line_correct": 0.0,
        "shipper_revised_word_limit": 0.0,
        "family_revised_word_limit": 0.0,
        "shipper_allowed_variables_only": 0.0,
        "family_allowed_variables_only": 0.0,
        "shipper_signature_appended": 0.0,
        "family_signature_appended": 0.0,
        "shipper_variable_renames_correct": 0.0,
        "family_variable_renames_correct": 0.0,
        "shipper_lunch_placeholder_and_plaintext_removed": 0.0,
        "family_lunch_placeholder_and_plaintext_removed": 0.0,
        "report_file_entry_fields_complete_shipper": 0.0,
        "report_file_entry_fields_complete_family": 0.0,
        "report_variables_found_match_shipper": 0.0,
        "report_variables_found_match_family": 0.0,
        "report_variables_fixed_match_shipper": 0.0,
        "report_variables_fixed_match_family": 0.0,
        "report_uses_allowed_variables_only_flags_correct": 0.0,
        "report_subject_present_flags_true": 0.0,
        "family_duplicate_signoffs_removed": 0.0,
    }

    drafts_dir = workspace / "input" / "drafts"
    config_path = workspace / "config" / "email_config.yaml"
    script_path = workspace / "scripts" / "mailer.py"
    output_templates_dir = workspace / "output" / "revised_templates"
    report_path = workspace / "output" / "report.json"

    cfg = parse_simple_yaml_config(config_path)
    if cfg is None:
        allowed_vars: List[str] = []
        signature_text = ""
    else:
        allowed_vars = cfg.get("allowed_vars", [])
        signature_text = cfg.get("signature", "")

    script_rules = detect_script_template_rules(script_path)

    draft_files: List[Path] = []
    if drafts_dir.exists():
        draft_files = sorted([p for p in drafts_dir.glob("*.md") if p.is_file()])
    draft_map = {p.name: p for p in draft_files}
    expected_drafts = ["shipper_update.md", "family_checkin.md"]

    revised_exist = True
    for fname in expected_drafts:
        revised_path = output_templates_dir / fname
        if not revised_path.exists():
            revised_exist = False
            break
    if revised_exist and output_templates_dir.exists():
        scores["revised_templates_exist"] = 1.0

    report = load_json_file(report_path)
    if isinstance(report, dict):
        scores["report_json_exists_and_well_formed"] = 1.0

    if isinstance(report, dict) and allowed_vars:
        rep_allowed = report.get("allowed_variables")
        if isinstance(rep_allowed, list) and set(rep_allowed) == set(allowed_vars):
            scores["report_top_level_allowed_variables_match"] = 1.0

    if isinstance(report, dict):
        rep_rules = report.get("script_template_rules_detected")
        if isinstance(rep_rules, dict):
            subj_ok = isinstance(rep_rules.get("subject_first_line"), bool) and rep_rules.get("subject_first_line") is True
            style_ok = isinstance(rep_rules.get("placeholder_style"), str) and rep_rules.get("placeholder_style") == script_rules.get("placeholder_style")
            if subj_ok and style_ok:
                scores["report_script_rules_detected_correct"] = 1.0

    rename_mapping = {
        "eta": "delivery_eta",
        "DriverName": "driver_name",
        "truckId": "truck_id",
        "currentLocation": "current_location",
        "carePkgTracking": "care_pkg_tracking",
    }

    def get_report_entry_for_file(input_path: Path) -> Optional[Dict[str, Any]]:
        if not isinstance(report, dict):
            return None
        entries = report.get("files")
        if not isinstance(entries, list):
            return None
        for e in entries:
            if not isinstance(e, dict):
                continue
            f = e.get("file")
            if isinstance(f, str):
                if f.replace("\\", "/").endswith(str(input_path).replace("\\", "/")):
                    return e
                if f.replace("\\", "/").endswith(str(input_path.name)):
                    return e
                try:
                    rel = str(input_path.relative_to(workspace)).replace("\\", "/")
                    if f.replace("\\", "/").endswith(rel):
                        return e
                except Exception:
                    pass
        for e in entries:
            if not isinstance(e, dict):
                continue
            of = e.get("output_file")
            if isinstance(of, str):
                if of.replace("\\", "/").endswith((output_templates_dir / input_path.name).as_posix()):
                    return e
        return None

    for fname in expected_drafts:
        input_path = draft_map.get(fname, drafts_dir / fname)
        revised_path = output_templates_dir / fname
        original_text_opt = safe_read_text(input_path)
        revised_text_opt = safe_read_text(revised_path)

        revised_exists = revised_path.exists() and isinstance(revised_text_opt, str) and revised_text_opt.strip() != ""
        original_text = original_text_opt if isinstance(original_text_opt, str) else ""
        revised_text = revised_text_opt if isinstance(revised_text_opt, str) else ""

        original_vars_set = set(find_placeholders(original_text))
        revised_vars_set = set(find_placeholders(revised_text))

        subj_first_nonempty_is_subject = False
        if revised_exists:
            for line in revised_text.splitlines():
                if line.strip():
                    if line.startswith("Subject:"):
                        subj_first_nonempty_is_subject = True
                    break

        body_no_subject = remove_subject_from_content(revised_text) if revised_exists else ""
        body_core = remove_signature_from_content(body_no_subject, signature_text) if revised_exists else ""

        allowed_only = False
        if revised_exists and allowed_vars:
            unknown = revised_vars_set.difference(set(allowed_vars))
            allowed_only = len(unknown) == 0

        signature_ok = False
        if revised_exists and signature_text:
            signature_ok = content_ends_with_signature(revised_text, signature_text)

        cleaned_body_for_plaintext = remove_placeholders(body_core or "")
        lunch_ok = revised_exists and ("lunch_note" in revised_vars_set) and (not contains_plaintext_food_terms(cleaned_body_for_plaintext))

        word_limit_ok = revised_exists and (count_words(body_core) <= 120)

        expected_renames = {k: v for k, v in rename_mapping.items() if k in original_vars_set}
        renames_ok = False
        if revised_exists:
            renames_ok = True
            for old, new in expected_renames.items():
                if new not in revised_vars_set or old in revised_vars_set:
                    renames_ok = False
                    break

        duplicate_removed_ok = False
        if revised_exists and fname == "family_checkin.md":
            duplicate_removed_ok = True
            if "love y'all" in revised_text.lower():
                duplicate_removed_ok = False
            if "- {{ driver_name }}" in remove_signature_from_content(revised_text, signature_text):
                duplicate_removed_ok = False

        if fname == "shipper_update.md":
            if subj_first_nonempty_is_subject:
                scores["shipper_subject_line_correct"] = 1.0
            if word_limit_ok:
                scores["shipper_revised_word_limit"] = 1.0
            if allowed_only:
                scores["shipper_allowed_variables_only"] = 1.0
            if signature_ok:
                scores["shipper_signature_appended"] = 1.0
            if renames_ok and "delivery_eta" in revised_vars_set:
                scores["shipper_variable_renames_correct"] = 1.0
            if lunch_ok:
                scores["shipper_lunch_placeholder_and_plaintext_removed"] = 1.0
        elif fname == "family_checkin.md":
            if subj_first_nonempty_is_subject:
                scores["family_subject_line_correct"] = 1.0
            if word_limit_ok:
                scores["family_revised_word_limit"] = 1.0
            if allowed_only:
                scores["family_allowed_variables_only"] = 1.0
            if signature_ok:
                scores["family_signature_appended"] = 1.0
            if renames_ok and {"current_location", "care_pkg_tracking"}.issubset(revised_vars_set):
                scores["family_variable_renames_correct"] = 1.0
            if lunch_ok:
                scores["family_lunch_placeholder_and_plaintext_removed"] = 1.0
            if duplicate_removed_ok:
                scores["family_duplicate_signoffs_removed"] = 1.0

        rep_entry = get_report_entry_for_file(input_path)
        if rep_entry is not None:
            required_fields = [
                "file",
                "output_file",
                "original_word_count",
                "revised_word_count",
                "subject_present",
                "variables_found",
                "variables_fixed",
                "uses_allowed_variables_only",
                "signature_appended_from_config",
                "notes",
            ]
            has_fields = all(k in rep_entry for k in required_fields)
            fields_ok = False
            if has_fields:
                owc = rep_entry.get("original_word_count")
                rwc = rep_entry.get("revised_word_count")
                sp = rep_entry.get("subject_present")
                vfound = rep_entry.get("variables_found")
                vfixed = rep_entry.get("variables_fixed")
                uavo = rep_entry.get("uses_allowed_variables_only")
                sign_app = rep_entry.get("signature_appended_from_config")
                notes = rep_entry.get("notes")
                types_ok = (
                    isinstance(owc, int)
                    and isinstance(rwc, int)
                    and isinstance(sp, bool)
                    and isinstance(vfound, (list, set))
                    and isinstance(vfixed, dict)
                    and isinstance(uavo, bool)
                    and isinstance(sign_app, bool)
                    and isinstance(notes, str)
                )
                limit_ok_report = isinstance(rwc, int) and rwc <= 120
                of = rep_entry.get("output_file")
                of_ok = isinstance(of, str) and of.replace("\\", "/").endswith((output_templates_dir / fname).as_posix())
                fields_ok = types_ok and limit_ok_report and of_ok
            if fname == "shipper_update.md" and fields_ok:
                scores["report_file_entry_fields_complete_shipper"] = 1.0
            if fname == "family_checkin.md" and fields_ok:
                scores["report_file_entry_fields_complete_family"] = 1.0

            vfound_list = rep_entry.get("variables_found")
            if isinstance(vfound_list, list):
                if set(vfound_list) == original_vars_set:
                    if fname == "shipper_update.md":
                        scores["report_variables_found_match_shipper"] = 1.0
                    elif fname == "family_checkin.md":
                        scores["report_variables_found_match_family"] = 1.0

            vfixed_map = rep_entry.get("variables_fixed")
            if isinstance(vfixed_map, dict):
                expected_map = {k: v for k, v in rename_mapping.items() if k in original_vars_set}
                if vfixed_map == expected_map:
                    if fname == "shipper_update.md":
                        scores["report_variables_fixed_match_shipper"] = 1.0
                    elif fname == "family_checkin.md":
                        scores["report_variables_fixed_match_family"] = 1.0

    report_subject_flags_ok = True
    report_uavo_flags_ok = True
    if isinstance(report, dict):
        all_entries = report.get("files")
        if isinstance(all_entries, list):
            for fname in expected_drafts:
                input_path = (drafts_dir / fname)
                rep_entry = None
                for e in all_entries:
                    if isinstance(e, dict):
                        f = e.get("file")
                        if isinstance(f, str):
                            if f.replace("\\", "/").endswith(str(input_path).replace("\\", "/")) or f.replace("\\", "/").endswith(str(input_path.name)):
                                rep_entry = e
                                break
                if rep_entry is None:
                    report_subject_flags_ok = False
                    report_uavo_flags_ok = False
                    continue
                sp = rep_entry.get("subject_present")
                if sp is not True:
                    report_subject_flags_ok = False
                uavo = rep_entry.get("uses_allowed_variables_only")
                revised_path = output_templates_dir / fname
                revised_text = safe_read_text(revised_path) or ""
                revised_vars_set = set(find_placeholders(revised_text))
                actual_allowed_only = len(revised_vars_set.difference(set(allowed_vars))) == 0 if allowed_vars else False
                if not (uavo is True and actual_allowed_only):
                    report_uavo_flags_ok = False
        else:
            report_subject_flags_ok = False
            report_uavo_flags_ok = False
    else:
        report_subject_flags_ok = False
        report_uavo_flags_ok = False

    if report_subject_flags_ok:
        scores["report_subject_present_flags_true"] = 1.0
    if report_uavo_flags_ok:
        scores["report_uses_allowed_variables_only_flags_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()