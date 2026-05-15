import json
import os
import re
import sys
from typing import List, Tuple, Dict, Optional

# Workspace and dirs
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Expected output paths
index_path = os.path.join(output_dir, "kanban", "index.md")
api_board_path = os.path.join(output_dir, "kanban", "api-core", "board.md")
api_log_path = os.path.join(output_dir, "kanban", "api-core", "log.md")
mkt_board_path = os.path.join(output_dir, "kanban", "marketing-site", "board.md")
mkt_log_path = os.path.join(output_dir, "kanban", "marketing-site", "log.md")

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def normalize_relpath(p: str) -> str:
    # Normalize to posix-like relative path without leading './'
    p = p.strip()
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p

def is_relative_path(p: str) -> bool:
    p = p.strip()
    if not p:
        return False
    if p.startswith("~"):
        return False
    if os.path.isabs(p):
        return False
    if re.match(r"^[a-zA-Z]:", p):  # Windows drive
        return False
    return True

def extract_section(text: str, section_title: str) -> Optional[str]:
    # Extract lines between "## <section_title>" and next "## "
    lines = text.splitlines()
    start_idx = None
    header_pattern = re.compile(r"^\s*##\s+" + re.escape(section_title) + r"\s*$", re.IGNORECASE)
    next_header_pattern = re.compile(r"^\s*##\s+")
    for i, line in enumerate(lines):
        if header_pattern.match(line):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find end
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if next_header_pattern.match(lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip("\n")

def parse_first_markdown_table(text: str) -> Tuple[List[str], List[List[str]]]:
    # Returns (headers, rows) where headers are lowercased stripped, rows are lists of stripped cells
    lines = text.splitlines()
    header_line_idx = None
    for i, line in enumerate(lines):
        if "|" in line:
            # Heuristic: the next non-empty line should be a separator with --- to be a table
            # Also ensure at least 2 pipes to be a table
            if line.count("|") >= 2:
                # Find next non-empty
                k = i + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k < len(lines) and re.search(r"-\s*-", lines[k]):
                    header_line_idx = i
                    break
    if header_line_idx is None:
        return [], []
    header_line = lines[header_line_idx]
    # Split header cells
    headers = [c.strip().lower() for c in header_line.strip().strip("|").split("|")]
    # Collect rows until a non-table line
    rows: List[List[str]] = []
    for j in range(header_line_idx + 2, len(lines)):
        line = lines[j]
        if "|" not in line:
            break
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Pad or trim to headers length
            if len(cells) < len(headers):
                cells += [""] * (len(headers) - len(cells))
            elif len(cells) > len(headers):
                cells = cells[:len(headers)]
            rows.append(cells)
        else:
            break
    return headers, rows

def table_rows_to_dicts(headers: List[str], rows: List[List[str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for r in rows:
        d = {}
        for i, h in enumerate(headers):
            d[h] = r[i] if i < len(r) else ""
        out.append(d)
    return out

def has_required_sections(board_text: str) -> bool:
    return (
        extract_section(board_text, "Meta") is not None and
        extract_section(board_text, "Lanes") is not None and
        extract_section(board_text, "Cards") is not None and
        extract_section(board_text, "WIP Limits") is not None
    )

def cards_table_info(board_text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    cards_sec = extract_section(board_text, "Cards")
    if cards_sec is None:
        return [], []
    headers, rows = parse_first_markdown_table(cards_sec)
    rows_dicts = table_rows_to_dicts(headers, rows)
    return headers, rows_dicts

def ids_match_kb_pattern(rows: List[Dict[str, str]]) -> bool:
    if not rows:
        return False
    for r in rows:
        # find 'id' column
        id_val = r.get("id", "").strip()
        if not re.fullmatch(r"KB-\d+", id_val):
            return False
    return True

def find_card_state(rows: List[Dict[str, str]], card_id: str, state_col: str = "state") -> Optional[str]:
    for r in rows:
        if r.get("id", "").strip() == card_id:
            return r.get(state_col, "").strip()
    return None

def parse_wip_limit(board_text: str, lane_name: str = "in-progress") -> Optional[int]:
    wip_sec = extract_section(board_text, "WIP Limits")
    if wip_sec is None:
        return None
    lines = [ln.strip() for ln in wip_sec.splitlines() if ln.strip()]
    # e.g., "- in-progress: 3"
    for ln in lines:
        m = re.match(r"^-+\s*([A-Za-z0-9\-_ ]+)\s*:\s*([0-9]+)\s*$", ln)
        if m:
            lane = m.group(1).strip().lower()
            if lane == lane_name.lower():
                try:
                    return int(m.group(2))
                except Exception:
                    return None
        else:
            # also support bullet without hyphen start
            m2 = re.match(r"^\*?\s*([A-Za-z0-9\-_ ]+)\s*:\s*([0-9]+)\s*$", ln)
            if m2:
                lane = m2.group(1).strip().lower()
                if lane == lane_name.lower():
                    try:
                        return int(m2.group(2))
                    except Exception:
                        return None
    return None

def count_cards_in_state(rows: List[Dict[str, str]], state_name: str = "in-progress") -> int:
    cnt = 0
    for r in rows:
        st = r.get("state", "")
        if st.strip().lower() == state_name.lower():
            cnt += 1
    return cnt

def log_table(text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    headers, rows = parse_first_markdown_table(text)
    rows_dicts = table_rows_to_dicts(headers, rows)
    return headers, rows_dicts

def has_log_header(headers: List[str]) -> bool:
    req = ["timestamp", "action", "card_id", "from_state", "to_state", "actor", "note"]
    headers_l = [h.strip().lower() for h in headers]
    return all(col in headers_l for col in req)

def any_create_entry(rows: List[Dict[str, str]]) -> bool:
    for r in rows:
        if r.get("action", "").strip().lower() == "create":
            return True
    return False

def any_movement_entry(rows: List[Dict[str, str]]) -> bool:
    for r in rows:
        action = r.get("action", "").strip().lower()
        if action != "create":
            from_state = r.get("from_state", "").strip().lower()
            to_state = r.get("to_state", "").strip().lower()
            # Consider as movement if from_state != to_state and to_state not empty
            if to_state and from_state != to_state:
                return True
    return False

def all_moves_have_rationale_prefix(rows: List[Dict[str, str]]) -> bool:
    ok = True
    seen_any_move = False
    for r in rows:
        action = r.get("action", "").strip().lower()
        if action != "create":
            seen_any_move = True
            note = r.get("note", "").strip()
            if not note.lower().startswith("rationale:"):
                ok = False
    # If there were no moves at all, fail this check (we expect at least one move per task instructions)
    if not seen_any_move:
        return False
    return ok

def done_moves_have_evidence_or_rationale(rows: List[Dict[str, str]]) -> bool:
    # If there is any to_state == 'done', ensure note contains 'rationale' or 'acceptance' or 'evidence'
    had_done = False
    for r in rows:
        to_state = r.get("to_state", "").strip().lower()
        if to_state == "done":
            had_done = True
            note = r.get("note", "").strip().lower()
            if not (("rationale" in note) or ("acceptance" in note) or ("evidence" in note)):
                return False
    # If no done moves, treat as pass (no violation)
    return True

def parse_index_projects(index_text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    # Find "## Projects" section first, then parse its first table
    projects_sec = extract_section(index_text, "Projects")
    if projects_sec is None:
        # Fallback: try entire doc
        projects_sec = index_text
    headers, rows = parse_first_markdown_table(projects_sec)
    rows_dicts = table_rows_to_dicts(headers, rows)
    return headers, rows_dicts

def check_last_used_valid(val: str) -> bool:
    v = val.strip()
    if not v:
        return False
    if v == "YYYY-MM-DD":
        return False
    # Accept ISO date-like formats YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return True
    # Permit ISO datetime "YYYY-MM-DD HH:MM" as acceptable
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", v):
        return True
    return False

checks: Dict[str, bool] = {
    # File existence
    "exist_index": False,
    "exist_api_board": False,
    "exist_api_log": False,
    "exist_mkt_board": False,
    "exist_mkt_log": False,
    # Index content
    "index_has_projects_table_columns": False,
    "index_has_api_entry": False,
    "index_has_marketing_entry": False,
    "index_mode_workspace_local_both": False,
    "index_paths_relative_and_correct_both": False,
    "index_last_used_nonplaceholder_both": False,
    # Board structure
    "api_board_has_sections": False,
    "mkt_board_has_sections": False,
    "api_cards_header_has_required_columns": False,
    "mkt_cards_header_has_required_columns": False,
    "api_all_ids_pattern": False,
    "mkt_all_ids_pattern": False,
    # Deterministic state updates
    "api_states_updated_kb002_and_kb003": False,
    "mkt_state_updated_kb101": False,
    # WIP enforcement
    "api_wip_enforced": False,
    "mkt_wip_enforced": False,
    # Log integrity
    "api_log_has_header": False,
    "mkt_log_has_header": False,
    "api_log_has_create_and_move": False,
    "mkt_log_has_create_and_move": False,
    "api_log_moves_have_rationale": False,
    "mkt_log_moves_have_rationale": False,
    "done_move_has_evidence_or_rationale": False,
}

# 1) File existence
index_text = None
api_board_text = None
api_log_text = None
mkt_board_text = None
mkt_log_text = None

if os.path.isfile(index_path):
    checks["exist_index"] = True
    index_text = read_text(index_path)

if os.path.isfile(api_board_path):
    checks["exist_api_board"] = True
    api_board_text = read_text(api_board_path)

if os.path.isfile(api_log_path):
    checks["exist_api_log"] = True
    api_log_text = read_text(api_log_path)

if os.path.isfile(mkt_board_path):
    checks["exist_mkt_board"] = True
    mkt_board_text = read_text(mkt_board_path)

if os.path.isfile(mkt_log_path):
    checks["exist_mkt_log"] = True
    mkt_log_text = read_text(mkt_log_path)

# 2) Index content checks
if checks["exist_index"] and isinstance(index_text, str):
    headers, rows_dicts = parse_index_projects(index_text)
    headers_l = [h.strip().lower() for h in headers]
    required_cols = ["project_id", "aliases", "workspace_root", "board_mode", "board_path", "rules_path", "log_path", "last_used"]
    if all(col in headers_l for col in required_cols):
        checks["index_has_projects_table_columns"] = True

    # Map rows by project_id
    proj_map: Dict[str, Dict[str, str]] = {}
    pid_idx = headers_l.index("project_id") if "project_id" in headers_l else -1
    for rd in rows_dicts:
        pid = rd.get("project_id", "").strip()
        if pid:
            proj_map[pid] = rd

    api_entry = proj_map.get("api-core")
    mkt_entry = proj_map.get("marketing-site")
    if api_entry:
        checks["index_has_api_entry"] = True
    if mkt_entry:
        checks["index_has_marketing_entry"] = True

    # Mode workspace-local both
    mode_ok = False
    paths_ok = False
    last_used_ok = False
    if api_entry and mkt_entry:
        api_mode = api_entry.get("board_mode", "").strip().lower()
        mkt_mode = mkt_entry.get("board_mode", "").strip().lower()
        if api_mode == "workspace-local" and mkt_mode == "workspace-local":
            mode_ok = True

        def validate_paths(entry: Dict[str, str], project: str) -> bool:
            # Check relative and points under output/kanban/<project>/
            bp = normalize_relpath(entry.get("board_path", ""))
            rp = normalize_relpath(entry.get("rules_path", ""))
            lp = normalize_relpath(entry.get("log_path", ""))
            if not (is_relative_path(bp) and is_relative_path(rp) and is_relative_path(lp)):
                return False
            expected_prefix = f"output/kanban/{project}/"
            if not (bp.lower().startswith(expected_prefix) and rp.lower().startswith(expected_prefix) and lp.lower().startswith(expected_prefix)):
                return False
            # Check exact expected filenames
            if not bp.lower().endswith("/board.md"):
                return False
            if not rp.lower().endswith("/rules.md"):
                return False
            if not lp.lower().endswith("/log.md"):
                return False
            return True

        if validate_paths(api_entry, "api-core") and validate_paths(mkt_entry, "marketing-site"):
            paths_ok = True

        # last_used non-placeholder for both
        lu_api = api_entry.get("last_used", "")
        lu_mkt = mkt_entry.get("last_used", "")
        if check_last_used_valid(lu_api) and check_last_used_valid(lu_mkt):
            last_used_ok = True

    if mode_ok:
        checks["index_mode_workspace_local_both"] = True
    if paths_ok:
        checks["index_paths_relative_and_correct_both"] = True
    if last_used_ok:
        checks["index_last_used_nonplaceholder_both"] = True

# 3) Board structure checks and 4) Deterministic updates
api_headers = []
api_rows: List[Dict[str, str]] = []
mkt_headers = []
mkt_rows: List[Dict[str, str]] = []

if checks["exist_api_board"] and isinstance(api_board_text, str):
    if has_required_sections(api_board_text):
        checks["api_board_has_sections"] = True
    api_headers, api_rows = cards_table_info(api_board_text)
    req_cols = ["id", "title", "state", "priority", "owner"]
    if api_headers:
        headers_l = [h.strip().lower() for h in api_headers]
        if all(c in headers_l for c in req_cols):
            checks["api_cards_header_has_required_columns"] = True
    if api_rows:
        if ids_match_kb_pattern(api_rows):
            checks["api_all_ids_pattern"] = True

if checks["exist_mkt_board"] and isinstance(mkt_board_text, str):
    if has_required_sections(mkt_board_text):
        checks["mkt_board_has_sections"] = True
    mkt_headers, mkt_rows = cards_table_info(mkt_board_text)
    req_cols = ["id", "title", "state", "priority", "owner"]
    if mkt_headers:
        headers_l = [h.strip().lower() for h in mkt_headers]
        if all(c in headers_l for c in req_cols):
            checks["mkt_cards_header_has_required_columns"] = True
    if mkt_rows:
        if ids_match_kb_pattern(mkt_rows):
            checks["mkt_all_ids_pattern"] = True

# Deterministic state updates
if api_rows:
    st_002 = find_card_state(api_rows, "KB-002")
    st_003 = find_card_state(api_rows, "KB-003")
    if (st_002 is not None and st_002.strip().lower() == "in-progress") and (st_003 is not None and st_003.strip().lower() == "blocked"):
        checks["api_states_updated_kb002_and_kb003"] = True

if mkt_rows:
    st_101 = find_card_state(mkt_rows, "KB-101")
    if st_101 is not None and st_101.strip().lower() == "in-progress":
        checks["mkt_state_updated_kb101"] = True

# 5) WIP limit enforcement
if api_rows and checks["exist_api_board"] and isinstance(api_board_text, str):
    limit = parse_wip_limit(api_board_text, "in-progress")
    if isinstance(limit, int):
        count = count_cards_in_state(api_rows, "in-progress")
        if count <= limit:
            checks["api_wip_enforced"] = True

if mkt_rows and checks["exist_mkt_board"] and isinstance(mkt_board_text, str):
    limit = parse_wip_limit(mkt_board_text, "in-progress")
    if isinstance(limit, int):
        count = count_cards_in_state(mkt_rows, "in-progress")
        if count <= limit:
            checks["mkt_wip_enforced"] = True

# 6) Log integrity and evidence checks
if checks["exist_api_log"] and isinstance(api_log_text, str):
    api_log_headers, api_log_rows = log_table(api_log_text)
    if has_log_header(api_log_headers):
        checks["api_log_has_header"] = True
    if api_log_rows:
        if any_create_entry(api_log_rows) and any_movement_entry(api_log_rows):
            checks["api_log_has_create_and_move"] = True
        if all_moves_have_rationale_prefix(api_log_rows):
            checks["api_log_moves_have_rationale"] = True

if checks["exist_mkt_log"] and isinstance(mkt_log_text, str):
    mkt_log_headers, mkt_log_rows = log_table(mkt_log_text)
    if has_log_header(mkt_log_headers):
        checks["mkt_log_has_header"] = True
    if mkt_log_rows:
        if any_create_entry(mkt_log_rows) and any_movement_entry(mkt_log_rows):
            checks["mkt_log_has_create_and_move"] = True
        if all_moves_have_rationale_prefix(mkt_log_rows):
            checks["mkt_log_moves_have_rationale"] = True

# Done movement evidence note across both logs
done_ok = True
saw_any_log = False
for rows in [
    (api_log_text and checks["exist_api_log"] and log_table(api_log_text)[1]) or [],
    (mkt_log_text and checks["exist_mkt_log"] and log_table(mkt_log_text)[1]) or [],
]:
    if rows:
        saw_any_log = True
        if not done_moves_have_evidence_or_rationale(rows):
            done_ok = False
# If no logs at all, keep False (depends on output)
if saw_any_log and done_ok:
    checks["done_move_has_evidence_or_rationale"] = True

# Compute reward: average of all boolean checks
total_checks = len(checks)
passed = sum(1 for v in checks.values() if v)
reward = 0.0
# No-op baseline: if output directory missing or empty essential artifacts, reward must be 0.0
essential_exist = checks["exist_index"] and checks["exist_api_board"] and checks["exist_api_log"] and checks["exist_mkt_board"] and checks["exist_mkt_log"]
if essential_exist:
    reward = passed / total_checks
else:
    reward = 0.0

result = {"reward": reward}
result.update(checks)

print(json.dumps(result))