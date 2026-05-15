import json
import csv
import sys
import re
import difflib
from pathlib import Path
from typing import Optional, List, Dict, Tuple


ALLOWED_KEYWORDS = {"MUST", "MUST NOT", "SHOULD", "SHOULD NOT", "MAY"}


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def file_exists_and_size(path: Path, min_bytes: int = 1) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size >= min_bytes
    except Exception:
        return False


def plausible_rfc_text(text: str, rfc_number: str) -> bool:
    if not text:
        return False
    # Basic plausibility checks for official RFC plaintexts
    # Check contains RFC number and phrases typical of RFC Editor/IETF headers
    number_ok = (f"RFC {rfc_number}" in text) or (f"RFC{rfc_number}" in text)
    header_ok = ("Request for Comments" in text) or ("RFC Editor" in text) or ("Internet Engineering Task Force" in text)
    # Also require some length
    long_enough = len(text) > 10000
    return number_ok and header_ok and long_enough


def parse_simple_ini(text: str) -> Dict[str, str]:
    """
    Parse a very simple INI-like configuration into a flat dict of "section.key" -> value (string).
    Assumes lines in form [section] or key = value within a section.
    """
    result: Dict[str, str] = {}
    if text is None:
        return result
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" in line and section:
            k, v = line.split("=", 1)
            key = k.strip()
            val = v.strip()
            result[f"{section}.{key}"] = val
    return result


def normalize_value(val: Optional[str]) -> str:
    if val is None:
        return ""
    v = val.strip()
    # Remove surrounding quotes if present
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    # For arrays, remove all spaces
    if v.startswith("[") and v.endswith("]"):
        # remove spaces
        v = "[" + "".join([c for c in v[1:-1] if not c.isspace()]) + "]"
        return v
    # For booleans, normalize lowercase
    if v.lower() in ("true", "false"):
        return v.lower()
    return v


def parse_baseline_yaml_simple(path: Path) -> Optional[List[Dict]]:
    """
    Parse the specific structure of input/anon_baseline.yaml using a simple state machine.
    Only supports the format present in the provided file.
    """
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    rules: List[Dict] = []
    current: Optional[Dict] = None
    in_set = False
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # start of rules list is ignored
        if stripped == "rules:":
            continue
        # new rule
        if stripped.startswith("- id:"):
            # Finish previous
            if current:
                rules.append(current)
            rid = stripped.split(":", 1)[1].strip()
            current = {"id": rid, "triggers": [], "set": {}}
            in_set = False
            continue
        if current is None:
            continue
        if stripped.startswith("triggers:"):
            # Expect a bracketed list: ["a", "b", "c"]
            after = stripped.split(":", 1)[1].strip()
            arr = []
            if after.startswith("[") and after.endswith("]"):
                content = after[1:-1]
                parts = content.split(",")
                for p in parts:
                    token = p.strip()
                    if token.startswith('"') and token.endswith('"'):
                        token = token[1:-1]
                    elif token.startswith("'") and token.endswith("'"):
                        token = token[1:-1]
                    arr.append(token)
            current["triggers"] = arr
            in_set = False
            continue
        if stripped.startswith("set:"):
            in_set = True
            continue
        if in_set:
            # Parse indented key: value with potential quotes
            # Expect format like: dhcp.send_hostname: "false"
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                key = k.strip()
                val = v.strip()
                # Remove trailing comments
                if "#" in val:
                    val = val.split("#", 1)[0].strip()
                # We keep value as string, but strip outer quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val_unquoted = val[1:-1]
                else:
                    val_unquoted = val
                current["set"][key] = val_unquoted
            continue
        # Ignore other keys
    if current:
        rules.append(current)
    return rules


def compute_triggers_from_requirements(requirements: List[Dict], rules: List[Dict]) -> Tuple[Dict[str, bool], Dict[str, List[str]]]:
    """
    Determine which rules are triggered based on requirements text.
    Returns:
      - dict: rule_id -> triggered boolean
      - dict: rule_id -> list of matched trigger terms
    """
    text_blobs = []
    for item in requirements:
        t = item.get("text", "")
        if isinstance(t, str):
            text_blobs.append(t.lower())
    joined = "\n".join(text_blobs)
    triggered: Dict[str, bool] = {}
    matched_terms: Dict[str, List[str]] = {}
    for rule in rules:
        rid = rule.get("id")
        terms = rule.get("triggers", []) or []
        hits = []
        for term in terms:
            if term and term.lower() in joined:
                hits.append(term)
        triggered[rid] = len(hits) > 0
        matched_terms[rid] = hits
    return triggered, matched_terms


