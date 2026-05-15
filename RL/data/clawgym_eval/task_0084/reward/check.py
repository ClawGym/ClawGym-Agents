import json
import os
import re
import sys
from math import floor

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def parse_tasks_jsonl(path):
    tasks = []
    txt = read_text(path)
    if txt is None:
        return None
    for i, line in enumerate(txt.splitlines()):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and "id" in obj and "task" in obj:
                tasks.append({"id": obj["id"], "task": obj["task"]})
        except:
            # skip invalid lines
            pass
    return tasks

def parse_skills_md(path):
    """
    Parse SKILLS.md table rows to extract:
    - name (lowercase)
    - file (path)
    - size_tokens (int)
    Returns dict: name_lower -> {"name": original_name, "file": file_path, "size_tokens": int}
    """
    txt = read_text(path)
    if txt is None:
        return None, 0
    skills = {}
    total_size = 0
    for line in txt.splitlines():
        line_stripped = line.strip()
        if not line_stripped.startswith("|"):
            continue
        if set(line_stripped.replace("|", "").strip()) <= set("-: "):
            # header separator row like |---|---|
            continue
        # Extract file path from backticks anywhere on the line
        file_match = re.search(r"`([^`]+)`", line_stripped)
        # Split cells
        cells = [c.strip() for c in line_stripped.strip().strip("|").split("|")]
        if not cells or len(cells) < 2:
            continue
        name_cell = cells[0].strip()
        name_clean = re.sub(r"\s+", " ", name_cell).strip()
        # Find size token in any cell (prefer last cells)
        size_tokens = None
        for cell in reversed(cells):
            m = re.search(r"~?\s*(\d+)\s*(?:tok|tokens)?\s*$", cell.lower())
            if m:
                try:
                    size_tokens = int(m.group(1))
                    break
                except:
                    pass
        # Determine file path
        file_path = None
        if file_match:
            file_path = file_match.group(1).strip()
        else:
            # fallback: try second cell as file if it looks like a path
            if len(cells) >= 2 and ("/" in cells[1] or "." in cells[1]):
                file_path = cells[1]
        # Validate row completeness
        if not name_clean or file_path is None or size_tokens is None:
            continue
        name_lower = name_clean.lower()
        skills[name_lower] = {
            "name": name_clean,
            "file": file_path,
            "size_tokens": size_tokens,
        }
        total_size += size_tokens
    return skills, total_size

def parse_yaml_keywords(path):
    """
    Minimal YAML parser for a mapping of:
    skill_name:
      - keyword1
      - keyword2
    or inline: skill_name: [kw1, kw2]
    Returns dict[str, list[str]]
    """
    txt = read_text(path)
    if txt is None:
        return None
    result = {}
    current_key = None
    for raw in txt.splitlines():
        # Strip comments
        if "#" in raw:
            # remove comments not in quotes (simple heuristic)
            parts = raw.split("#", 1)
            raw = parts[0]
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue
        # Key with inline list: key: [a, b, c]
        m_inline = re.match(r"^\s*([A-Za-z0-9_\- \/&]+)\s*:\s*\[(.*)\]\s*$", line)
        if m_inline:
            key = m_inline.group(1).strip().lower()
            inside = m_inline.group(2).strip()
            # Split by comma
            items = []
            if inside:
                for it in inside.split(","):
                    val = it.strip().strip('"').strip("'")
                    if val:
                        items.append(val)
            result[key] = items
            current_key = None
            continue
        # New key line: key:
        m_key = re.match(r"^\s*([A-Za-z0-9_\- \/&]+)\s*:\s*$", line)
        if m_key:
            key = m_key.group(1).strip().lower()
            if key not in result:
                result[key] = []
            current_key = key
            continue
        # List item under current key: - value
        m_item = re.match(r"^\s*-\s*(.+?)\s*$", line)
        if m_item and current_key:
            val = m_item.group(1).strip().strip('"').strip("'")
            if val:
                result[current_key].append(val)
            continue
        # Scalar key: key: value (not used here, ignore)
        m_scalar = re.match(r"^\s*([A-Za-z0-9_\- \/&]+)\s*:\s*(.+?)\s*$", line)
        if m_scalar:
            key = m_scalar.group(1).strip().lower()
            # Not a list; ignore for keywords
            if key not in result:
                result[key] = []
            current_key = None
            continue
    return result

