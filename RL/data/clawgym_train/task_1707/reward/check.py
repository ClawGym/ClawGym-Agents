import json
import sys
import subprocess
import csv
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                return row
        return None
    except Exception:
        return None


def yaml_top_level_keys(path: Path) -> Optional[List[str]]:
    try:
        text = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    keys = []
    for line in text:
        stripped = line.strip("\n")
        if not stripped.strip():
            continue
        if stripped.lstrip().startswith("#"):
            continue
        if line and not line.startswith((" ", "\t")) and ":" in line:
            key = line.split(":", 1)[0].strip()
            if key:
                keys.append(key)
    return keys if keys else []


def run_validator(workspace: Path) -> Tuple[int, str, str]:
    script = workspace / "input" / "tools" / "validate_projects.py"
    csv_path = workspace / "input" / "data" / "projects.csv"
    if not script.exists() or not csv_path.exists():
        return (127, "", "Missing validator or projects.csv")
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(csv_path)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (proc.returncode, proc.stdout, proc.stderr)
    except Exception as e:
        return (1, "", f"{type(e).__name__}: {e}")


def extract_first_error_line(stderr: str) -> Optional[str]:
    for line in stderr.splitlines():
        if line.strip().startswith("ValueError:"):
            return line.strip()
    for line in reversed(stderr.splitlines()):
        if line.strip():
            return line.strip()
    return None


