import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_simple_yaml(yaml_text: str) -> Optional[Dict[str, Any]]:
    # Minimal YAML parser for the specific structure provided.
    # Supports:
    # key: value
    # key:
    #   - item1
    #   - item2
    data: Dict[str, Any] = {}
    lines = yaml_text.splitlines()
    i = 0
    current_key: Optional[str] = None
    while i < len(lines):
        line = lines[i]
        # strip comments and whitespace
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.rstrip()
        if not line.strip():
            i += 1
            continue
        if re.match(r"^\s*-\s+", line):
            # This is an unexpected top-level list item without a current key
            # Skip such cases to avoid crash
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if m:
            key = m.group(1)
            value = m.group(2).strip()
            if value == "":
                # Possibly a list follows
                # Collect indented list items
                items: List[Any] = []
                j = i + 1
                while j < len(lines):
                    li = lines[j]
                    if "#" in li:
                        li = li.split("#", 1)[0]
                    if not li.strip():
                        j += 1
                        continue
                    if re.match(r"^\s*-\s+(.*)$", li):
                        item_val = re.match(r"^\s*-\s+(.*)$", li).group(1).strip()
                        # strip quotes if any
                        if re.match(r"^['\"].*['\"]$", item_val):
                            item_val = item_val[1:-1]
                        items.append(item_val)
                        j += 1
                        continue
                    # Stop if next top-level key begins
                    if re.match(r"^[A-Za-z0-9_\-]+\s*:\s*", li):
                        break
                    # Otherwise, not a list item; break
                    break
                if items:
                    data[key] = items
                    i = j
                    continue
                else:
                    # Empty or nested structures not supported
                    data[key] = None
                    i = j
                    continue
            else:
                # Scalar value
                sval = value
                # strip quotes
                if re.match(r"^['\"].*['\"]$", sval):
                    sval = sval[1:-1]
                else:
                    # try int
                    if re.match(r"^-?\d+$", sval):
                        try:
                            sval = int(sval)
                        except Exception:
                            pass
                data[key] = sval
                i += 1
                continue
        else:
            i += 1
            continue
    # Map expected keys to normalized names used in grading
    # The YAML keys are version, release_cadence, coverage_threshold, stages, services
    return data


