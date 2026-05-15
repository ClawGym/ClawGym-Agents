import json
import os
import sys
import csv

def workspace_paths(root):
    return {
        "input": os.path.join(root, "input"),
        "output": os.path.join(root, "output"),
        "reward": os.path.join(root, "reward"),
    }

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def read_lines_preserve(path):
    # Return lines without stripping internal spaces; remove trailing newline characters
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n\r") for line in f.read().splitlines()]

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_csv_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # normalize headers to lower-case trimmed
        if reader.fieldnames is None:
            return rows
        lower_fields = [fn.strip().lower() for fn in reader.fieldnames]
        for raw in reader:
            row = {}
            for k in raw:
                lk = k.strip().lower()
                # map into normalized key
                if lk in lower_fields:
                    val = raw[k]
                else:
                    val = raw[k]
                row[lk] = (val if val is not None else "").strip()
            rows.append(row)
    return rows

def normalize_status_for_create(status):
    s = (status or "").strip()
    sl = s.lower()
    if sl in {"to do", "todo"}:
        return "todo"
    if sl in {"in-progress", "in progress"}:
        return "in progress"
    if sl == "blocked":
        return "blocked"
    if sl == "done":
        return "done"
    # if value not recognized, keep as original (preserve original casing trimmed)
    return s

def canonical_contact_text(payload):
    return (
        "Qordinate, create a contact in the contacts list:\n"
        f"  name: {payload.get('name','')}\n"
        f"  company: {payload.get('company','')}\n"
        f"  role: {payload.get('role','')}\n"
        f"  notes: {payload.get('notes','')}"
    )

def canonical_task_text(payload):
    return (
        "Qordinate, add a new task to the tasks list:\n"
        f"  title: {payload.get('title','')}\n"
        f"  status: {payload.get('status','')}\n"
        f"  due: {payload.get('due','')}\n"
        f"  notes: {payload.get('notes','')}"
    )

def canonical_update_text(title, changes):
    # Special case: only 'status' and it's 'done' (case-insensitive)
    if isinstance(changes, dict) and len(changes) == 1:
        for k, v in changes.items():
            if k.lower() == "status" and isinstance(v, str) and v.strip().lower() == "done":
                return f"Qordinate, mark the task '{title}' in the tasks list as done."
    # Generic case: alphabetical by field name
    parts = []
    for k in sorted(changes.keys(), key=lambda x: x.lower()):
        parts.append(f"{k}: {changes[k]}")
    joined = "; ".join(parts)
    return f"Qordinate, in the tasks list, update the task '{title}' to set {joined}."

