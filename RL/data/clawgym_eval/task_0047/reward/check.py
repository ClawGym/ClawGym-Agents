import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime, timedelta


def _read_text_safe(p: Path):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _extract_scene_tokens(markdown_text: str):
    tokens = []
    for line in markdown_text.splitlines():
        m = re.match(r'^(S\d+:)', line.strip())
        if m:
            tokens.append(m.group(1))
    return tokens


def _first_paragraph(text: str):
    lines = text.splitlines()
    buf = []
    for line in lines:
        if line.strip() == "" and buf:
            break
        if line.strip() == "" and not buf:
            continue
        buf.append(line)
    return "\n".join(buf).strip()


def _count_sentences(paragraph: str):
    parts = re.split(r'[.!?]+', paragraph)
    count = 0
    for p in parts:
        if re.search(r'[A-Za-z0-9]', p):
            count += 1
    return count


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _format_date(d):
    return d.strftime("%Y-%m-%d")


def _topo_order(tasks_by_id, deps_map):
    indeg = {tid: 0 for tid in tasks_by_id}
    for tid, deps in deps_map.items():
        for d in deps:
            if d in indeg:
                indeg[tid] += 1
    queue = [tid for tid, deg in indeg.items() if deg == 0]
    order = []
    while queue:
        queue.sort()
        n = queue.pop(0)
        order.append(n)
        for m, deps in deps_map.items():
            if n in deps:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
    if len(order) != len(tasks_by_id):
        return None
    return order


def _compute_schedule(tasks, start_date):
    tasks_by_id = {t.get("id"): t for t in tasks if isinstance(t, dict) and "id" in t}
    deps_map = {
        tid: list(tasks_by_id[tid].get("depends_on", []))
        if isinstance(tasks_by_id[tid].get("depends_on", []), list)
        else []
        for tid in tasks_by_id
    }
    order = _topo_order(tasks_by_id, deps_map)
    if order is None:
        return None, None, None
    start_dates = {}
    due_dates = {}
    for tid in order:
        t = tasks_by_id[tid]
        est = t.get("estimate_days")
        if not isinstance(est, int):
            return None, None, None
        deps = deps_map.get(tid, [])
        if not deps:
            st = start_date
        else:
            max_due = None
            for d in deps:
                if d not in due_dates:
                    return None, None, None
                if max_due is None or due_dates[d] > max_due:
                    max_due = due_dates[d]
            st = max_due + timedelta(days=1)
        du = st + timedelta(days=est - 1)
        start_dates[tid] = st
        due_dates[tid] = du
    return order, start_dates, due_dates


