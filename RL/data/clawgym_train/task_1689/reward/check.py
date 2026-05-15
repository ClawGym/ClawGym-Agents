import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple, Optional

# Resolve workspace root
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

# Build absolute paths
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Helper: read text file safely
def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

# Try to import PyYAML; if not available, use a minimal YAML parser
def try_load_yaml(text: str) -> Optional[Dict[str, Any]]:
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        # Fallback to minimal YAML parser (supports mappings and lists with indentation)
        try:
            return minimal_yaml_parse(text)
        except Exception:
            return None

def minimal_yaml_parse(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any, Optional[str]]] = [(-1, root, None)]
    for raw in lines:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#") or line.strip() in ("---", "..."):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")
        # Determine current parent based on indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- "):
            item_content = content[2:].strip()
            # Ensure parent is a list
            if isinstance(parent, dict):
                # If parent is dict expecting a value list, create default list under last key
                key = stack[-1][2]
                if key is None:
                    raise ValueError("List item without a parent key")
                if key not in parent or not isinstance(parent[key], list):
                    parent[key] = []
                parent = parent[key]
            if not isinstance(parent, list):
                # Convert current parent to list if needed
                raise ValueError("Invalid YAML structure near: " + content)
            # list item can be a mapping inline like "key: value" or a scalar
            if ":" in item_content:
                k, v = item_content.split(":", 1)
                k = k.strip()
                v = v.strip()
                node: Dict[str, Any] = {}
                if v != "":
                    node[k] = parse_yaml_scalar(v)
                    parent.append(node)
                    # Prepare for nested items under this mapping key
                    stack.append((indent, node, None))
                    # Next level is under this node with key k already set; if more items come, they will adjust
                else:
                    node[k] = {}
                    parent.append(node)
                    # Enter the new mapping for deeper nesting
                    stack.append((indent, node, k))
                # Mark we are inside a list item mapping
            else:
                # scalar list item
                parent.append(parse_yaml_scalar(item_content))
                # Enter this item if following lines are nested under it
                stack.append((indent, parent, None))
        else:
            if ":" not in content:
                # Bare value? Not supported in minimal parser
                raise ValueError("Unsupported YAML line: " + content)
            key, val = content.split(":", 1)
            key = key.strip()
            val = val.strip()
            if isinstance(parent, list):
                # Last element should be a dict to hold this key
                if not parent or not isinstance(parent[-1], dict):
                    parent.append({})
                parent[-1][key] = parse_yaml_scalar(val) if val != "" else {}
                # If nested structure follows, push stack for this key within that dict
                stack.append((indent, parent[-1], key if val == "" else None))
            elif isinstance(parent, dict):
                parent[key] = parse_yaml_scalar(val) if val != "" else {}
                stack.append((indent, parent, key if val == "" else None))
            else:
                raise ValueError("Invalid parent type in YAML parse")
    return root

def parse_yaml_scalar(val: str) -> Any:
    # Remove surrounding quotes if present
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1]
    # Try to cast to int/float/bool/null
    low = val.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", "~"):
        return None
    # Numeric detection
    try:
        if re.match(r"^-?\d+$", val):
            return int(val)
        if re.match(r"^-?\d+\.\d+$", val):
            return float(val)
    except Exception:
        pass
    return val

# Utility functions for checks
def has_required_keys(mapping: Dict[str, Any], key_path: List[str]) -> bool:
    cur: Any = mapping
    for k in key_path:
        if not isinstance(cur, dict) or k not in cur:
            return False
        cur = cur[k]
    return True

def get_nested(mapping: Dict[str, Any], key_path: List[str], default=None):
    cur: Any = mapping
    for k in key_path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def count_outcomes_with_requirements(outcomes: Any) -> Tuple[bool, int, int]:
    if not isinstance(outcomes, list):
        return (False, 0, 0)
    count = len(outcomes)
    valid_items = 0
    for item in outcomes:
        if isinstance(item, dict):
            measure = item.get("measure")
            timeline = item.get("timeline")
            has_digit = any(ch.isdigit() for ch in str(measure)) if measure is not None else False
            if has_digit and isinstance(timeline, str) and timeline.strip() != "":
                valid_items += 1
    return (True, count, valid_items)