def build_expected_messages(input_dir):
    # Read inputs
    tasks_path = os.path.join(input_dir, "tasks.csv")
    contacts_path = os.path.join(input_dir, "contacts.csv")
    updates_path = os.path.join(input_dir, "updates.json")
    queries_path = os.path.join(input_dir, "queries.txt")

    contacts_rows = read_csv_rows(contacts_path) if os.path.isfile(contacts_path) else []
    tasks_rows = read_csv_rows(tasks_path) if os.path.isfile(tasks_path) else []
    updates_data = read_json(updates_path) if os.path.isfile(updates_path) else []
    queries_lines = read_lines_preserve(queries_path) if os.path.isfile(queries_path) else []

    # Build contact creates sorted by name (A-Z, case-insensitive)
    contacts = []
    for r in contacts_rows:
        payload = {
            "name": r.get("name", "").strip(),
            "company": r.get("company", "").strip(),
            "role": r.get("role", "").strip(),
            "notes": r.get("notes", "").strip(),
        }
        contacts.append(payload)
    # Sort by name ascending case-insensitive, stable
    contacts_sorted = sorted(enumerate(contacts), key=lambda iv: (iv[1]["name"].lower(), iv[0]))
    contact_msgs = []
    for _, payload in contacts_sorted:
        rendered = canonical_contact_text(payload)
        contact_msgs.append({
            "type": "create",
            "list": "contacts",
            "payload": payload,
            "rendered_text": rendered,
        })

    # Deduplicate tasks by title (case-insensitive), keeping first occurrence
    seen_titles = set()
    task_msgs = []
    for r in tasks_rows:
        title = (r.get("title", "") or "").strip()
        title_key = title.lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        status_norm = normalize_status_for_create(r.get("status", ""))
        due_val = (r.get("due", "") or "").strip()
        # If due missing/blank, set to empty string
        if due_val == "":
            due_val = ""
        payload = {
            "title": title,
            "status": status_norm,
            "due": due_val,
            "notes": (r.get("notes", "") or "").strip(),
        }
        rendered = canonical_task_text(payload)
        task_msgs.append({
            "type": "create",
            "list": "tasks",
            "payload": payload,
            "rendered_text": rendered,
        })

    # Updates in given order
    updates_msgs = []
    if isinstance(updates_data, dict):
        # Allow a dict wrapping (e.g., {"updates":[...]})
        if "updates" in updates_data and isinstance(updates_data["updates"], list):
            updates_list = updates_data["updates"]
        else:
            updates_list = []
    else:
        updates_list = updates_data if isinstance(updates_data, list) else []

    for item in updates_list:
        if not isinstance(item, dict):
            continue
        title = (item.get("title", "") or "").strip()
        # Support both {"title":..., "changes":{...}} and {"title":..., "<field>":...}
        if "changes" in item and isinstance(item["changes"], dict):
            changes = {k: item["changes"][k] for k in item["changes"].keys()}
        else:
            # take all keys except 'title'
            changes = {k: v for k, v in item.items() if k != "title"}
        # Preserve keys as they are; values as strings where appropriate
        # Ensure deterministic string conversion
        norm_changes = {}
        for k, v in changes.items():
            if v is None:
                norm_changes[k] = ""
            else:
                norm_changes[k] = str(v)
        rendered = canonical_update_text(title, norm_changes)
        updates_msgs.append({
            "type": "update",
            "list": "tasks",
            "title": title,
            "changes": norm_changes,
            "rendered_text": rendered,
        })

    # Queries: exactly two, in order they appear
    queries_msgs = []
    if len(queries_lines) >= 1:
        rendered = queries_lines[0]
        filt = {"status": ["todo", "in progress"], "due_within_days": 7, "sort": "due"}
        queries_msgs.append({
            "type": "query",
            "list": "tasks",
            "filter": filt,
            "rendered_text": rendered,
        })
    if len(queries_lines) >= 2:
        rendered = queries_lines[1]
        filt = {"name": "Harpinder Singh"}
        queries_msgs.append({
            "type": "query",
            "list": "contacts",
            "filter": filt,
            "rendered_text": rendered,
        })

    # Final ordering:
    # 1) contacts creates sorted by name
    # 2) tasks creates in first-seen order
    # 3) updates in given order
    # 4) queries in given order
    expected_messages = contact_msgs + task_msgs + updates_msgs + queries_msgs
    return expected_messages

def parse_jsonl_messages(path):
    messages = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            ln = line.strip("\n\r")
            if ln.strip() == "":
                continue
            try:
                obj = json.loads(ln)
                messages.append(obj)
            except Exception:
                raise
    return messages

def extract_rendered_texts(messages):
    texts = []
    for m in messages:
        rt = m.get("rendered_text", "")
        if not isinstance(rt, str):
            rt = str(rt)
        texts.append(rt)
    return texts

