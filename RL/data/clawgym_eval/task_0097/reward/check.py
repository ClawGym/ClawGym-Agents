import json
import os
import sys
import re

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def is_int_positive(x):
    return isinstance(x, int) and not isinstance(x, bool) and x > 0

def deep_iter_values(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from deep_iter_values(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from deep_iter_values(item)
    else:
        yield obj

def extract_step_refs(params, step_ids_set):
    refs = []
    for v in deep_iter_values(params):
        if isinstance(v, str) and v.startswith("$"):
            # Match $step.output... or $step.wave_score
            m = re.match(r"^\$([a-zA-Z0-9_\-]+)\.(output|wave_score)\b", v)
            if m:
                sid = m.group(1)
                if sid in step_ids_set:
                    refs.append(sid)
    return refs

def load_json_safely(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_json_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        nonempty = [ln for ln in lines if ln.strip() != ""]
        parsed = []
        for ln in nonempty:
            try:
                parsed.append(json.loads(ln))
            except Exception:
                return None, None
        return nonempty, parsed
    except Exception:
        return None, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # execute_pipeline.json checks
        "execute_file_exists": False,
        "execute_valid_json": False,
        "execute_top_fields_ok": False,
        "execute_pipeline_name_ok": False,
        "execute_steps_ok": False,
        "execute_params_wiring_ok": False,
        "execute_threshold_and_token_ok": False,
        "execute_no_forward_refs_ok": False,
        # transcript.jsonl checks
        "transcript_file_exists": False,
        "transcript_valid_and_order": False,
        "transcript_pipeline_consistency_ok": False,
        "transcript_stepcomplete_fields_ok": False,
        "transcript_verify_output_ok": False,
        "transcript_export_output_ok": False,
        "transcript_coherence_report_ok": False,
        "transcript_overall_score_meets_threshold_ok": False,
        "transcript_step_scores_ok": False,
        "transcript_conservation_ok": False,
        "transcript_atom_trail_ok": False,
        # readme.txt checks
        "readme_file_exists": False,
        "readme_content_ok": False,
    }

    # Read input references (do not score on reading)
    _ = load_json_safely(os.path.join(input_dir, "manifest.json"))
    _ = load_json_safely(os.path.join(input_dir, "idea.json"))

    expected_step_order = ["spark", "expand", "visual", "verify", "assemble", "export"]
    expected_actions = {
        "spark": "create_note",
        "expand": "ai_expand",
        "visual": "generate_figure",
        "verify": "wave_check",
        "assemble": "merge_notes",
        "export": "export_pdf",
    }

    # 1) Validate execute_pipeline.json
    exec_path = os.path.join(output_dir, "execution", "execute_pipeline.json")
    exec_data = None
    if os.path.isfile(exec_path):
        checks["execute_file_exists"] = True
        exec_data = load_json_safely(exec_path)
        if isinstance(exec_data, dict):
            checks["execute_valid_json"] = True

            # Top-level fields
            jsonrpc_ok = exec_data.get("jsonrpc") == "2.0"
            method_ok = exec_data.get("method") == "EXECUTE_PIPELINE"
            id_ok = isinstance(exec_data.get("id"), (int, float)) and not isinstance(exec_data.get("id"), bool)
            if jsonrpc_ok and method_ok and id_ok:
                checks["execute_top_fields_ok"] = True

            # Pipeline name
            params = exec_data.get("params")
            if isinstance(params, dict):
                if params.get("pipeline") == "idea-to-publish":
                    checks["execute_pipeline_name_ok"] = True

                # Steps existence and order + actions
                steps = params.get("steps")
                if isinstance(steps, list) and len(steps) == 6:
                    ids = [s.get("id") for s in steps if isinstance(s, dict)]
                    actions = [s.get("action") for s in steps if isinstance(s, dict)]
                    if ids == expected_step_order:
                        # actions must map exactly as expected
                        actions_ok = True
                        for sid, act in zip(ids, actions):
                            if act != expected_actions.get(sid):
                                actions_ok = False
                                break
                        if actions_ok:
                            checks["execute_steps_ok"] = True

                    # Param wiring checks
                    wiring_ok = False
                    if checks["execute_steps_ok"]:
                        step_map = {s["id"]: s for s in steps}
                        try:
                            # spark
                            spark_params = step_map["spark"].get("params", {})
                            cond_spark = (
                                isinstance(spark_params, dict) and
                                spark_params.get("title") == "$INPUT.title" and
                                spark_params.get("content") == "$INPUT.description"
                            )
                            # expand
                            expand_params = step_map["expand"].get("params", {})
                            cond_expand = (
                                isinstance(expand_params, dict) and
                                expand_params.get("note_id") == "$spark.output.id"
                            )
                            # visual
                            visual_params = step_map["visual"].get("params", {})
                            cond_visual = (
                                isinstance(visual_params, dict) and
                                visual_params.get("note_id") == "$expand.output.id"
                            )
                            # verify
                            verify_params = step_map["verify"].get("params", {})
                            cond_verify = (
                                isinstance(verify_params, dict) and
                                verify_params.get("content") == "$expand.output.content"
                            )
                            # assemble
                            assemble_params = step_map["assemble"].get("params", {})
                            ids_list = assemble_params.get("ids") if isinstance(assemble_params, dict) else None
                            title_val = assemble_params.get("title") if isinstance(assemble_params, dict) else None
                            cond_assemble = (
                                isinstance(ids_list, list) and
                                "$spark.output.id" in ids_list and
                                "$expand.output.id" in ids_list and
                                title_val == "DRAFT: $INPUT.title"
                            )
                            # export
                            export_params = step_map["export"].get("params", {})
                            cond_export = (
                                isinstance(export_params, dict) and
                                export_params.get("note_id") == "$assemble.output.id"
                            )

                            wiring_ok = cond_spark and cond_expand and cond_visual and cond_verify and cond_assemble and cond_export
                        except Exception:
                            wiring_ok = False

                    if wiring_ok:
                        checks["execute_params_wiring_ok"] = True

                    # No forward references
                    no_forward_ok = False
                    try:
                        id_to_index = {sid: idx for idx, sid in enumerate(expected_step_order)}
                        forward_violation = False
                        for idx, s in enumerate(steps):
                            sid = s.get("id")
                            params_s = s.get("params", {})
                            if isinstance(params_s, (dict, list)):
                                refs = extract_step_refs(params_s, set(expected_step_order))
                                for ref_sid in refs:
                                    if id_to_index.get(ref_sid, -1) >= idx:
                                        forward_violation = True
                                        break
                            if forward_violation:
                                break
                        no_forward_ok = not forward_violation
                    except Exception:
                        no_forward_ok = False
                    if no_forward_ok:
                        checks["execute_no_forward_refs_ok"] = True

                # Threshold and atom token
                th_ok = False
                token_ok = False
                if isinstance(params, dict):
                    th = params.get("coherence_threshold")
                    atom_token = params.get("atom_token")
                    if is_number(th) and 0.85 <= float(th) <= 1.0:
                        th_ok = True
                    if isinstance(atom_token, str) and atom_token.strip() != "":
                        token_ok = True
                if th_ok and token_ok:
                    checks["execute_threshold_and_token_ok"] = True

    # Extract coherence_threshold for transcript comparison
    exec_threshold = None
    if exec_data and isinstance(exec_data, dict):
        prms = exec_data.get("params", {})
        if isinstance(prms, dict):
            th = prms.get("coherence_threshold")
            if is_number(th):
                exec_threshold = float(th)

    # 2) Validate transcript.jsonl
    transcript_path = os.path.join(output_dir, "execution", "transcript.jsonl")
    transcript_lines, transcript = load_json_lines(transcript_path)
    if transcript_lines is not None and transcript is not None:
        checks["transcript_file_exists"] = True

        # Must be exactly 7 non-empty lines: 6 STEP_COMPLETE then 1 COHERENCE_REPORT
        order_ok = False
        pid_consistent = False
        stepcomplete_fields_ok = False
        verify_ok = False
        export_ok = False
        coh_ok = False
        overall_vs_threshold_ok = False
        step_scores_ok = False
        conservation_ok = False
        atom_trail_ok = False

        if len(transcript) == 7:
            # First six: STEP_COMPLETE in expected step order
            sc_ok = True
            ids_seen = []
            pipeline_ids = []
            for i, expected_sid in enumerate(expected_step_order):
                entry = transcript[i]
                if not (isinstance(entry, dict) and entry.get("jsonrpc") == "2.0" and entry.get("method") == "STEP_COMPLETE"):
                    sc_ok = False
                    break
                params = entry.get("params")
                if not isinstance(params, dict):
                    sc_ok = False
                    break
                pid = params.get("pipeline_id")
                sid = params.get("step_id")
                status = params.get("status")
                output = params.get("output")
                wave_score = params.get("wave_score")
                duration_ms = params.get("duration_ms")

                if not (isinstance(pid, str) and pid.strip() != ""):
                    sc_ok = False
                    break
                pipeline_ids.append(pid)

                if sid != expected_sid:
                    sc_ok = False
                    break
                ids_seen.append(sid)

                if status != "complete":
                    sc_ok = False
                    break

                if not isinstance(output, dict):
                    sc_ok = False
                    break

                if not (is_number(wave_score) and 0.0 <= float(wave_score) <= 1.0):
                    sc_ok = False
                    break

                if not is_int_positive(duration_ms):
                    sc_ok = False
                    break

                # Special checks for verify and export
                if sid == "verify":
                    sc = output.get("score")
                    ps = output.get("pass")
                    if not (is_number(sc) and 0.0 <= float(sc) <= 1.0 and isinstance(ps, bool)):
                        verify_ok = False
                        sc_ok = False
                        break
                    else:
                        verify_ok = True
                if sid == "export":
                    pth = output.get("path")
                    sz = output.get("size_bytes")
                    if not (isinstance(pth, str) and pth.strip() != "" and is_int_positive(sz)):
                        export_ok = False
                        sc_ok = False
                        break
                    else:
                        export_ok = True

            if sc_ok and ids_seen == expected_step_order:
                stepcomplete_fields_ok = True
                order_ok = True
                # pipeline id consistency across all 7 messages checked later including the 7th
                pid_all = pipeline_ids[:]

                # 7th line: COHERENCE_REPORT
                final_entry = transcript[6]
                if isinstance(final_entry, dict) and final_entry.get("jsonrpc") == "2.0" and final_entry.get("method") == "COHERENCE_REPORT":
                    final_params = final_entry.get("params")
                    if isinstance(final_params, dict):
                        pid7 = final_params.get("pipeline_id")
                        if isinstance(pid7, str) and pid7.strip() != "":
                            pid_all.append(pid7)
                            # Consistency: all are equal
                            pid_consistent = all(p == pid_all[0] for p in pid_all)

                        overall = final_params.get("overall_score")
                        step_scores = final_params.get("step_scores")
                        cons = final_params.get("conservation_check")
                        atom_trail_id = final_params.get("atom_trail_id")

                        coh_ok = is_number(overall) and 0.0 <= float(overall) <= 1.0

                        # overall >= execute_threshold
                        if exec_threshold is not None and coh_ok:
                            overall_vs_threshold_ok = float(overall) >= float(exec_threshold)
                        else:
                            # If threshold missing or invalid in execute, cannot pass
                            overall_vs_threshold_ok = False

                        # step_scores contains all six with values in [0,1]
                        if isinstance(step_scores, dict):
                            present_all = True
                            for sid in expected_step_order:
                                val = step_scores.get(sid, None)
                                if not (is_number(val) and 0.0 <= float(val) <= 1.0):
                                    present_all = False
                                    break
                            step_scores_ok = present_all
                        else:
                            step_scores_ok = False

                        # conservation check
                        if isinstance(cons, dict):
                            alpha = cons.get("alpha")
                            omega = cons.get("omega")
                            valid = cons.get("valid")
                            if isinstance(alpha, int) and not isinstance(alpha, bool) and \
                               isinstance(omega, int) and not isinstance(omega, bool) and \
                               (alpha + omega == 15) and (valid is True):
                                conservation_ok = True
                        # atom trail id
                        if isinstance(atom_trail_id, str) and atom_trail_id.strip() != "":
                            atom_trail_ok = True

        if order_ok:
            checks["transcript_valid_and_order"] = True
        if pid_consistent:
            checks["transcript_pipeline_consistency_ok"] = True
        if stepcomplete_fields_ok:
            checks["transcript_stepcomplete_fields_ok"] = True
        if verify_ok:
            checks["transcript_verify_output_ok"] = True
        if export_ok:
            checks["transcript_export_output_ok"] = True
        if coh_ok:
            checks["transcript_coherence_report_ok"] = True
        if overall_vs_threshold_ok:
            checks["transcript_overall_score_meets_threshold_ok"] = True
        if step_scores_ok:
            checks["transcript_step_scores_ok"] = True
        if conservation_ok:
            checks["transcript_conservation_ok"] = True
        if atom_trail_ok:
            checks["transcript_atom_trail_ok"] = True

    # 3) Validate readme.txt
    readme_path = os.path.join(output_dir, "execution", "readme.txt")
    if os.path.isfile(readme_path):
        checks["readme_file_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                content = f.read()
            target = "spark,expand,visual,verify,assemble,export"
            # Accept exactly the target or the target with a single trailing newline (no extra whitespace)
            if content == target or content == target + "\n":
                checks["readme_content_ok"] = True
        except Exception:
            pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0
    # Ensure reward in [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()