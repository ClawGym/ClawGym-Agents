import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Any


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _load_json(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _parse_csv(path: Path) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames if reader.fieldnames is not None else []
        return True, rows, headers
    except Exception:
        return False, [], []


def _parse_roles_yaml(path: Path) -> Tuple[bool, Dict[str, float]]:
    ok, text = _read_text(path)
    if not ok:
        return False, {}
    roles: Dict[str, float] = {}
    in_roles = False
    current_name = None
    current_max = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not in_roles:
            if stripped.startswith("roles:"):
                in_roles = True
            continue
        if stripped.startswith("- "):
            if current_name is not None and current_max is not None:
                roles[current_name] = float(current_max)
            current_name = None
            current_max = None
            m = re.match(r"-\s+name:\s*(.+)$", stripped)
            if m:
                current_name = m.group(1).strip()
            continue
        if "name:" in stripped and stripped.startswith("name:"):
            current_name = stripped.split("name:", 1)[1].strip()
        if "max_hours_per_quarter:" in stripped:
            try:
                val = stripped.split("max_hours_per_quarter:", 1)[1].strip()
                current_max = float(val)
            except Exception:
                current_max = None
    if current_name is not None and current_max is not None:
        roles[current_name] = float(current_max)
    if not roles:
        return False, {}
    return True, roles


def _extract_priorities(md_path: Path) -> Tuple[bool, List[str]]:
    ok, text = _read_text(md_path)
    if not ok:
        return False, []
    priorities: List[str] = []
    in_objectives = False
    for line in text.splitlines():
        if "Our objectives" in line:
            in_objectives = True
            continue
        if in_objectives:
            m = re.match(r"\s*\d+\.\s*(.+)$", line)
            if m:
                item = m.group(1).strip()
                name = item.split(":", 1)[0].strip()
                if name:
                    priorities.append(name)
    if not priorities:
        for line in text.splitlines():
            m = re.match(r"\s*\d+\.\s*(.+)$", line)
            if m:
                name = m.group(1).strip().split(":", 1)[0].strip()
                if name:
                    priorities.append(name)
    if not priorities:
        return False, []
    return True, priorities


def _parse_memo_sections(path: Path) -> Tuple[bool, Dict[str, str]]:
    ok, text = _read_text(path)
    if not ok:
        return False, {}
    lines = text.splitlines()
    sections: Dict[str, str] = {}
    current_heading = None
    buffer: List[str] = []

    def commit():
        nonlocal current_heading, buffer
        if current_heading is not None:
            sections[current_heading] = "\n".join(buffer).strip()
            buffer = []

    for raw in lines:
        line = raw.rstrip()
        clean = line.lstrip("#").strip()
        if clean in [
            "Overview",
            "External frameworks consulted",
            "Curriculum plan summary",
            "Hours by role vs. budget",
            "Risks and next steps",
        ]:
            commit()
            current_heading = clean
            continue
        if current_heading is not None:
            buffer.append(line)
    commit()
    return True, sections


def _normalize_token(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _split_semicolon_list(val: str) -> List[str]:
    return [x.strip() for x in val.split(";") if x.strip()]


def _allowed_publishers() -> Dict[str, str]:
    allowed = {
        "hhs": "HHS",
        "onc": "ONC",
        "ocr": "OCR",
        "nist": "NIST",
        "ahrq": "AHRQ",
        "himss": "HIMSS",
        "the joint commission": "The Joint Commission",
    }
    return allowed


def _curriculum_expected_headers() -> List[str]:
    return [
        "module_id",
        "title",
        "audience_roles",
        "hours",
        "delivery_mode",
        "source_alignment",
        "new_or_existing",
        "priority_mapping",
    ]


def _load_existing_modules(path: Path) -> Tuple[bool, Dict[str, Dict[str, str]]]:
    ok, rows, headers = _parse_csv(path)
    if not ok or not rows:
        return False, {}
    lookup = {}
    for r in rows:
        mid = r.get("module_id", "").strip()
        if mid:
            lookup[mid] = r
    return True, lookup


def _parse_curriculum(path: Path) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    ok, rows, headers = _parse_csv(path)
    if not ok:
        return False, [], []
    expected = _curriculum_expected_headers()
    if headers != expected:
        return False, [], headers or []
    parsed: List[Dict[str, Any]] = []
    for r in rows:
        item: Dict[str, Any] = {}
        for h in expected:
            if h not in r:
                return False, [], headers
            item[h] = r[h]
        try:
            item["hours"] = float(str(item["hours"]).strip())
        except Exception:
            return False, [], headers
        parsed.append(item)
    return True, parsed, headers


def _compute_hours_by_role(curriculum: List[Dict[str, Any]], roles: Dict[str, float]) -> Dict[str, float]:
    totals = {role: 0.0 for role in roles.keys()}
    for row in curriculum:
        try:
            hrs = float(row.get("hours", 0.0))
        except Exception:
            hrs = 0.0
        aud = row.get("audience_roles", "")
        tokens = _split_semicolon_list(aud)
        if not tokens:
            continue
        target_roles = set()
        if any(_normalize_token(t) == "all" for t in tokens):
            target_roles = set(roles.keys())
        else:
            for t in tokens:
                if t in roles:
                    target_roles.add(t)
        for role in target_roles:
            totals[role] += hrs
    return totals


def _frameworks_info(frameworks: List[Dict[str, Any]]) -> Tuple[set, List[str], List[str]]:
    orgs = set()
    titles = []
    cat_all = []
    for f in frameworks:
        pb = f.get("publishing_body", "")
        if isinstance(pb, str):
            orgs.add(pb)
        titles.append(f.get("source_title", ""))
        cats = f.get("competency_categories", [])
        if isinstance(cats, list):
            for c in cats:
                if isinstance(c, str):
                    cat_all.append(c)
    return orgs, titles, cat_all


def _module_alignment_valid(row: Dict[str, Any], frameworks: List[Dict[str, Any]]) -> bool:
    align = row.get("source_alignment", "")
    if not isinstance(align, str) or not align.strip():
        return False
    align_lower = align.lower()
    referenced = False
    includes_category = False
    for fw in frameworks:
        pb = fw.get("publishing_body", "")
        st = fw.get("source_title", "")
        if pb and pb.lower() in align_lower:
            referenced = True
        if st and st.lower() in align_lower:
            referenced = True
        cats = fw.get("competency_categories", [])
        if isinstance(cats, list):
            for c in cats:
                if isinstance(c, str) and c.lower() in align_lower:
                    includes_category = True
    return referenced and includes_category


def _contains_no_urls(text: str) -> bool:
    if not isinstance(text, str):
        return False
    low = text.lower()
    return ("http://" not in low) and ("https://" not in low)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "frameworks_file_present_and_valid": 0.0,
        "frameworks_min_two_and_allowed_orgs": 0.0,
        "frameworks_unique_sources": 0.0,
        "no_urls_in_frameworks": 0.0,
        "curriculum_file_present_and_valid_structure": 0.0,
        "curriculum_roles_and_hours_valid": 0.0,
        "curriculum_delivery_mode_valid": 0.0,
        "curriculum_source_alignment_references_frameworks": 0.0,
        "curriculum_priorities_coverage": 0.0,
        "curriculum_reuse_vs_new_validity": 0.0,
        "new_modules_within_guideline": 0.0,
        "reuse_favored": 0.0,
        "hours_within_role_budgets": 0.0,
        "validation_json_correctness": 0.0,
        "executive_memo_headings_present": 0.0,
        "executive_memo_frameworks_listed": 0.0,
        "executive_memo_hours_section_roles_listed": 0.0,
        "no_urls_in_memo_frameworks_section": 0.0,
        "search_log_queries_and_sources_present": 0.0,
    }

    roles_path = workspace / "input" / "roles.yaml"
    existing_trainings_path = workspace / "input" / "existing_training.csv"
    priorities_md_path = workspace / "input" / "strategic_priorities.md"

    ok_roles, roles = _parse_roles_yaml(roles_path)
    ok_existing, existing_lookup = _load_existing_modules(existing_trainings_path)
    ok_priorities, priorities = _extract_priorities(priorities_md_path)

    frameworks_path = workspace / "output" / "frameworks_summary.json"
    curriculum_path = workspace / "output" / "curriculum_plan.csv"
    validation_path = workspace / "output" / "validation.json"
    memo_path = workspace / "output" / "executive_memo.md"
    search_log_path = workspace / "output" / "search_log.txt"

    # Frameworks checks
    fw_ok, fw_data = _load_json(frameworks_path)
    frameworks: List[Dict[str, Any]] = []
    if fw_ok and isinstance(fw_data, list):
        required_fw_keys = ["source_title", "publishing_body", "year_or_version", "competency_categories", "citation_note"]
        structure_valid = True
        no_urls = True
        allowed_map = _allowed_publishers()
        allowed_set = set(allowed_map.values())
        allowed_norms = set(allowed_map.keys())
        allowed_count = 0
        for item in fw_data:
            if not isinstance(item, dict):
                structure_valid = False
                break
            for k in required_fw_keys:
                if k not in item:
                    structure_valid = False
                    break
            if not structure_valid:
                break
            pb = str(item.get("publishing_body", "")).strip()
            pb_norm = _normalize_token(pb)
            if pb in allowed_set or pb_norm in allowed_norms:
                allowed_count += 1
            cats = item.get("competency_categories", [])
            if not isinstance(cats, list) or not cats or not all(isinstance(c, str) and c.strip() for c in cats):
                structure_valid = False
                break
            for key in ["source_title", "publishing_body", "year_or_version", "citation_note"]:
                val = item.get(key, "")
                if isinstance(val, str) and not _contains_no_urls(val):
                    no_urls = False
        if structure_valid:
            frameworks = fw_data
            scores["frameworks_file_present_and_valid"] = 1.0
        if structure_valid and allowed_count >= 2:
            scores["frameworks_min_two_and_allowed_orgs"] = 1.0
        if structure_valid:
            seen = set()
            dup = False
            for f in frameworks:
                st = f.get("source_title", "")
                if st in seen:
                    dup = True
                    break
                seen.add(st)
            if not dup and len(seen) == len(frameworks) and len(frameworks) >= 2:
                scores["frameworks_unique_sources"] = 1.0
        if no_urls and structure_valid:
            scores["no_urls_in_frameworks"] = 1.0

    # Curriculum checks
    cur_ok, curriculum_rows, headers = _parse_curriculum(curriculum_path)
    if cur_ok:
        scores["curriculum_file_present_and_valid_structure"] = 1.0
        roles_valid = True
        delivery_valid = True
        source_alignment_valid_all = True
        priority_coverage_tokens: List[str] = []
        priorities_set_norm = {_normalize_token(p) for p in (priorities if ok_priorities else [])}
        for row in curriculum_rows:
            try:
                hours_val = float(row.get("hours", 0.0))
            except Exception:
                roles_valid = False
                break
            if hours_val <= 0:
                roles_valid = False
                break
            dm = str(row.get("delivery_mode", "")).strip()
            if dm not in {"self-paced", "live-virtual", "in-person"}:
                delivery_valid = False
            aud = str(row.get("audience_roles", "")).strip()
            if not aud:
                roles_valid = False
            aud_tokens = _split_semicolon_list(aud)
            aud_tokens_norm = [_normalize_token(t) for t in aud_tokens]
            if any(t == "all" for t in aud_tokens_norm):
                if len(aud_tokens_norm) != 1:
                    roles_valid = False
            else:
                if not ok_roles:
                    roles_valid = False
                else:
                    for t in aud_tokens:
                        if t not in roles:
                            roles_valid = False
                            break
            if not frameworks:
                source_alignment_valid_all = False
            else:
                if not _module_alignment_valid(row, frameworks):
                    source_alignment_valid_all = False
            pm = str(row.get("priority_mapping", "")).strip()
            for token in _split_semicolon_list(pm):
                priority_coverage_tokens.append(token)
        if roles_valid:
            scores["curriculum_roles_and_hours_valid"] = 1.0
        if delivery_valid:
            scores["curriculum_delivery_mode_valid"] = 1.0
        if source_alignment_valid_all:
            scores["curriculum_source_alignment_references_frameworks"] = 1.0
        if ok_priorities:
            tokens_norm = {_normalize_token(t) for t in priority_coverage_tokens}
            covered_all = all(p in tokens_norm for p in priorities_set_norm)
            if covered_all:
                scores["curriculum_priorities_coverage"] = 1.0
        reuse_valid = True
        new_count = 0
        reused_count = 0
        if ok_existing:
            for row in curriculum_rows:
                neo = str(row.get("new_or_existing", "")).strip()
                if neo == "New":
                    new_count += 1
                else:
                    if neo in existing_lookup:
                        reused_count += 1
                    else:
                        reuse_valid = False
            if reuse_valid:
                scores["curriculum_reuse_vs_new_validity"] = 1.0
            if new_count <= 5:
                scores["new_modules_within_guideline"] = 1.0
            if reused_count >= new_count:
                scores["reuse_favored"] = 1.0
        if ok_roles:
            totals = _compute_hours_by_role(curriculum_rows, roles)
            within = all(totals.get(role, 0.0) <= roles[role] + 1e-9 for role in roles.keys())
            if within:
                scores["hours_within_role_budgets"] = 1.0

    # validation.json correctness
    val_ok, val_data = _load_json(validation_path)
    if val_ok and isinstance(val_data, dict) and cur_ok and ok_roles:
        totals = _compute_hours_by_role(curriculum_rows, roles)
        within_budget = {role: (totals.get(role, 0.0) <= roles[role] + 1e-9) for role in roles.keys()}
        fw_orgs_set, fw_titles, _ = _frameworks_info(frameworks) if frameworks else (set(), [], [])
        frameworks_orgs_list = sorted(list(fw_orgs_set))
        frameworks_used_count = len(frameworks) if frameworks else 0
        new_count = 0
        reused_count = 0
        if ok_existing:
            for row in curriculum_rows:
                neo = str(row.get("new_or_existing", "")).strip()
                if neo == "New":
                    new_count += 1
                elif neo in existing_lookup:
                    reused_count += 1
        covered_all = False
        if ok_priorities:
            pm_tokens = set()
            for row in curriculum_rows:
                for token in _split_semicolon_list(str(row.get("priority_mapping", ""))):
                    pm_tokens.add(_normalize_token(token))
            covered_all = all(_normalize_token(p) in pm_tokens for p in priorities)
        try:
            hours_by_role = val_data.get("hours_by_role", {})
            within_budget_json = val_data.get("within_budget", {})
            fw_used_count_json = val_data.get("frameworks_used_count", None)
            fw_orgs_json = val_data.get("frameworks_orgs", [])
            new_module_count_json = val_data.get("new_module_count", None)
            existing_reused_count_json = val_data.get("existing_module_reused_count", None)
            covers_all_priorities_json = val_data.get("covers_all_priorities", None)

            hours_match = isinstance(hours_by_role, dict) and len(hours_by_role) == len(totals)
            if hours_match:
                for role, val in totals.items():
                    if role not in hours_by_role:
                        hours_match = False
                        break
                    try:
                        if abs(float(hours_by_role[role]) - float(val)) > 1e-6:
                            hours_match = False
                            break
                    except Exception:
                        hours_match = False
                        break
            within_match = isinstance(within_budget_json, dict) and len(within_budget_json) == len(within_budget)
            if within_match:
                for role, b in within_budget.items():
                    if role not in within_budget_json or bool(within_budget_json[role]) != b:
                        within_match = False
                        break
            fw_count_match = (fw_used_count_json == frameworks_used_count)
            fw_orgs_match = isinstance(fw_orgs_json, list) and set(fw_orgs_json) == set(frameworks_orgs_list)
            new_count_match = (new_module_count_json == new_count)
            reused_count_match = (existing_reused_count_json == reused_count)
            covered_match = (covers_all_priorities_json == covered_all)
            if hours_match and within_match and fw_count_match and fw_orgs_match and new_count_match and reused_count_match and covered_match:
                scores["validation_json_correctness"] = 1.0
        except Exception:
            pass

    # Executive memo checks
    memo_ok, sections = _parse_memo_sections(memo_path)
    if memo_ok:
        headings = [
            "Overview",
            "External frameworks consulted",
            "Curriculum plan summary",
            "Hours by role vs. budget",
            "Risks and next steps",
        ]
        if all(h in sections for h in headings):
            scores["executive_memo_headings_present"] = 1.0
        if frameworks and "External frameworks consulted" in sections:
            content = sections.get("External frameworks consulted", "")
            listed = True
            for f in frameworks:
                pb = f.get("publishing_body", "")
                st = f.get("source_title", "")
                if (pb and pb in content) and (st and st in content):
                    continue
                else:
                    listed = False
                    break
            if listed:
                scores["executive_memo_frameworks_listed"] = 1.0
            if _contains_no_urls(content):
                scores["no_urls_in_memo_frameworks_section"] = 1.0
        if ok_roles and "Hours by role vs. budget" in sections:
            content = sections.get("Hours by role vs. budget", "")
            if all(role in content for role in roles.keys()):
                scores["executive_memo_hours_section_roles_listed"] = 1.0

    # Search log checks
    sl_ok, sl_text = _read_text(search_log_path)
    if sl_ok:
        lines = [ln.strip() for ln in sl_text.splitlines()]
        query_lines = []
        for ln in lines:
            if not ln:
                continue
            lnl = ln.lower()
            if lnl.startswith("query") or lnl.startswith("search") or ln.startswith("- ") or ln.startswith("* ") or ln.endswith("?"):
                query_lines.append(ln)
        unique_queries = list(dict.fromkeys(query_lines))
        queries_ok = len(unique_queries) >= 3
        sources_ok = True
        if frameworks:
            for f in frameworks:
                pb = f.get("publishing_body", "")
                st = f.get("source_title", "")
                content = sl_text
                if (pb and pb in content) and (st and st in content):
                    continue
                else:
                    sources_ok = False
                    break
        if queries_ok and sources_ok:
            scores["search_log_queries_and_sources_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()