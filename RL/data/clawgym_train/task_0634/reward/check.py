import json
import os
import re
import sys
from datetime import datetime, date

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def parse_iso8601_datetime(s):
    if not isinstance(s, str):
        return None
    try:
        # support trailing Z
        if s.endswith("Z"):
            s_adj = s[:-1] + "+00:00"
        else:
            s_adj = s
        dt = datetime.fromisoformat(s_adj)
        return dt
    except Exception:
        return None

def is_valid_date_yyyy_mm_dd(s):
    if not isinstance(s, str):
        return False, None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False, None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        return True, d
    except Exception:
        return False, None

def word_count(text):
    if not isinstance(text, str):
        return 0
    # count words by word boundaries
    return len(re.findall(r"\b\w+\b", text))

def contains_banned_terms(text, banned_terms):
    # case-insensitive exact word or phrase match using word boundaries
    if not isinstance(text, str):
        return True
    for term in banned_terms:
        pattern = r"(?i)\b" + re.escape(term) + r"\b"
        if re.search(pattern, text):
            return True
    return False

def mentions_any(text, terms):
    if not isinstance(text, str):
        return False
    t_lower = text.lower()
    for term in terms:
        if not isinstance(term, str):
            continue
        if term.strip() == "":
            continue
        # use case-insensitive substring search; for single-word, require word boundary
        term_lower = term.lower()
        # If alphanumeric only, enforce word boundaries; otherwise (contains space/special), substring is acceptable
        if re.fullmatch(r"[A-Za-z0-9_]+", term):
            if re.search(r"\b" + re.escape(term_lower) + r"\b", t_lower):
                return True
        else:
            if term_lower in t_lower:
                return True
    return False