def extract_sections(lines: List[str], section_titles: List[str]) -> Dict[str, Tuple[int, int]]:
    # Return a mapping of section title -> (start_idx, end_idx_exclusive)
    indices = {}
    title_indices = []
    for i, line in enumerate(lines):
        for title in section_titles:
            if title.lower() in line.strip().lower():
                indices[title] = i
                title_indices.append((i, title))
    title_indices.sort()
    sections = {}
    for idx, (start_i, title) in enumerate(title_indices):
        end_i = len(lines)
        if idx + 1 < len(title_indices):
            end_i = title_indices[idx + 1][0]
        sections[title] = (start_i, end_i)
    return sections

def count_questions_and_blocks(section_lines: List[str]) -> Tuple[int, Dict[int, Tuple[int, int]]]:
    # Count lines starting with 'Q:' and map each question block to its (start, end) within the section
    q_indices = [i for i, l in enumerate(section_lines) if l.strip().startswith("Q:")]
    blocks = {}
    for idx, q_i in enumerate(q_indices):
        end_i = len(section_lines)
        if idx + 1 < len(q_indices):
            end_i = q_indices[idx + 1]
        blocks[q_i] = (q_i, end_i)
    return (len(q_indices), blocks)

def block_contains_required_lines(section_lines: List[str], start: int, end: int) -> bool:
    block = section_lines[start:end]
    has_probe = any("Probe:" in l for l in block)
    has_green = any("Green signal:" in l for l in block)
    has_red = any("Red flag:" in l for l in block)
    return has_probe and has_green and has_red

def parse_percent_from_line(line: str) -> Optional[float]:
    m = re.search(r"(\d+(\.\d+)?)\s*%", line)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

# Initialize checks dict with default False
checks: Dict[str, bool] = {
    # Existence
    "exists_scorecard": False,
    "exists_interview_loop": False,
    "exists_question_bank": False,
    "exists_take_home": False,
    "exists_system_design": False,
    "exists_interviewer_scorecard": False,
    "exists_debrief_protocol": False,
    "exists_communications_templates": False,
    # YAML validity
    "yaml_valid_scorecard": False,
    "yaml_valid_interview_loop": False,
    "yaml_valid_interviewer_scorecard": False,
    # Scorecard content checks
    "scorecard_mission_statement_is_single_sentence": False,
    "scorecard_outcomes_count_valid": False,
    "scorecard_outcomes_have_measure_and_timeline": False,
    "scorecard_technical_must_have_two_with_level_evidence": False,
    "scorecard_behavioral_must_have_antipatterns": False,
    "scorecard_comp_band_has_dash": False,
    "scorecard_dealbreakers_no_subjective": False,
    # Interview loop checks
    "interview_loop_has_required_stages": False,
    "interview_loop_stage_fields_present": False,
    "interview_loop_system_design_applies_senior_plus": False,
    "interview_loop_timeline_present": False,
    # Question bank checks
    "question_bank_sections_present": False,
    "question_bank_two_questions_per_section": False,
    "question_bank_each_question_has_probe_green_red": False,
    # Take-home checks
    "take_home_has_required_sections": False,
    "take_home_rubric_sums_to_100": False,
    # System design checks
    "system_design_has_duration_structure_evaluation": False,
    # Interviewer scorecard checks
    "interviewer_scorecard_has_keys": False,
    "interviewer_scorecard_competency_scores_count": False,
    # Debrief protocol checks
    "debrief_protocol_has_required_phrases": False,
    # Communications templates checks
    "communications_templates_has_labels": False,
    # Rubric heuristics (informational, do not affect reward)
    "rubric_outcomes_have_measurable_terms": False,
    "rubric_platform_scope_referenced": False,
}