def _run_script_and_capture(script_path: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(script_path.parent.parent) if script_path.parent.name == "scripts" else None,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        else:
            return None
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    # Normalize line endings and strip trailing newlines for comparison
    return s.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _parse_ci_log(ci_text: str) -> Optional[Dict[str, Any]]:
    try:
        build_id = None
        stages_status: Dict[str, str] = {}
        tests_total = None
        tests_passed = None
        tests_failed = None
        failing_tests: List[Dict[str, str]] = []
        coverage_measured = None

        for line in ci_text.splitlines():
            # Build ID
            m = re.search(r"\[CI\]\s*Build ID:\s*(\S+)", line)
            if m:
                build_id = m.group(1).strip()
            # Tests summary
            m = re.search(r"Running tests:\s*total=(\d+),\s*passed=(\d+),\s*failed=(\d+)", line)
            if m:
                tests_total = int(m.group(1))
                tests_passed = int(m.group(2))
                tests_failed = int(m.group(3))
            # PASS/FAIL lines for tests
            m_fail = re.search(r"^FAIL:\s*([^ ]+)\s+on\s+([A-Za-z0-9\-_]+)\s*->\s*(.*)$", line)
            if m_fail:
                name = m_fail.group(1).strip()
                service = m_fail.group(2).strip()
                message = m_fail.group(3).strip()
                failing_tests.append({"name": name, "service": service, "message": message})
            # Coverage
            m_cov = re.search(r"Coverage:\s*(\d+)%", line)
            if m_cov:
                coverage_measured = int(m_cov.group(1))
            # Stage statuses
            m_stage_ok = re.search(r"\[STAGE\s+([^\]]+)\]\s+OK\b", line)
            if m_stage_ok:
                stages_status[m_stage_ok.group(1).strip()] = "OK"
            m_stage_fail = re.search(r"\[STAGE\s+([^\]]+)\]\s+FAIL\b", line)
            if m_stage_fail:
                stages_status[m_stage_fail.group(1).strip()] = "FAIL"
            m_stage_skipped = re.search(r"\[STAGE\s+([^\]]+)\]\s+SKIPPED\b", line)
            if m_stage_skipped:
                stages_status[m_stage_skipped.group(1).strip()] = "SKIPPED"

        parsed = {
            "build_id": build_id,
            "stages_status": stages_status,
            "tests_total": tests_total,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "failing_tests": failing_tests,
            "coverage_measured": coverage_measured,
        }
        # Validate minimal presence
        if build_id is None or coverage_measured is None or tests_total is None or tests_passed is None or tests_failed is None:
            return None
        return parsed
    except Exception:
        return None


def _build_expected_summary(config: Dict[str, Any], ci: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        version = config.get("version")
        release_cadence = config.get("release_cadence")
        coverage_threshold = config.get("coverage_threshold")
        stages_list = config.get("stages")
        if not isinstance(version, str) or not isinstance(release_cadence, str) or not isinstance(coverage_threshold, int) or not isinstance(stages_list, list):
            return None

        stages_summary: List[Dict[str, str]] = []
        stages_status_map: Dict[str, str] = ci.get("stages_status", {})
        for s in stages_list:
            status = stages_status_map.get(s)
            if status not in ("OK", "FAIL", "SKIPPED"):
                # If missing or invalid, cannot build expected summary
                return None
            stages_summary.append({"name": s, "status": status})

        measured = ci["coverage_measured"]
        meets_threshold = bool(measured >= coverage_threshold)
        tests_block = {
            "total": ci["tests_total"],
            "passed": ci["tests_passed"],
            "failed": ci["tests_failed"],
            "failing": ci["failing_tests"],
        }
        # release_ready only if all stages OK, zero failing tests, and meets_threshold
        all_ok = all(s["status"] == "OK" for s in stages_summary)
        zero_fail_tests = tests_block["failed"] == 0
        release_ready = bool(all_ok and zero_fail_tests and meets_threshold)

        expected = {
            "pipeline_version": version,
            "build_id": ci["build_id"],
            "release_cadence": release_cadence,
            "coverage": {
                "measured_percent": measured,
                "threshold_percent": coverage_threshold,
                "meets_threshold": meets_threshold,
            },
            "stages": stages_summary,
            "tests": tests_block,
            "release_ready": release_ready,
        }
        return expected
    except Exception:
        return None


def _compare_json_structs(a: Any, b: Any) -> bool:
    return a == b


def _parse_team_roles(text: str) -> Dict[str, str]:
    roles = {}
    for line in text.splitlines():
        m = re.search(r"-\s*API lead:\s*(.+)", line)
        if m:
            roles["api_lead"] = m.group(1).strip()
        m = re.search(r"-\s*Web lead:\s*(.+)", line)
        if m:
            roles["web_lead"] = m.group(1).strip()
        m = re.search(r"-\s*QA lead:\s*(.+)", line)
        if m:
            roles["qa_lead"] = m.group(1).strip()
    return roles


def _find_section(lines: List[str], section_name: str) -> Tuple[int, int]:
    # Return (start_index, end_index_exclusive) of the section identified by title matching section_name (case-insensitive).
    # We consider headings or plain lines exactly matching section_name (case-insensitive).
    start = -1
    for idx, line in enumerate(lines):
        if line.strip().lower() == section_name.lower() or re.match(r"^\s*#+\s*"+re.escape(section_name)+r"\s*$", line.strip(), flags=re.IGNORECASE):
            start = idx + 1
            break
    if start == -1:
        return (-1, -1)
    # Find end: next heading line or end of file
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^\s*#+\s+.+", lines[j]):  # simple heading detector
            end = j
            break
    return (start, end)


def _extract_bullets(lines: List[str], start: int, end: int) -> List[str]:
    bullets = []
    for i in range(max(0, start), max(0, end)):
        line = lines[i]
        if re.match(r"^\s*[\-\*]\s+.+", line):
            bullets.append(line.strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ci_log_reproduces_script_output": 0.0,
        "ci_summary_json_schema_and_values": 0.0,
        "status_report_includes_required_facts": 0.0,
        "status_report_stage_bullets_and_deploy_prod_skipped": 0.0,
        "status_report_coverage_and_gate": 0.0,
        "status_report_release_ready_conclusion": 0.0,
        "meeting_notes_context_and_decisions": 0.0,
        "meeting_notes_actions_failing_tests_with_correct_owners": 0.0,
        "meeting_notes_actions_failing_stages_with_correct_owners": 0.0,
        "meeting_notes_action_for_coverage_with_qa_owner": 0.0,
        "deployment_policy_release_cadence_updated": 0.0,
        "deployment_policy_coverage_threshold_updated": 0.0,
        "deployment_policy_pipeline_stages_list_updated": 0.0,
        "deployment_policy_bilingual_comms_appended": 0.0,
    }

    # Paths
    ci_log_path = workspace / "outputs" / "ci.log"
    ci_summary_path = workspace / "outputs" / "ci_summary.json"
    status_report_path = workspace / "outputs" / "status_report.md"
    meeting_notes_path = workspace / "outputs" / "meeting_notes.md"
    policy_path = workspace / "docs" / "deployment_policy.md"
    team_roles_path = workspace / "docs" / "team_roles.md"
    pipeline_yaml_path = workspace / "config" / "pipeline.yaml"
    run_ci_script_path = workspace / "scripts" / "run_ci.py"

    # Load files
    pipeline_yaml_text = _read_text_safe(pipeline_yaml_path)
    ci_log_text = _read_text_safe(ci_log_path)
    ci_summary_json = _load_json_safe(ci_summary_path)
    status_report_text = _read_text_safe(status_report_path)
    meeting_notes_text = _read_text_safe(meeting_notes_path)
    policy_text = _read_text_safe(policy_path)
    team_roles_text = _read_text_safe(team_roles_path)

    # Parse config
    config = None
    if pipeline_yaml_text is not None:
        config = _parse_simple_yaml(pipeline_yaml_text)

    # 1) ci_log_reproduces_script_output
    # Compare outputs/ci.log with running scripts/run_ci.py
    expected_ci_output = None
    if run_ci_script_path.exists():
        expected_ci_output = _run_script_and_capture(run_ci_script_path)
    if expected_ci_output is not None and ci_log_text is not None:
        if _normalize_text(expected_ci_output) == _normalize_text(ci_log_text):
            scores["ci_log_reproduces_script_output"] = 1.0
        else:
            scores["ci_log_reproduces_script_output"] = 0.0
    else:
        # If either missing or failed, cannot verify
        scores["ci_log_reproduces_script_output"] = 0.0

    # 2) ci_summary_json_schema_and_values
    expected_summary = None
    ci_parsed = None
    if ci_log_text is not None:
        ci_parsed = _parse_ci_log(ci_log_text)
    if config is not None and ci_parsed is not None:
        expected_summary = _build_expected_summary(config, ci_parsed)
    if expected_summary is not None and isinstance(ci_summary_json, dict):
        # Strict equality check
        if _compare_json_structs(ci_summary_json, expected_summary):
            scores["ci_summary_json_schema_and_values"] = 1.0
        else:
            scores["ci_summary_json_schema_and_values"] = 0.0
    else:
        scores["ci_summary_json_schema_and_values"] = 0.0

    # For subsequent checks, use summary as source of truth if available
    summary = ci_summary_json if isinstance(ci_summary_json, dict) else None

    # 3) status_report checks
    if status_report_text is not None and isinstance(summary, dict):
        # a) Includes pipeline version and build id
        version = summary.get("pipeline_version")
        build_id = summary.get("build_id")
        has_version = isinstance(version, str) and (version in status_report_text)
        has_build_id = isinstance(build_id, str) and (build_id in status_report_text)
        if has_version and has_build_id:
            scores["status_report_includes_required_facts"] = 1.0

        # b) Stage-by-stage status as bullet points, and note if deploy_prod skipped
        stages = summary.get("stages")
        if isinstance(stages, list):
            lines = status_report_text.splitlines()
            bullets = [ln.strip() for ln in lines if re.match(r"^\s*[\-\*]\s+.+", ln)]
            stage_bullets_ok = True
            for st in stages:
                name = st.get("name")
                status = st.get("status")
                if not isinstance(name, str) or not isinstance(status, str):
                    stage_bullets_ok = False
                    break
                found = False
                for b in bullets:
                    if name in b and re.search(r"\b" + re.escape(status) + r"\b", b, flags=re.IGNORECASE):
                        found = True
                        break
                if not found:
                    stage_bullets_ok = False
                    break
            # Explicitly note if deploy_prod was skipped
            deploy_prod_note = False
            for ln in lines:
                if "deploy_prod" in ln and re.search(r"skipped", ln, flags=re.IGNORECASE):
                    deploy_prod_note = True
                    break
            if stage_bullets_ok and deploy_prod_note:
                scores["status_report_stage_bullets_and_deploy_prod_skipped"] = 1.0

        # c) Coverage vs threshold and whether it gates release
        cov = summary.get("coverage") if isinstance(summary, dict) else None
        cov_ok = False
        if isinstance(cov, dict):
            measured = cov.get("measured_percent")
            threshold = cov.get("threshold_percent")
            meets = cov.get("meets_threshold")
            found_measured = re.search(rf"{measured}\s*%|\b{measured}\b", status_report_text) is not None
            found_threshold = re.search(rf"{threshold}\s*%|\b{threshold}\b", status_report_text) is not None
            # gate mention based on meets_threshold
            gate_phrase_ok = False
            if re.search(r"coverage", status_report_text, re.IGNORECASE) and re.search(r"threshold", status_report_text, re.IGNORECASE):
                if meets is True and re.search(r"(meets|>=|above)", status_report_text, re.IGNORECASE):
                    gate_phrase_ok = True
                if meets is False and re.search(r"(below|not\s+met|<)", status_report_text, re.IGNORECASE):
                    gate_phrase_ok = True
            if found_measured and found_threshold and gate_phrase_ok:
                cov_ok = True
        if cov_ok:
            scores["status_report_coverage_and_gate"] = 1.0

        # d) Test summary totals and failing tests details
        tests = summary.get("tests") if isinstance(summary, dict) else None
        tests_ok = False
        if isinstance(tests, dict):
            total = tests.get("total")
            passed = tests.get("passed")
            failed = tests.get("failed")
            failing = tests.get("failing")
            nums_ok = (re.search(rf"\btotal\D+{total}\b", status_report_text, re.IGNORECASE) is not None and
                       re.search(rf"\bpassed\D+{passed}\b", status_report_text, re.IGNORECASE) is not None and
                       re.search(rf"\bfailed\D+{failed}\b", status_report_text, re.IGNORECASE) is not None)
            failing_details_ok = True
            if isinstance(failing, list):
                for ft in failing:
                    name = ft.get("name")
                    service = ft.get("service")
                    message = ft.get("message")
                    # Ensure all are mentioned
                    if not (isinstance(name, str) and isinstance(service, str) and isinstance(message, str)):
                        failing_details_ok = False
                        break
                    if not (name in status_report_text and service in status_report_text and message in status_report_text):
                        failing_details_ok = False
                        break
            else:
                failing_details_ok = False
            if nums_ok and failing_details_ok:
                tests_ok = True
        if tests_ok:
            scores["status_report_includes_required_facts"] = 1.0 if scores["status_report_includes_required_facts"] == 1.0 else scores["status_report_includes_required_facts"]
            scores["status_report_stage_bullets_and_deploy_prod_skipped"] = 1.0 if scores["status_report_stage_bullets_and_deploy_prod_skipped"] == 1.0 else scores["status_report_stage_bullets_and_deploy_prod_skipped"]
        # e) Release ready conclusion
        rr = summary.get("release_ready")
        release_ready_line = None
        for ln in status_report_text.splitlines():
            if re.search(r"release\s+ready\s*:\s*(yes|no)", ln, re.IGNORECASE):
                release_ready_line = ln
                break
        if isinstance(rr, bool) and release_ready_line:
            yesno = "yes" if rr else "no"
            if re.search(rf"release\s+ready\s*:\s*{yesno}", release_ready_line, re.IGNORECASE):
                scores["status_report_release_ready_conclusion"] = 1.0
    # 4) meeting_notes checks
    if meeting_notes_text is not None and isinstance(summary, dict) and team_roles_text is not None:
        lines = meeting_notes_text.splitlines()
        roles = _parse_team_roles(team_roles_text)
        api_lead = roles.get("api_lead")
        web_lead = roles.get("web_lead")
        qa_lead = roles.get("qa_lead")

        # Context paragraph: first non-empty paragraph
        paras = [p.strip() for p in meeting_notes_text.split("\n\n") if p.strip()]
        context_ok = False
        if paras:
            ctx = paras[0]
            has_pause = re.search(r"pause|paused|pausing", ctx, re.IGNORECASE) is not None
            has_prod_deploy = re.search(r"prod|production.*deploy|deploy.*prod", ctx, re.IGNORECASE) is not None
            # At least one gating issue mentioned
            gating_mentions = (re.search(r"smoke", ctx, re.IGNORECASE) or
                               re.search(r"test", ctx, re.IGNORECASE) or
                               re.search(r"coverage", ctx, re.IGNORECASE))
            if has_pause and has_prod_deploy and gating_mentions:
                context_ok = True

        # Decisions needed section: should mention gating issues
        dn_start, dn_end = _find_section(lines, "Decisions needed")
        decisions_ok = False
        if dn_start != -1:
            dn_bullets = _extract_bullets(lines, dn_start, dn_end)
            text_block = "\n".join(dn_bullets)
            gating_ok = True
            # If failing tests >0
            tests = summary.get("tests", {})
            if isinstance(tests, dict) and isinstance(tests.get("failed"), int) and tests.get("failed") > 0:
                if not (re.search(r"test", text_block, re.IGNORECASE) and re.search(r"fail", text_block, re.IGNORECASE)):
                    gating_ok = False
            # Smoke test failure
            stages = summary.get("stages", [])
            smoke_fail = any(s.get("name") == "smoke_test" and s.get("status") == "FAIL" for s in stages if isinstance(s, dict))
            if smoke_fail:
                if not re.search(r"smoke", text_block, re.IGNORECASE):
                    gating_ok = False
            # Coverage below threshold
            cov = summary.get("coverage", {})
            if isinstance(cov, dict) and cov.get("meets_threshold") is False:
                if not (re.search(r"coverage", text_block, re.IGNORECASE) and re.search(r"threshold|below|raise|increase", text_block, re.IGNORECASE)):
                    gating_ok = False
            if gating_ok:
                decisions_ok = True

        # Action items section and checks
        ai_start, ai_end = _find_section(lines, "Action items")
        actions_tests_ok = False
        actions_stages_ok = False
        actions_cov_ok = False
        if ai_start != -1:
            ai_bullets = _extract_bullets(lines, ai_start, ai_end)

            # Each failing test has an action with correct owner and rationale
            failing = summary.get("tests", {}).get("failing", [])
            if isinstance(failing, list) and api_lead and web_lead:
                ft_all_ok = True
                for ft in failing:
                    name = ft.get("name")
                    service = ft.get("service")
                    if not (isinstance(name, str) and isinstance(service, str)):
                        ft_all_ok = False
                        break
                    owner = api_lead if service == "hauora-api" else (web_lead if service == "kaitiaki-web" else None)
                    if owner is None:
                        ft_all_ok = False
                        break
                    # Find a bullet containing name and owner and a rationale (keywords)
                    found = False
                    for b in ai_bullets:
                        if (name in b and owner in b and
                                (re.search(r"\bbecause\b", b, re.IGNORECASE) or
                                 re.search(r"\bdue to\b", b, re.IGNORECASE) or
                                 re.search(r"\bso that\b", b, re.IGNORECASE) or
                                 re.search(r"\bto\b", b))):
                            found = True
                            break
                    if not found:
                        ft_all_ok = False
                        break
                if ft_all_ok:
                    actions_tests_ok = True

            # One for each failing stage with correct owner
            stages = summary.get("stages", [])
            if isinstance(stages, list) and api_lead and web_lead:
                stage_ok = True
                for st in stages:
                    if not isinstance(st, dict):
                        stage_ok = False
                        break
                    if st.get("status") == "FAIL":
                        nm = st.get("name")
                        if nm == "smoke_test":
                            # expect action mentioning smoke and web lead
                            found = any(re.search(r"smoke", b, re.IGNORECASE) and (web_lead in b) for b in ai_bullets)
                        elif nm == "test":
                            # expect action mentioning test stage and API lead
                            found = any(re.search(r"\btest\b", b, re.IGNORECASE) and (api_lead in b) for b in ai_bullets)
                        else:
                            # generic failing stage; must be mentioned with either web or api lead
                            found = any((nm in b) and ((web_lead in b) or (api_lead in b)) for b in ai_bullets)
                        if not found:
                            stage_ok = False
                            break
                if stage_ok:
                    actions_stages_ok = True

            # One to raise coverage to meet threshold with QA lead
            cov = summary.get("coverage", {})
            if isinstance(cov, dict) and cov.get("meets_threshold") is False and qa_lead:
                coverage_action_found = any(
                    (re.search(r"coverage", b, re.IGNORECASE) and
                     (re.search(r"threshold", b, re.IGNORECASE) or re.search(r"raise|increase|improve", b, re.IGNORECASE)) and
                     (qa_lead in b))
                    for b in ai_bullets
                )
                if coverage_action_found:
                    actions_cov_ok = True

        if context_ok and decisions_ok:
            scores["meeting_notes_context_and_decisions"] = 1.0
        if actions_tests_ok:
            scores["meeting_notes_actions_failing_tests_with_correct_owners"] = 1.0
        if actions_stages_ok:
            scores["meeting_notes_actions_failing_stages_with_correct_owners"] = 1.0
        if actions_cov_ok:
            scores["meeting_notes_action_for_coverage_with_qa_owner"] = 1.0

    # 5) deployment_policy updates
    if policy_text is not None and config is not None:
        # Release cadence line
        rc = config.get("release_cadence")
        if isinstance(rc, str):
            if re.search(rf"Release cadence:\s*{re.escape(rc)}\s*$", policy_text, re.IGNORECASE | re.MULTILINE):
                scores["deployment_policy_release_cadence_updated"] = 1.0
        # Coverage threshold line
        ct = config.get("coverage_threshold")
        if isinstance(ct, int):
            if re.search(rf"Coverage threshold:\s*{ct}\s*%?\s*$", policy_text, re.IGNORECASE | re.MULTILINE):
                scores["deployment_policy_coverage_threshold_updated"] = 1.0
        # Pipeline stages list exactly matches ordered stages in config
        stages = config.get("stages")
        if isinstance(stages, list):
            # Extract pipeline stages section from policy
            lines = policy_text.splitlines()
            # Find "Pipeline stages:" line
            idx = -1
            for i, ln in enumerate(lines):
                if re.match(r"^\s*Pipeline stages:\s*$", ln):
                    idx = i
                    break
            if idx != -1:
                # Collect consecutive dash list items after this line
                items = []
                j = idx + 1
                while j < len(lines):
                    ln = lines[j]
                    m = re.match(r"^\s*-\s*(\S+)\s*$", ln)
                    if m:
                        items.append(m.group(1))
                        j += 1
                        continue
                    else:
                        break
                if items == stages:
                    scores["deployment_policy_pipeline_stages_list_updated"] = 1.0
        # Bilingual release communications subsection at end with exact sentence
        # We will check the presence near the end of the document
        lines = [ln.rstrip() for ln in policy_text.splitlines()]
        # Find last non-empty line index
        last_non_empty = -1
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                last_non_empty = i
                break
        bilingual_ok = False
        if last_non_empty != -1:
            # The subsection title should appear before the sentence
            # Search for title and sentence anywhere, but ensure the sentence is exactly as specified.
            title_idx = None
            for i, ln in enumerate(lines):
                if re.match(r"^\s*Bilingual release communications\s*$", ln, re.IGNORECASE):
                    title_idx = i
            expected_sentence = "All release notes must include a reo Māori summary alongside English."
            sentence_idx = None
            for i, ln in enumerate(lines):
                if ln.strip() == expected_sentence:
                    sentence_idx = i
            if title_idx is not None and sentence_idx is not None and sentence_idx > title_idx:
                # Ensure that this is appended at the end (sentence should be at or near the end)
                if sentence_idx >= len(lines) - 3:
                    bilingual_ok = True
        if bilingual_ok:
            scores["deployment_policy_bilingual_comms_appended"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()