def apply_rules_to_config(base_cfg: Dict[str, str], rules: List[Dict], triggered: Dict[str, bool]) -> Dict[str, str]:
    """
    Apply rule 'set' values to base config for triggered rules.
    Returns a new dict with modifications.
    """
    result = dict(base_cfg)
    for rule in rules:
        rid = rule.get("id")
        if not triggered.get(rid, False):
            continue
        settings = rule.get("set", {}) or {}
        for full_key, target in settings.items():
            # full_key like "dhcp.send_hostname"
            if "." in full_key:
                section, key = full_key.split(".", 1)
                flat_key = f"{section}.{key}"
            else:
                flat_key = full_key
            result[flat_key] = target.strip()
    return result


def compute_expected_changes(base_cfg: Dict[str, str], result_cfg: Dict[str, str]) -> Dict[str, Tuple[str, str]]:
    changes: Dict[str, Tuple[str, str]] = {}
    keys = set(base_cfg.keys()).union(set(result_cfg.keys()))
    for k in keys:
        before = base_cfg.get(k)
        after = result_cfg.get(k)
        if before is None or after is None:
            # new keys shouldn't happen but treat as change
            if before != after:
                changes[k] = (before or "", after or "")
        else:
            if normalize_value(before) != normalize_value(after):
                changes[k] = (before, after)
    return changes


def parse_mitigation_catalog(path: Path) -> Optional[List[Dict]]:
    rows = read_csv_dicts(path)
    if rows is None:
        return None
    # Coerce scores to ints
    out = []
    for r in rows:
        try:
            r2 = dict(r)
            r2["impact_score"] = int(r2.get("impact_score", "0"))
            r2["effort_score"] = int(r2.get("effort_score", "0"))
            out.append(r2)
        except Exception:
            return None
    return out


def compute_observed_triggers(requirements: List[Dict], rules: List[Dict]) -> List[str]:
    triggered, _ = compute_triggers_from_requirements(requirements, rules)
    observed = []
    for rule in rules:
        rid = rule.get("id")
        if triggered.get(rid, False):
            for t in rule.get("triggers", []) or []:
                observed.append(t)
    # unique lowercased, trimmed
    seen = set()
    canonical = []
    for t in observed:
        lc = t.strip().lower()
        if lc and lc not in seen:
            seen.add(lc)
            canonical.append(lc)
    return canonical


def filter_and_rank_mitigations(rows: List[Dict], observed_triggers: List[str]) -> List[Dict]:
    trigset = set([t.strip().lower() for t in observed_triggers if t is not None])
    filtered = []
    for r in rows:
        kw_field = r.get("keywords", "") or ""
        parts = [p.strip().lower() for p in kw_field.split(";")]
        if any(p in trigset for p in parts):
            # Compute priority = (impact_score * 2) - effort_score
            try:
                priority = (int(r["impact_score"]) * 2) - int(r["effort_score"])
            except Exception:
                priority = 0
            r2 = dict(r)
            r2["priority"] = priority
            filtered.append(r2)
    # Sort by priority desc, then impact_score desc
    filtered.sort(key=lambda x: (x.get("priority", 0), x.get("impact_score", 0)), reverse=True)
    return filtered[:10]