# Paths to expected deliverables
scorecard_path = os.path.join(output_dir, "scorecard.yaml")
interview_loop_path = os.path.join(output_dir, "interview_loop.yaml")
question_bank_path = os.path.join(output_dir, "question_bank.md")
take_home_path = os.path.join(output_dir, "assessments", "take_home.md")
system_design_path = os.path.join(output_dir, "assessments", "system_design.md")
interviewer_scorecard_path = os.path.join(output_dir, "evaluation", "interviewer_scorecard.yaml")
debrief_protocol_path = os.path.join(output_dir, "evaluation", "debrief_protocol.md")
communications_templates_path = os.path.join(output_dir, "communications", "templates.md")

# Existence checks
if os.path.isfile(scorecard_path):
    checks["exists_scorecard"] = True
if os.path.isfile(interview_loop_path):
    checks["exists_interview_loop"] = True
if os.path.isfile(question_bank_path):
    checks["exists_question_bank"] = True
if os.path.isfile(take_home_path):
    checks["exists_take_home"] = True
if os.path.isfile(system_design_path):
    checks["exists_system_design"] = True
if os.path.isfile(interviewer_scorecard_path):
    checks["exists_interviewer_scorecard"] = True
if os.path.isfile(debrief_protocol_path):
    checks["exists_debrief_protocol"] = True
if os.path.isfile(communications_templates_path):
    checks["exists_communications_templates"] = True

# Scorecard YAML checks
scorecard_data: Optional[Dict[str, Any]] = None
if checks["exists_scorecard"]:
    text = read_text(scorecard_path)
    if text is not None:
        data = try_load_yaml(text)
        if isinstance(data, dict):
            scorecard_data = data
            checks["yaml_valid_scorecard"] = True

        # Continue content checks using parsed data if available, else fallback by regex
        if scorecard_data and "scorecard" in scorecard_data and isinstance(scorecard_data["scorecard"], dict):
            sc = scorecard_data["scorecard"]
            # mission.statement single sentence
            mission = sc.get("mission", {})
            if isinstance(mission, dict):
                stmt = mission.get("statement")
                if isinstance(stmt, str):
                    # Single sentence: no newline and at most one period
                    if ("\n" not in stmt) and (stmt.count(".") <= 1):
                        checks["scorecard_mission_statement_is_single_sentence"] = True
            # outcomes length 3-5 and each has measure with digit and timeline
            outcomes = sc.get("outcomes")
            valid_outcomes, count, valid_items = count_outcomes_with_requirements(outcomes)
            if valid_outcomes and 3 <= count <= 5:
                checks["scorecard_outcomes_count_valid"] = True
            if valid_items == count and count > 0:
                checks["scorecard_outcomes_have_measure_and_timeline"] = True
            # competencies technical must_have >= 2 with name, level, evidence
            comp = sc.get("competencies", {})
            tech_ok = False
            if isinstance(comp, dict):
                tech = comp.get("technical", {})
                if isinstance(tech, dict):
                    must = tech.get("must_have")
                    if isinstance(must, list) and len(must) >= 2:
                        enough = 0
                        for itm in must:
                            if isinstance(itm, dict) and all(k in itm for k in ("name", "level", "evidence")):
                                enough += 1
                        if enough >= 2:
                            tech_ok = True
            checks["scorecard_technical_must_have_two_with_level_evidence"] = tech_ok
            # behavioral must_have each include anti_pattern
            beh_ok = False
            if isinstance(comp, dict):
                beh = comp.get("behavioral", {})
                if isinstance(beh, dict):
                    mustb = beh.get("must_have")
                    if isinstance(mustb, list) and len(mustb) > 0:
                        beh_ok = True
                        for itm in mustb:
                            if not (isinstance(itm, dict) and "anti_pattern" in itm and "definition" in itm and "name" in itm):
                                beh_ok = False
                                break
            checks["scorecard_behavioral_must_have_antipatterns"] = beh_ok
            # compensation band has dash
            compn = sc.get("compensation", {})
            band_ok = False
            if isinstance(compn, dict):
                band = compn.get("band")
                if isinstance(band, str) and "-" in band:
                    band_ok = True
            checks["scorecard_comp_band_has_dash"] = band_ok
            # deal_breakers no subjective
            deal_ok = False
            db = sc.get("deal_breakers")
            if isinstance(db, list) and len(db) > 0:
                bad = False
                for itm in db:
                    s = str(itm).lower()
                    if ("vibe" in s) or ("culture fit" in s) or ("gut" in s):
                        bad = True
                        break
                deal_ok = not bad
            checks["scorecard_dealbreakers_no_subjective"] = deal_ok

            # Rubric heuristics (informational)
            # outcomes measurable terms
            if isinstance(outcomes, list) and len(outcomes) > 0:
                measurable = 0
                for itm in outcomes:
                    if isinstance(itm, dict):
                        m = str(itm.get("measure", ""))
                        if any(ch.isdigit() for ch in m) or "%" in m:
                            measurable += 1
                if measurable == len(outcomes):
                    checks["rubric_outcomes_have_measurable_terms"] = True
                # platform scope referenced: check keywords in outcomes measures/outcome text
                keywords = ("CI/CD", "SLO", "uptime", "reliability", "MTTR", "deployment", "platform", "observability")
                found_kw = False
                for itm in outcomes:
                    if isinstance(itm, dict):
                        txt = (str(itm.get("outcome", "")) + " " + str(itm.get("measure", ""))).lower()
                        if any(k.lower() in txt for k in keywords):
                            found_kw = True
                            break
                checks["rubric_platform_scope_referenced"] = found_kw
        else:
            # Fallback by regex for minimal checks if parsing failed (keep yaml_valid_scorecard as False)
            # We will attempt minimal validations where possible without parsing
            pass

