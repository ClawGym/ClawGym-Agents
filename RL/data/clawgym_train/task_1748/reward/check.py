import json
import os
import sys
import csv
from typing import List, Dict

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return []

def parse_updates_jsonl(path):
    completed = 0
    escalated = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                status = obj.get("status")
                if status == "completed":
                    completed += 1
                if status == "blocked":
                    days_blocked = obj.get("days_blocked")
                    try:
                        if days_blocked is not None and int(days_blocked) >= 3:
                            escalated += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return completed, escalated

def parse_resources_csv(path):
    # Return dict: name -> set of projects where critical == True
    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            sniffer = csv.Sniffer()
            sample = f.read(1024)
            f.seek(0)
            dialect = None
            try:
                dialect = sniffer.sniff(sample)
            except Exception:
                pass
            reader = csv.DictReader(f, dialect=dialect) if dialect else csv.DictReader(f)
            headers = [h.lower() for h in reader.fieldnames] if reader.fieldnames else []
            name_key = None
            project_key = None
            critical_key = None
            for h in headers:
                if h in ["name", "resource", "person"]:
                    name_key = name_key or h
                if h in ["project", "project_name"]:
                    project_key = project_key or h
                if h in ["critical", "is_critical", "critical_flag"]:
                    critical_key = critical_key or h
            if not (name_key and project_key and critical_key):
                return result
            for row in reader:
                name = row.get(name_key, "").strip()
                project = row.get(project_key, "").strip()
                crit_val = str(row.get(critical_key, "")).strip().lower()
                is_critical = crit_val in ["true", "1", "yes", "y", "t"]
                if not name or not project:
                    continue
                if is_critical:
                    result.setdefault(name, set()).add(project)
    except Exception:
        pass
    return result

def parse_prompts_raw_count(path):
    # Count number of raw prompts separated by blank lines or lines starting with ---
    lines = read_lines(path)
    text = "".join(lines).strip()
    if not text:
        return 0
    # Simple heuristic: split on two or more newlines
    blocks = [b for b in text.split("\n\n") if b.strip()]
    # Aim for 2 prompts; but if not reliable, fall back to counting lines starting with "Prompt"
    if len(blocks) >= 2:
        return 2
    # Fallback
    count = 0
    for line in lines:
        if line.strip():
            count += 1
            break
    # default assume 2 per task spec
    return 2

def extract_paper_title(path):
    # Get first markdown H1 line as title
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("#"):
                    # remove leading '# ' or '### '
                    title = s.lstrip("#").strip()
                    return title
    except Exception:
        pass
    return None

def count_nonempty_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return None

