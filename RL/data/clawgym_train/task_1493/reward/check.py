import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_json_load(path: Path) -> Optional[dict]:
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def safe_csv_read(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def list_markdown_files(root: Path) -> List[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted([p for p in root.rglob("*.md") if p.is_file()])


def compute_pii_counts_for_text(text: str) -> Dict[str, int]:
    email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    phone_pattern = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")
    sid_pattern = re.compile(r"SID: \d{9}")
    secret_pattern = re.compile(r"^(?:API_KEY|PASSWORD)=[^\s]+", re.MULTILINE)

    emails = email_pattern.findall(text) if text else []
    phones = phone_pattern.findall(text) if text else []
    student_ids = sid_pattern.findall(text) if text else []
    secrets = secret_pattern.findall(text) if text else []

    return {
        "emails": len(emails),
        "phones": len(phones),
        "student_ids": len(student_ids),
        "secrets": len(secrets),
    }


def compute_expected_from_inputs(workspace: Path) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], Dict[str, int], List[Tuple[str, int]]]:
    notes_root = workspace / "input" / "notes"
    files = list_markdown_files(notes_root)
    per_file: Dict[str, Dict[str, int]] = {}
    email_domains: Dict[str, int] = {}
    totals = {"emails": 0, "phones": 0, "student_ids": 0, "secrets": 0}
    for f in files:
        rel = f.as_posix().replace(workspace.as_posix().rstrip("/") + "/", "")
        text = safe_read_text(f) or ""
        counts = compute_pii_counts_for_text(text)
        total_exposures = counts["emails"] + counts["phones"] + counts["student_ids"] + counts["secrets"]
        per_file[rel] = {
            "emails": counts["emails"],
            "phones": counts["phones"],
            "student_ids": counts["student_ids"],
            "secrets": counts["secrets"],
            "total_exposures": total_exposures,
        }
        if counts["emails"] > 0:
            email_pattern = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
            for _, domain in email_pattern.findall(text):
                email_domains[domain] = email_domains.get(domain, 0) + 1
        for k in ["emails", "phones", "student_ids", "secrets"]:
            totals[k] += counts[k]
    sorted_files = sorted([(f, data["total_exposures"]) for f, data in per_file.items()], key=lambda x: (-x[1], x[0]))
    top_k = sorted_files[:3]
    return per_file, totals, email_domains, top_k