# Interview loop YAML checks
interview_loop_data: Optional[Dict[str, Any]] = None
if checks["exists_interview_loop"]:
    text = read_text(interview_loop_path)
    if text is not None:
        data = try_load_yaml(text)
        if isinstance(data, dict):
            interview_loop_data = data
            checks["yaml_valid_interview_loop"] = True

        if interview_loop_data and "interview_loop" in interview_loop_data and isinstance(interview_loop_data["interview_loop"], dict):
            il = interview_loop_data["interview_loop"]
            stages = il.get("stages")
            required_stages = ["Phone Screen", "Technical Assessment", "System Design", "Behavioral Deep-Dive", "Hiring Manager Final"]
            stages_ok = False
            fields_ok = False
            applies_ok = False
            if isinstance(stages, list) and len(stages) > 0:
                names_present = set()
                fields_ok = True
                for st in stages:
                    if isinstance(st, dict):
                        name = st.get("stage")
                        if isinstance(name, str):
                            names_present.add(name)
                        # Each stage fields check
                        required_fields = ["duration", "who", "evaluates", "format", "pass_rate_target"]
                        for rf in required_fields:
                            if rf not in st:
                                fields_ok = False
                        # System Design applies_to Senior+
                        if isinstance(name, str) and name.strip().lower() == "system design":
                            applies = st.get("applies_to")
                            if isinstance(applies, str) and ("senior+" in applies.lower()):
                                applies_ok = True
                stages_ok = all(rs in names_present for rs in required_stages)
            checks["interview_loop_has_required_stages"] = stages_ok
            checks["interview_loop_stage_fields_present"] = fields_ok
            checks["interview_loop_system_design_applies_senior_plus"] = applies_ok
            # Timeline section
            timeline = il.get("timeline", {})
            if isinstance(timeline, dict) and all(k in timeline for k in ("screen_to_onsite", "onsite_to_decision", "decision_to_offer", "total_process")):
                checks["interview_loop_timeline_present"] = True

