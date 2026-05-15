import json
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path


BASELINE_MODULE_ORDER = [
    "sourcing_standards",
    "material_testing",
    "packaging_labeling",
    "traceability",
    "wrapup_assessment",
]

BASELINE_TITLES = {
    "sourcing_standards": "Sourcing Standards & Certifications",
    "material_testing": "Material Testing & Safety",
    "packaging_labeling": "Packaging, Labeling, and Claims",
    "traceability": "Traceability & Record-Keeping",
    "wrapup_assessment": "Wrap-up & Assessment",
}

# Baseline "OLD" durations from the provided initial input
BASELINE_OLD_DURATIONS = {
    "sourcing_standards": 70,
    "material_testing": 65,
    "packaging_labeling": 60,
    "traceability": 45,
    "wrapup_assessment": 25,
}


def _safe_load_json(path: Path):
    try:
        if not path.exists():
            return None, "missing"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def _read_text(path: Path):
    try:
        if not path.exists():
            return None, "missing"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _last_non_empty_line(lines):
    for line in reversed(lines):
        if line.strip():
            return line.rstrip("\n")
    return ""


def _find_section_indices(lines, headers):
    indices = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for h in headers:
            if stripped.lower().startswith(h.lower()):
                if h not in indices:
                    indices[h] = idx
    return indices


def _get_section_content(lines, header_indices, headers, header):
    if header not in header_indices:
        return []
    start = header_indices[header] + 1
    subsequent = [header_indices[h] for h in headers if h in header_indices and header_indices[h] > header_indices[header]]
    end = min(subsequent) if subsequent else len(lines)
    return [l.rstrip("\n") for l in lines[start:end]]