def is_string_list(lst):
    return isinstance(lst, list) and all(isinstance(x, str) for x in lst)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_roadmap_json": False,
        "roadmap_json_valid": False,
        "roadmap_has_required_top_keys": False,
        "roadmap_session_user_match_input": False,
        "roadmap_generatedAt_iso8601": False,
        "roadmap_phases_count": False,
        "roadmap_phases_sequence_and_fields": False,
        "roadmap_phase_durations_format": False,
        "roadmap_focus_resources_nonempty": False,
        "roadmap_milestones_count": False,
        "roadmap_milestones_fields_and_format": False,
        "roadmap_milestones_dates_on_or_after_assessment": False,
        "roadmap_recommendedCertifications_valid": False,

        "has_summary_md": False,
        "summary_min_words_150": False,
        "summary_mentions_input_skill_or_platform": False,
        "summary_no_banned_terms": False,
        "summary_no_emdash_or_doublehyphen": False,

        "has_evaluation_json": False,
        "evaluation_json_valid": False,
        "evaluation_has_required_keys": False,
        "evaluation_scorecard_valid": False,
        "evaluation_evidence_valid": False,
        "evaluation_verdict_valid": False,
        "evaluation_top_fixes_valid": False,
    }

    # Load input assessment for reference
    input_assessment_path = os.path.join(input_dir, "assessment.json")
    input_data, _ = load_json(input_assessment_path)
    input_user_id = None
    input_session_id = None
    assessment_timestamp_dt = None
    if isinstance(input_data, dict):
        input_user_id = input_data.get("userId", None)
        ad = input_data.get("assessmentData", {})
        if isinstance(ad, dict):
            input_session_id = ad.get("sessionId", None)
            ts = ad.get("timestamp", None)
            dt = parse_iso8601_datetime(ts) if ts else None
            assessment_timestamp_dt = dt
    # Required output files
    roadmap_path = os.path.join(output_dir, "roadmap.json")
    summary_path = os.path.join(output_dir, "summary.md")
    evaluation_path = os.path.join(output_dir, "evaluation_report.json")

    # ROADMAP checks
    if os.path.isfile(roadmap_path):
        checks["has_roadmap_json"] = True
        roadmap, err = load_json(roadmap_path)
        if isinstance(roadmap, dict):
            checks["roadmap_json_valid"] = True
            required_keys = ["roadmapId", "userId", "sessionId", "phases", "milestones", "recommendedCertifications", "generatedAt"]
            if all(k in roadmap for k in required_keys):
                # Validate types for top-level fields
                top_level_types_ok = (
                    isinstance(roadmap.get("roadmapId"), str) and len(roadmap.get("roadmapId")) > 0 and
                    ("userId" in roadmap) and (isinstance(roadmap.get("userId"), (int, type(None)))) and
                    isinstance(roadmap.get("sessionId"), str) and
                    isinstance(roadmap.get("phases"), list) and
                    isinstance(roadmap.get("milestones"), list) and
                    isinstance(roadmap.get("recommendedCertifications"), list) and
                    isinstance(roadmap.get("generatedAt"), str)
                )
                if top_level_types_ok:
                    checks["roadmap_has_required_top_keys"] = True

                # Session and user matching
                session_match = (input_session_id is None) or (roadmap.get("sessionId") == input_session_id)
                # If input_user_id is present (not None), roadmap.userId must equal it. Otherwise roadmap.userId must be null.
                if input_user_id is not None:
                    user_match = (roadmap.get("userId") == input_user_id)
                else:
                    user_match = (roadmap.get("userId") is None)
                if session_match and user_match:
                    checks["roadmap_session_user_match_input"] = True

                # generatedAt ISO8601
                gen_dt = parse_iso8601_datetime(roadmap.get("generatedAt"))
                if gen_dt is not None and "T" in roadmap.get("generatedAt"):
                    checks["roadmap_generatedAt_iso8601"] = True

                # Phases
                phases = roadmap.get("phases", [])
                if isinstance(phases, list) and len(phases) >= 3:
                    checks["roadmap_phases_count"] = True

                    seq_ok = True
                    fields_ok = True
                    durations_ok = True
                    focus_res_ok = True

                    expected_phase_num = 1
                    for ph in phases:
                        if not isinstance(ph, dict):
                            fields_ok = False
                            seq_ok = False
                            durations_ok = False
                            focus_res_ok = False
                            break
                        # field presence
                        if not all(k in ph for k in ["phase", "title", "duration", "focus", "resources"]):
                            fields_ok = False
                        # phase numbering
                        if not isinstance(ph.get("phase"), int) or ph.get("phase") != expected_phase_num:
                            seq_ok = False
                        expected_phase_num += 1
                        # duration contains 'month'
                        dur = ph.get("duration")
                        if not (isinstance(dur, str) and ("month" in dur.lower())):
                            durations_ok = False
                        # focus/resources arrays non-empty of strings
                        focus = ph.get("focus")
                        resources = ph.get("resources")
                        if not (isinstance(focus, list) and len(focus) > 0 and all(isinstance(x, str) and x.strip() != "" for x in focus)):
                            focus_res_ok = False
                        if not (isinstance(resources, list) and len(resources) > 0 and all(isinstance(x, str) and x.strip() != "" for x in resources)):
                            focus_res_ok = False

                    if seq_ok:
                        checks["roadmap_phases_sequence_and_fields"] = checks["roadmap_phases_sequence_and_fields"] or True
                    if fields_ok:
                        checks["roadmap_phases_sequence_and_fields"] = checks["roadmap_phases_sequence_and_fields"] and True
                    else:
                        checks["roadmap_phases_sequence_and_fields"] = False
                    if durations_ok:
                        checks["roadmap_phase_durations_format"] = True
                    if focus_res_ok:
                        checks["roadmap_focus_resources_nonempty"] = True

                # Milestones
                milestones = roadmap.get("milestones", [])
                if isinstance(milestones, list) and len(milestones) >= 3:
                    checks["roadmap_milestones_count"] = True

                    fields_ok = True
                    dates_ok = True
                    after_assessment_ok = True

                    for m in milestones:
                        if not isinstance(m, dict):
                            fields_ok = False
                            dates_ok = False
                            after_assessment_ok = False
                            break
                        if not all(k in m for k in ["milestone", "targetDate", "difficulty"]):
                            fields_ok = False
                        if not isinstance(m.get("milestone"), str) or not isinstance(m.get("difficulty"), str):
                            fields_ok = False
                        valid_fmt, d = is_valid_date_yyyy_mm_dd(m.get("targetDate"))
                        if not valid_fmt:
                            dates_ok = False
                        else:
                            # compare with assessment date if available
                            if assessment_timestamp_dt is not None:
                                assess_date = assessment_timestamp_dt.date()
                                if d < assess_date:
                                    after_assessment_ok = False

                    if fields_ok and dates_ok:
                        checks["roadmap_milestones_fields_and_format"] = True
                    if after_assessment_ok and len(milestones) >= 1:
                        checks["roadmap_milestones_dates_on_or_after_assessment"] = True

                # recommendedCertifications
                certs = roadmap.get("recommendedCertifications", [])
                if isinstance(certs, list) and len(certs) >= 2 and all(isinstance(x, str) and x.strip() != "" for x in certs):
                    checks["roadmap_recommendedCertifications_valid"] = True

        else:
            # roadmap exists but not valid JSON
            checks["roadmap_json_valid"] = False

    # SUMMARY checks
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
        except Exception:
            summary_text = None

        if isinstance(summary_text, str):
            if word_count(summary_text) >= 150:
                checks["summary_min_words_150"] = True

            # banned terms
            banned = ["delve", "leverage", "robust", "comprehensive", "seamless", "pivotal", "embark", "beacon", "paradigm", "utilize", "game-changer", "underscores", "tapestry", "realm"]
            if not contains_banned_terms(summary_text, banned):
                checks["summary_no_banned_terms"] = True

            # no em dash or double hyphen
            if "—" not in summary_text and "--" not in summary_text:
                checks["summary_no_emdash_or_doublehyphen"] = True

            # mentions any skill/platform from input
            terms = []
            skills_obj = None
            if isinstance(input_data, dict):
                ad = input_data.get("assessmentData", {})
                if isinstance(ad, dict):
                    skills_obj = ad.get("skills", {})
            if isinstance(skills_obj, dict):
                for key in ["programmingLanguages", "gameEngines", "platforms"]:
                    val = skills_obj.get(key)
                    if isinstance(val, list):
                        for x in val:
                            if isinstance(x, str):
                                terms.append(x)
            if mentions_any(summary_text, terms) and len(terms) > 0:
                checks["summary_mentions_input_skill_or_platform"] = True

    # EVALUATION checks
    if os.path.isfile(evaluation_path):
        checks["has_evaluation_json"] = True
        evaluation, err = load_json(evaluation_path)
        if isinstance(evaluation, dict):
            checks["evaluation_json_valid"] = True
            has_keys = all(k in evaluation for k in ["scorecard", "evidence", "verdict", "top_fixes"])
            if has_keys and isinstance(evaluation.get("scorecard"), dict) and isinstance(evaluation.get("evidence"), dict):
                checks["evaluation_has_required_keys"] = True

                # scorecard fields 1-5 numeric
                dims = ["Correctness", "Relevance", "Actionability", "Risk flags", "Tool reliability"]
                sc = evaluation.get("scorecard", {})
                sc_ok = True
                for dname in dims:
                    val = sc.get(dname)
                    if not isinstance(val, (int, float)) or not (1 <= float(val) <= 5):
                        sc_ok = False
                        break
                if sc_ok:
                    checks["evaluation_scorecard_valid"] = True

                # evidence strings for same dims
                ev = evaluation.get("evidence", {})
                ev_ok = True
                for dname in dims:
                    sval = ev.get(dname)
                    if not isinstance(sval, str) or len(sval.strip()) == 0:
                        ev_ok = False
                        break
                if ev_ok:
                    checks["evaluation_evidence_valid"] = True

                # verdict value
                verdict = evaluation.get("verdict")
                if verdict in ["Go", "Conditional Go", "No-Go"]:
                    checks["evaluation_verdict_valid"] = True

                # top_fixes array length >= 2 strings
                tf = evaluation.get("top_fixes")
                if isinstance(tf, list) and len(tf) >= 2 and all(isinstance(x, str) and x.strip() != "" for x in tf):
                    checks["evaluation_top_fixes_valid"] = True
        else:
            checks["evaluation_json_valid"] = False

    # Compute reward
    required_files_exist = checks["has_roadmap_json"] and checks["has_summary_md"] and checks["has_evaluation_json"]

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_files_exist:
        reward = 0.0
    else:
        # fraction of checks passed
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # clamp
        reward = max(0.0, min(1.0, float(reward)))

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()