def compare_structures(expected, actual):
    if len(expected) != len(actual):
        return False
    for i in range(len(expected)):
        if expected[i] != actual[i]:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    paths = workspace_paths(workspace_root)
    input_dir = paths["input"]
    output_dir = paths["output"]

    checks = {
        "jsonl_exists": False,
        "txt_exists": False,
        "jsonl_valid": False,
        "messages_match_expected": False,
        "txt_matches_jsonl": False,
        "contacts_creates_sorted": False,
        "tasks_creates_dedup_and_normalized": False,
        "updates_count_and_format": False,
        "queries_count_and_filters": False,
    }

    jsonl_path = os.path.join(output_dir, "qordinate_messages.jsonl")
    txt_path = os.path.join(output_dir, "qordinate_messages.txt")

    if os.path.isfile(jsonl_path):
        checks["jsonl_exists"] = True
    if os.path.isfile(txt_path):
        checks["txt_exists"] = True

    expected_messages = []
    try:
        expected_messages = build_expected_messages(input_dir)
    except Exception:
        expected_messages = []

    actual_messages = []
    if checks["jsonl_exists"]:
        try:
            actual_messages = parse_jsonl_messages(jsonl_path)
            checks["jsonl_valid"] = True
        except Exception:
            checks["jsonl_valid"] = False

    # Compare messages to expected strictly
    if checks["jsonl_valid"] and expected_messages:
        # Normalize any non-string values in actual to compare reliably (but schema expects strings)
        # We keep strict equality as specified.
        try:
            checks["messages_match_expected"] = compare_structures(expected_messages, actual_messages)
        except Exception:
            checks["messages_match_expected"] = False

    # txt must equal rendered_text entries from the JSONL in same order with exactly one blank line between
    if checks["txt_exists"] and checks["jsonl_valid"]:
        try:
            actual_text = read_text(txt_path)
            # Normalize line endings to \n
            actual_text_norm = actual_text.replace("\r\n", "\n").replace("\r", "\n")
            rendered_texts = extract_rendered_texts(actual_messages)
            expected_txt = "\n\n".join(rendered_texts)
            # Allow optional trailing newline at EOF
            if actual_text_norm == expected_txt or actual_text_norm.rstrip("\n") == expected_txt:
                checks["txt_matches_jsonl"] = True
        except Exception:
            checks["txt_matches_jsonl"] = False

    # Additional structural checks derived from actual output vs inputs
    # Contacts creates sorted by name
    if checks["jsonl_valid"]:
        # Determine contact create subset from actual
        contact_creates = [m for m in actual_messages if m.get("type") == "create" and m.get("list") == "contacts"]
        # Build expected contacts sorted order from inputs
        try:
            expected_contacts = [m for m in expected_messages if m.get("type") == "create" and m.get("list") == "contacts"]
            if len(contact_creates) == len(expected_contacts):
                # Check ordering by comparing the sequence of names
                actual_names = [m.get("payload", {}).get("name", "") for m in contact_creates]
                expected_names = [m.get("payload", {}).get("name", "") for m in expected_contacts]
                if actual_names == expected_names:
                    # Also verify canonical rendered_text format for contacts
                    fmt_ok = True
                    for m in contact_creates:
                        payload = m.get("payload", {})
                        rendered = m.get("rendered_text", "")
                        if rendered != canonical_contact_text(payload):
                            fmt_ok = False
                            break
                    if fmt_ok:
                        checks["contacts_creates_sorted"] = True
        except Exception:
            pass

    # Tasks creates dedup and normalized
    if checks["jsonl_valid"]:
        task_creates = [m for m in actual_messages if m.get("type") == "create" and m.get("list") == "tasks"]
        try:
            expected_task_creates = [m for m in expected_messages if m.get("type") == "create" and m.get("list") == "tasks"]
            if len(task_creates) == len(expected_task_creates):
                # Order and titles
                act_titles = [m.get("payload", {}).get("title", "") for m in task_creates]
                exp_titles = [m.get("payload", {}).get("title", "") for m in expected_task_creates]
                if act_titles == exp_titles:
                    # Status normalization and canonical text
                    fmt_ok = True
                    for am, em in zip(task_creates, expected_task_creates):
                        a_payload = am.get("payload", {})
                        e_payload = em.get("payload", {})
                        # Check normalized status equals expected
                        if a_payload.get("status") != e_payload.get("status"):
                            fmt_ok = False
                            break
                        # Check due default empty string handling
                        if a_payload.get("due", None) != e_payload.get("due", None):
                            fmt_ok = False
                            break
                        # Ensure canonical rendered_text
                        if am.get("rendered_text", "") != canonical_task_text(a_payload):
                            fmt_ok = False
                            break
                    if fmt_ok:
                        checks["tasks_creates_dedup_and_normalized"] = True
        except Exception:
            pass

    # Updates count and format
    if checks["jsonl_valid"]:
        actual_updates = [m for m in actual_messages if m.get("type") == "update" and m.get("list") == "tasks"]
        expected_updates = [m for m in expected_messages if m.get("type") == "update" and m.get("list") == "tasks"]
        if len(actual_updates) == len(expected_updates):
            ok = True
            for a, e in zip(actual_updates, expected_updates):
                # title and changes equality
                if a.get("title") != e.get("title"):
                    ok = False
                    break
                if a.get("changes") != e.get("changes"):
                    ok = False
                    break
                # rendered_text exact match according to canonical built from actual changes
                if a.get("rendered_text", "") != canonical_update_text(a.get("title", ""), a.get("changes", {})):
                    ok = False
                    break
            if ok:
                checks["updates_count_and_format"] = True

    # Queries count and filters
    if checks["jsonl_valid"]:
        actual_queries = [m for m in actual_messages if m.get("type") == "query"]
        expected_queries = [m for m in expected_messages if m.get("type") == "query"]
        if len(actual_queries) == len(expected_queries) == 2:
            ok = True
            for a, e in zip(actual_queries, expected_queries):
                if a.get("rendered_text", "") != e.get("rendered_text", ""):
                    ok = False
                    break
                # Filters must match exactly
                if a.get("filter") != e.get("filter"):
                    ok = False
                    break
                # Ensure list is appropriate ('tasks' then 'contacts')
                if a.get("list") != e.get("list"):
                    ok = False
                    break
            if ok:
                checks["queries_count_and_filters"] = True

    # Compute reward: gate on both files existing; otherwise 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    if not (checks["jsonl_exists"] and checks["txt_exists"]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()