def parse_config_yaml(path):
    """
    Minimal YAML parser to extract catalog_tokens scalar integer.
    """
    txt = read_text(path)
    if txt is None:
        return None
    catalog_tokens = None
    for raw in txt.splitlines():
        if "#" in raw:
            raw = raw.split("#", 1)[0]
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^catalog_tokens\s*:\s*([0-9]+)\s*$", line)
        if m:
            try:
                catalog_tokens = int(m.group(1))
            except:
                pass
    return {"catalog_tokens": catalog_tokens}

def count_keyword_hits(text, keyword):
    """
    Count case-insensitive substring occurrences of keyword in text.
    Non-overlapping counts, simple .count on lowered strings.
    """
    if not keyword:
        return 0
    tl = text.lower()
    kl = keyword.lower()
    return tl.count(kl)

def compute_expected(tasks, skills_catalog, keywords_map):
    """
    Compute expected recommendations per task and expected unique skills_loaded.
    Returns:
      expected_by_id: dict[int, list[dict]]
      unique_expected: dict[skill -> dict]
    """
    expected_by_id = {}
    conf_rank = {"medium": 1, "high": 2}
    unique_expected = {}

    # Consider only skills present in catalog
    valid_skills = set(skills_catalog.keys())

    for task_obj in tasks:
        tid = task_obj["id"]
        text = str(task_obj["task"] or "")
        counts = {}
        # Initialize counts for skills that have keywords
        for skill, kw_list in (keywords_map or {}).items():
            skill_l = skill.lower().strip()
            if skill_l not in valid_skills:
                continue
            total_hits = 0
            for kw in kw_list:
                total_hits += count_keyword_hits(text, str(kw))
            counts[skill_l] = total_hits
        # If no counts or all zero -> no recommendations
        max_hits = max(counts.values()) if counts else 0
        recs = []
        if max_hits > 0:
            threshold = 0.5 * max_hits
            for skill_l, hits in counts.items():
                if hits <= 0:
                    continue
                if hits == max_hits:
                    conf = "high"
                elif hits >= threshold:
                    conf = "medium"
                else:
                    continue  # exclude low relevance
                # Build record from catalog
                cat = skills_catalog[skill_l]
                recs.append({
                    "skill": skill_l,
                    "file": cat["file"],
                    "confidence": conf,
                    "size_tokens": cat["size_tokens"],
                })
                # Update unique set with highest confidence
                prev = unique_expected.get(skill_l)
                if prev is None or conf_rank[conf] > conf_rank[prev["confidence"]]:
                    unique_expected[skill_l] = {
                        "skill": skill_l,
                        "file": cat["file"],
                        "confidence": conf,
                        "size_tokens": cat["size_tokens"],
                    }
        expected_by_id[tid] = recs
    return expected_by_id, unique_expected

def normalize_recommendations_list(lst):
    """
    Normalize recommendations list into a dict by skill with canonical fields.
    """
    result = {}
    if not isinstance(lst, list):
        return result
    for item in lst:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill", "")).strip().lower()
        filep = item.get("file")
        conf = str(item.get("confidence", "")).strip().lower()
        size = item.get("size_tokens")
        try:
            size_int = int(size)
        except:
            continue
        result[skill] = {
            "skill": skill,
            "file": filep,
            "confidence": conf,
            "size_tokens": size_int,
        }
    return result

def compute_session_plan_numbers(skills_catalog, unique_expected, catalog_tokens):
    naive = sum(v["size_tokens"] for v in skills_catalog.values())
    loaded_sum = sum(v["size_tokens"] for v in unique_expected.values())
    cat = int(catalog_tokens or 0)
    lazy = cat + loaded_sum
    savings = naive - lazy
    pct = floor((savings / naive) * 100) if naive > 0 else 0
    return naive, lazy, savings, pct

