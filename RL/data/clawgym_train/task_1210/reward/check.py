import json
import os
import sys
import re
from glob import glob

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def find_headings(lines):
    # Return dict of heading name (lowercased) to list of indices
    heads = {}
    for i, line in enumerate(lines):
        s = line.strip()
        # Markdown headings or plain line headings
        if re.match(r"^#{1,6}\s*\S", s):
            name = re.sub(r"^#{1,6}\s*", "", s).strip().lower()
            heads.setdefault(name, []).append(i)
        else:
            # Plain heading line, single word or words, no bullet, no code
            if s and not s.startswith(("-", "*", ">","`")) and len(s) <= 80:
                # Heuristic: consider standalone "Themes" or "Principles" as headings
                if s.lower() in ("themes", "principles"):
                    heads.setdefault(s.lower(), []).append(i)
    return heads

def slice_section(lines, start_idx):
    # Return slice from start_idx+1 to next heading or end
    end = len(lines)
    for j in range(start_idx + 1, len(lines)):
        s = lines[j].strip()
        if re.match(r"^#{1,6}\s*\S", s):
            end = j
            break
        # Also treat plain "Themes"/"Principles" as headings
        if s.lower() in ("themes", "principles"):
            end = j
            break
    return lines[start_idx + 1:end]

def get_nested_task_snapshot(obj):
    # Accept top-level or nested under 'task'
    if isinstance(obj, dict):
        if ("status" in obj and "steps" in obj and isinstance(obj["steps"], list)):
            return obj
        if "task" in obj and isinstance(obj["task"], dict):
            t = obj["task"]
            if ("status" in t and "steps" in t and isinstance(t["steps"], list)):
                return t
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Task tracker
        "tasks_dir_has_json": False,
        "task_struct_ok": False,
        "task_name_has_testimonial": False,
        "task_status_done": False,
        "task_steps_count_ok": False,
        "task_all_steps_done": False,
        # Push log
        "push_log_exists": False,
        "push_has_launch": False,
        "push_has_heartbeat": False,
        "push_has_multiple_progress": False,
        "push_has_completion": False,
        "push_has_next_step_hint": False,
        "push_final_counts_match": False,
        # Analysis doc
        "analysis_exists": False,
        "analysis_has_themes_section": False,
        "analysis_themes_min5": False,
        "analysis_has_principles_section": False,
        "analysis_min3_principles_named": False,
        # Revised testimonials
        "revised_exists": False,
        "revised_array_min3": False,
        "revised_items_have_fields": False,
        # Status snapshot
        "status_exists": False,
        "status_done_and_steps_ok": False,
    }

    # ---------- 1) Task tracker JSON ----------
    tasks_dir = os.path.join(output_dir, "tasks")
    chosen_task = None
    chosen_steps_len = None

    if os.path.isdir(tasks_dir):
        json_files = [p for p in glob(os.path.join(tasks_dir, "*.json")) if os.path.isfile(p)]
        if json_files:
            checks["tasks_dir_has_json"] = True

            # Parse all, filter to those with minimal structure and name contains "Testimonial"
            candidates = []
            for p in sorted(json_files):
                data = load_json(p)
                if not isinstance(data, dict):
                    continue
                has_fields = all(k in data for k in ("taskId", "taskName", "status", "steps"))
                if not has_fields or not isinstance(data.get("steps"), list):
                    continue
                tn = str(data.get("taskName", ""))
                contains_word = "testimonial" in tn.lower()
                # Collect meta for selection: prefer done, then updated/finished timestamp if present
                done = (str(data.get("status", "")).lower() == "done")
                timestamp = ""
                for key in ("finishedAt", "updatedAt", "startedAt"):
                    val = data.get(key)
                    if isinstance(val, str) and val:
                        timestamp = val
                        break
                candidates.append((done, contains_word, timestamp, p, data))

            # Choose best: done & contains_word first, then done only, then contains_word only, else first
            chosen = None
            for predicate in [
                lambda item: item[0] and item[1],
                lambda item: item[0],
                lambda item: item[1],
                lambda item: True,
            ]:
                filtered = [c for c in candidates if predicate(c)]
                if filtered:
                    # Sort by timestamp string descending (ISO expected), fallback to path
                    filtered.sort(key=lambda x: (x[2], x[3]), reverse=True)
                    chosen = filtered[0]
                    break
            if chosen:
                _, contains_word, _, chosen_path, chosen_data = chosen
                # Validate structure
                checks["task_struct_ok"] = True
                if "testimonial" in str(chosen_data.get("taskName", "")).lower():
                    checks["task_name_has_testimonial"] = True
                if str(chosen_data.get("status", "")).lower() == "done":
                    checks["task_status_done"] = True
                steps = chosen_data.get("steps", [])
                if isinstance(steps, list):
                    chosen_steps_len = len(steps)
                    if chosen_steps_len >= 5:
                        checks["task_steps_count_ok"] = True
                    # All steps done
                    all_done = True
                    for s in steps:
                        if not isinstance(s, dict) or str(s.get("status", "")).lower() != "done":
                            all_done = False
                            break
                    if all_done and steps:
                        checks["task_all_steps_done"] = True

    # ---------- 2) Push log ----------
    push_log_path = os.path.join(output_dir, "push_log.txt")
    if os.path.isfile(push_log_path):
        checks["push_log_exists"] = True
        content = read_text(push_log_path) or ""
        # Normalize newlines
        lines = content.splitlines()

        if "🚀" in content:
            checks["push_has_launch"] = True
        if "💓" in content:
            checks["push_has_heartbeat"] = True
        # Count progress lines with "✅ [x/y]"
        progress_re = re.compile(r"✅\s*\[(\d+)\/(\d+)\]")
        progress_matches = []
        for ln in lines:
            m = progress_re.search(ln)
            if m:
                progress_matches.append((int(m.group(1)), int(m.group(2))))
        if len(progress_matches) >= 2:
            checks["push_has_multiple_progress"] = True
        # Completion indicator: 🎉 or literal "✅ 完成"
        if ("🎉" in content) or ("✅ 完成" in content):
            checks["push_has_completion"] = True
        # Next-step hint line starting with arrow on its own line
        arrow_line = any(l.strip().startswith("→") for l in lines)
        if arrow_line:
            checks["push_has_next_step_hint"] = True
        # Final [x/y] must match step count and x == y
        # Find last occurrence of bracket counts anywhere in file (not just progress)
        any_bracket_re = re.compile(r"\[(\d+)\/(\d+)\]")
        any_matches = any_bracket_re.findall(content)
        if any_matches and isinstance(chosen_steps_len, int):
            last_x, last_y = any_matches[-1]
            try:
                lx, ly = int(last_x), int(last_y)
                if chosen_steps_len == ly and lx == ly and ly >= 1:
                    checks["push_final_counts_match"] = True
            except ValueError:
                pass

    # ---------- 3) Analysis document ----------
    analysis_path = os.path.join(output_dir, "deliverables", "analysis.md")
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        analysis_text = read_text(analysis_path) or ""
        analysis_lines = analysis_text.splitlines()
        heads = find_headings(analysis_lines)

        # Themes section present
        themes_present = False
        themes_indices = []
        # Accept heading names containing "themes"
        for name, idxs in heads.items():
            if "themes" == name or "themes" in name:
                themes_present = True
                themes_indices.extend(idxs)
        if themes_present:
            checks["analysis_has_themes_section"] = True
            # Use first themes heading
            start_idx = sorted(themes_indices)[0]
            theme_section_lines = slice_section(analysis_lines, start_idx)
            bullet_count = sum(1 for l in theme_section_lines if l.lstrip().startswith("- ") or l.lstrip().startswith("* "))
            if bullet_count >= 5:
                checks["analysis_themes_min5"] = True

        # Principles section present
        principles_present = False
        principles_indices = []
        for name, idxs in heads.items():
            if "principles" == name or "principles" in name:
                principles_present = True
                principles_indices.extend(idxs)
        if principles_present:
            checks["analysis_has_principles_section"] = True

        # At least 3 recognized principles named anywhere in the doc
        recognized = [
            "Social Proof",
            "Loss Aversion",
            "Anchoring",
            "Scarcity",
            "Paradox of Choice",
            "Reciprocity",
            "Decoy Effect",
            "Framing",
            "Authority",
            "Default Effect",
            "Goal-Gradient",
        ]
        found = set()
        lower_text = analysis_text.lower()
        for p in recognized:
            if p.lower() in lower_text:
                found.add(p)
        if len(found) >= 3:
            checks["analysis_min3_principles_named"] = True

    # ---------- 4) Revised testimonials ----------
    revised_path = os.path.join(output_dir, "deliverables", "revised_testimonials.json")
    revised = load_json(revised_path) if os.path.isfile(revised_path) else None
    if revised is not None:
        checks["revised_exists"] = True
        if isinstance(revised, list) and len(revised) >= 3:
            checks["revised_array_min3"] = True
            all_ok = True
            for item in revised:
                if not (isinstance(item, dict) and isinstance(item.get("original"), str) and isinstance(item.get("revised"), str)):
                    all_ok = False
                    break
            if all_ok:
                checks["revised_items_have_fields"] = True

    # ---------- 5) Status snapshot ----------
    status_path = os.path.join(output_dir, "status.json")
    status_obj = load_json(status_path) if os.path.isfile(status_path) else None
    if status_obj is not None:
        checks["status_exists"] = True
        task_snapshot = get_nested_task_snapshot(status_obj)
        if task_snapshot:
            if str(task_snapshot.get("status", "")).lower() == "done":
                steps_val = task_snapshot.get("steps", [])
                if isinstance(steps_val, list) and len(steps_val) >= 5:
                    checks["status_done_and_steps_ok"] = True

    # ---------- Scoring ----------
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if no outputs present, ensure 0.0
    # This is naturally handled because no checks would be True.
    reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()