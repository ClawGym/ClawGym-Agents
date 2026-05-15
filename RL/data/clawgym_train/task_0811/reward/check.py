import json
import os
import re
import sys
from datetime import datetime, timezone

def parse_iso_utc(ts):
    # Handle timestamps like 2026-06-18T12:34:56Z
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        # Fallback strict strptime for Z pattern
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            return None

def iso_week_str(dt):
    iso = dt.isocalendar()
    # Python 3.8 tuple vs 3.11 object
    try:
        year = iso.year
        week = iso.week
    except AttributeError:
        year, week, _ = iso
    return f"{year}-W{week:02d}"

def read_jsonl(path):
    items = []
    if not os.path.isfile(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                items.append(obj)
            except Exception:
                # Skip invalid line
                pass
    return items

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
        return ""

def listdir_safe(path):
    try:
        return os.listdir(path)
    except Exception:
        return []

def header_line_for(mem):
    # mem fields: timestamp, type, importance
    return f"## [{mem['timestamp']}] {mem['type']} (importance: {mem['importance']})"

def get_block_ranges(lines):
    # Return list of (start_index, end_index) for each header block
    header_re = re.compile(r"^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\] (learning|decision|insight|event|interaction) \(importance: [1-9][0-9]?\)$")
    headers = [i for i, ln in enumerate(lines) if header_re.match(ln)]
    ranges = []
    for idx, start in enumerate(headers):
        end = len(lines) - 1
        if idx + 1 < len(headers):
            end = headers[idx + 1] - 1
        ranges.append((start, end))
    return ranges

def find_block_for_header(lines, header_line):
    # Find block by exact header line
    indices = [i for i, ln in enumerate(lines) if ln == header_line]
    if not indices:
        return None
    hi = indices[0]
    # Find next header occurrence after hi
    header_re = re.compile(r"^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\] (learning|decision|insight|event|interaction) \(importance: [1-9][0-9]?\)$")
    end = len(lines) - 1
    for j in range(hi + 1, len(lines)):
        if header_re.match(lines[j]):
            end = j - 1
            break
    return (hi, end)

def safe_get(d, k, default=None):
    try:
        return d[k]
    except Exception:
        return default

def word_count(text):
    return len([w for w in re.split(r"\s+", text.strip()) if w])

def is_sorted_non_increasing(seq):
    return all(seq[i] >= seq[i+1] for i in range(len(seq)-1))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Index related
        "out_index_exists": False,
        "index_valid_json": False,
        "index_version_correct": False,
        "index_total_memories_match": False,
        "index_memories_fields_valid": False,
        "index_ids_and_files_valid": False,
        "index_values_match_input": False,
        "index_id_sequence_per_day_correct": False,
        "index_stats_by_type_correct": False,
        "index_stats_by_importance_correct": False,

        # Daily logs
        "daily_all_files_exist": False,
        "daily_entries_format_valid": False,
        "daily_content_and_tags_lines_valid": False,
        "daily_context_lines_for_nonempty_present": False,

        # Consolidation
        "consolidation_exists": False,
        "consolidation_header_correct": False,
        "consolidation_high_importance_section_complete": False,
        "consolidation_high_importance_no_low": False,
        "consolidation_by_type_section_complete": False,
        "consolidation_by_type_subsections_all_present": False,
        "consolidation_by_type_contents_correct": False,

        # Search results
        "search_file_valid": False,
        "search_filter_and_sort_correct": False,
        "search_contains_expected_ids": False,

        # README
        "readme_exists": False,
        "readme_length_ok": False,
        "readme_contains_required_terms": False,
    }

    # If output dir is missing or empty, reward must be 0.0; but we still compute checks safely
    output_exists = os.path.isdir(output_dir)
    if not output_exists:
        # print final result with zero reward and all False
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Read input memories
    input_memories_path = os.path.join(input_dir, "memories.jsonl")
    input_memories = read_jsonl(input_memories_path)
    # Normalize input tags to list of strings if possible
    for mem in input_memories:
        tags = mem.get("tags")
        if isinstance(tags, list):
            mem["_tags_list"] = [str(t) for t in tags if str(t) != ""]
        elif isinstance(tags, str):
            # split by comma, strip spaces
            mem["_tags_list"] = [t.strip() for t in tags.split(",") if t.strip() != ""]
        else:
            mem["_tags_list"] = []
        mem["_timestamp_dt"] = parse_iso_utc(mem.get("timestamp", ""))

    # Prepare expected dates set
    expected_dates = set()
    for mem in input_memories:
        dt = mem.get("_timestamp_dt")
        if not isinstance(dt, datetime):
            continue
        expected_dates.add(dt.date().isoformat())

    # Load index
    index_path = os.path.join(output_dir, "index", "memory-index.json")
    index_data = load_json(index_path)
    if os.path.isfile(index_path):
        checks["out_index_exists"] = True
    if isinstance(index_data, dict):
        checks["index_valid_json"] = True

    # Prepare some structures
    index_memories = []
    index_by_content = {}
    index_by_id = {}
    daily_dir = os.path.join(output_dir, "daily")

    if checks["index_valid_json"]:
        # version
        if index_data.get("version") == "2.0":
            checks["index_version_correct"] = True

        # memories array
        mems = index_data.get("memories")
        if isinstance(mems, list):
            index_memories = mems

        # total memories match input
        try:
            stats = index_data.get("stats", {})
            total = stats.get("totalMemories", None)
            if isinstance(total, int) and total == len(input_memories) and len(index_memories) == len(input_memories):
                checks["index_total_memories_match"] = True
        except Exception:
            pass

        # fields validation
        fields_ok = True
        ids_and_files_ok = True
        values_match_ok = True
        id_seq_ok = True

        id_re = re.compile(r"^mem_\d{8}_\d{3}$")
        type_set = {"learning", "decision", "insight", "event", "interaction"}

        # Build mappings
        for m in index_memories:
            cid = m.get("id")
            if isinstance(cid, str):
                index_by_id[cid] = m
            ccontent = m.get("content")
            if isinstance(ccontent, str) and ccontent not in index_by_content:
                index_by_content[ccontent] = m

        # Validate each memory object
        for m in index_memories:
            # Ensure required fields presence and types
            has_fields = (
                isinstance(m.get("id"), str) and
                isinstance(m.get("timestamp"), str) and
                isinstance(m.get("type"), str) and m.get("type") in type_set and
                (isinstance(m.get("importance"), int) or isinstance(m.get("importance"), float)) and
                isinstance(m.get("content"), str) and
                isinstance(m.get("file"), str) and
                isinstance(m.get("line"), int) and
                isinstance(m.get("tags"), list) and len(m.get("tags")) > 0 and
                "context" in m  # field exists; may be empty string
            )
            if not has_fields:
                fields_ok = False

            # id regex and date match, file path and file existence
            cid = m.get("id", "")
            ts = m.get("timestamp", "")
            dt = parse_iso_utc(ts)
            file_rel = m.get("file", "")
            date_ok = False
            file_ok = False
            if id_re.match(cid) and isinstance(dt, datetime):
                # date part equals timestamp date
                date_str = dt.date().isoformat()
                id_date = cid[4:12]  # YYYYMMDD
                if id_date == date_str.replace("-", ""):
                    date_ok = True
            # file must equal daily/YYYY-MM-DD.md and that file exists
            if isinstance(dt, datetime):
                expected_file_rel = f"daily/{dt.date().isoformat()}.md"
                file_path = os.path.join(output_dir, expected_file_rel)
                if file_rel == expected_file_rel and os.path.isfile(file_path):
                    file_ok = True
            if not (date_ok and file_ok):
                ids_and_files_ok = False

        if fields_ok:
            checks["index_memories_fields_valid"] = True
        if ids_and_files_ok:
            checks["index_ids_and_files_valid"] = True

        # Values match input by unique content
        if input_memories and index_memories:
            for im in input_memories:
                content = im.get("content")
                idxm = index_by_content.get(content)
                if not idxm:
                    values_match_ok = False
                    break
                # Compare selected fields
                if idxm.get("timestamp") != im.get("timestamp"):
                    values_match_ok = False
                    break
                if idxm.get("type") != im.get("type"):
                    values_match_ok = False
                    break
                # importance numeric equality
                if int(idxm.get("importance")) != int(im.get("importance")):
                    values_match_ok = False
                    break
                # tags equality (array)
                in_tags = im.get("tags")
                if not isinstance(in_tags, list):
                    in_tags = im.get("_tags_list", [])
                idx_tags = idxm.get("tags")
                if [str(t) for t in idx_tags] != [str(t) for t in in_tags]:
                    values_match_ok = False
                    break
            if values_match_ok:
                checks["index_values_match_input"] = True

        # ID sequence per day correct: for each date, order by timestamp ascending and check ids increment from 001
        if checks["index_values_match_input"]:
            seq_ok = True
            # Build per-date list from input in chronological order
            per_date = {}
            for im in sorted(input_memories, key=lambda x: (safe_get(x, "_timestamp_dt", datetime(1970,1,1, tzinfo=timezone.utc)), input_memories.index(x))):
                dt = im.get("_timestamp_dt")
                if not isinstance(dt, datetime):
                    continue
                date_key = dt.date().isoformat()
                per_date.setdefault(date_key, []).append(im)
            for date_key, im_list in per_date.items():
                # For each, map to index memory by content and check suffix
                for i, im in enumerate(im_list, start=1):
                    idxm = index_by_content.get(im.get("content"))
                    if not idxm:
                        seq_ok = False
                        break
                    cid = idxm.get("id", "")
                    if not re.match(r"^mem_\d{8}_\d{3}$", cid or ""):
                        seq_ok = False
                        break
                    suffix = cid[-3:]
                    expected_suffix = f"{i:03d}"
                    if suffix != expected_suffix:
                        seq_ok = False
                        break
                if not seq_ok:
                    break
            if seq_ok:
                checks["index_id_sequence_per_day_correct"] = True

        # Stats checks
        # byType
        expected_by_type = {"learning": 0, "decision": 0, "insight": 0, "event": 0, "interaction": 0}
        for im in input_memories:
            t = im.get("type")
            if t in expected_by_type:
                expected_by_type[t] += 1
        actual_by_type = index_data.get("stats", {}).get("byType")
        if isinstance(actual_by_type, dict):
            # allow missing keys if zero, but require that for all five keys counts match
            ok = True
            for k, v in expected_by_type.items():
                if int(actual_by_type.get(k, 0)) != int(v):
                    ok = False
                    break
            if ok:
                checks["index_stats_by_type_correct"] = True

        # byImportance
        expected_by_imp = {}
        for im in input_memories:
            imp = im.get("importance")
            try:
                key = str(int(imp))
            except Exception:
                continue
            expected_by_imp[key] = expected_by_imp.get(key, 0) + 1
        actual_by_imp = index_data.get("stats", {}).get("byImportance")
        if isinstance(actual_by_imp, dict):
            ok = True
            # Require that for all keys present in expected, actual matches; allow extra zero keys
            for k, v in expected_by_imp.items():
                if int(actual_by_imp.get(k, 0)) != int(v):
                    ok = False
                    break
            # Also ensure actual doesn't claim nonzero counts for keys not in expected
            for k, v in actual_by_imp.items():
                try:
                    vv = int(v)
                except Exception:
                    ok = False
                    break
                if vv != 0 and k not in expected_by_imp:
                    ok = False
                    break
            if ok:
                checks["index_stats_by_importance_correct"] = True

    # Daily logs checks
    if expected_dates:
        daily_files_exist = True
        for date_str in expected_dates:
            path = os.path.join(output_dir, "daily", f"{date_str}.md")
            if not os.path.isfile(path):
                daily_files_exist = False
                break
        if daily_files_exist:
            checks["daily_all_files_exist"] = True

    # format and content checks
    entries_format_ok = True
    content_tags_ok = True
    context_nonempty_ok = True

    # Build memories per date for checking
    mems_by_date = {}
    for im in input_memories:
        dt = im.get("_timestamp_dt")
        if not isinstance(dt, datetime):
            continue
        mems_by_date.setdefault(dt.date().isoformat(), []).append(im)

    for date_str, mems_list in mems_by_date.items():
        daily_path = os.path.join(output_dir, "daily", f"{date_str}.md")
        if not os.path.isfile(daily_path):
            entries_format_ok = False
            content_tags_ok = False
            context_nonempty_ok = False
            continue
        text = read_text(daily_path)
        lines = text.splitlines()
        # For each memory in that date, check header line and content/tags/context within block
        for im in mems_list:
            hdr = header_line_for(im)
            # Header regex presence
            if hdr not in lines:
                entries_format_ok = False
                # continue checking other mems to aggregate errors
                continue
            block = find_block_for_header(lines, hdr)
            if not block:
                content_tags_ok = False
                if im.get("context"):
                    context_nonempty_ok = False
                continue
            start, end = block
            block_lines = lines[start:end+1]
            # content line should appear exactly once in block
            content_line = im.get("content", "")
            if content_line not in block_lines:
                content_tags_ok = False
            # tags line exact, comma-space separated
            tags_list = im.get("_tags_list", [])
            expected_tags_line = "**Tags:** " + ", ".join([str(t) for t in tags_list])
            if expected_tags_line not in block_lines:
                content_tags_ok = False
            # context if non-empty
            ctx = im.get("context")
            if ctx is not None and str(ctx).strip() != "":
                expected_ctx_line = "**Context:** " + str(ctx)
                if expected_ctx_line not in block_lines:
                    context_nonempty_ok = False

    if checks["daily_all_files_exist"] and entries_format_ok:
        checks["daily_entries_format_valid"] = True
    if checks["daily_all_files_exist"] and content_tags_ok:
        checks["daily_content_and_tags_lines_valid"] = True
    if checks["daily_all_files_exist"] and context_nonempty_ok:
        checks["daily_context_lines_for_nonempty_present"] = True

    # Consolidation checks
    cons_path = os.path.join(output_dir, "consolidated", "2026-W25.md")
    if os.path.isfile(cons_path):
        checks["consolidation_exists"] = True
        cons_text = read_text(cons_path)
        cons_lines = cons_text.splitlines()

        # Header line
        if len(cons_lines) > 0 and cons_lines[0].strip() == "# Weekly Memory Consolidation: 2026-W25":
            checks["consolidation_header_correct"] = True

        # Generated: line present anywhere
        # Not scored as a separate check; but requirement says should exist. We can implicitly accept via other checks.

        # Parse High-Importance section lines between that header and "## By Type"
        try:
            hi_idx = next(i for i, ln in enumerate(cons_lines) if ln.strip() == "## High-Importance Memories (8+)")
            try:
                by_type_idx = next(i for i, ln in enumerate(cons_lines) if ln.strip() == "## By Type")
            except StopIteration:
                by_type_idx = len(cons_lines)
            hi_section = cons_lines[hi_idx+1:by_type_idx]
            hi_bullets = [ln.strip() for ln in hi_section if ln.strip().startswith("- ")]
        except StopIteration:
            hi_bullets = []

        # Expected high importance from input for week 2026-W25
        expected_hi_bullets = []
        for im in input_memories:
            dt = im.get("_timestamp_dt")
            if not isinstance(dt, datetime):
                continue
            if iso_week_str(dt) == "2026-W25":
                try:
                    imp = int(im.get("importance"))
                except Exception:
                    continue
                if imp >= 8:
                    expected_hi_bullets.append(f"- {im['timestamp']} | {im['type']} | imp:{imp} | {im['content']}")
        # Check completeness: all expected appear
        if expected_hi_bullets:
            if all(b in hi_bullets for b in expected_hi_bullets):
                checks["consolidation_high_importance_section_complete"] = True
        else:
            # If no expected high importance, treat as trivially complete (no bullets required)
            checks["consolidation_high_importance_section_complete"] = True

        # Ensure no low-importance bullets in HI section
        low_present = False
        for b in hi_bullets:
            m = re.search(r"imp:(\d+)", b)
            if m:
                try:
                    imp = int(m.group(1))
                    if imp < 8:
                        low_present = True
                        break
                except Exception:
                    pass
        if not low_present and len(hi_bullets) >= 0:
            checks["consolidation_high_importance_no_low"] = True

        # By Type section checks
        cons_text_full = cons_text
        if "## By Type" in cons_text_full:
            checks["consolidation_by_type_section_complete"] = True

            # Find subsections
            subtype_headers = {
                "learning": "### learning",
                "decision": "### decision",
                "interaction": "### interaction",
                "event": "### event",
                "insight": "### insight",
            }
            # Positions of each subsection
            try:
                by_type_start = next(i for i, ln in enumerate(cons_lines) if ln.strip() == "## By Type")
            except StopIteration:
                by_type_start = None

            subs_present = True
            subtype_ranges = {}
            if by_type_start is not None:
                # Find all indices of ### headers after by_type_start
                sub_indices = []
                for i in range(by_type_start+1, len(cons_lines)):
                    if cons_lines[i].strip().startswith("### "):
                        sub_indices.append(i)
                # Map names to ranges
                # Ensure all five subsections appear
                names_found = {}
                for idx in sub_indices:
                    name = cons_lines[idx].strip().replace("### ", "").strip().lower()
                    names_found[name] = idx
                for name, hdr in subtype_headers.items():
                    if name not in names_found:
                        subs_present = False
                        break
                if subs_present:
                    # Determine ranges per subsection
                    ordered = sorted([(names_found[name], name) for name in names_found])
                    for i, (start_idx, name) in enumerate(ordered):
                        end_idx = len(cons_lines) - 1
                        if i + 1 < len(ordered):
                            end_idx = ordered[i+1][0] - 1
                        subtype_ranges[name] = (start_idx, end_idx)
            if subs_present and len(subtype_ranges) == 5:
                checks["consolidation_by_type_subsections_all_present"] = True

                # Validate bullets under each subsection correspond to that week's memories of that type
                contents_ok = True
                for tname in ["learning", "decision", "interaction", "event", "insight"]:
                    start, end = subtype_ranges[tname]
                    section_lines = [ln.strip() for ln in cons_lines[start+1:end+1]]
                    bullets = [ln for ln in section_lines if ln.startswith("- ")]
                    expected_bullets = []
                    for im in input_memories:
                        dt = im.get("_timestamp_dt")
                        if not isinstance(dt, datetime):
                            continue
                        if iso_week_str(dt) == "2026-W25" and im.get("type") == tname:
                            try:
                                imp = int(im.get("importance"))
                            except Exception:
                                continue
                            expected_bullets.append(f"- {im['timestamp']} | {im['type']} | imp:{imp} | {im['content']}")
                    # All expected must appear (order not enforced)
                    if not all(b in bullets for b in expected_bullets):
                        contents_ok = False
                        break
                    # No bullets should refer to other types in this section
                    for b in bullets:
                        m = re.search(r"\|\s*([a-zA-Z]+)\s*\|\s*imp:", b)
                        if m:
                            btype = m.group(1).strip().lower()
                            if btype != tname:
                                contents_ok = False
                                break
                    if not contents_ok:
                        break
                if contents_ok:
                    checks["consolidation_by_type_contents_correct"] = True

    # Search results checks
    search_path = os.path.join(output_dir, "search_browser.json")
    search_data = load_json(search_path)
    if isinstance(search_data, list):
        # basic schema validation
        valid_items = True
        for it in search_data:
            if not (isinstance(it, dict) and isinstance(it.get("id"), str) and (isinstance(it.get("importance"), int) or isinstance(it.get("importance"), float)) and isinstance(it.get("content"), str)):
                valid_items = False
                break
        if valid_items:
            checks["search_file_valid"] = True

        # Build expected IDs based on input condition and index mapping
        expected_ids = []
        expected_importances = {}
        for im in input_memories:
            content = im.get("content", "")
            imp = im.get("importance")
            try:
                imp_int = int(imp)
            except Exception:
                continue
            if "automation" in content.lower() and imp_int >= 8:
                idxm = index_by_content.get(content)
                if idxm:
                    eid = idxm.get("id")
                    if isinstance(eid, str):
                        expected_ids.append(eid)
                        expected_importances[eid] = imp_int

        # Filter and sort correctness: all items contain 'automation' and imp >=8, sorted by importance descending
        filter_sort_ok = True
        improp = [it.get("importance") for it in search_data]
        if not is_sorted_non_increasing(improp):
            filter_sort_ok = False
        for it in search_data:
            if "automation" not in it.get("content", "").lower():
                filter_sort_ok = False
                break
            try:
                if int(it.get("importance")) < 8:
                    filter_sort_ok = False
                    break
            except Exception:
                filter_sort_ok = False
                break
        if filter_sort_ok:
            checks["search_filter_and_sort_correct"] = True

        # Contains expected ids (set equality)
        got_ids = [it.get("id") for it in search_data if isinstance(it, dict)]
        if set(got_ids) == set(expected_ids):
            checks["search_contains_expected_ids"] = True

    # README checks
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        readme_text = read_text(readme_path)
        if word_count(readme_text) >= 200:
            checks["readme_length_ok"] = True
        # Contains required terms (case-insensitive)
        lower = readme_text.lower()
        required_terms = ["overview", "index", "consolidation", "search"]
        if all(term in lower for term in required_terms):
            checks["readme_contains_required_terms"] = True

    # If output directory has no files at all, force reward 0.0
    has_any_output_file = False
    for root, dirs, files in os.walk(output_dir):
        if files:
            has_any_output_file = True
            break
    # Compute reward as fraction of passed checks, but zero if no outputs
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if has_any_output_file else 0.0

    # Ensure reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()