def is_relative_path(p):
    if not isinstance(p, str):
        return False
    if p.startswith("/") or "://" in p:
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "recommendations_exists": False,
        "recommendations_task_coverage": False,
        "recommendations_correct": False,
        "no_low_confidence_in_recommendations": False,
        "skills_loaded_exists": False,
        "skills_loaded_dedup_and_correct": False,
        "not_all_skills_loaded": False,
        "session_plan_exists": False,
        "session_plan_format_correct": False,
        "session_plan_values_correct": False,
        "paths_relative": False,
    }

    # Load inputs
    skills_md_path = os.path.join(input_dir, "SKILLS.md")
    keywords_yaml_path = os.path.join(input_dir, "keywords.yaml")
    tasks_jsonl_path = os.path.join(input_dir, "tasks.jsonl")
    config_yaml_path = os.path.join(input_dir, "config.yaml")

    skills_catalog, naive_total = parse_skills_md(skills_md_path)
    keywords_map = parse_yaml_keywords(keywords_yaml_path)
    tasks = parse_tasks_jsonl(tasks_jsonl_path)
    config = parse_config_yaml(config_yaml_path)

    # If inputs missing, we still proceed, but outputs cannot be correct anyway.
    if skills_catalog is None or tasks is None or config is None:
        # We still must compute reward strictly from outputs; leave checks False.
        pass

    # Compute expected results if possible
    expected_by_id = {}
    expected_unique = {}
    if skills_catalog is not None and tasks is not None and keywords_map is not None:
        expected_by_id, expected_unique = compute_expected(tasks, skills_catalog, keywords_map)

    # Read outputs
    recs_path = os.path.join(output_dir, "recommendations.json")
    skills_loaded_path = os.path.join(output_dir, "skills_loaded.json")
    session_plan_path = os.path.join(output_dir, "session_plan.md")

    recs_data = load_json(recs_path)
    if isinstance(recs_data, list):
        checks["recommendations_exists"] = True

    skills_loaded_data = load_json(skills_loaded_path)
    if isinstance(skills_loaded_data, list):
        checks["skills_loaded_exists"] = True

    session_plan_txt = read_text(session_plan_path)
    if isinstance(session_plan_txt, str):
        checks["session_plan_exists"] = True

    # Validate recommendations.json
    if checks["recommendations_exists"] and tasks is not None and skills_catalog is not None:
        # Build map id -> recommended list
        recs_by_id = {}
        ids_in_output = set()
        low_conf_found = False
        all_paths_relative = True
        try:
            for obj in recs_data:
                if not isinstance(obj, dict):
                    continue
                tid = obj.get("id")
                recs_list = obj.get("recommended")
                if isinstance(tid, int) and isinstance(recs_list, list):
                    recs_by_id[tid] = recs_list
                    ids_in_output.add(tid)
                    # Validate each item confidence and path
                    for it in recs_list:
                        if isinstance(it, dict):
                            conf = str(it.get("confidence", "")).lower()
                            if conf not in ("high", "medium"):
                                low_conf_found = True
                            fp = it.get("file")
                            if not is_relative_path(fp):
                                all_paths_relative = False
        except:
            recs_by_id = {}
        # Task coverage
        expected_ids = set([t["id"] for t in tasks]) if tasks else set()
        if expected_ids and ids_in_output == expected_ids:
            checks["recommendations_task_coverage"] = True
        # Correctness check
        all_match = True
        files_and_sizes_match = True
        if expected_by_id and recs_by_id:
            for tid in expected_ids:
                exp_list = expected_by_id.get(tid, [])
                got_list = recs_by_id.get(tid, [])
                # Normalize to dict by skill for comparison
                exp_map = normalize_recommendations_list(exp_list)
                got_map = normalize_recommendations_list(got_list)
                # Compare keys (skills)
                if set(exp_map.keys()) != set(got_map.keys()):
                    all_match = False
                    break
                # Compare details for each skill
                for sk in exp_map.keys():
                    exp_item = exp_map[sk]
                    got_item = got_map[sk]
                    # file must match catalog exactly
                    if got_item["file"] != exp_item["file"]:
                        files_and_sizes_match = False
                        all_match = False
                        break
                    # size must match
                    if got_item["size_tokens"] != exp_item["size_tokens"]:
                        files_and_sizes_match = False
                        all_match = False
                        break
                    # confidence must match ('high' or 'medium' only)
                    if got_item["confidence"] != exp_item["confidence"]:
                        all_match = False
                        break
                if not all_match:
                    break
        else:
            all_match = False
        if all_match and files_and_sizes_match:
            checks["recommendations_correct"] = True
        # No low confidence
        if not low_conf_found:
            checks["no_low_confidence_in_recommendations"] = True
        # Paths relative check (accumulate)
        if all_paths_relative:
            # Will be combined with skills_loaded check later
            pass
        else:
            # Mark paths_relative false; we may still set true later only if both pass
            pass

    # Validate skills_loaded.json
    paths_relative_ok = True
    if checks["skills_loaded_exists"] and skills_catalog is not None:
        sl_list = skills_loaded_data if isinstance(skills_loaded_data, list) else []
        sl_map = {}
        duplicate_found = False
        low_conf_in_loaded = False
        for it in sl_list:
            if not isinstance(it, dict):
                continue
            skill = str(it.get("skill", "")).strip().lower()
            filep = it.get("file")
            conf = str(it.get("confidence", "")).strip().lower()
            size = it.get("size_tokens")
            try:
                size_int = int(size)
            except:
                size_int = None
            if not is_relative_path(filep):
                paths_relative_ok = False
            if conf not in ("high", "medium"):
                low_conf_in_loaded = True
            if skill in sl_map:
                duplicate_found = True
            else:
                sl_map[skill] = {"file": filep, "confidence": conf, "size_tokens": size_int}
        # Compare with expected unique
        exp_unique = expected_unique or {}
        # Skills set must match
        skills_match = set(sl_map.keys()) == set(exp_unique.keys())
        details_match = skills_match
        if details_match:
            for sk in exp_unique.keys():
                exp_item = exp_unique[sk]
                got_item = sl_map.get(sk, {})
                # file must match catalog
                if got_item.get("file") != exp_item["file"]:
                    details_match = False
                    break
                if got_item.get("size_tokens") != exp_item["size_tokens"]:
                    details_match = False
                    break
                if got_item.get("confidence") != exp_item["confidence"]:
                    details_match = False
                    break
        if (not duplicate_found) and skills_match and details_match:
            checks["skills_loaded_dedup_and_correct"] = True
        # not all skills loaded
        if len(sl_map) < len(skills_catalog):
            checks["not_all_skills_loaded"] = True
        # paths relative will be combined with recommendations status
        if not paths_relative_ok:
            pass

    # Paths relative check across both outputs (if both exist)
    if checks["recommendations_exists"] and checks["skills_loaded_exists"]:
        # Re-validate paths relative for recommendations
        rec_paths_ok = True
        try:
            for obj in recs_data:
                recs_list = obj.get("recommended", []) if isinstance(obj, dict) else []
                for it in recs_list:
                    if isinstance(it, dict):
                        fp = it.get("file")
                        if not is_relative_path(fp):
                            rec_paths_ok = False
                            break
                if not rec_paths_ok:
                    break
        except:
            rec_paths_ok = False
        if rec_paths_ok and paths_relative_ok:
            checks["paths_relative"] = True

    # Validate session_plan.md
    if checks["session_plan_exists"] and skills_catalog is not None:
        lines = [ln.rstrip("\n") for ln in session_plan_txt.splitlines()]
        if len(lines) == 4:
            # Expect exact labels
            pat1 = r"^Naive cost tokens:\s*([0-9]+)\s*$"
            pat2 = r"^Lazy cost tokens:\s*([0-9]+)\s*$"
            pat3 = r"^Savings tokens:\s*([0-9]+)\s*$"
            pat4 = r"^Savings percent:\s*(-?[0-9]+)%\s*$"
            m1 = re.match(pat1, lines[0])
            m2 = re.match(pat2, lines[1])
            m3 = re.match(pat3, lines[2])
            m4 = re.match(pat4, lines[3])
            if m1 and m2 and m3 and m4:
                checks["session_plan_format_correct"] = True
                try:
                    naive_val = int(m1.group(1))
                    lazy_val = int(m2.group(1))
                    savings_val = int(m3.group(1))
                    pct_val = int(m4.group(1))
                except:
                    naive_val = lazy_val = savings_val = pct_val = None
                # Compute expected values using expected_unique (from expected recommendations)
                if expected_unique is not None and config is not None:
                    catalog_tokens = (config or {}).get("catalog_tokens")
                    expected_naive, expected_lazy, expected_savings, expected_pct = compute_session_plan_numbers(
                        skills_catalog, expected_unique, catalog_tokens
                    )
                    if (naive_val == expected_naive and
                        lazy_val == expected_lazy and
                        savings_val == expected_savings and
                        pct_val == expected_pct):
                        checks["session_plan_values_correct"] = True

    # Compute reward as weighted sum
    weights = {
        "recommendations_exists": 0.05,
        "recommendations_task_coverage": 0.08,
        "recommendations_correct": 0.32,
        "no_low_confidence_in_recommendations": 0.05,
        "skills_loaded_exists": 0.05,
        "skills_loaded_dedup_and_correct": 0.22,
        "not_all_skills_loaded": 0.03,
        "session_plan_exists": 0.05,
        "session_plan_format_correct": 0.05,
        "session_plan_values_correct": 0.08,
        "paths_relative": 0.02,
    }
    total_weight = sum(weights.values())
    earned = 0.0
    # Ensure baseline: if output dir missing or no artifacts, reward stays 0.0
    for k, w in weights.items():
        if checks.get(k, False):
            earned += w
    reward = round(earned / total_weight, 6) if total_weight > 0 else 0.0
    # No-op baseline: if neither recommendations nor skills_loaded nor session_plan exists, force 0
    if not (checks["recommendations_exists"] or checks["skills_loaded_exists"] or checks["session_plan_exists"]):
        reward = 0.0

    # Print single JSON line
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()