# Question bank checks
if checks["exists_question_bank"]:
    qtext = read_text(question_bank_path)
    if qtext is not None:
        lines = qtext.splitlines()
        # Sections
        section_titles = [
            "Ownership & Initiative",
            "Communication & Collaboration",
            "Technical Excellence",
            "Leadership & Mentoring",
        ]
        sections = extract_sections(lines, section_titles)
        checks["question_bank_sections_present"] = all(title in sections for title in section_titles)
        twoper = True
        all_blocks_have_requirements = True
        if checks["question_bank_sections_present"]:
            for title in section_titles:
                start, end = sections[title]
                section_lines = lines[start:end]
                q_count, blocks = count_questions_and_blocks(section_lines)
                if q_count < 2:
                    twoper = False
                for _, (bstart, bend) in blocks.items():
                    if not block_contains_required_lines(section_lines, bstart, bend):
                        all_blocks_have_requirements = False
        else:
            twoper = False
            all_blocks_have_requirements = False
        checks["question_bank_two_questions_per_section"] = twoper
        checks["question_bank_each_question_has_probe_green_red"] = all_blocks_have_requirements

# Take-home assessment checks
if checks["exists_take_home"]:
    th_text = read_text(take_home_path)
    if th_text is not None:
        low = th_text.lower()
        has_time_limit = "time_limit" in low
        has_deadline = "deadline" in low
        has_deliverables = "deliverables" in low
        has_rubric = "evaluation_rubric" in low
        checks["take_home_has_required_sections"] = all([has_time_limit, has_deadline, has_deliverables, has_rubric])

        # Extract rubric percentages for five categories
        categories = ["functionality", "code_quality", "testing", "documentation", "extras"]
        sums = 0.0
        found_all = True
        for cat in categories:
            # Find the line containing the category
            m = re.search(rf"(^|\n)[^\n]*{cat}[^\n]*\n?", th_text, flags=re.IGNORECASE)
            if not m:
                found_all = False
                break
            # Extract percentage from the matching line span
            # Get the line content around the match
            line_start = th_text.rfind("\n", 0, m.end()) + 1
            line_end_n = th_text.find("\n", m.end())
            if line_end_n == -1:
                line_end_n = len(th_text)
            line = th_text[line_start:line_end_n]
            pct = parse_percent_from_line(line)
            if pct is None:
                found_all = False
                break
            sums += pct
        if found_all and abs(sums - 100.0) <= 1.0:
            checks["take_home_rubric_sums_to_100"] = True

# System design assessment checks
if checks["exists_system_design"]:
    sd_text = read_text(system_design_path)
    if sd_text is not None:
        low = sd_text.lower()
        has_duration = "duration" in low
        # Structure sub-parts
        has_requirements = "requirements" in low
        has_high_level = "high_level" in low or "high level" in low
        has_deep_dive = "deep_dive" in low or "deep dive" in low
        has_trade_offs = "trade_offs" in low or "trade-offs" in low or "trade offs" in low
        has_extensions = "extensions" in low
        # Evaluation categories
        eval_reqs = "requirements_gathering" in low
        eval_high = "high_level_design" in low or "high level design" in low
        eval_depth = "depth" in low
        eval_trade = "trade_off_awareness" in low or "trade-off awareness" in low
        eval_scale = "scalability" in low
        checks["system_design_has_duration_structure_evaluation"] = all([
            has_duration, has_requirements, has_high_level, has_deep_dive, has_trade_offs, has_extensions,
            eval_reqs, eval_high, eval_depth, eval_trade, eval_scale
        ])