def parse_float_safe(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def load_constraints(workspace: Path) -> Optional[Dict[str, object]]:
    path = workspace / "input" / "data" / "constraints.yaml"
    text = read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    result: Dict[str, object] = {}
    current_list_key: Optional[str] = None
    for ln in lines:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ln.startswith(" ") or ln.startswith("\t"):
            if current_list_key and stripped.startswith("- "):
                item = stripped[2:].strip()
                result.setdefault(current_list_key, []).append(item)
            continue
        if ":" in ln:
            key, val = ln.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                result[key] = []
                current_list_key = key
            else:
                current_list_key = None
                v: object
                if val.isdigit():
                    v = int(val)
                else:
                    try:
                        v = float(val)
                    except Exception:
                        v = val
                result[key] = v
    return result


def compute_expected_priority(workspace: Path) -> Optional[Dict[str, object]]:
    projects_path = workspace / "input" / "data" / "projects.csv"
    rows = read_csv_dicts(projects_path)
    if rows is None:
        return None
    constraints = load_constraints(workspace)
    if constraints is None:
        return None
    min_benefit = constraints.get("min_benefit_score")
    budget_total = constraints.get("budget_total_usd")
    max_projects = constraints.get("max_projects")
    prefer_neighborhoods = constraints.get("prefer_neighborhoods", [])
    maint_thresh = constraints.get("maintenance_years_penalty_threshold")
    if not isinstance(min_benefit, (int, float)):
        return None
    if not isinstance(budget_total, (int, float)):
        return None
    if not isinstance(max_projects, int):
        try:
            max_projects = int(max_projects)
        except Exception:
            return None
    if not isinstance(prefer_neighborhoods, list):
        return None
    if not isinstance(maint_thresh, (int, float)):
        return None

    def row_is_valid_for_validator(row: Dict[str, str]) -> bool:
        val = (row.get("estimated_cost_usd") or "").strip()
        if val == "":
            return False
        try:
            cost = float(val)
        except Exception:
            return False
        if cost <= 0:
            return False
        return True

    eligible_ids = set()
    scores: Dict[int, float] = {}
    costs: Dict[int, float] = {}
    names: Dict[int, str] = {}
    neighborhoods: Dict[int, str] = {}

    for row in rows:
        if not row_is_valid_for_validator(row):
            continue
        try:
            proj_id = int((row.get("id") or "").strip())
        except Exception:
            continue
        try:
            benefit = float((row.get("expected_green_benefit_score") or "").strip())
        except Exception:
            continue
        if benefit < float(min_benefit):
            continue
        name = (row.get("name") or "").strip()
        neighborhood = (row.get("neighborhood") or "").strip()
        try:
            cost_val = float((row.get("estimated_cost_usd") or "").strip())
        except Exception:
            continue
        try:
            maint_years = float((row.get("maintenance_commitment_years") or "").strip())
        except Exception:
            maint_years = 0.0
        cost_eff = round(100000.0 / cost_val, 2)
        neighborhood_bonus = 2 if neighborhood in prefer_neighborhoods else 0
        maintenance_penalty = -1 if maint_years > float(maint_thresh) else 0
        total_score = round(benefit + neighborhood_bonus + maintenance_penalty + cost_eff, 2)

        eligible_ids.add(proj_id)
        scores[proj_id] = total_score
        costs[proj_id] = cost_val
        names[proj_id] = name
        neighborhoods[proj_id] = neighborhood

    sorted_ids = sorted(
        list(eligible_ids),
        key=lambda pid: (-scores[pid], costs[pid], pid),
    )
    selection_order: List[int] = []
    remaining_budget = float(budget_total)
    for pid in sorted_ids:
        if len(selection_order) >= int(max_projects):
            break
        if costs[pid] <= remaining_budget:
            selection_order.append(pid)
            remaining_budget -= costs[pid]
        else:
            continue

    return {
        "eligible_ids": eligible_ids,
        "scores": scores,
        "costs": costs,
        "names": names,
        "neighborhoods": neighborhoods,
        "selection_order": selection_order,
    }


def parse_priority_plan_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return read_csv_dicts(path)


def float_equal_2dp(a: float, b: float) -> bool:
    return abs(round(a - b, 2)) <= 0.01


def find_input_files(workspace: Path) -> List[Path]:
    base = workspace / "input"
    if not base.exists():
        return []
    return sorted([p for p in base.rglob("*") if p.is_file()])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "architecture_exists_and_paths": 0.0,
        "architecture_context_goals_alignment": 0.0,
        "architecture_includes_validator_error": 0.0,
        "architecture_process_sections_present": 0.0,
        "architecture_has_milestones": 0.0,
        "architecture_local_first": 0.0,
        "priority_plan_exists_and_header": 0.0,
        "priority_plan_eligibility_filtering": 0.0,
        "priority_plan_scoring_correctness": 0.0,
        "priority_plan_sorting_and_selection": 0.0,
        "priority_plan_selected_ranks": 0.0,
        "input_inventory_covers_all_files": 0.0,
        "input_inventory_summaries_correct": 0.0,
        "meeting_notes_agenda_and_duration": 0.0,
        "meeting_notes_action_items_with_owners": 0.0,
        "meeting_notes_includes_error_text": 0.0,
        "meeting_notes_decisions_needed": 0.0,
    }

    rc, v_stdout, v_stderr = run_validator(workspace)
    error_line = extract_first_error_line(v_stderr) if rc != 0 else None
    ok_line = None
    if rc == 0:
        for line in v_stdout.splitlines():
            if line.strip().startswith("OK:"):
                ok_line = line.strip()
                break

    arch_path = workspace / "outputs" / "solution" / "green_sponsorship_architecture.md"
    arch_text = read_text(arch_path)
    if arch_text:
        lowered_arch = arch_text.lower()
        refs_found = 0
        for token in ["projects.csv", "constraints.yaml", "background.md", "validate_projects.py"]:
            if token in lowered_arch:
                refs_found += 1
        if refs_found >= 4:
            scores["architecture_exists_and_paths"] = 1.0

        goal_tokens = [
            "northside",
            "downtown",
            "60,000",
            "$60,000",
            "60000",
            "maintenance",
            "5 years",
            "walkability",
            "shade",
            "stormwater",
            "local workflow",
            "local-first",
        ]
        matched = set()
        for tok in goal_tokens:
            if tok.lower() in lowered_arch:
                matched.add(tok)
        if len(matched) >= 2:
            scores["architecture_context_goals_alignment"] = 1.0

        if error_line:
            if error_line in arch_text:
                scores["architecture_includes_validator_error"] = 1.0
        else:
            if ok_line and ok_line in arch_text:
                scores["architecture_includes_validator_error"] = 1.0

        proc_keywords = ["intake", "validation", "prioritization", "reporting"]
        if all(k in lowered_arch for k in proc_keywords):
            scores["architecture_process_sections_present"] = 1.0

        bullets = [ln for ln in arch_text.splitlines() if ln.strip().startswith(("-", "*", "1.", "2.", "3.", "4.", "5."))]
        if "milestone" in lowered_arch and len(bullets) >= 3:
            scores["architecture_has_milestones"] = 1.0

        if "local" in lowered_arch or "local-first" in lowered_arch:
            scores["architecture_local_first"] = 1.0

    plan_path = workspace / "outputs" / "analysis" / "priority_plan.csv"
    plan_header = read_csv_header(plan_path)
    expected_header = ["id", "name", "neighborhood", "estimated_cost_usd", "total_score", "selected_rank"]
    if plan_header is not None and [h.strip() for h in plan_header] == expected_header:
        scores["priority_plan_exists_and_header"] = 1.0
    plan_rows = parse_priority_plan_csv(plan_path)
    expected = compute_expected_priority(workspace)
    if plan_rows is not None and expected is not None:
        actual_ids = set()
        header = None
        try:
            with plan_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames
                for row in reader:
                    try:
                        actual_ids.add(int((row.get("id") or "").strip()))
                    except Exception:
                        pass
        except Exception:
            header = None
        if header == expected_header and actual_ids == set(expected["eligible_ids"]):
            scores["priority_plan_eligibility_filtering"] = 1.0

        scoring_ok = True
        if header == expected_header:
            for row in plan_rows:
                try:
                    pid = int((row.get("id") or "").strip())
                except Exception:
                    scoring_ok = False
                    break
                if pid not in expected["eligible_ids"]:
                    continue
                expected_score = float(expected["scores"][pid])
                actual_score_str = (row.get("total_score") or "").strip()
                actual_score = parse_float_safe(actual_score_str)
                if actual_score is None or not float_equal_2dp(actual_score, expected_score):
                    scoring_ok = False
                    break
        else:
            scoring_ok = False
        scores["priority_plan_scoring_correctness"] = 1.0 if scoring_ok else 0.0

        ranks_ok = True
        pid_to_rank: Dict[int, Optional[int]] = {}
        for row in plan_rows:
            try:
                pid = int((row.get("id") or "").strip())
            except Exception:
                continue
            rstr = (row.get("selected_rank") or "").strip()
            if rstr == "":
                pid_to_rank[pid] = None
            else:
                try:
                    pid_to_rank[pid] = int(rstr)
                except Exception:
                    pid_to_rank[pid] = None
        expected_order: List[int] = list(expected["selection_order"])
        for idx, pid in enumerate(expected_order, start=1):
            r = pid_to_rank.get(pid)
            if r != idx:
                ranks_ok = False
                break
        for pid in expected["eligible_ids"]:
            if pid not in expected_order:
                r = pid_to_rank.get(pid)
                if r not in (None, ""):
                    ranks_ok = False
                    break
        selection_ok = True
        scores["priority_plan_sorting_and_selection"] = 1.0 if selection_ok else 0.0
        scores["priority_plan_selected_ranks"] = 1.0 if ranks_ok else 0.0

    inventory_path = workspace / "outputs" / "analysis" / "input_inventory.txt"
    inventory_text = read_text(inventory_path)
    input_files = find_input_files(workspace)
    if inventory_text is not None and input_files:
        lines = inventory_text.splitlines()
        line_map = {}
        for ln in lines:
            if not ln.strip():
                continue
            parts = ln.split(" ", 1)
            key = parts[0].strip()
            line_map[key] = ln
        covered = 0
        for f in input_files:
            rel = str(f.relative_to(workspace))
            if rel in line_map or any(ln.strip().startswith(rel) for ln in lines):
                covered += 1
        if covered == len(input_files):
            scores["input_inventory_covers_all_files"] = 1.0

        summaries_ok = True
        for f in input_files:
            rel = str(f.relative_to(workspace))
            matched_line = None
            if rel in line_map:
                matched_line = line_map[rel]
            else:
                for ln in lines:
                    if ln.strip().startswith(rel):
                        matched_line = ln
                        break
            if not matched_line:
                summaries_ok = False
                break
            if f.suffix.lower() == ".csv":
                header = read_csv_header(f) or []
                for h in header:
                    if h not in matched_line:
                        summaries_ok = False
                        break
                if not summaries_ok:
                    break
            elif f.suffix.lower() in (".yaml", ".yml"):
                keys = yaml_top_level_keys(f)
                if keys is None:
                    summaries_ok = False
                    break
                for k in keys:
                    if k not in matched_line:
                        summaries_ok = False
                        break
                if not summaries_ok:
                    break
            elif f.suffix.lower() in (".md", ".markdown"):
                txt = read_text(f) or ""
                first_non_empty = ""
                for l in txt.splitlines():
                    if l.strip():
                        first_non_empty = l.strip()
                        break
                if first_non_empty and first_non_empty not in matched_line:
                    summaries_ok = False
                    break
            elif f.suffix.lower() == ".py":
                module_name = f.stem
                if module_name not in matched_line or ("validate" not in matched_line.lower() and "validator" not in matched_line.lower()):
                    summaries_ok = False
                    break
            else:
                pass
        scores["input_inventory_summaries_correct"] = 1.0 if summaries_ok else 0.0

    notes_path = workspace / "outputs" / "meetings" / "next_steps.md"
    notes_text = read_text(notes_path)
    if notes_text:
        lower_notes = notes_text.lower()
        has_agenda = "agenda" in lower_notes and any(s in lower_notes for s in ["30-minute", "30 min", "30 minute"])
        if has_agenda:
            scores["meeting_notes_agenda_and_duration"] = 1.0
        action_lines = [ln for ln in notes_text.splitlines() if (ln.strip().startswith(("-", "*")) and ("owner:" in ln.lower()))]
        if len(action_lines) >= 5:
            scores["meeting_notes_action_items_with_owners"] = 1.0
        if error_line:
            if error_line in notes_text:
                scores["meeting_notes_includes_error_text"] = 1.0
        else:
            if ok_line and ok_line in notes_text:
                scores["meeting_notes_includes_error_text"] = 1.0
        has_decisions = ("decision" in lower_notes)
        bullet_lines = [ln for ln in notes_text.splitlines() if ln.strip().startswith(("-", "*"))]
        if has_decisions and len(bullet_lines) >= 1:
            scores["meeting_notes_decisions_needed"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()