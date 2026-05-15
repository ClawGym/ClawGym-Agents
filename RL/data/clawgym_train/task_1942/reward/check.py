import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_frontmatter(markdown_text):
    # Expect YAML frontmatter at top between '---' lines
    if markdown_text is None:
        return {}, ""
    lines = markdown_text.splitlines()
    fm = {}
    body = markdown_text
    if len(lines) >= 3 and lines[0].strip() == "---":
        # find closing ---
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is not None:
            fm_lines = lines[1:end_idx]
            body = "\n".join(lines[end_idx+1:])
            for ln in fm_lines:
                # simple key: value parser
                if ":" in ln:
                    key, val = ln.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    # strip surrounding quotes if any
                    if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
                        val = val[1:-1]
                    fm[key] = val
    return fm, body

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def approx_equal_seconds(sec, ms, tol=0.2):
    try:
        return abs(sec - (ms / 1000.0)) <= tol
    except Exception:
        return False

def has_required_heading(body_text, keyword):
    if body_text is None:
        return False
    for line in body_text.splitlines():
        if line.strip().startswith("##"):
            if keyword.lower() in line.lower():
                return True
    return False

def find_eval_dirs(iter_dir):
    if not os.path.isdir(iter_dir):
        return []
    dirs = []
    for name in os.listdir(iter_dir):
        full = os.path.join(iter_dir, name)
        if os.path.isdir(full):
            dirs.append(name)
    return dirs

def validate_eval_dir_name(name):
    # must contain a hyphen and not be exactly 'eval-0' or 'eval-1'
    if name in ("eval-0", "eval-1"):
        return False
    return "-" in name

def validate_assertions(obj):
    return isinstance(obj, list) and len(obj) >= 2

def validate_outputs_dir_has_file(outputs_path):
    if not os.path.isdir(outputs_path):
        return False
    for fn in os.listdir(outputs_path):
        if fn.lower().endswith(".txt") or fn.lower().endswith(".json"):
            full = os.path.join(outputs_path, fn)
            if os.path.isfile(full):
                return True
    return False

def validate_timing_json(path):
    data = read_json(path)
    if not isinstance(data, dict):
        return False
    tt = data.get("total_tokens")
    dm = data.get("duration_ms")
    ds = data.get("total_duration_seconds")
    if not (is_number(tt) and is_number(dm) and is_number(ds)):
        return False
    return approx_equal_seconds(float(ds), float(dm), tol=0.2)

def validate_grading_json(path):
    data = read_json(path)
    if not isinstance(data, dict):
        return False
    exps = data.get("expectations")
    if not isinstance(exps, list) or len(exps) == 0:
        return False
    for e in exps:
        if not isinstance(e, dict):
            return False
        if "text" not in e or "passed" not in e or "evidence" not in e:
            return False
        if not isinstance(e["text"], str):
            return False
        if not isinstance(e["passed"], bool):
            return False
        if not isinstance(e["evidence"], str):
            return False
    return True