# Interviewer scorecard YAML checks
interviewer_scorecard_data: Optional[Dict[str, Any]] = None
if checks["exists_interviewer_scorecard"]:
    t = read_text(interviewer_scorecard_path)
    if t is not None:
        data = try_load_yaml(t)
        if isinstance(data, dict):
            interviewer_scorecard_data = data
            checks["yaml_valid_interviewer_scorecard"] = True

        if interviewer_scorecard_data:
            # The YAML may have top-level keys directly
            d = interviewer_scorecard_data
            # Required keys
            keys_ok = all(k in d for k in ["candidate", "interviewer", "stage", "date", "overall"])
            checks["interviewer_scorecard_has_keys"] = keys_ok
            # competency_scores list with >=2 entries and each has competency, score, evidence
            comp_scores = d.get("competency_scores")
            comp_ok = False
            if isinstance(comp_scores, list) and len(comp_scores) >= 2:
                comp_ok = True
                for entry in comp_scores:
                    if not (isinstance(entry, dict) and all(k in entry for k in ["competency", "score", "evidence"])):
                        comp_ok = False
                        break
            checks["interviewer_scorecard_competency_scores_count"] = comp_ok

# Debrief protocol checks
if checks["exists_debrief_protocol"]:
    dp_text = read_text(debrief_protocol_path)
    if dp_text is not None:
        low = dp_text.lower()
        has_before = "before debrief" in low
        has_structure = "debrief structure" in low
        has_after = "after debrief" in low
        has_final_vote = "final vote" in low
        checks["debrief_protocol_has_required_phrases"] = all([has_before, has_structure, has_after, has_final_vote])

# Communications templates checks
if checks["exists_communications_templates"]:
    ct_text = read_text(communications_templates_path)
    if ct_text is not None:
        low = ct_text.lower()
        has_advancing = "advancing" in low
        has_reject_phone = "rejection (after phone screen)".lower() in low
        has_reject_onsite = "rejection (after onsite)".lower() in low
        has_offer = "offer" in low
        checks["communications_templates_has_labels"] = all([has_advancing, has_reject_phone, has_reject_onsite, has_offer])

# Compute reward as proportion of passed required checks
required_check_keys = [
    "exists_scorecard",
    "yaml_valid_scorecard",
    "scorecard_mission_statement_is_single_sentence",
    "scorecard_outcomes_count_valid",
    "scorecard_outcomes_have_measure_and_timeline",
    "scorecard_technical_must_have_two_with_level_evidence",
    "scorecard_behavioral_must_have_antipatterns",
    "scorecard_comp_band_has_dash",
    "scorecard_dealbreakers_no_subjective",
    "exists_interview_loop",
    "yaml_valid_interview_loop",
    "interview_loop_has_required_stages",
    "interview_loop_stage_fields_present",
    "interview_loop_system_design_applies_senior_plus",
    "interview_loop_timeline_present",
    "exists_question_bank",
    "question_bank_sections_present",
    "question_bank_two_questions_per_section",
    "question_bank_each_question_has_probe_green_red",
    "exists_take_home",
    "take_home_has_required_sections",
    "take_home_rubric_sums_to_100",
    "exists_system_design",
    "system_design_has_duration_structure_evaluation",
    "exists_interviewer_scorecard",
    "yaml_valid_interviewer_scorecard",
    "interviewer_scorecard_has_keys",
    "interviewer_scorecard_competency_scores_count",
    "exists_debrief_protocol",
    "debrief_protocol_has_required_phrases",
    "exists_communications_templates",
    "communications_templates_has_labels",
]

passed = sum(1 for k in required_check_keys if checks.get(k, False))
total = len(required_check_keys)

# No-op baseline: if output directory missing or effectively no files produced, reward must be 0.0
output_exists_and_nonempty = os.path.isdir(output_dir) and any(checks[k] for k in [
    "exists_scorecard",
    "exists_interview_loop",
    "exists_question_bank",
    "exists_take_home",
    "exists_system_design",
    "exists_interviewer_scorecard",
    "exists_debrief_protocol",
    "exists_communications_templates",
])

reward = 0.0
if output_exists_and_nonempty and total > 0:
    reward = passed / total
else:
    reward = 0.0

# Build final output JSON
result = {"reward": round(reward, 6)}
# Append checks in deterministic order
for key in sorted(checks.keys()):
    result[key] = checks[key]

# Print exactly one JSON object on the last non-empty stdout line
print(json.dumps(result))