def parse_requirements_json_structure(data) -> Tuple[bool, List[Dict], Dict[Tuple[str, str], int]]:
    """
    Validate structure and aggregate counts.
    Returns:
      - valid flag
      - list of entries
      - aggregation dict keyed by (rfc, keyword) -> count
    """
    if not isinstance(data, list):
        return False, [], {}
    ok = True
    agg: Dict[Tuple[str, str], int] = {}
    cleaned: List[Dict] = []
    for item in data:
        if not isinstance(item, dict):
            ok = False
            break
        rfc = item.get("rfc")
        section = item.get("section", None)
        keyword = item.get("keyword")
        text = item.get("text")
        if not isinstance(rfc, str):
            ok = False
            break
        if not (rfc in ("RFC7844", "RFC7258")):
            # allow only expected two RFCs
            ok = False
            break
        if section is not None and not isinstance(section, str):
            ok = False
            break
        if not isinstance(keyword, str) or keyword not in ALLOWED_KEYWORDS:
            ok = False
            break
        if not isinstance(text, str) or not text.strip():
            ok = False
            break
        key = (rfc, keyword)
        agg[key] = agg.get(key, 0) + 1
        cleaned.append(item)
    return ok, cleaned, agg


def load_requirements_summary_csv(path: Path) -> Tuple[bool, Dict[Tuple[str, str], int]]:
    rows = read_csv_dicts(path)
    if rows is None:
        return False, {}
    # Check header columns
    # DictReader uses first row as header; we ensure keys are rfc, keyword, count
    expected_cols = {"rfc", "keyword", "count"}
    if set(rows[0].keys()) != expected_cols:
        # Some CSVs might reorder; accept if at least contains expected
        if not expected_cols.issubset(set(rows[0].keys())):
            return False, {}
    agg: Dict[Tuple[str, str], int] = {}
    for r in rows:
        rfc = r.get("rfc")
        kw = r.get("keyword")
        cnt_str = r.get("count")
        try:
            cnt = int(cnt_str)
        except Exception:
            return False, {}
        agg[(rfc, kw)] = agg.get((rfc, kw), 0) + cnt
    return True, agg


def recompute_unified_diff(a_text: str, b_text: str, a_name: str, b_name: str) -> str:
    a_lines = a_text.splitlines(keepends=True)
    b_lines = b_text.splitlines(keepends=True)
    diff = difflib.unified_diff(a_lines, b_lines, fromfile=a_name, tofile=b_name, lineterm="")
    return "\n".join(diff)


def validate_diff_contains_changes(diff_text: str) -> bool:
    if not diff_text:
        return False
    # Basic unified diff markers
    has_header = ("--- " in diff_text) and ("+++ " in diff_text)
    has_hunks = "@@" in diff_text
    has_change_lines = any(line.startswith(("+", "-")) and not line.startswith(("+++", "---")) for line in diff_text.splitlines())
    return has_change_lines and (has_header or has_hunks)


def extract_section_lines(text: str, heading: str) -> List[str]:
    """
    Extract lines under a section heading until the next heading or blank line separation.
    Very simple heuristic.
    """
    if text is None:
        return []
    lines = text.splitlines()
    start_idx = None
    heading_lower = heading.lower()
    for i, line in enumerate(lines):
        if heading_lower in line.strip().lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    collected = []
    for j in range(start_idx, len(lines)):
        line = lines[j]
        # Stop at next heading-like line
        if j > start_idx and (lines[j].strip().startswith("#") or lines[j].strip().lower().startswith("##") or lines[j].strip().lower().startswith("top mitigations") or lines[j].strip().lower().startswith("config changes") or lines[j].strip().lower().startswith("action items")):
            break
        collected.append(line)
    return collected


def count_bullets(lines: List[str]) -> int:
    count = 0
    for line in lines:
        s = line.strip()
        if s.startswith("- ") or s.startswith("* ") or s.startswith("•"):
            count += 1
    return count