def _load_plan_csv(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        idx = {name: i for i, name in enumerate(header)}
        by_id = {}
        for r in data_rows:
            if len(r) != len(header):
                return header, None
            ridx = idx.get("id")
            if ridx is None:
                return header, None
            rid = r[ridx]
            rowdict = {header[i]: r[i] for i in range(len(header))}
            by_id[rid] = rowdict
        return header, by_id
    except Exception:
        return None, None


def _run_planify(workspace: Path):
    script = workspace / "scripts" / "planify.py"
    if not script.exists():
        return False, "", ""
    try:
        cp = subprocess.run(
            [sys.executable, str(script), "--start", "2026-05-01"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return cp.returncode == 0, cp.stdout, cp.stderr
    except Exception:
        return False, "", ""


def _collect_research_topics(workspace: Path):
    csv_path = workspace / "input" / "research_index.csv"
    rows = _load_csv_dicts_safe(csv_path)
    if not rows:
        return None
    topics = []
    for r in rows:
        t = r.get("topic")
        if t is not None:
            topics.append(t)
    return topics


def _is_valid_chain(chain_ids, deps_map):
    if not chain_ids:
        return False
    for i in range(1, len(chain_ids)):
        prev_id = chain_ids[i - 1]
        cur_id = chain_ids[i]
        deps = deps_map.get(cur_id, [])
        if prev_id not in deps:
            return False
    return True


def _critical_path_any(tasks):
    tasks_by_id = {t.get("id"): t for t in tasks if isinstance(t, dict) and "id" in t}
    deps_map = {
        tid: list(tasks_by_id[tid].get("depends_on", []))
        if isinstance(tasks_by_id[tid].get("depends_on", []), list)
        else []
        for tid in tasks_by_id
    }
    order = _topo_order(tasks_by_id, deps_map)
    if order is None:
        return None, None, None
    longest = {}
    prev = {}
    for tid in order:
        est = tasks_by_id[tid].get("estimate_days")
        if not isinstance(est, int):
            return None, None, None
        if not deps_map[tid]:
            longest[tid] = est
            prev[tid] = None
        else:
            bestp = None
            bestv = -1
            for d in deps_map[tid]:
                v = longest.get(d)
                if v is None:
                    return None, None, None
                if v > bestv:
                    bestv = v
                    bestp = d
            longest[tid] = bestv + est
            prev[tid] = bestp
    end = max(longest.keys(), key=lambda k: longest[k])
    maxlen = longest[end]
    path = []
    cur = end
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path, maxlen, deps_map


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outline_exists": 0.0,
        "outline_scene_numbering_preserved": 0.0,
        "outline_summary_3_5_sentences": 0.0,
        "roadmap_json_valid_and_extended": 0.0,
        "tasks_have_required_fields": 0.0,
        "status_in_columns": 0.0,
        "phases_present": 0.0,
        "ids_unique": 0.0,
        "depends_on_ids_resolvable": 0.0,
        "research_topics_covered_in_research_tasks": 0.0,
        "planify_runs_successfully": 0.0,
        "plan_csv_header_correct": 0.0,
        "plan_dates_correct": 0.0,
        "plan_depends_on_column_contains_refs": 0.0,
        "critical_path_valid": 0.0,
        "sensitivity_invite_exists": 0.0,
        "sensitivity_invite_bullets_count": 0.0,
        "sensitivity_invite_window_matches_phase": 0.0,
        "agent_query_exists": 0.0,
        "agent_query_includes_draft_date": 0.0,
        "agent_query_has_bio_paragraph": 0.0,
    }

    # Outline checks
    input_outline_path = workspace / "input" / "outline.md"
    output_outline_path = workspace / "output" / "outline_rewrite.md"
    input_outline = _read_text_safe(input_outline_path)
    output_outline = _read_text_safe(output_outline_path)
    if output_outline is not None:
        scores["outline_exists"] = 1.0
    if input_outline is not None and output_outline is not None:
        in_tokens = _extract_scene_tokens(input_outline)
        out_tokens = _extract_scene_tokens(output_outline)
        if in_tokens and in_tokens == out_tokens:
            scores["outline_scene_numbering_preserved"] = 1.0
    if output_outline is not None:
        para = _first_paragraph(output_outline)
        n_sent = _count_sentences(para) if para else 0
        if 3 <= n_sent <= 5:
            scores["outline_summary_3_5_sentences"] = 1.0

    # Roadmap JSON structure and tasks
    roadmap_path = workspace / "config" / "roadmap.json"
    data = _load_json_safe(roadmap_path)

    tasks = []
    columns = []
    all_have_fields = False
    ids_unique_flag = False
    statuses_ok = False
    phases_req = {"Research", "Draft", "Sensitivity Review", "Revision", "Query"}
    phases_present_flag = False
    all_deps_resolvable = False
    deps_type_ok_all = False
    if isinstance(data, dict):
        tasks = data.get("tasks", [])
        columns = data.get("columns", [])
        all_have_fields = True
        ids = []
        ids_set = set()
        statuses_ok = True
        task_phases = set()
        deps_type_ok_all = True
        for t in tasks if isinstance(tasks, list) else []:
            if not isinstance(t, dict):
                all_have_fields = False
                continue
            has_id = "id" in t and isinstance(t["id"], str) and t["id"].strip() != ""
            has_title = "title" in t and isinstance(t["title"], str)
            has_status = "status" in t and isinstance(t["status"], str)
            has_phase = "phase" in t and isinstance(t["phase"], str)
            has_estimate = "estimate_days" in t and isinstance(t["estimate_days"], int)
            has_depends = "depends_on" in t and isinstance(t["depends_on"], list)
            if not (has_id and has_title and has_status and has_phase and has_estimate and has_depends):
                all_have_fields = False
            if has_id:
                ids.append(t["id"])
                if t["id"] in ids_set:
                    ids_unique_flag = False
                else:
                    ids_set.add(t["id"])
            if has_status and isinstance(columns, list) and columns:
                if t["status"] not in columns:
                    statuses_ok = False
            if has_phase:
                task_phases.add(t["phase"])
            if has_depends:
                for dep in t["depends_on"]:
                    if not isinstance(dep, str):
                        deps_type_ok_all = False
        ids_unique_flag = len(ids_set) == len(ids) and len(ids) > 0
        # After collecting ids, check resolvability
        all_deps_resolvable = True
        if isinstance(tasks, list) and ids_set:
            for t in tasks:
                if isinstance(t, dict) and isinstance(t.get("depends_on", []), list):
                    for dep in t.get("depends_on", []):
                        if not isinstance(dep, str) or dep not in ids_set:
                            all_deps_resolvable = False
        else:
            all_deps_resolvable = False
        phases_present_flag = phases_req.issubset(task_phases)

    # Only award JSON validity if extended with required fields across tasks
    if isinstance(data, dict) and isinstance(tasks, list) and tasks and all_have_fields:
        scores["roadmap_json_valid_and_extended"] = 1.0
    if all_have_fields:
        scores["tasks_have_required_fields"] = 1.0
    if all_have_fields and statuses_ok and isinstance(columns, list) and columns:
        scores["status_in_columns"] = 1.0
    if all_have_fields and phases_present_flag:
        scores["phases_present"] = 1.0
    if all_have_fields and ids_unique_flag:
        scores["ids_unique"] = 1.0
    if all_have_fields and all_deps_resolvable and deps_type_ok_all:
        scores["depends_on_ids_resolvable"] = 1.0

    # Research topics coverage (require all_have_fields to avoid baseline credit)
    if all_have_fields:
        topics = _collect_research_topics(workspace)
        if topics is not None and isinstance(tasks, list):
            covered_all = True
            for topic in topics:
                found = False
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    if t.get("phase") != "Research":
                        continue
                    title = t.get("title", "")
                    notes = t.get("notes", "")
                    if isinstance(title, str) and topic in title:
                        found = True
                        break
                    if isinstance(notes, str) and topic in notes:
                        found = True
                        break
                if not found:
                    covered_all = False
                    break
            if covered_all and len(topics) > 0:
                scores["research_topics_covered_in_research_tasks"] = 1.0

    # Run planify and require expected artifacts
    ran_ok, out_s, err_s = _run_planify(workspace)
    plan_csv_path = workspace / "plan" / "plan.csv"
    crit_path_path = workspace / "plan" / "critical_path.txt"
    header, plan_by_id = _load_plan_csv(plan_csv_path)
    expected_header = ['id', 'title', 'phase', 'status', 'estimate_days', 'start_date', 'due_date', 'depends_on']
    if ran_ok and header == expected_header and crit_path_path.exists():
        scores["planify_runs_successfully"] = 1.0

    # Plan CSV header
    if header == expected_header and isinstance(plan_by_id, dict) and plan_by_id:
        scores["plan_csv_header_correct"] = 1.0

    # Plan dates correctness and depends_on field containing ids
    if all_have_fields and header == expected_header and isinstance(plan_by_id, dict) and plan_by_id:
        start_date = _parse_date("2026-05-01")
        order, starts, dues = _compute_schedule(tasks, start_date)
        if order is not None and starts is not None and dues is not None:
            all_match = True
            all_deprefs_present = True
            for tid in {t.get("id") for t in tasks if isinstance(t, dict) and "id" in t}:
                if tid not in plan_by_id:
                    all_match = False
                    all_deprefs_present = False
                    break
                prow = plan_by_id[tid]
                ps = _parse_date(prow.get("start_date", ""))
                pd = _parse_date(prow.get("due_date", ""))
                if ps != starts.get(tid) or pd != dues.get(tid):
                    all_match = False
                deps = []
                t = next((x for x in tasks if isinstance(x, dict) and x.get("id") == tid), {})
                dval = t.get("depends_on", [])
                if isinstance(dval, list):
                    deps = [d for d in dval if isinstance(d, str)]
                depcell = prow.get("depends_on", "")
                for d in deps:
                    if d and d not in depcell:
                        all_deprefs_present = False
                if isinstance(t, dict):
                    if prow.get("phase") != t.get("phase"):
                        all_match = False
                    if prow.get("status") != t.get("status"):
                        all_match = False
                    try:
                        est_val = int(prow.get("estimate_days", ""))
                    except Exception:
                        est_val = None
                    if est_val != t.get("estimate_days"):
                        all_match = False
            if all_match:
                scores["plan_dates_correct"] = 1.0
            if all_deprefs_present:
                scores["plan_depends_on_column_contains_refs"] = 1.0

    # Critical path validity
    crit_text = _read_text_safe(crit_path_path)
    if all_have_fields and isinstance(tasks, list) and crit_text is not None:
        cp, maxlen, deps_map = _critical_path_any(tasks)
        if cp is not None and maxlen is not None and deps_map is not None:
            file_chain = [line.strip() for line in crit_text.splitlines() if line.strip()]
            if file_chain:
                valid_chain = _is_valid_chain(file_chain, deps_map)
                tasks_by_id = {t.get("id"): t for t in tasks if isinstance(t, dict) and "id" in t}
                chain_len = 0
                ok_ids = True
                for cid in file_chain:
                    if cid not in tasks_by_id or not isinstance(tasks_by_id[cid].get("estimate_days"), int):
                        ok_ids = False
                        break
                    chain_len += tasks_by_id[cid]["estimate_days"]
                if valid_chain and ok_ids and chain_len == maxlen:
                    scores["critical_path_valid"] = 1.0

    # Emails
    sens_invite_path = workspace / "output" / "emails" / "sensitivity_invite.md"
    agent_query_path = workspace / "output" / "emails" / "agent_query.md"
    sens_text = _read_text_safe(sens_invite_path)
    agent_text = _read_text_safe(agent_query_path)
    if sens_text is not None:
        scores["sensitivity_invite_exists"] = 1.0
        bullets = []
        for line in sens_text.splitlines():
            if re.match(r'^\s*[-*]\s+', line) or re.match(r'^\s*\d+\.\s+', line):
                bullets.append(line)
        if len(bullets) == 3:
            scores["sensitivity_invite_bullets_count"] = 1.0
    if agent_text is not None:
        scores["agent_query_exists"] = 1.0

    # Email windows aligned and agent query draft date and bio paragraph
    if header == expected_header and isinstance(plan_by_id, dict) and plan_by_id:
        sens_rows = [r for r in plan_by_id.values() if r.get("phase") == "Sensitivity Review"]
        if sens_rows:
            sens_starts = [_parse_date(r.get("start_date", "")) for r in sens_rows]
            sens_dues = [_parse_date(r.get("due_date", "")) for r in sens_rows]
            if all(d is not None for d in sens_starts + sens_dues):
                sens_window_start = min(sens_starts)
                sens_window_due = max(sens_dues)
                if sens_text is not None:
                    s_str = _format_date(sens_window_start)
                    d_str = _format_date(sens_window_due)
                    if s_str in sens_text and d_str in sens_text:
                        scores["sensitivity_invite_window_matches_phase"] = 1.0
        draft_rows = [r for r in plan_by_id.values() if r.get("phase") == "Draft"]
        if draft_rows and agent_text is not None:
            draft_dues = [_parse_date(r.get("due_date", "")) for r in draft_rows]
            if all(d is not None for d in draft_dues):
                draft_full_due = max(draft_dues)
                due_str = _format_date(draft_full_due)
                if due_str in agent_text:
                    scores["agent_query_includes_draft_date"] = 1.0
            paras = []
            cur = []
            for line in agent_text.splitlines():
                if line.strip() == "":
                    if cur:
                        paras.append("\n".join(cur).strip())
                        cur = []
                else:
                    cur.append(line)
            if cur:
                paras.append("\n".join(cur).strip())
            bio_like = False
            keywords = ["bio", "Bio", "background", "experience", "author", "writer", "I am", "I write", "novel"]
            for p in paras:
                if any(k in p for k in keywords):
                    bio_like = True
                    break
            if bio_like:
                scores["agent_query_has_bio_paragraph"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()