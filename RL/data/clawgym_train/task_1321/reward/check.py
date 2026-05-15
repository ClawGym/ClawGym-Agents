import json
import os
import re
import sys
from typing import List, Dict, Any, Optional, Tuple

# Workspace and paths
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# File paths
seed_path = os.path.join(input_dir, "TODO_seed.md")
instructions_path = os.path.join(input_dir, "instructions.md")
today_path = os.path.join(input_dir, "today.json")
out_todo_path = os.path.join(output_dir, "TODO.md")
out_report_path = os.path.join(output_dir, "report.json")

# Regex helpers
RE_TODO = re.compile(r'^\s*-\s\[( |x|X)\]\s(.*)$')
RE_TODO_PREFIX = re.compile(r'^\s*-\s\[( |x|X)\]\s')
RE_INVALID_TODO_BRACKET = re.compile(r'^\s*-\s*\[(?! |x|X).*\]')
RE_TAG = re.compile(r'#([A-Za-z0-9-]+)')
RE_PRIORITY = re.compile(r'!(high|medium|low)', re.IGNORECASE)
RE_DUE = re.compile(r'@due\((\d{4}-\d{2}-\d{2})\)', re.IGNORECASE)
RE_HEADER = re.compile(r'^\s*#+\s+.*')

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_todos(md: str) -> List[Dict[str, Any]]:
    items = []
    lines = md.splitlines()
    for idx, line in enumerate(lines):
        m = RE_TODO.match(line)
        if not m:
            continue
        status = m.group(1)
        text = m.group(2).strip()
        done = True if status.lower() == 'x' else False
        tags = extract_tags(text)
        priority = extract_priority(text)
        due_date = extract_due_date(text)
        items.append({
            "lineNo": idx,
            "raw": line.rstrip("\n"),
            "done": done,
            "text": text,
            "tags": tags,
            "priority": priority,
            "dueDate": due_date
        })
    return items

def is_todo_line(line: str) -> bool:
    return bool(RE_TODO.match(line))

def extract_tags(text: str) -> List[str]:
    tags = [m.lower() for m in RE_TAG.findall(text or "")]
    # dedupe preserving order
    seen = set()
    result = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result

def extract_priority(text: str) -> Optional[str]:
    m = RE_PRIORITY.search(text or "")
    if not m:
        return None
    return m.group(1).lower()

def extract_due_date(text: str) -> Optional[str]:
    m = RE_DUE.search(text or "")
    if not m:
        return None
    return m.group(1)