def collect_pass_fail_from_grading(path):
    data = read_json(path)
    passed_any = False
    failed_any = False
    if isinstance(data, dict) and isinstance(data.get("expectations"), list):
        for e in data["expectations"]:
            if isinstance(e, dict) and isinstance(e.get("passed"), bool):
                if e["passed"]:
                    passed_any = True
                else:
                    failed_any = True
    return passed_any, failed_any

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Skill file checks
        "skill_file_exists": False,
        "skill_frontmatter_has_name": False,
        "skill_frontmatter_has_description": False,
        "skill_description_has_use_when": False,
        "skill_description_has_even_if": False,
        "skill_body_has_examples_heading": False,
        "skill_body_has_output_heading": False,
        # Evals definition checks
        "evals_json_exists": False,
        "evals_json_parses": False,
        "evals_json_has_skill_name": False,
        "evals_json_has_evals_array_len2": False,
        "evals_items_valid": False,
        # Workspace structure checks
        "workspace_iteration_exists": False,
        "workspace_has_two_eval_dirs": False,
        "eval_dir_names_descriptive": False,
        "all_eval_metadata_present": False,
        "all_eval_metadata_fields_valid": False,
        "all_runs_have_outputs_dirs": False,
        "outputs_files_present_and_valid": False,
        "all_timing_jsons_valid": False,
        "all_grading_jsons_valid": False,
        "per_eval_variation_pass_and_fail": False,
        # Benchmark checks
        "benchmark_exists": False,
        "benchmark_parses": False,
        "benchmark_has_required_fields": False,
        "benchmark_configs_named_with_fields": False,
        "benchmark_skill_name_matches": False,
    }

    # Paths
    skill_md_path = os.path.join(output_dir, "meeting-notes-skill", "SKILL.md")
    evals_json_path = os.path.join(output_dir, "meeting-notes-skill", "evals", "evals.json")
    iteration_dir = os.path.join(output_dir, "meeting-notes-skill-workspace", "iteration-1")
    benchmark_path = os.path.join(iteration_dir, "benchmark.json")

    # Skill checks
    skill_text = read_text(skill_md_path)
    if skill_text is not None:
        checks["skill_file_exists"] = True
        fm, body = parse_frontmatter(skill_text)
        name_val = fm.get("name")
        desc_val = fm.get("description")
        if isinstance(name_val, str) and len(name_val.strip()) > 0:
            checks["skill_frontmatter_has_name"] = True
        if isinstance(desc_val, str) and len(desc_val.strip()) > 0:
            checks["skill_frontmatter_has_description"] = True
            if "use when" in desc_val.lower():
                checks["skill_description_has_use_when"] = True
            if "even if" in desc_val.lower():
                checks["skill_description_has_even_if"] = True
        # Body headings
        if has_required_heading(body, "examples"):
            checks["skill_body_has_examples_heading"] = True
        if has_required_heading(body, "output"):
            checks["skill_body_has_output_heading"] = True
    else:
        fm = {}
        body = ""

    skill_name_from_md = fm.get("name") if isinstance(fm, dict) else None

    # Evals definition checks
    evals_data = None
    if os.path.isfile(evals_json_path):
        checks["evals_json_exists"] = True
        evals_data = read_json(evals_json_path)
        if isinstance(evals_data, dict):
            checks["evals_json_parses"] = True
            skill_name_field = evals_data.get("skill_name")
            if isinstance(skill_name_field, str) and len(skill_name_field.strip()) > 0:
                checks["evals_json_has_skill_name"] = True
            evals_list = evals_data.get("evals")
            if isinstance(evals_list, list) and len(evals_list) >= 2:
                checks["evals_json_has_evals_array_len2"] = True
                # validate items
                items_ok = True
                for item in evals_list:
                    if not isinstance(item, dict):
                        items_ok = False
                        break
                    if not is_number(item.get("id")):
                        items_ok = False
                        break
                    if not (isinstance(item.get("prompt"), str) and len(item.get("prompt").strip()) > 0):
                        items_ok = False
                        break
                    if not isinstance(item.get("expected_output"), str):
                        items_ok = False
                        break
                    if not isinstance(item.get("files"), list):
                        items_ok = False
                        break
                if items_ok:
                    checks["evals_items_valid"] = True
        # else parse failure leaves related checks False
    skill_name_from_evals = None
    if isinstance(evals_data, dict):
        sn = evals_data.get("skill_name")
        if isinstance(sn, str) and sn.strip():
            skill_name_from_evals = sn.strip()

    # Workspace iteration structure
    if os.path.isdir(iteration_dir):
        checks["workspace_iteration_exists"] = True
        eval_dirs = [d for d in find_eval_dirs(iteration_dir) if d != "__pycache__"]
        # Filter out non-eval known files like benchmark.json
        eval_dirs = [d for d in eval_dirs if os.path.isdir(os.path.join(iteration_dir, d))]
        # Must have at least two
        if len(eval_dirs) >= 2:
            checks["workspace_has_two_eval_dirs"] = True
            # Names descriptive
            names_ok = all(validate_eval_dir_name(n) for n in eval_dirs)
            if names_ok:
                checks["eval_dir_names_descriptive"] = True

            # For each eval dir, check eval_metadata.json and runs
            all_meta_present = True
            all_meta_fields_valid = True
            all_runs_have_outputs_dirs = True
            outputs_files_ok = True
            all_timing_ok = True
            all_grading_ok = True
            per_eval_variation_all = True  # requires each eval to have variation across runs

            for ed in eval_dirs:
                ed_path = os.path.join(iteration_dir, ed)
                meta_path = os.path.join(ed_path, "eval_metadata.json")
                if not os.path.isfile(meta_path):
                    all_meta_present = False
                    all_meta_fields_valid = False
                else:
                    meta = read_json(meta_path)
                    if not isinstance(meta, dict):
                        all_meta_fields_valid = False
                    else:
                        eval_id_ok = is_number(meta.get("eval_id"))
                        eval_name_ok = isinstance(meta.get("eval_name"), str) and len(meta.get("eval_name").strip()) > 0
                        prompt_ok = isinstance(meta.get("prompt"), str) and len(meta.get("prompt").strip()) > 0
                        assertions_ok = validate_assertions(meta.get("assertions"))
                        if not (eval_id_ok and eval_name_ok and prompt_ok and assertions_ok):
                            all_meta_fields_valid = False

                # Runs
                run_variation_pass_any = False
                run_variation_fail_any = False
                for run_name in ("with_skill", "without_skill"):
                    run_dir = os.path.join(ed_path, run_name)
                    outputs_dir = os.path.join(run_dir, "outputs")
                    timing_path = os.path.join(run_dir, "timing.json")
                    grading_path = os.path.join(run_dir, "grading.json")
                    # outputs dir existence
                    if not os.path.isdir(outputs_dir):
                        all_runs_have_outputs_dirs = False
                    # outputs file exists and valid extension
                    if not validate_outputs_dir_has_file(outputs_dir):
                        outputs_files_ok = False
                    # timing.json
                    if not (os.path.isfile(timing_path) and validate_timing_json(timing_path)):
                        all_timing_ok = False
                    # grading.json
                    if not (os.path.isfile(grading_path) and validate_grading_json(grading_path)):
                        all_grading_ok = False
                    # collect variation
                    p_any, f_any = collect_pass_fail_from_grading(grading_path) if os.path.isfile(grading_path) else (False, False)
                    run_variation_pass_any = run_variation_pass_any or p_any
                    run_variation_fail_any = run_variation_fail_any or f_any

                # per-eval variation requires at least one pass True and one False across the two runs
                if not (run_variation_pass_any and run_variation_fail_any):
                    per_eval_variation_all = False

            if all_meta_present:
                checks["all_eval_metadata_present"] = True
            if all_meta_fields_valid and all_meta_present:
                checks["all_eval_metadata_fields_valid"] = True
            if all_runs_have_outputs_dirs:
                checks["all_runs_have_outputs_dirs"] = True
            if outputs_files_ok and all_runs_have_outputs_dirs:
                checks["outputs_files_present_and_valid"] = True
            if all_timing_ok:
                checks["all_timing_jsons_valid"] = True
            if all_grading_ok:
                checks["all_grading_jsons_valid"] = True
            if per_eval_variation_all and checks["all_grading_jsons_valid"]:
                checks["per_eval_variation_pass_and_fail"] = True

    # Benchmark checks
    benchmark_data = None
    if os.path.isfile(benchmark_path):
        checks["benchmark_exists"] = True
        benchmark_data = read_json(benchmark_path)
        if isinstance(benchmark_data, dict):
            checks["benchmark_parses"] = True
            # required fields
            has_skill_name = isinstance(benchmark_data.get("skill_name"), str) and len(benchmark_data.get("skill_name").strip()) > 0
            configs = benchmark_data.get("configs")
            notes_ok = isinstance(benchmark_data.get("notes"), str)
            if has_skill_name and isinstance(configs, list) and len(configs) == 2 and notes_ok:
                checks["benchmark_has_required_fields"] = True
                # configs named with fields
                required_names = {"with_skill", "without_skill"}
                seen_names = set()
                configs_fields_ok = True
                for cfg in configs:
                    if not isinstance(cfg, dict):
                        configs_fields_ok = False
                        break
                    name_val = cfg.get("name")
                    if not isinstance(name_val, str):
                        configs_fields_ok = False
                        break
                    seen_names.add(name_val)
                    pr = cfg.get("pass_rate")
                    adm = cfg.get("avg_duration_ms")
                    atok = cfg.get("avg_tokens")
                    if not (is_number(pr) and 0.0 <= float(pr) <= 1.0 and is_number(adm) and is_number(atok)):
                        configs_fields_ok = False
                        break
                if configs_fields_ok and seen_names == required_names:
                    checks["benchmark_configs_named_with_fields"] = True

            # skill name matches either SKILL.md name or evals.json skill_name
            if isinstance(benchmark_data, dict) and isinstance(benchmark_data.get("skill_name"), str):
                bname = benchmark_data.get("skill_name").strip()
                md_name = skill_name_from_md.strip() if isinstance(skill_name_from_md, str) else None
                ev_name = skill_name_from_evals.strip() if isinstance(skill_name_from_evals, str) else None
                if bname and (bname == md_name or bname == ev_name):
                    checks["benchmark_skill_name_matches"] = True

    # Compute reward as ratio of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # No-op baseline: if output directory missing or empty of required artifacts, reward should be 0.0
    # Our ratio will naturally be 0.0 if nothing passes.
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure numeric bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()