def _parse_module_block(lines, header_line):
    try:
        idx = lines.index(header_line)
    except ValueError:
        return []
    block = []
    for i in range(idx + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        block.append(lines[i])
    return [l.rstrip("\n") for l in block]


def _extract_ints_from_arrow(line):
    m = re.search(r"(\d+)\s*->\s*(\d+)", line)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _iso_date_in_line(line):
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", line)
    return m.group(1) if m else None


def _line_has_owner_indicator(line):
    role_keywords = [
        "Lead",
        "Coordinator",
        "Assistant",
        "Manager",
        "Supervisor",
        "Director",
        "Owner",
        "Engineer",
        "Specialist",
        "Officer",
        "Analyst",
        "Associate",
    ]
    if "owner" in line.lower():
        return True
    for kw in role_keywords:
        if kw in line:
            return True
    # Parenthesized role hint
    if re.search(r"\([A-Za-z][A-Za-z ,&/-]*\)", line):
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_total_matches_target": 0.0,
        "config_learning_outcomes_added": 0.0,
        "config_durations_within_ranges_and_total": 0.0,
        "config_order_and_titles_preserved_with_lo": 0.0,
        "syllabus_headers_and_total_line": 0.0,
        "syllabus_topics_match_config_with_lo": 0.0,
        "syllabus_learning_outcomes_match_config": 0.0,
        "syllabus_materials_checklists_match": 0.0,
        "validation_json_fields_and_values_correct": 0.0,
        "generator_updated_keywords_present": 0.0,
        "meeting_notes_sections_and_workshop_info": 0.0,
        "meeting_notes_duration_adjustments_correct": 0.0,
        "meeting_notes_risks_and_mitigations_min2": 0.0,
        "meeting_notes_action_items_offsets_and_roles": 0.0,
        "meeting_notes_next_steps_bullets": 0.0,
    }

    cfg_path = workspace / "input" / "qc_training_config.json"
    cfg, cfg_err = _safe_load_json(cfg_path)
    if not isinstance(cfg, dict):
        return scores

    title = cfg.get("title")
    workshop_date = cfg.get("workshop_date")
    target_total = cfg.get("target_total_minutes")
    modules = cfg.get("modules", [])
    if not isinstance(modules, list):
        modules = []

    # Compute totals and range validity
    total = 0
    within_ranges = True
    for m in modules:
        try:
            dur = int(m.get("duration_minutes"))
            mn = int(m.get("min_minutes"))
            mx = int(m.get("max_minutes"))
        except Exception:
            within_ranges = False
            break
        if not (mn <= dur <= mx):
            within_ranges = False
            break
        total += dur

    # Check total matches target exactly
    if isinstance(target_total, int) and total == target_total == 240:
        scores["config_total_matches_target"] = 1.0

    # Learning outcomes added to every module (at least two concise strings)
    los_ok = True
    for m in modules:
        los = m.get("learning_outcomes")
        if not isinstance(los, list) or len(los) < 2:
            los_ok = False
            break
        for s in los:
            if not isinstance(s, str) or not s.strip():
                los_ok = False
                break
        if not los_ok:
            break
    if los_ok and modules:
        scores["config_learning_outcomes_added"] = 1.0

    # Durations within ranges AND total match (avoid awarding for baseline that already fits ranges)
    if within_ranges and scores["config_total_matches_target"] == 1.0:
        scores["config_durations_within_ranges_and_total"] = 1.0

    # Order and titles preserved, awarded only if learning outcomes added (to avoid baseline credit)
    order_ok = [m.get("id") for m in modules] == BASELINE_MODULE_ORDER
    titles_ok = all((m.get("title") == BASELINE_TITLES.get(m.get("id"))) for m in modules)
    if order_ok and titles_ok and scores["config_learning_outcomes_added"] == 1.0:
        scores["config_order_and_titles_preserved_with_lo"] = 1.0

    # Load materials_checklists.json for later validations
    checklists_path = workspace / "input" / "materials_checklists.json"
    checklists, _ = _safe_load_json(checklists_path)
    if not isinstance(checklists, dict):
        checklists = {}

    # Validate output/syllabus.md
    syllabus_path = workspace / "output" / "syllabus.md"
    syllabus_text, _ = _read_text(syllabus_path)
    if isinstance(syllabus_text, str):
        lines = [l.rstrip("\n") for l in syllabus_text.splitlines()]
        # Headers and final total line
        headers_ok = False
        if lines and title:
            header_expected = f"# {title}"
            date_expected = f"Date: {workshop_date}" if workshop_date else None
            if lines[0].strip() == header_expected and (date_expected is None or any(l.strip() == date_expected for l in lines[0:5])):
                # Ensure each module header line exists
                mod_headers_present = True
                module_blocks = {}
                for idx, m in enumerate(modules, start=1):
                    h = f"## {idx}. {m.get('title')} ({m.get('duration_minutes')} min)"
                    if h not in lines:
                        mod_headers_present = False
                        break
                    block = _parse_module_block(lines, h)
                    module_blocks[m.get("id")] = block
                last_line = _last_non_empty_line(lines)
                if mod_headers_present and last_line == f"Total time: {total} minutes":
                    # ensure LO section is present for every module to avoid baseline pass
                    lo_sections_present = all("Learning Outcomes:" in module_blocks.get(m.get("id"), []) for m in modules)
                    if lo_sections_present:
                        headers_ok = True
                # Topics match config and Learning Outcomes exist
                topics_ok = True
                lo_ok_md = True
                mc_ok = True
                if mod_headers_present:
                    for m in modules:
                        mid = m.get("id")
                        block = module_blocks.get(mid, [])
                        # Topics
                        if "Topics:" not in block:
                            topics_ok = False
                            break
                        idx_topics = block.index("Topics:")
                        topic_lines = []
                        for i in range(idx_topics + 1, len(block)):
                            if not block[i].strip():
                                break
                            # If next section header (word ending with colon), stop
                            if re.match(r"^[A-Za-z].*:$", block[i]):
                                break
                            if block[i].startswith("- "):
                                topic_lines.append(block[i][2:].strip())
                            else:
                                break
                        expected_topics = m.get("topics", [])
                        # Require all expected topics present (order-insensitive)
                        if len(topic_lines) < len(expected_topics) or any(t not in topic_lines for t in expected_topics):
                            topics_ok = False
                            break
                        # Learning Outcomes
                        if "Learning Outcomes:" not in block:
                            lo_ok_md = False
                            break
                        idx_lo = block.index("Learning Outcomes:")
                        lo_lines = []
                        for i in range(idx_lo + 1, len(block)):
                            if not block[i].strip():
                                break
                            if re.match(r"^[A-Za-z].*:$", block[i]):
                                break
                            if block[i].startswith("- "):
                                lo_lines.append(block[i][2:].strip())
                            else:
                                break
                        cfg_los = m.get("learning_outcomes")
                        if not isinstance(cfg_los, list) or len(cfg_los) < 2:
                            lo_ok_md = False
                            break
                        # Require all config LOs present in syllabus (order-insensitive exact string match)
                        if len(lo_lines) < len(cfg_los) or any(x not in lo_lines for x in cfg_los):
                            lo_ok_md = False
                            break
                        # Materials Checklist
                        if "Materials Checklist:" not in block:
                            mc_ok = False
                            break
                        idx_mc = block.index("Materials Checklist:")
                        mc_lines = []
                        for i in range(idx_mc + 1, len(block)):
                            if not block[i].strip():
                                break
                            if re.match(r"^[A-Za-z].*:$", block[i]):
                                break
                            # capture lines as they are
                            mc_lines.append(block[i].strip())
                        if mid in checklists and isinstance(checklists[mid], list):
                            # Expect bullet list items
                            items = [l[2:].strip() for l in mc_lines if l.startswith("- ")]
                            expected = checklists[mid]
                            if len(items) < len(expected) or any(it not in items for it in expected):
                                mc_ok = False
                                break
                        else:
                            # expect "No checklist available."
                            if not any("No checklist available." in l for l in mc_lines):
                                mc_ok = False
                                break
                if headers_ok:
                    scores["syllabus_headers_and_total_line"] = 1.0
                # Only award topics if learning outcomes sections are present to avoid baseline credit
                if topics_ok and headers_ok:
                    scores["syllabus_topics_match_config_with_lo"] = 1.0
                if lo_ok_md and headers_ok:
                    scores["syllabus_learning_outcomes_match_config"] = 1.0
                if mc_ok and headers_ok:
                    scores["syllabus_materials_checklists_match"] = 1.0

    # Validate output/validation.json
    validation_path = workspace / "output" / "validation.json"
    validation, _ = _safe_load_json(validation_path)
    if isinstance(validation, dict):
        try:
            fields_present = all(k in validation for k in [
                "target_total_minutes",
                "computed_total_minutes",
                "per_module_minutes",
                "durations_within_range",
                "matches_target_total",
                "missing_checklists",
            ])
            values_ok = True
            if not fields_present:
                values_ok = False
            else:
                if validation.get("target_total_minutes") != target_total:
                    values_ok = False
                if validation.get("computed_total_minutes") != total:
                    values_ok = False
                pmm = validation.get("per_module_minutes")
                if not isinstance(pmm, dict):
                    values_ok = False
                else:
                    for m in modules:
                        if pmm.get(m.get("id")) != m.get("duration_minutes"):
                            values_ok = False
                            break
                # durations_within_range flag
                if bool(validation.get("durations_within_range")) != bool(within_ranges):
                    values_ok = False
                # matches_target_total flag
                if bool(validation.get("matches_target_total")) != bool(total == target_total):
                    values_ok = False
                # missing_checklists: module ids with no checklist
                expected_missing = [m.get("id") for m in modules if m.get("id") not in checklists]
                if validation.get("missing_checklists") != expected_missing:
                    values_ok = False
            if fields_present and values_ok:
                scores["validation_json_fields_and_values_correct"] = 1.0
        except Exception:
            pass

    # Generator updated keywords present
    gen_path = workspace / "tools" / "generate_syllabus.py"
    gen_text, _ = _read_text(gen_path)
    if isinstance(gen_text, str):
        required_snippets = [
            "Learning Outcomes",
            "Materials Checklist",
            "validation.json",
            "Total time:",
            "missing_checklists",
        ]
        if all(s in gen_text for s in required_snippets):
            scores["generator_updated_keywords_present"] = 1.0

    # Meeting notes validations
    mn_path = workspace / "output" / "meeting_notes.md"
    mn_text, _ = _read_text(mn_path)
    if isinstance(mn_text, str):
        mn_lines = [l.rstrip("\n") for l in mn_text.splitlines()]
        headers = [
            "Workshop:",
            "Duration Adjustments:",
            "Risks and Mitigations:",
            "Action Items:",
            "Next Steps:",
        ]
        idxs = _find_section_indices(mn_lines, headers)

        # Sections order and workshop info
        sections_ok = False
        if all(h in idxs for h in headers):
            order_positions = [idxs[h] for h in headers]
            if all(x < y for x, y in zip(order_positions, order_positions[1:])):
                # Check title and date appear in Workshop section content
                wk_content = _get_section_content(mn_lines, idxs, headers, "Workshop:")
                title_ok = any(title in l for l in wk_content) if title else False
                date_ok = any(str(workshop_date) in l for l in wk_content) if workshop_date else False
                if title_ok and date_ok:
                    sections_ok = True
        if sections_ok:
            scores["meeting_notes_sections_and_workshop_info"] = 1.0

        # Duration Adjustments correctness (each module id with OLD -> NEW)
        dur_adj_ok = False
        if "Duration Adjustments:" in idxs:
            content = _get_section_content(mn_lines, idxs, headers, "Duration Adjustments:")
            parsed = {}
            for line in content:
                if "->" in line:
                    found_id = None
                    for mid in BASELINE_MODULE_ORDER:
                        if mid in line:
                            found_id = mid
                            break
                    if found_id:
                        old_val, new_val = _extract_ints_from_arrow(line)
                        if old_val is not None and new_val is not None:
                            parsed[found_id] = (old_val, new_val)
            if set(parsed.keys()) == set(BASELINE_MODULE_ORDER):
                all_match = True
                for mid in BASELINE_MODULE_ORDER:
                    old_val, new_val = parsed[mid]
                    if old_val != BASELINE_OLD_DURATIONS[mid]:
                        all_match = False
                        break
                    new_cfg = None
                    for m in modules:
                        if m.get("id") == mid:
                            new_cfg = m.get("duration_minutes")
                            break
                    if new_cfg != new_val:
                        all_match = False
                        break
                dur_adj_ok = all_match
        if dur_adj_ok:
            scores["meeting_notes_duration_adjustments_correct"] = 1.0

        # Risks and Mitigations: at least two bullets
        risks_ok = False
        if "Risks and Mitigations:" in idxs:
            content = _get_section_content(mn_lines, idxs, headers, "Risks and Mitigations:")
            bullets = [l for l in content if l.strip().startswith("- ")]
            if len(bullets) >= 2:
                risks_ok = True
        if risks_ok:
            scores["meeting_notes_risks_and_mitigations_min2"] = 1.0

        # Action Items: at least three, with owner role and due_date offsets exactly (-2, -1, +3 days)
        ai_ok = False
        if "Action Items:" in idxs:
            content = _get_section_content(mn_lines, idxs, headers, "Action Items:")
            bullet_lines = [l for l in content if l.strip().startswith("- ")]
            items_with_dates = [(l, _iso_date_in_line(l)) for l in bullet_lines if _iso_date_in_line(l)]
            if len(items_with_dates) >= 3 and workshop_date:
                try:
                    ws_date = datetime.strptime(workshop_date, "%Y-%m-%d").date()
                    required_dates = {
                        (ws_date - timedelta(days=2)).isoformat(),
                        (ws_date - timedelta(days=1)).isoformat(),
                        (ws_date + timedelta(days=3)).isoformat(),
                    }
                    present_dates = {d for _, d in items_with_dates if d}
                    date_ok = required_dates.issubset(present_dates)
                    roles_ok = sum(1 for l, d in items_with_dates if _line_has_owner_indicator(l)) >= 3
                    if date_ok and roles_ok:
                        ai_ok = True
                except Exception:
                    ai_ok = False
        if ai_ok:
            scores["meeting_notes_action_items_offsets_and_roles"] = 1.0

        # Next Steps: one or two bullets
        ns_ok = False
        if "Next Steps:" in idxs:
            content = _get_section_content(mn_lines, idxs, headers, "Next Steps:")
            bullets = [l for l in content if l.strip().startswith("- ")]
            if 1 <= len(bullets) <= 2:
                ns_ok = True
        if ns_ok:
            scores["meeting_notes_next_steps_bullets"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()