def contains_no_urls(text: str) -> bool:
    if text is None:
        return False
    url_patterns = [r"http://", r"https://", r"www\."]
    for p in url_patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path or ".")
    scores: Dict[str, float] = {
        "rfc7844_text_plausible": 0.0,
        "rfc7258_text_plausible": 0.0,
        "requirements_json_structure": 0.0,
        "requirements_summary_consistency": 0.0,
        "endpoint_config_changes_applied": 0.0,
        "endpoint_diff_unified_present": 0.0,
        "mitigation_ranked_correct": 0.0,
        "briefing_notes_executive_summary": 0.0,
        "briefing_notes_top_mitigations": 0.0,
        "briefing_notes_config_changes": 0.0,
        "briefing_notes_action_items": 0.0,
        "deliverables_all_present": 0.0,
    }

    # Paths
    p_rfc7844 = workspace / "downloaded" / "rfc7844.txt"
    p_rfc7258 = workspace / "downloaded" / "rfc7258.txt"
    p_req_json = workspace / "output" / "requirements.json"
    p_req_summary = workspace / "output" / "requirements_summary.csv"
    p_base_conf = workspace / "config" / "endpoint.conf"
    p_out_conf = workspace / "output" / "endpoint.conf"
    p_out_diff = workspace / "output" / "endpoint.conf.diff"
    p_baseline_yaml = workspace / "input" / "anon_baseline.yaml"
    p_mitigation_catalog = workspace / "input" / "mitigation_catalog.csv"
    p_mitigation_ranked = workspace / "output" / "mitigation_ranked.csv"
    p_briefing_notes = workspace / "output" / "briefing_notes.md"

    # Deliverables presence
    deliverables = [
        p_rfc7844,
        p_rfc7258,
        p_req_json,
        p_req_summary,
        p_out_conf,
        p_out_diff,
        p_mitigation_ranked,
        p_briefing_notes,
    ]
    if all(file_exists_and_size(p, 1) for p in deliverables):
        scores["deliverables_all_present"] = 1.0
    else:
        scores["deliverables_all_present"] = 0.0

    # RFC plausibility
    t7844 = read_text(p_rfc7844) if p_rfc7844.exists() else None
    t7258 = read_text(p_rfc7258) if p_rfc7258.exists() else None
    scores["rfc7844_text_plausible"] = 1.0 if (t7844 is not None and plausible_rfc_text(t7844, "7844")) else 0.0
    scores["rfc7258_text_plausible"] = 1.0 if (t7258 is not None and plausible_rfc_text(t7258, "7258")) else 0.0

    # Requirements JSON structure and summary consistency
    req_data = load_json(p_req_json)
    json_ok = False
    agg_counts: Dict[Tuple[str, str], int] = {}
    entries: List[Dict] = []
    if req_data is not None:
        json_ok, entries, agg_counts = parse_requirements_json_structure(req_data)
    scores["requirements_json_structure"] = 1.0 if json_ok else 0.0

    # Summary CSV
    summary_ok = False
    if json_ok and p_req_summary.exists():
        csv_ok, csv_agg = load_requirements_summary_csv(p_req_summary)
        if csv_ok:
            # Compare aggregation equals
            # csv_agg may sum counts across rows with same (rfc, keyword)
            # The keys must match exactly agg_counts and values equal
            if csv_agg == agg_counts:
                summary_ok = True
    scores["requirements_summary_consistency"] = 1.0 if summary_ok else 0.0

    # Endpoint config changes applied
    base_conf_text = read_text(p_base_conf) if p_base_conf.exists() else None
    out_conf_text = read_text(p_out_conf) if p_out_conf.exists() else None
    endpoint_ok = False
    if base_conf_text is not None and out_conf_text is not None:
        base_cfg = parse_simple_ini(base_conf_text)
        out_cfg = parse_simple_ini(out_conf_text)
        rules = parse_baseline_yaml_simple(p_baseline_yaml) or []
        # Compute triggers from requirements
        if isinstance(entries, list):
            requirements_entries = entries
        else:
            requirements_entries = []
        triggered, _ = compute_triggers_from_requirements(requirements_entries, rules)
        # Compute expected out config by applying triggers to base
        expected_out_cfg = apply_rules_to_config(base_cfg, rules, triggered)
        # Validate that out_cfg matches expected_out_cfg for changed keys and preserves others
        # Compare all keys for equality on normalized values
        keys_union = set(base_cfg.keys()).union(set(expected_out_cfg.keys()))
        all_match = True
        for k in keys_union:
            expected_val = expected_out_cfg.get(k)
            actual_val = out_cfg.get(k)
            if expected_val is None:
                expected_norm = ""
            else:
                expected_norm = normalize_value(expected_val)
            actual_norm = normalize_value(actual_val) if actual_val is not None else ""
            # If key existed in base but not in expected_out_cfg (i.e., unchanged), expected is base value
            if k not in expected_out_cfg and k in base_cfg:
                expected_norm = normalize_value(base_cfg.get(k))
            if expected_norm != actual_norm:
                all_match = False
                break
        endpoint_ok = all_match
    scores["endpoint_config_changes_applied"] = 1.0 if endpoint_ok else 0.0

    # Endpoint diff unified present
    diff_ok = False
    if p_out_diff.exists() and base_conf_text is not None and out_conf_text is not None:
        diff_text = read_text(p_out_diff) or ""
        # Validate diff structure and that it reflects changes (or lack). If no changes, diff may be empty.
        # Compute expected changes
        base_cfg_map = parse_simple_ini(base_conf_text)
        out_cfg_map = parse_simple_ini(out_conf_text)
        changes = compute_expected_changes(base_cfg_map, out_cfg_map)
        if changes:
            # Expect a diff with markers
            diff_ok = validate_diff_contains_changes(diff_text)
        else:
            # No changes expected: diff may be empty but "clearly shows the changes" implies none; accept empty or a valid diff with no +/-?
            diff_ok = diff_text.strip() == "" or validate_diff_contains_changes(diff_text)
    scores["endpoint_diff_unified_present"] = 1.0 if diff_ok else 0.0

    # Mitigation ranked correctness
    ranked_ok = False
    ranked_rows = read_csv_dicts(p_mitigation_ranked) if p_mitigation_ranked.exists() else None
    catalog_rows = parse_mitigation_catalog(p_mitigation_catalog) if p_mitigation_catalog.exists() else None
    if ranked_rows is not None and catalog_rows is not None and json_ok and p_baseline_yaml.exists():
        rules = parse_baseline_yaml_simple(p_baseline_yaml) or []
        observed_triggers = compute_observed_triggers(entries, rules)
        expected = filter_and_rank_mitigations(catalog_rows, observed_triggers)
        # Compare only columns of interest: id, title, category, impact_score, effort_score, priority, keywords
        def normalize_rank_rows(rows: List[Dict]) -> List[Dict]:
            out = []
            for r in rows:
                try:
                    out.append({
                        "id": str(r.get("id", "")),
                        "title": str(r.get("title", "")),
                        "category": str(r.get("category", "")),
                        "impact_score": int(r.get("impact_score", 0)),
                        "effort_score": int(r.get("effort_score", 0)),
                        "priority": int(r.get("priority", 0)),
                        "keywords": str(r.get("keywords", "")),
                    })
                except Exception:
                    return []
            return out

        expected_norm = normalize_rank_rows(expected)
        actual_norm = normalize_rank_rows(ranked_rows)
        # Check top N are equal in order and fields
        if len(actual_norm) == len(expected_norm):
            order_match = True
            for i in range(len(expected_norm)):
                if actual_norm[i] != expected_norm[i]:
                    order_match = False
                    break
            ranked_ok = order_match
        else:
            ranked_ok = False
    scores["mitigation_ranked_correct"] = 1.0 if ranked_ok else 0.0

    # Briefing notes checks
    notes_text = read_text(p_briefing_notes) if p_briefing_notes.exists() else None
    # Executive summary: 3–5 bullets referencing two RFCs and themes
    exec_ok = False
    if notes_text is not None and len(notes_text) > 0:
        exec_lines = extract_section_lines(notes_text, "Executive summary")
        bullets = count_bullets(exec_lines)
        references_rfc = ("RFC 7844" in notes_text or "RFC7844" in notes_text) and ("RFC 7258" in notes_text or "RFC7258" in notes_text)
        exec_ok = (bullets >= 3 and bullets <= 5) and references_rfc
    scores["briefing_notes_executive_summary"] = 1.0 if exec_ok else 0.0

    # Top mitigations: concise list of top 5 items from mitigation_ranked.csv with priority scores
    top_mit_ok = False
    if notes_text is not None and ranked_rows is not None:
        # Use expected ranking computed above when available; else derive from file
        if catalog_rows is not None and json_ok and p_baseline_yaml.exists():
            rules = parse_baseline_yaml_simple(p_baseline_yaml) or []
            observed_triggers = compute_observed_triggers(entries, rules)
            expected_top = filter_and_rank_mitigations(catalog_rows, observed_triggers)[:5]
        else:
            # Fall back to top 5 from the provided ranked file
            # Ensure 'priority' is parseable integer
            expected_top = []
            for r in ranked_rows[:5]:
                try:
                    r2 = dict(r)
                    r2["priority"] = int(r2.get("priority", 0))
                    expected_top.append(r2)
                except Exception:
                    pass
        # Check that each of top 5 appears in notes with priority value
        present_all = True
        for r in expected_top:
            rid = str(r.get("id", ""))
            prio = r.get("priority", None)
            if rid and (rid in notes_text):
                # find a number occurrence of priority near the item; we just check priority number somewhere
                if prio is None:
                    present_all = False
                    break
                # Ensure the priority integer appears as substring
                if str(prio) not in notes_text:
                    present_all = False
                    break
            else:
                present_all = False
                break
        top_mit_ok = present_all
    scores["briefing_notes_top_mitigations"] = 1.0 if top_mit_ok else 0.0

    # Config changes applied: enumerate each changed key (before → after) and the baseline rule id
    cfg_changes_ok = False
    if notes_text is not None and base_conf_text is not None and out_conf_text is not None and p_baseline_yaml.exists():
        base_cfg_map = parse_simple_ini(base_conf_text)
        out_cfg_map = parse_simple_ini(out_conf_text)
        changes = compute_expected_changes(base_cfg_map, out_cfg_map)
        if changes:
            # Ensure for each changed key we can find a line with "key" and an arrow and a rule id that maps to that key
            rules = parse_baseline_yaml_simple(p_baseline_yaml) or []
            key_to_rule_ids: Dict[str, List[str]] = {}
            for rule in rules:
                rid = rule.get("id")
                for fk in (rule.get("set", {}) or {}).keys():
                    key_to_rule_ids.setdefault(fk, []).append(rid)
            all_found = True
            for flat_key, (before, after) in changes.items():
                # The notes should contain 'before -> after' or 'before → after' with the key and rule id
                key_name = flat_key.split(".", 1)[1] if "." in flat_key else flat_key
                # Prepare patterns
                before_norm = normalize_value(before)
                after_norm = normalize_value(after)
                arrow_found = False
                # Look for a line containing the key and arrow
                for line in notes_text.splitlines():
                    if key_name in line and ("->" in line or "→" in line):
                        # check that before or after values appear somewhere in the line (best-effort)
                        if (before_norm and before_norm in line) or (after_norm and after_norm in line) or (normalize_value(key_name) in line):
                            # Also require a rule id from baseline present in the line
                            # Determine candidate rule ids for this key
                            fk1 = flat_key
                            fk2 = flat_key.lower()
                            candidate_ids = key_to_rule_ids.get(fk1, []) + key_to_rule_ids.get(fk2, [])
                            if not candidate_ids:
                                # try matching by suffix key only
                                for fk, ids in key_to_rule_ids.items():
                                    if fk.endswith("." + key_name):
                                        candidate_ids.extend(ids)
                            if any(rid in line for rid in candidate_ids):
                                arrow_found = True
                                break
                if not arrow_found:
                    all_found = False
                    break
            cfg_changes_ok = all_found
        else:
            # If no changes expected, ensure notes mention no changes or section present but empty; accept true if present section exists
            cfg_section = extract_section_lines(notes_text, "Config changes applied")
            cfg_changes_ok = True if cfg_section is not None else False
    scores["briefing_notes_config_changes"] = 1.0 if cfg_changes_ok else 0.0

    # Action items: at least 5 clear, assignable items with Owner and Due fields
    action_ok = False
    if notes_text is not None:
        lines = [ln for ln in notes_text.splitlines() if ln.strip()]
        count_items = 0
        for ln in lines:
            if "Owner: SecurityOps" in ln and "Due: Next sprint" in ln:
                count_items += 1
        # Ensure at least 5 such items and no URLs in deliverables
        action_ok = count_items >= 5 and contains_no_urls(notes_text)
    scores["briefing_notes_action_items"] = 1.0 if action_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()