def parse_policy_yaml_simple(path: Path) -> Optional[dict]:
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    data = {
        "redact_pii": None,
        "enforce_exclusions": None,
        "allowed_email_domains": None,
        "exclude_patterns": None,
    }
    current_key = None
    current_indent = None
    current_list: List[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if re.match(r"^[A-Za-z0-9_]+:", line):
            if current_key in ("allowed_email_domains", "exclude_patterns") and current_list is not None:
                data[current_key] = current_list
            current_key = None
            current_indent = None
            current_list = []
            key, _, rest = line.partition(":")
            key = key.strip()
            value = rest.strip()
            if key in ("redact_pii", "enforce_exclusions"):
                val = value.lower() if value else ""
                if val in ("true", "false"):
                    data[key] = (val == "true")
                else:
                    data[key] = None if val == "" else None
            elif key in ("allowed_email_domains", "exclude_patterns"):
                current_key = key
                current_indent = None
                current_list = []
                if value.startswith("[") and value.endswith("]"):
                    inner = value[1:-1].strip()
                    items = []
                    if inner:
                        for item in inner.split(","):
                            items.append(item.strip().strip('"').strip("'"))
                    data[key] = items
                    current_key = None
                else:
                    pass
            else:
                current_key = None
        else:
            if current_key in ("allowed_email_domains", "exclude_patterns"):
                m = re.match(r"^(\s*)-\s*(.*)$", line)
                if m:
                    item = m.group(2).strip()
                    item = item.strip('"').strip("'")
                    current_list.append(item)
                    if current_indent is None:
                        current_indent = len(m.group(1))
                else:
                    pass
            else:
                pass
    if current_key in ("allowed_email_domains", "exclude_patterns") and current_list is not None:
        data[current_key] = current_list
    return data


def parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def normalize_path_str(p: str) -> str:
    return str(Path(p)).replace("\\", "/")


def match_row_to_expected(files_expected: Dict[str, Dict[str, int]], row_file_value: str) -> Optional[str]:
    v = normalize_path_str(row_file_value.strip())
    if v in files_expected:
        return v
    basename = Path(v).name
    candidates = [k for k in files_expected.keys() if Path(k).name == basename]
    if len(candidates) == 1:
        return candidates[0]
    return None


def check_brief_totals_from_json(brief_text: str, json_data: dict) -> float:
    if not isinstance(json_data, dict):
        return 0.0
    totals = json_data.get("totals")
    if not isinstance(totals, dict):
        return 0.0
    label_map = {
        "emails": ["email", "emails"],
        "phones": ["phone", "phones"],
        "student_ids": ["student id", "student_id", "student ids", "student_ids"],
        "secrets": ["secret", "secrets"],
    }
    lines = brief_text.lower().splitlines()
    ok = True
    for key, synonyms in label_map.items():
        val = totals.get(key)
        if not isinstance(val, int):
            return 0.0
        found = False
        for line in lines:
            if any(s in line for s in synonyms) and str(val) in line:
                found = True
                break
        if not found:
            ok = False
            break
    return 1.0 if ok else 0.0


def extract_bullet_lines(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped)
    return bullets


def brief_contains_high_risk_list(brief_text: str, high_risk: List[dict]) -> float:
    if not isinstance(high_risk, list):
        return 0.0
    bullets = extract_bullet_lines(brief_text)
    if not bullets:
        return 0.0
    ok_all = True
    for item in high_risk:
        f = item.get("file")
        total = item.get("total_exposures")
        if not isinstance(f, str) or not isinstance(total, int):
            return 0.0
        fname = Path(f).name.lower()
        matched = False
        for b in bullets:
            bl = b.lower()
            if (fname in bl or f.lower() in bl) and str(total) in bl:
                matched = True
                break
        if not matched:
            ok_all = False
            break
    return 1.0 if ok_all else 0.0


def brief_action_items_checks(brief_text: str) -> Tuple[float, float]:
    bullets = extract_bullet_lines(brief_text)
    count_ok = 1.0 if len(bullets) >= 3 else 0.0
    text_lower = brief_text.lower()
    cond_a = (("redact" in text_lower or "remove" in text_lower) and ("pii" in text_lower or "personal info" in text_lower or "personal information" in text_lower))
    cond_b = ("university.edu" in text_lower and "only" in text_lower and ("email" in text_lower or "emails" in text_lower))
    cond_c = ("exclude" in text_lower and "grade" in text_lower and ("config/security_policy.yaml" in text_lower or "security_policy.yaml" in text_lower))
    specifics_ok = 1.0 if (cond_a and cond_b and cond_c) else 0.0
    return count_ok, specifics_ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "csv_exists_and_structure": 0.0,
        "csv_counts_correct": 0.0,
        "json_exists_and_structure": 0.0,
        "json_totals_correct": 0.0,
        "json_email_domains_correct": 0.0,
        "json_high_risk_correct": 0.0,
        "policy_redact_pii_true": 0.0,
        "policy_enforce_exclusions_true": 0.0,
        "policy_allowed_email_domains_only_university": 0.0,
        "policy_exclude_patterns_includes_grades": 0.0,
        "brief_exists": 0.0,
        "brief_includes_totals_summary": 0.0,
        "brief_lists_high_risk_files_with_counts": 0.0,
        "brief_action_items_three_or_more": 0.0,
        "brief_action_items_specifics": 0.0,
    }

    expected_by_file, expected_totals, expected_domains, expected_top3 = compute_expected_from_inputs(workspace)

    csv_path = workspace / "output" / "pii_by_file.csv"
    rows = None
    if csv_path.exists():
        rows = safe_csv_read(csv_path)
        if rows is not None:
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
            except Exception:
                header = []
            expected_header = ["file", "emails", "phones", "student_ids", "secrets", "total_exposures"]
            if header == expected_header:
                scores["csv_exists_and_structure"] = 1.0
            else:
                scores["csv_exists_and_structure"] = 0.0
        else:
            scores["csv_exists_and_structure"] = 0.0
    else:
        scores["csv_exists_and_structure"] = 0.0

    if rows is not None:
        matched_files = set()
        counts_ok = True
        if len(rows) != len(expected_by_file):
            counts_ok = False
        used_row_indices = set()
        for i, row in enumerate(rows):
            file_val = row.get("file", "")
            target_key = match_row_to_expected(expected_by_file, file_val)
            if target_key is None:
                counts_ok = False
                continue
            if target_key in matched_files:
                counts_ok = False
                continue
            expected = expected_by_file[target_key]
            emails = parse_int(row.get("emails", ""))
            phones = parse_int(row.get("phones", ""))
            sids = parse_int(row.get("student_ids", ""))
            secrets = parse_int(row.get("secrets", ""))
            total = parse_int(row.get("total_exposures", ""))
            if None in (emails, phones, sids, secrets, total):
                counts_ok = False
            else:
                if not (emails == expected["emails"] and phones == expected["phones"] and sids == expected["student_ids"] and secrets == expected["secrets"]):
                    counts_ok = False
                if total != emails + phones + sids + secrets:
                    counts_ok = False
                if total != expected["total_exposures"]:
                    counts_ok = False
            matched_files.add(target_key)
            used_row_indices.add(i)
        if matched_files != set(expected_by_file.keys()):
            counts_ok = False
        scores["csv_counts_correct"] = 1.0 if counts_ok else 0.0
    else:
        scores["csv_counts_correct"] = 0.0

    json_path = workspace / "output" / "aggregate_summary.json"
    json_data = None
    if json_path.exists():
        json_data = safe_json_load(json_path)
        if isinstance(json_data, dict):
            has_totals = isinstance(json_data.get("totals"), dict)
            has_domains = isinstance(json_data.get("email_domains"), dict)
            has_high_risk = isinstance(json_data.get("high_risk_files"), list)
            if has_totals and has_domains and has_high_risk:
                t = json_data.get("totals", {})
                totals_keys_ok = all(k in t for k in ["emails", "phones", "student_ids", "secrets"])
                hr = json_data.get("high_risk_files", [])
                hr_struct_ok = all(isinstance(x, dict) and "file" in x and "total_exposures" in x for x in hr)
                scores["json_exists_and_structure"] = 1.0 if (totals_keys_ok and hr_struct_ok) else 0.0
            else:
                scores["json_exists_and_structure"] = 0.0
        else:
            scores["json_exists_and_structure"] = 0.0
    else:
        scores["json_exists_and_structure"] = 0.0

    if isinstance(json_data, dict):
        t = json_data.get("totals")
        if isinstance(t, dict):
            totals_ok = (
                isinstance(t.get("emails"), int) and t.get("emails") == expected_totals.get("emails", 0) and
                isinstance(t.get("phones"), int) and t.get("phones") == expected_totals.get("phones", 0) and
                isinstance(t.get("student_ids"), int) and t.get("student_ids") == expected_totals.get("student_ids", 0) and
                isinstance(t.get("secrets"), int) and t.get("secrets") == expected_totals.get("secrets", 0)
            )
            scores["json_totals_correct"] = 1.0 if totals_ok else 0.0
        else:
            scores["json_totals_correct"] = 0.0
        d = json_data.get("email_domains")
        if isinstance(d, dict):
            try:
                domains_ok = True
                if set(d.keys()) != set(expected_domains.keys()):
                    domains_ok = False
                else:
                    for k, v in d.items():
                        if not isinstance(v, int) or v != expected_domains.get(k, None):
                            domains_ok = False
                            break
                scores["json_email_domains_correct"] = 1.0 if domains_ok else 0.0
            except Exception:
                scores["json_email_domains_correct"] = 0.0
        else:
            scores["json_email_domains_correct"] = 0.0
        hr = json_data.get("high_risk_files")
        if isinstance(hr, list):
            try:
                if len(hr) > 3:
                    scores["json_high_risk_correct"] = 0.0
                else:
                    totals_list = [item.get("total_exposures") for item in hr]
                    if any(not isinstance(x, int) for x in totals_list):
                        scores["json_high_risk_correct"] = 0.0
                    else:
                        sorted_non_inc = all(totals_list[i] >= totals_list[i+1] for i in range(len(totals_list)-1))
                        if not sorted_non_inc:
                            scores["json_high_risk_correct"] = 0.0
                        else:
                            provided_set = set((normalize_path_str(item.get("file", "")), item.get("total_exposures")) for item in hr)
                            expected_set = set((normalize_path_str(f), tot) for f, tot in expected_top3)
                            if provided_set == expected_set:
                                scores["json_high_risk_correct"] = 1.0
                            else:
                                provided_set_base = set((Path(item.get("file", "")).name, item.get("total_exposures")) for item in hr)
                                expected_set_base = set((Path(f).name, tot) for f, tot in expected_top3)
                                scores["json_high_risk_correct"] = 1.0 if provided_set_base == expected_set_base else 0.0
            except Exception:
                scores["json_high_risk_correct"] = 0.0
        else:
            scores["json_high_risk_correct"] = 0.0
    else:
        scores["json_totals_correct"] = 0.0
        scores["json_email_domains_correct"] = 0.0
        scores["json_high_risk_correct"] = 0.0

    policy_path = workspace / "config" / "security_policy.yaml"
    policy = None
    if policy_path.exists():
        policy = parse_policy_yaml_simple(policy_path)
    if isinstance(policy, dict):
        scores["policy_redact_pii_true"] = 1.0 if policy.get("redact_pii") is True else 0.0
        scores["policy_enforce_exclusions_true"] = 1.0 if policy.get("enforce_exclusions") is True else 0.0
        allowed = policy.get("allowed_email_domains")
        if isinstance(allowed, list) and len(allowed) == 1:
            item = (allowed[0] or "").strip().strip('"').strip("'")
            scores["policy_allowed_email_domains_only_university"] = 1.0 if item == "university.edu" else 0.0
        else:
            scores["policy_allowed_email_domains_only_university"] = 0.0
        patterns = policy.get("exclude_patterns")
        if isinstance(patterns, list) and any("grade" in (p or "").lower() for p in patterns):
            scores["policy_exclude_patterns_includes_grades"] = 1.0
        else:
            scores["policy_exclude_patterns_includes_grades"] = 0.0
    else:
        scores["policy_redact_pii_true"] = 0.0
        scores["policy_enforce_exclusions_true"] = 0.0
        scores["policy_allowed_email_domains_only_university"] = 0.0
        scores["policy_exclude_patterns_includes_grades"] = 0.0

    brief_path = workspace / "output" / "study_group_security_brief.md"
    brief_text = None
    if brief_path.exists():
        brief_text = safe_read_text(brief_path)
        scores["brief_exists"] = 1.0 if brief_text is not None and brief_text.strip() != "" else 0.0
    else:
        scores["brief_exists"] = 0.0

    if brief_text:
        if isinstance(json_data, dict):
            scores["brief_includes_totals_summary"] = check_brief_totals_from_json(brief_text, json_data)
        else:
            scores["brief_includes_totals_summary"] = 0.0

        if isinstance(json_data, dict):
            hr = json_data.get("high_risk_files", [])
            if isinstance(hr, list):
                if len(expected_by_file) == 0:
                    if len(hr) == 0:
                        scores["brief_lists_high_risk_files_with_counts"] = 1.0
                    else:
                        scores["brief_lists_high_risk_files_with_counts"] = 0.0
                else:
                    scores["brief_lists_high_risk_files_with_counts"] = brief_contains_high_risk_list(brief_text, hr)
            else:
                scores["brief_lists_high_risk_files_with_counts"] = 0.0
        else:
            scores["brief_lists_high_risk_files_with_counts"] = 0.0

        count_ok, specifics_ok = brief_action_items_checks(brief_text)
        scores["brief_action_items_three_or_more"] = count_ok
        scores["brief_action_items_specifics"] = specifics_ok
    else:
        scores["brief_includes_totals_summary"] = 0.0
        scores["brief_lists_high_risk_files_with_counts"] = 0.0
        scores["brief_action_items_three_or_more"] = 0.0
        scores["brief_action_items_specifics"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()