def read_csv_numeric_series(path):
    # Try to read a numeric series from CSV. Prefer column named 'y'.
    values = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return []
        # Detect header
        header = rows[0]
        has_header = any(any(c.isalpha() for c in cell) for cell in header)
        if has_header:
            # Use DictReader
            with open(path, "r", encoding="utf-8") as f2:
                dr = csv.DictReader(f2)
                fieldnames = [fn.strip() for fn in dr.fieldnames] if dr.fieldnames else []
                target_field = None
                for fn in fieldnames:
                    if fn.lower() == "y":
                        target_field = fn
                        break
                if target_field is None and fieldnames:
                    # Try first field that can be parsed as float for most rows
                    for fn in fieldnames:
                        cnt = 0
                        total = 0
                        for row in rows[1:]:
                            try:
                                idx = fieldnames.index(fn)
                                val = row[idx]
                                if val.strip() != "":
                                    float(val)
                                    cnt += 1
                            except Exception:
                                pass
                            total += 1
                        if cnt >= max(1, total // 2):
                            target_field = fn
                            break
                if target_field is None:
                    # fallback to first field
                    target_field = fieldnames[0] if fieldnames else None
                for row in dr:
                    try:
                        v = float(row[target_field])
                        values.append(v)
                    except Exception:
                        continue
        else:
            # No header: assume first column numeric
            for r in rows:
                if not r:
                    continue
                try:
                    values.append(float(r[0]))
                except Exception:
                    continue
    except Exception:
        return []
    return values

def compute_cma_mse(values: List[float]):
    # One-step-ahead CMA: for t=2..N, predict mean(y1..y_{t-1})
    n = len(values)
    if n < 2:
        return None
    errs = []
    running_sum = values[0]
    for t in range(1, n):
        pred = running_sum / t
        err = values[t] - pred
        errs.append(err * err)
        running_sum += values[t]
    mse = sum(errs) / len(errs) if errs else None
    return mse

def parse_sections_for_prompts(md_path):
    lines = read_lines(md_path)
    sections = []
    # Identify section starts by lines containing "Contract" or "Framework"
    indices = []
    for i, line in enumerate(lines):
        if "Contract" in line:
            indices.append((i, "Contract"))
        elif "Framework" in line:
            indices.append((i, "Framework"))
    indices.append((len(lines), None))  # sentinel
    for idx in range(len(indices) - 1):
        start_i, sec_type = indices[idx]
        end_i, _ = indices[idx + 1]
        content = "".join(lines[start_i:end_i])
        sections.append({"type": sec_type, "content": content, "heading": lines[start_i].strip() if start_i < len(lines) else ""})
    return sections

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # Project plan
        "project_plan_exists": False,
        "project_plan_name_ok": False,
        "project_plan_phases_ok": False,
        "project_plan_tasks_ok": False,
        "project_plan_buffer_percent_ok": False,
        "project_plan_critical_path_ok": False,
        "project_plan_risks_ok": False,
        # Status reports
        "status_client_exists_and_audience": False,
        "status_team_exists_and_audience": False,
        # Status summary
        "status_summary_exists_and_valid": False,
        # Scope tradeoffs
        "scope_tradeoffs_exists_and_length": False,
        "scope_tradeoffs_fields_valid": False,
        # Portfolio conflicts
        "portfolio_conflicts_exists": False,
        "portfolio_conflicts_valid": False,
        # Prompts optimized
        "prompts_optimized_exists": False,
        "prompts_contract_sections_two": False,
        "prompts_contract_sections_labels": False,
        "prompts_framework_sections_two": False,
        "prompts_framework_named": False,
        # Paper reproduction
        "repro_plan_sections_present": False,
        "repro_algorithm_py_ok": False,
        "repro_run_py_ok": False,
        "repro_config_ok": False,
        "repro_logs_exist": False,
        "repro_results_ok": False,
        "repro_readme_en_ok": False,
        "repro_readme_cn_exists": False,
    }

    # 1) Project plan
    project_plan_path = os.path.join(output_dir, "project_plan.json")
    if os.path.isfile(project_plan_path):
        checks["project_plan_exists"] = True
        data = safe_read_json(project_plan_path)
        if isinstance(data, dict):
            if data.get("project_name") == "Client Analytics Dashboard":
                checks["project_plan_name_ok"] = True
            # phases
            phases = data.get("phases")
            if isinstance(phases, list) and len(phases) >= 3:
                checks["project_plan_phases_ok"] = True
            # tasks validation
            tasks = data.get("tasks")
            valid_tasks = False
            if isinstance(tasks, list) and len(tasks) > 0:
                ids = set()
                task_list_ok = True
                for t in tasks:
                    if not isinstance(t, dict):
                        task_list_ok = False
                        break
                    tid = t.get("id")
                    dur = t.get("duration_days")
                    deps = t.get("dependencies")
                    if not isinstance(tid, str) or tid == "":
                        task_list_ok = False
                        break
                    ids.add(tid)
                    if not isinstance(dur, int) or not (1 <= dur <= 5):
                        task_list_ok = False
                        break
                    if deps is None:
                        deps = []
                    if not isinstance(deps, list):
                        task_list_ok = False
                        break
                # dependency references
                if task_list_ok:
                    for t in tasks:
                        deps = t.get("dependencies") or []
                        for d in deps:
                            if d not in ids:
                                task_list_ok = False
                                break
                        if not task_list_ok:
                            break
                valid_tasks = task_list_ok
            if valid_tasks:
                checks["project_plan_tasks_ok"] = True

            # buffer_percent
            buf_val = None
            if "buffer_percent" in data:
                buf_val = data.get("buffer_percent")
            elif "timeline" in data and isinstance(data.get("timeline"), dict) and "buffer_percent" in data["timeline"]:
                buf_val = data["timeline"].get("buffer_percent")
            try:
                if buf_val is not None:
                    fv = float(buf_val)
                    if 0.30 <= fv <= 0.50:
                        checks["project_plan_buffer_percent_ok"] = True
            except Exception:
                pass

            # critical_path
            cp = data.get("critical_path")
            if isinstance(cp, list) and len(cp) > 0:
                # ensure each id present in tasks
                if isinstance(tasks, list):
                    tidset = {t.get("id") for t in tasks if isinstance(t, dict) and isinstance(t.get("id"), str)}
                    if all((isinstance(x, str) and x in tidset) for x in cp):
                        checks["project_plan_critical_path_ok"] = True

            # risks
            risks = data.get("risks")
            if isinstance(risks, list) and 3 <= len(risks) <= 5:
                ok = True
                for r in risks:
                    if not isinstance(r, dict):
                        ok = False
                        break
                    mit = r.get("mitigation")
                    if not isinstance(mit, str) or not mit.strip():
                        ok = False
                        break
                if ok:
                    checks["project_plan_risks_ok"] = True

    # 2) Status reports
    client_report_path = os.path.join(output_dir, "status_report_client.md")
    team_report_path = os.path.join(output_dir, "status_report_team.md")
    # Client
    if os.path.isfile(client_report_path):
        lines = read_lines(client_report_path)
        first_nonempty = ""
        for l in lines:
            s = l.strip()
            if s:
                first_nonempty = s
                break
        if first_nonempty and "audience: client" in first_nonempty.lower():
            checks["status_client_exists_and_audience"] = True
    # Team
    if os.path.isfile(team_report_path):
        lines = read_lines(team_report_path)
        first_nonempty = ""
        for l in lines:
            s = l.strip()
            if s:
                first_nonempty = s
                break
        if first_nonempty and "audience: team" in first_nonempty.lower():
            checks["status_team_exists_and_audience"] = True

    # 3) Status summary
    status_summary_path = os.path.join(output_dir, "status", "summary.json")
    updates_path = os.path.join(input_dir, "updates.jsonl")
    expected_completed, expected_escalated = parse_updates_jsonl(updates_path)
    summary = safe_read_json(status_summary_path) if os.path.isfile(status_summary_path) else None
    if isinstance(summary, dict):
        ct = summary.get("completed_tasks")
        eb = summary.get("escalated_blockers")
        if isinstance(ct, int) and isinstance(eb, int):
            if ct == expected_completed and eb == expected_escalated:
                checks["status_summary_exists_and_valid"] = True

    # 4) Scope tradeoffs
    scope_out_path = os.path.join(output_dir, "scope_tradeoffs.json")
    scope_in_path = os.path.join(input_dir, "scope_requests.json")
    input_scope = safe_read_json(scope_in_path)
    output_scope = safe_read_json(scope_out_path) if os.path.isfile(scope_out_path) else None
    if isinstance(input_scope, list) and isinstance(output_scope, list):
        if len(input_scope) == len(output_scope):
            checks["scope_tradeoffs_exists_and_length"] = True
        # Fields validation
        valid = True
        input_ids = {item.get("id") for item in input_scope if isinstance(item, dict)}
        for item in output_scope:
            if not isinstance(item, dict):
                valid = False
                break
            if item.get("id") not in input_ids:
                valid = False
                break
            etd = item.get("extend_timeline_days")
            if not isinstance(etd, int) or etd < 0:
                valid = False
                break
            swap_feature = item.get("swap_feature", None)
            if swap_feature is not None and not isinstance(swap_feature, str):
                valid = False
                break
            if "phase_two" not in item or not isinstance(item.get("phase_two"), bool):
                valid = False
                break
            rec = item.get("recommendation")
            if rec not in {"extend_timeline", "swap", "phase_two"}:
                valid = False
                break
            rationale = item.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                valid = False
                break
        if isinstance(output_scope, list) and valid and len(output_scope) == len(input_scope):
            checks["scope_tradeoffs_fields_valid"] = True

    # 5) Portfolio conflicts
    conflicts_path = os.path.join(output_dir, "portfolio_conflicts.json")
    conflicts_out = safe_read_json(conflicts_path) if os.path.isfile(conflicts_path) else None
    if os.path.isfile(conflicts_path) and isinstance(conflicts_out, list):
        checks["portfolio_conflicts_exists"] = True
        expected_map = parse_resources_csv(os.path.join(input_dir, "resources.csv"))
        expected_conflicts = {name: projs for name, projs in expected_map.items() if len(projs) >= 2}
        ok = True
        if expected_conflicts:
            # Ensure each expected name appears at least once with projects length >=2
            for name in expected_conflicts:
                found = False
                for item in conflicts_out:
                    if isinstance(item, dict) and item.get("name") == name:
                        projects = item.get("projects")
                        if isinstance(projects, list) and len(set([p for p in projects if isinstance(p, str)])) >= 2:
                            found = True
                            break
                if not found:
                    ok = False
                    break
        else:
            # If no expected conflicts, consider valid if the file is an array (can be empty)
            ok = True
        if ok:
            checks["portfolio_conflicts_valid"] = True

    # 6) Prompts optimized
    prompts_out_path = os.path.join(output_dir, "prompts", "optimized_prompts.md")
    if os.path.isfile(prompts_out_path):
        checks["prompts_optimized_exists"] = True
        sections = parse_sections_for_prompts(prompts_out_path)
        contract_sections = [s for s in sections if s["type"] == "Contract"]
        framework_sections = [s for s in sections if s["type"] == "Framework"]
        # Need at least two of each
        if len(contract_sections) >= 2:
            checks["prompts_contract_sections_two"] = True
            # Check labels in first two contract sections
            labels_ok = True
            needed_labels = ["Role:", "Task:", "Constraints:", "Output:"]
            for cs in contract_sections[:2]:
                content = cs["content"]
                for lab in needed_labels:
                    if lab not in content:
                        labels_ok = False
                        break
                if not labels_ok:
                    break
            if labels_ok:
                checks["prompts_contract_sections_labels"] = True
        if len(framework_sections) >= 2:
            checks["prompts_framework_sections_two"] = True
            names = ["RACE", "Chain-of-Thought", "Constraint-Stacking", "Few-Shot"]
            names_ok = True
            for fs in framework_sections[:2]:
                combined = (fs["heading"] + "\n" + fs["content"])
                if not any(n in combined for n in names):
                    names_ok = False
                    break
            if names_ok:
                checks["prompts_framework_named"] = True

    # 7) Paper reproduction
    repro_dir = os.path.join(output_dir, "repro")
    plan_md = os.path.join(repro_dir, "plan.md")
    if os.path.isfile(plan_md):
        txt = "".join(read_lines(plan_md))
        if all(h in txt for h in ["Problem Definition", "Algorithm Steps", "Evaluation Protocol"]):
            checks["repro_plan_sections_present"] = True

    alg_py = os.path.join(repro_dir, "algorithm.py")
    run_py = os.path.join(repro_dir, "run.py")
    alg_lines = count_nonempty_lines(alg_py) if os.path.isfile(alg_py) else None
    if alg_lines is not None and alg_lines <= 200:
        checks["repro_algorithm_py_ok"] = True
    run_lines = count_nonempty_lines(run_py) if os.path.isfile(run_py) else None
    if run_lines is not None and run_lines <= 200:
        checks["repro_run_py_ok"] = True

    config_path = os.path.join(repro_dir, "config.json")
    cfg = safe_read_json(config_path) if os.path.isfile(config_path) else None
    if isinstance(cfg, dict):
        if cfg.get("algorithm") == "CMA" and cfg.get("data_path") == "input/sample_data.csv":
            checks["repro_config_ok"] = True

    logs_dir = os.path.join(repro_dir, "logs")
    logs_exist = False
    if os.path.isdir(logs_dir):
        try:
            for fn in os.listdir(logs_dir):
                if fn.endswith(".log"):
                    logs_exist = True
                    break
        except Exception:
            pass
    if logs_exist:
        checks["repro_logs_exist"] = True

    # results.json with MSE validated against computed
    results_path = os.path.join(repro_dir, "results.json")
    results = safe_read_json(results_path) if os.path.isfile(results_path) else None
    mse_ok = False
    if isinstance(results, dict) and "mse" in results:
        try:
            mse_val = float(results.get("mse"))
            # recompute from input/sample_data.csv using CMA
            data_csv = os.path.join(input_dir, "sample_data.csv")
            series = read_csv_numeric_series(data_csv)
            comp_mse = compute_cma_mse(series)
            if comp_mse is not None and abs(mse_val - comp_mse) <= 1e-6:
                mse_ok = True
        except Exception:
            mse_ok = False
    if mse_ok:
        checks["repro_results_ok"] = True

    # README checks
    readme_en = os.path.join(repro_dir, "README.md")
    readme_cn = os.path.join(repro_dir, "README_zh-CN.md")
    if os.path.isfile(readme_en):
        # Check starts with H1 with paper title from input/paper.md
        title = extract_paper_title(os.path.join(input_dir, "paper.md"))
        lines = read_lines(readme_en)
        first_nonempty = ""
        for l in lines:
            if l.strip():
                first_nonempty = l.strip()
                break
        starts_ok = False
        if title and first_nonempty.startswith("#"):
            # remove leading hashes
            rn = first_nonempty.lstrip("#").strip()
            if rn == title:
                starts_ok = True
        # also check it includes 'setup' and 'how to run' (case-insensitive)
        content = "".join(lines).lower()
        if starts_ok and ("setup" in content) and ("how to run" in content):
            checks["repro_readme_en_ok"] = True
    if os.path.isfile(readme_cn):
        checks["repro_readme_cn_exists"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0
    # Ensure baseline: if output missing or empty leading to all false, reward is 0.0 by definition
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()