def normalize_priority(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v == "null":
            return None
        if v in ("high", "medium", "low"):
            return v
    return None

def normalize_due(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if v.lower() == "null":
            return None
        # Accept YYYY-MM-DD by regex
        if re.match(r'^\d{4}-\d{2}-\d{2}$', v):
            return v
    return None

def parse_today_value(content: Optional[str]) -> Optional[str]:
    if content is None:
        return None
    content = content.strip()
    # Try JSON parsing
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and "today" in obj and isinstance(obj["today"], str):
            return obj["today"]
        if isinstance(obj, str):
            return obj
    except Exception:
        # Fall back: raw content may be YYYY-MM-DD
        pass
    # Simple line with date
    if re.match(r'^\d{4}-\d{2}-\d{2}$', content):
        return content
    return None

def non_todo_lines(md: str) -> List[str]:
    lines = md.splitlines()
    res = []
    for line in lines:
        if not RE_TODO.match(line):
            res.append(line.rstrip("\n"))
    return res

def find_header_indices(md_lines: List[str], header_text: str) -> List[int]:
    # Case-insensitive exact match of header line after trimming spaces
    target = header_text.strip().lower()
    indices = []
    for i, line in enumerate(md_lines):
        if line.strip().lower() == target:
            # Must be a header line (starts with '#')
            if line.lstrip().startswith("#"):
                indices.append(i)
    return indices

def find_next_header_index(md_lines: List[str], start_idx: int) -> int:
    for i in range(start_idx + 1, len(md_lines)):
        if RE_HEADER.match(md_lines[i] or ""):
            return i
    return len(md_lines)

def strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def parse_target_from_line(line: str) -> Dict[str, Any]:
    # Return {"by":"index","index":int} or {"by":"text","text":str} or {}
    # Try number after command
    num = re.search(r'(?<![#/A-Za-z])(\d+)(?![A-Za-z])', line)
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', line)
    if "/todo-" in line.lower():
        # Prefer argument after command
        m = re.search(r'/todo-(?:done|edit|remove)\s+(.+)$', line, flags=re.IGNORECASE)
        if m:
            arg = m.group(1).strip()
            # If arg begins with number, use index
            mnum = re.match(r'^(\d+)\b', arg)
            if mnum:
                try:
                    return {"by": "index", "index": int(mnum.group(1))}
                except Exception:
                    pass
            # Else take quoted text if present
            if quoted:
                for q1, q2 in quoted:
                    q = q1 or q2
                    if q:
                        return {"by": "text", "text": q}
            # Fallback: all remaining as text
            return {"by": "text", "text": arg}
    # General fallback
    if quoted:
        q = quoted[0][0] or quoted[0][1]
        return {"by": "text", "text": q}
    if num:
        try:
            return {"by": "index", "index": int(num.group(1))}
        except Exception:
            pass
    return {}

def parse_add_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not re.search(r'(?i)\b(add|insert|/todo-add)\b', s):
        return None
    # Pattern 1: Under "Header", add: "Text"
    m = re.search(r'(?i)under\s+(?:"([^"]+)"|\'([^\']+)\'|([^,]+?))\s*,?\s*(?:please\s*)?(?:add|insert)[:\s]\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))$', s, flags=0)
    if m:
        header = m.group(1) or m.group(2) or (m.group(3).strip() if m.group(3) else None)
        text = m.group(4) or m.group(5) or (m.group(6).strip() if m.group(6) else None)
        if text:
            return {"text": text.strip(), "header": header.strip() if header else None}
    # Pattern 2: /todo-add <text> [under|in] "Header"
    m = re.search(r'(?i)/todo-add\s+(.+?)(?:\s+(?:under|in)\s+(?:"([^"]+)"|\'([^\']+)\'|(.+)))?$', s)
    if m:
        text = (m.group(1) or "").strip()
        header = m.group(2) or m.group(3) or (m.group(4).strip() if m.group(4) else None)
        # Remove trailing spaces from text if header portion included mistakenly
        # Already handled by regex
        if text:
            return {"text": strip_quotes(text), "header": header.strip() if header else None}
    # Pattern 3: add "Text" under "Header"
    m = re.search(r'(?i)\b(?:add|insert)\s+(?:"([^"]+)"|\'([^\']+)\'|(.+?))(?:\s+(?:under|in)\s+(?:"([^"]+)"|\'([^\']+)\'|(.+)))?$', s)
    if m:
        text = m.group(1) or m.group(2) or (m.group(3).strip() if m.group(3) else None)
        header = m.group(4) or m.group(5) or (m.group(6).strip() if m.group(6) else None)
        if text:
            return {"text": text.strip(), "header": header.strip() if header else None}
    return None

def parse_edit_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not re.search(r'(?i)\b(edit|/todo-edit|update)\b', s):
        return None
    # Case A: /todo-edit <index> <new text>
    m = re.search(r'(?i)/todo-edit\s+(\d+)\s+(.+)$', s)
    if m:
        idx = int(m.group(1))
        new_text = m.group(2).strip()
        return {"target": {"by": "index", "index": idx}, "new_text": new_text, "new_due": None}
    # Case B: edit "<old>" to "<new>"
    m = re.search(r'(?i)\bedit\b\s+(?:"([^"]+)"|\'([^\']+)\'|(.+?))\s+(?:to|->)\s+(?:"([^"]+)"|\'([^\']+)\'|(.+))$', s)
    if m:
        old = m.group(1) or m.group(2) or (m.group(3).strip() if m.group(3) else None)
        new = m.group(4) or m.group(5) or (m.group(6).strip() if m.group(6) else None)
        if old and new:
            return {"target": {"by": "text", "text": old}, "new_text": new, "new_due": None}
    # Case C: update due date for target to YYYY-MM-DD
    m = re.search(r'(?i)update\s+due\s+date\s+for\s+(?:"([^"]+)"|\'([^\']+)\'|(\d+))\s+to\s+(\d{4}-\d{2}-\d{2})', s)
    if m:
        targ_text = m.group(1) or m.group(2)
        if targ_text:
            return {"target": {"by": "text", "text": targ_text}, "new_text": None, "new_due": m.group(4)}
        else:
            return {"target": {"by": "index", "index": int(m.group(3))}, "new_text": None, "new_due": m.group(4)}
    # Case D: /todo-edit <index> --due YYYY-MM-DD
    m = re.search(r'(?i)/todo-edit\s+(\d+).*(?:--due|\bdue\s+to)\s+(\d{4}-\d{2}-\d{2})', s)
    if m:
        return {"target": {"by": "index", "index": int(m.group(1))}, "new_text": None, "new_due": m.group(2)}
    # Case E: edit <index> to "<new>"
    m = re.search(r'(?i)\bedit\b\s+(\d+)\s+(?:to|->)\s+(?:"([^"]+)"|\'([^\']+)\'|(.+))$', s)
    if m:
        idx = int(m.group(1))
        new = m.group(2) or m.group(3) or (m.group(4).strip() if m.group(4) else None)
        if new:
            return {"target": {"by": "index", "index": idx}, "new_text": new, "new_due": None}
    return None

def parse_done_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not re.search(r'(?i)(/todo-done|mark\s+done|mark.+as\s+done|complete\s+)', s):
        return None
    # /todo-done
    m = re.search(r'(?i)/todo-done\s+(.+)$', s)
    if m:
        arg = m.group(1).strip()
        if re.match(r'^\d+$', arg):
            return {"target": {"by": "index", "index": int(arg)}}
        qs = re.findall(r'"([^"]+)"|\'([^\']+)\'', arg)
        if qs:
            q = qs[0][0] or qs[0][1]
            return {"target": {"by": "text", "text": q}}
        return {"target": {"by": "text", "text": arg}}
    # mark done "..."
    m = re.search(r'(?i)mark.*done.*?(?:"([^"]+)"|\'([^\']+)\'|(\d+))', s)
    if m:
        if m.group(3):
            return {"target": {"by": "index", "index": int(m.group(3))}}
        text = m.group(1) or m.group(2)
        if text:
            return {"target": {"by": "text", "text": text}}
    # complete item
    m = re.search(r'(?i)complete\s+(?:"([^"]+)"|\'([^\']+)\'|(\d+))', s)
    if m:
        if m.group(3):
            return {"target": {"by": "index", "index": int(m.group(3))}}
        text = m.group(1) or m.group(2)
        if text:
            return {"target": {"by": "text", "text": text}}
    return None

def parse_remove_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not re.search(r'(?i)(/todo-remove|remove|delete)\b', s):
        return None
    # /todo-remove
    m = re.search(r'(?i)/todo-remove\s+(.+)$', s)
    if m:
        arg = m.group(1).strip()
        if re.match(r'^\d+$', arg):
            return {"target": {"by": "index", "index": int(arg)}}
        qs = re.findall(r'"([^"]+)"|\'([^\']+)\'', arg)
        if qs:
            q = qs[0][0] or qs[0][1]
            return {"target": {"by": "text", "text": q}}
        return {"target": {"by": "text", "text": arg}}
    # remove/delete "..." or number
    m = re.search(r'(?i)(?:remove|delete)\s+(?:"([^"]+)"|\'([^\']+)\'|(\d+))', s)
    if m:
        if m.group(3):
            return {"target": {"by": "index", "index": int(m.group(3))}}
        text = m.group(1) or m.group(2)
        if text:
            return {"target": {"by": "text", "text": text}}
    return None

def parse_instructions(md: str) -> Dict[str, List[Dict[str, Any]]]:
    adds = []
    edits = []
    dones = []
    removes = []
    for raw_line in md.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        add = parse_add_line(line)
        if add:
            adds.append(add)
            continue
        ed = parse_edit_line(line)
        if ed:
            edits.append(ed)
            continue
        dn = parse_done_line(line)
        if dn:
            dones.append(dn)
            continue
        rm = parse_remove_line(line)
        if rm:
            removes.append(rm)
            continue
    return {"adds": adds, "edits": edits, "dones": dones, "removes": removes}

def index_from_seed(seed_items: List[Dict[str, Any]], target: Dict[str, Any], open_only: bool = True) -> Optional[int]:
    # Return lineNo index into seed_items list (actual item index in seed_items)
    candidates = [it for it in seed_items if (not open_only) or (not it["done"])]
    if target.get("by") == "index":
        idx = target.get("index")
        if idx is None:
            return None
        # indices are 1-based typically; also try 0-based as fallback
        if 1 <= idx <= len(candidates):
            # Find which seed_items index corresponds
            chosen = candidates[idx - 1]
            # Return original seed_items index
            for i, it in enumerate(seed_items):
                if it["lineNo"] == chosen["lineNo"]:
                    return i
        elif 0 <= idx < len(candidates):
            chosen = candidates[idx]
            for i, it in enumerate(seed_items):
                if it["lineNo"] == chosen["lineNo"]:
                    return i
        return None
    if target.get("by") == "text":
        t = (target.get("text") or "").strip()
        if not t:
            return None
        # Try exact match first among candidates
        for i, it in enumerate(seed_items):
            if open_only and it["done"]:
                continue
            if it["text"].strip() == t:
                return i
        # Try substring match
        for i, it in enumerate(seed_items):
            if open_only and it["done"]:
                continue
            if t in it["text"]:
                return i
    return None

def find_in_output_by_text(output_items: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    res = []
    t = text.strip()
    for it in output_items:
        if it["text"].strip() == t:
            res.append(it)
    if res:
        return res
    # fallback substring
    for it in output_items:
        if t in it["text"]:
            res.append(it)
    return res

def compute_report_from_todo(md: str, today: Optional[str]) -> Dict[str, Any]:
    items = parse_todos(md)
    open_items = [it for it in items if not it["done"]]
    done_items = [it for it in items if it["done"]]
    open_objs = []
    for it in open_items:
        open_objs.append({
            "text": it["text"],
            "tags": it["tags"],
            "priority": it["priority"],
            "dueDate": it["dueDate"],
        })
    overdue_open = []
    if today:
        for it in open_items:
            if it["dueDate"] and it["dueDate"] < today:
                overdue_open.append({
                    "text": it["text"],
                    "tags": it["tags"],
                    "priority": it["priority"],
                    "dueDate": it["dueDate"],
                })
        overdue_open.sort(key=lambda o: o["dueDate"])
    tag_counts: Dict[str, int] = {}
    for it in open_items:
        for tag in it["tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    priority_counts = {"high": 0, "medium": 0, "low": 0}
    for it in open_items:
        p = it["priority"]
        if p in priority_counts:
            priority_counts[p] += 1
    search_list = []
    if today:
        for it in open_items:
            if ("dev" in it["tags"]) and (it["priority"] == "high") and (it["dueDate"] and it["dueDate"] < today):
                search_list.append(it["text"])
    return {
        "today": today,
        "open_count": len(open_items),
        "done_count": len(done_items),
        "open": open_objs,
        "overdue_open": overdue_open,
        "tag_counts": tag_counts,
        "priority_counts": priority_counts,
        "search": {"high_priority_dev_overdue": search_list},
    }

def normalize_open_list(objs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normed = []
    for o in objs:
        text = (o.get("text") or "").strip()
        tags = [t.lower() for t in (o.get("tags") or [])]
        # dedupe tag order
        seen = set()
        tags2 = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                tags2.append(t)
        priority = normalize_priority(o.get("priority"))
        due = normalize_due(o.get("dueDate"))
        normed.append({
            "text": text,
            "tags": tags2,
            "priority": priority,
            "dueDate": due
        })
    # stable sort by (text, priority or '', due or '')
    normed.sort(key=lambda x: (x["text"], x["priority"] or "", x["dueDate"] or ""))
    return normed

def normalize_overdue_list(objs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Same normalization, but keep ensured sorted by dueDate asc afterwards
    normed = normalize_open_list(objs)
    normed.sort(key=lambda x: (x["dueDate"] or "", x["text"]))
    return normed

def compare_open_lists(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:
    return normalize_open_list(a) == normalize_open_list(b)

def compare_overdue_lists(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:
    return normalize_overdue_list(a) == normalize_overdue_list(b)

def main():
    checks: Dict[str, bool] = {}
    applicable: Dict[str, bool] = {}

    # Initialize checks as False (artifact-dependent)
    check_names = [
        "has_output_todo",
        "has_output_report",
        "preserved_non_todo_lines",
        "checkbox_syntax_valid",
        "additions_present",
        "additions_placement_ok",
        "mark_done_applied",
        "edit_applied",
        "remove_applied",
        "report_today_match",
        "report_counts_match",
        "report_open_items_match",
        "report_overdue_match",
        "report_tag_counts_match",
        "report_priority_counts_match",
        "report_search_match",
    ]
    for n in check_names:
        checks[n] = False
        applicable[n] = False

    seed_md = read_text(seed_path) or ""
    instr_md = read_text(instructions_path) or ""
    today_content = read_text(today_path)
    out_todo_md = read_text(out_todo_path)
    out_report_txt = read_text(out_report_path)

    # Existence checks
    if out_todo_md is not None:
        checks["has_output_todo"] = True
    applicable["has_output_todo"] = True

    if out_report_txt is not None:
        checks["has_output_report"] = True
    applicable["has_output_report"] = True

    # If missing main outputs, print zero reward
    if out_todo_md is None or out_report_txt is None:
        result = {"reward": 0.0}
        # Append all check booleans to result
        result.update(checks)
        print(json.dumps(result))
        return

    # Non-todo lines preserved (order and content)
    try:
        seed_non = non_todo_lines(seed_md)
        out_non = non_todo_lines(out_todo_md)
        applicable["preserved_non_todo_lines"] = True
        if seed_non == out_non:
            checks["preserved_non_todo_lines"] = True
    except Exception:
        pass

    # Checkbox syntax validity
    try:
        bad = False
        for line in out_todo_md.splitlines():
            if RE_INVALID_TODO_BRACKET.match(line):
                bad = True
                break
            # If it uses checkbox, ensure it matches valid pattern
            if line.lstrip().startswith("- ["):
                if not RE_TODO.match(line):
                    # lines like "- [] ..." should be considered invalid
                    bad = True
                    break
        applicable["checkbox_syntax_valid"] = True
        checks["checkbox_syntax_valid"] = not bad
    except Exception:
        pass

    # Parse instructions
    parsed_instr = parse_instructions(instr_md)
    found_adds = parsed_instr.get("adds", [])
    found_edits = parsed_instr.get("edits", [])
    found_dones = parsed_instr.get("dones", [])
    found_removes = parsed_instr.get("removes", [])

    # Parse seed and output TODOs
    seed_items = parse_todos(seed_md)
    out_items = parse_todos(out_todo_md)
    out_lines = out_todo_md.splitlines()
    seed_lines = seed_md.splitlines()

    # Additions presence and placement
    if found_adds:
        applicable["additions_present"] = True
        applicable["additions_placement_ok"] = True
        all_present = True
        placement_ok = True

        # Determine last TODO index in output for append checks
        last_todo_idx_out = -1
        for i, line in enumerate(out_lines):
            if is_todo_line(line):
                last_todo_idx_out = i

        for add in found_adds:
            add_text = (add.get("text") or "").strip()
            header = (add.get("header") or "").strip() if add.get("header") else None
            # Check existence in output as open item
            exists = False
            line_index_candidates = []
            for i, line in enumerate(out_lines):
                m = RE_TODO.match(line)
                if not m:
                    continue
                t = (m.group(2) or "").strip()
                if t == add_text:
                    exists = True
                    line_index_candidates.append(i)
            if not exists:
                all_present = False
            else:
                # Placement checks
                if header:
                    # Case-insensitive header lookup in seed
                    seed_header_idxs = find_header_indices(seed_lines, header)
                    if seed_header_idxs:
                        # Should be under the header in output
                        # Find header in output (case-insensitive exact match)
                        out_header_idxs = find_header_indices(out_lines, header)
                        if not out_header_idxs:
                            placement_ok = False
                        else:
                            # For each occurrence, ensure at least one candidate is within that header section
                            in_any_section = False
                            for hidx in out_header_idxs:
                                next_h = find_next_header_index(out_lines, hidx)
                                # insertion baseline: skip immediate blank lines
                                insertion_base = hidx + 1
                                while insertion_base < next_h and (out_lines[insertion_base].strip() == ""):
                                    insertion_base += 1
                                for cand in line_index_candidates:
                                    if insertion_base <= cand < next_h:
                                        in_any_section = True
                                        break
                                if in_any_section:
                                    break
                            if not in_any_section:
                                placement_ok = False
                    else:
                        # Header not found in seed; must be appended after last existing TODO in output
                        # Each candidate should be after last todo index in seed? The instruction says append after last existing TODO item
                        # Verify that at least one candidate index equals or greater than the last todo index in output (i.e., near the end)
                        if not line_index_candidates:
                            placement_ok = False
                        else:
                            # Must be at or after last existing todo (we accept at end)
                            if not any(c >= last_todo_idx_out for c in line_index_candidates):
                                placement_ok = False
                else:
                    # No header specified, should append at end (after last todo)
                    if not line_index_candidates:
                        placement_ok = False
                    else:
                        if not any(c >= last_todo_idx_out for c in line_index_candidates):
                            placement_ok = False

        checks["additions_present"] = all_present
        checks["additions_placement_ok"] = placement_ok

    # Mark done applied
    if found_dones:
        applicable["mark_done_applied"] = True
        ok = True
        for dn in found_dones:
            # Target refers to open list in seed
            seed_idx = index_from_seed(seed_items, dn.get("target", {}), open_only=True)
            if seed_idx is None:
                ok = False
                break
            seed_item = seed_items[seed_idx]
            # In output, find item with same text (unchanged) and ensure done
            matches = find_in_output_by_text(out_items, seed_item["text"])
            if not matches:
                ok = False
                break
            # Any of the matches should be done
            if not any(m["done"] for m in matches):
                ok = False
                break
        checks["mark_done_applied"] = ok

    # Edit applied
    if found_edits:
        applicable["edit_applied"] = True
        ok = True
        for ed in found_edits:
            seed_idx = index_from_seed(seed_items, ed.get("target", {}), open_only=False)
            if seed_idx is None:
                ok = False
                break
            seed_item = seed_items[seed_idx]
            # Determine expected state
            expected_done_state = seed_item["done"]
            new_text = ed.get("new_text")
            new_due = ed.get("new_due")

            if new_text:
                # Verify that an item with new_text exists and has same done state
                matches = find_in_output_by_text(out_items, new_text)
                if not matches:
                    ok = False
                    break
                if not any(m["done"] == expected_done_state for m in matches):
                    ok = False
                    break
                # Original text should not still exist as a todo line (unless same as new)
                if new_text.strip() != seed_item["text"].strip():
                    orig_matches = find_in_output_by_text(out_items, seed_item["text"])
                    if orig_matches:
                        ok = False
                        break
            elif new_due:
                # Find item in output with same text and verify due date updated
                matches = find_in_output_by_text(out_items, seed_item["text"])
                if not matches:
                    ok = False
                    break
                # Any match should have same done state and updated due
                # Extract due from the text fields
                updated = False
                for m in matches:
                    if m["done"] != expected_done_state:
                        continue
                    # Ensure due date equals new_due
                    if m["dueDate"] == new_due:
                        updated = True
                        break
                if not updated:
                    ok = False
                    break
            else:
                # No actionable edit
                ok = False
                break
        checks["edit_applied"] = ok

    # Remove applied
    if found_removes:
        applicable["remove_applied"] = True
        ok = True
        for rm in found_removes:
            # Removal can target any (done/open) by index among all? We'll attempt both open-only and all
            seed_idx = index_from_seed(seed_items, rm.get("target", {}), open_only=False)
            if seed_idx is None:
                # try open-only as fallback
                seed_idx = index_from_seed(seed_items, rm.get("target", {}), open_only=True)
            if seed_idx is None:
                ok = False
                break
            seed_item = seed_items[seed_idx]
            # Ensure no item remains in output with that exact text
            matches = find_in_output_by_text(out_items, seed_item["text"])
            if matches:
                ok = False
                break
        checks["remove_applied"] = ok

    # Report validations
    # Parse report JSON
    rep_ok = False
    rep_obj: Dict[str, Any] = {}
    try:
        rep_obj = json.loads(out_report_txt)
        rep_ok = isinstance(rep_obj, dict)
    except Exception:
        rep_ok = False
    if rep_ok:
        # today
        applicable["report_today_match"] = True
        today_value = parse_today_value(today_content)
        if isinstance(rep_obj.get("today"), str) and today_value == rep_obj.get("today"):
            checks["report_today_match"] = True

        # counts and open/done lists
        expected_report = compute_report_from_todo(out_todo_md, today_value)

        # counts
        applicable["report_counts_match"] = True
        if (rep_obj.get("open_count") == expected_report["open_count"]
                and rep_obj.get("done_count") == expected_report["done_count"]):
            checks["report_counts_match"] = True

        # open items list
        applicable["report_open_items_match"] = True
        rep_open = rep_obj.get("open")
        if isinstance(rep_open, list):
            if compare_open_lists(rep_open, expected_report["open"]):
                checks["report_open_items_match"] = True

        # overdue open
        applicable["report_overdue_match"] = True
        rep_overdue = rep_obj.get("overdue_open")
        if isinstance(rep_overdue, list):
            if compare_overdue_lists(rep_overdue, expected_report["overdue_open"]):
                checks["report_overdue_match"] = True

        # tag_counts
        applicable["report_tag_counts_match"] = True
        rep_tag_counts = rep_obj.get("tag_counts")
        if isinstance(rep_tag_counts, dict):
            # normalize keys to lowercase ints
            try:
                norm_rep = {str(k).lower(): int(v) for k, v in rep_tag_counts.items()}
                checks["report_tag_counts_match"] = norm_rep == expected_report["tag_counts"]
            except Exception:
                checks["report_tag_counts_match"] = False

        # priority_counts
        applicable["report_priority_counts_match"] = True
        rep_pr_counts = rep_obj.get("priority_counts")
        if isinstance(rep_pr_counts, dict):
            try:
                rep_high = int(rep_pr_counts.get("high", 0))
                rep_med = int(rep_pr_counts.get("medium", 0))
                rep_low = int(rep_pr_counts.get("low", 0))
                exp_pr = expected_report["priority_counts"]
                checks["report_priority_counts_match"] = (rep_high == exp_pr["high"] and
                                                          rep_med == exp_pr["medium"] and
                                                          rep_low == exp_pr["low"])
            except Exception:
                checks["report_priority_counts_match"] = False

        # search.high_priority_dev_overdue
        applicable["report_search_match"] = True
        rep_search = rep_obj.get("search")
        if isinstance(rep_search, dict) and isinstance(rep_search.get("high_priority_dev_overdue"), list):
            rep_list = [str(x) for x in rep_search.get("high_priority_dev_overdue")]
            exp_list = expected_report["search"]["high_priority_dev_overdue"]
            # compare as sets
            if set(rep_list) == set(exp_list):
                checks["report_search_match"] = True

    # Compute reward: ratio of passed checks among applicable ones
    passed = 0
    total = 0
    for name in check_names:
        if applicable.get(name, False):
            total += 1
            if checks.get(name, False):
                passed += 1

    # No-op baseline: if no outputs or total == 0, reward is 0
    if (out_todo_md.strip() == "" and out_report_txt.strip() == "") or total == 0:
        reward = 0.0
    else:
        reward = (passed / total) if total > 0 else 0.0

    # Bound reward
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Add "found_" metadata flags (do not count towards reward)
    # These indicate whether we detected instruction types
    checks_with_meta = dict(checks)
    checks_with_meta["found_add_instructions"] = bool(found_adds)
    checks_with_meta["found_edit_instructions"] = bool(found_edits)
    checks_with_meta["found_done_instructions"] = bool(found_dones)
    checks_with_meta["found_remove_instructions"] = bool(found_removes)

    # Final result
    result = {"reward": reward}
    result.update(checks_with_meta)
    print(json.dumps(result))

if __name__ == "__main__":
    main()