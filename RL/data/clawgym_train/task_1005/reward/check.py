import json
import os
import sys
import csv
from datetime import datetime

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_jsonl_file(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    return None
        return items
    except Exception:
        return None

def read_messages_jsonl(path):
    msgs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    msgs.append(obj)
                except Exception:
                    return None
        return msgs
    except Exception:
        return None

def parse_ts(ts):
    if not isinstance(ts, str):
        return None
    try:
        # Normalize Zulu time to +00:00 for fromisoformat
        if ts.endswith("Z"):
            ts_norm = ts[:-1] + "+00:00"
        else:
            ts_norm = ts
        return datetime.fromisoformat(ts_norm)
    except Exception:
        return None

def ts_key_asc(ts):
    dt = parse_ts(ts)
    if dt is not None:
        return (0, dt)
    return (1, ts if isinstance(ts, str) else "")

def ts_key_desc(ts):
    dt = parse_ts(ts)
    if dt is not None:
        return (0, -dt.timestamp())
    # Fallback string order reversed
    return (1, "" if not isinstance(ts, str) else "".join(chr(255 - ord(c)) for c in ts))

def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def load_threads(threads_path):
    data = parse_json_file(threads_path)
    if data is None:
        return {}
    threads = {}
    if isinstance(data, dict) and "threads" in data and isinstance(data["threads"], list):
        thread_list = data["threads"]
    elif isinstance(data, list):
        thread_list = data
    else:
        thread_list = []
    for t in thread_list:
        if not isinstance(t, dict):
            continue
        tid = t.get("thread_id") or t.get("id")
        if not isinstance(tid, str):
            continue
        thread_name = t.get("thread_name") or t.get("name") or ""
        participants = t.get("participants") or []
        threads[tid] = {
            "thread_id": tid,
            "thread_name": thread_name if isinstance(thread_name, str) else "",
            "participants": participants if isinstance(participants, list) else []
        }
    return threads

def build_participants_list(thread_obj):
    # Unique non-bridge display_name strings, sorted case-insensitively
    names = []
    seen = set()
    for p in thread_obj.get("participants", []):
        if not isinstance(p, dict):
            continue
        is_bridge = bool(p.get("is_bridge", False))
        if is_bridge:
            continue
        dn = p.get("display_name")
        if not isinstance(dn, str):
            continue
        if dn not in seen:
            seen.add(dn)
            names.append(dn)
    names_sorted = sorted(names, key=lambda s: s.casefold())
    return names_sorted

def load_messages(messages_path):
    msgs = read_messages_jsonl(messages_path)
    if msgs is None:
        return None
    by_id = {}
    by_thread_all = {}
    for m in msgs:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if not isinstance(mid, str):
            continue
        by_id[mid] = m
        tid = m.get("thread_id")
        if isinstance(tid, str):
            by_thread_all.setdefault(tid, []).append(m)
    return by_id, by_thread_all

def is_system_or_bridge(msg):
    if not isinstance(msg, dict):
        return True
    if bool(msg.get("is_system", False)):
        return True
    sender = msg.get("sender") or {}
    if isinstance(sender, dict):
        if bool(sender.get("is_bridge", False)):
            return True
    return False

def get_sender_display_name(msg):
    sender = msg.get("sender") or {}
    dn = None
    if isinstance(sender, dict):
        dn = sender.get("display_name") or sender.get("name")
    if not isinstance(dn, str):
        dn = msg.get("sender_display_name")
    if not isinstance(dn, str):
        dn = ""
    return dn

def build_thread_messages_filtered(by_thread_all):
    # For each thread, build list of non-system, non-bridge messages sorted by timestamp asc, then id asc
    filt = {}
    for tid, msgs in by_thread_all.items():
        kept = []
        for m in msgs:
            if not is_system_or_bridge(m):
                ts = m.get("timestamp")
                mid = m.get("id")
                kept.append((m, ts_key_asc(ts), (mid if isinstance(mid, str) else "")))
        kept.sort(key=lambda x: (x[1], x[2]))
        filt[tid] = [km[0] for km in kept]
    return filt

def load_search_results(search_path, allowed_terms):
    data = parse_json_file(search_path)
    if data is None:
        return {}
    msg_to_terms = {}
    # Structure assumed: term -> list of entries {message_id, thread_id?}
    if isinstance(data, dict):
        items = data.items()
    else:
        items = []
    for term, entries in items:
        term_l = term.lower() if isinstance(term, str) else ""
        if term_l not in allowed_terms:
            continue
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            mid = e.get("message_id") or e.get("id")
            if not isinstance(mid, str):
                continue
            msg_to_terms.setdefault(mid, set()).add(term_l)
    return msg_to_terms

def choose_keyword(terms):
    # choose term with greatest number of characters; tie-break lex asc
    if not terms:
        return None
    best = None
    for t in terms:
        if not isinstance(t, str):
            continue
        if best is None:
            best = t
        else:
            if len(t) > len(best):
                best = t
            elif len(t) == len(best) and t < best:
                best = t
    return best

def build_expected(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    threads_path = os.path.join(input_dir, "threads.json")
    messages_path = os.path.join(input_dir, "messages.jsonl")
    search_path = os.path.join(input_dir, "search_results.json")

    threads_index = load_threads(threads_path)
    msgs_loaded = load_messages(messages_path)
    if msgs_loaded is None:
        return None
    messages_by_id, by_thread_all = msgs_loaded
    by_thread_filtered = build_thread_messages_filtered(by_thread_all)

    allowed_terms = {"invoice", "payment", "paid", "wire", "net 30", "po", "purchase order"}
    msg_to_terms = load_search_results(search_path, allowed_terms)

    # Build qualifying hits
    hits = []
    seen_msg_ids = set()
    for mid, terms in msg_to_terms.items():
        m = messages_by_id.get(mid)
        if m is None:
            continue
        if is_system_or_bridge(m):
            continue
        tid = m.get("thread_id")
        if not isinstance(tid, str):
            continue
        ts = m.get("timestamp")
        if not isinstance(ts, str):
            continue
        kw = choose_keyword(terms)
        if kw is None:
            continue
        if mid in seen_msg_ids:
            continue
        seen_msg_ids.add(mid)
        hits.append({
            "thread_id": tid,
            "message_id": mid,
            "keyword": kw,
            "match_timestamp": ts
        })

    # Sort hits for contexts.jsonl output
    hits.sort(key=lambda h: (ts_key_asc(h["match_timestamp"]), h["thread_id"], h["message_id"]))

    # Build contexts for each hit
    contexts = []
    for h in hits:
        tid = h["thread_id"]
        mid = h["message_id"]
        thread_msgs = by_thread_filtered.get(tid, [])
        idx = None
        for i, m in enumerate(thread_msgs):
            if m.get("id") == mid:
                idx = i
                break
        # If for some reason the hit message is not in filtered list (should not happen), skip context
        before_list = []
        after_list = []
        if idx is not None:
            # Up to 2 before, oldest-to-newest
            start = max(0, idx - 2)
            for j in range(start, idx):
                cm = thread_msgs[j]
                before_list.append({
                    "id": cm.get("id", ""),
                    "timestamp": cm.get("timestamp", ""),
                    "sender_display_name": get_sender_display_name(cm),
                    "text": cm.get("text", "")
                })
            # Up to 1 after
            if idx + 1 < len(thread_msgs):
                cm = thread_msgs[idx + 1]
                after_list.append({
                    "id": cm.get("id", ""),
                    "timestamp": cm.get("timestamp", ""),
                    "sender_display_name": get_sender_display_name(cm),
                    "text": cm.get("text", "")
                })
        contexts.append({
            "thread_id": h["thread_id"],
            "message_id": h["message_id"],
            "keyword": h["keyword"],
            "match_timestamp": h["match_timestamp"],
            "context_before": before_list,
            "context_after": after_list
        })

    # Build per-thread summaries
    hits_by_thread = {}
    for h in hits:
        hits_by_thread.setdefault(h["thread_id"], []).append(h)

    summaries = []
    for tid, hit_list in hits_by_thread.items():
        # Thread metadata
        tmeta = threads_index.get(tid, {"thread_id": tid, "thread_name": "", "participants": []})
        thread_name = tmeta.get("thread_name") or ""
        participants = build_participants_list(tmeta)

        # timestamps
        first_ts = None
        last_ts = None
        for h in hit_list:
            ts = h["match_timestamp"]
            if first_ts is None:
                first_ts = ts
                last_ts = ts
            else:
                # Compare using ts_key_asc
                if ts_key_asc(ts) < ts_key_asc(first_ts):
                    first_ts = ts
                if ts_key_asc(ts) > ts_key_asc(last_ts):
                    last_ts = ts

        # matched_messages_count
        matched_count = len(hit_list)

        # keyword_frequency
        kf = {}
        for h in hit_list:
            k = h["keyword"]
            kf[k] = kf.get(k, 0) + 1

        # total_messages_considered
        total_considered = len(by_thread_filtered.get(tid, []))

        summaries.append({
            "thread_id": tid,
            "thread_name": thread_name,
            "participants": participants,
            "first_match_ts": first_ts if isinstance(first_ts, str) else "",
            "last_match_ts": last_ts if isinstance(last_ts, str) else "",
            "matched_messages_count": matched_count,
            "keyword_frequency": kf,
            "total_messages_considered": total_considered
        })

    # Sort summaries by thread_name case-insensitive ascending
    summaries.sort(key=lambda s: (s["thread_name"].casefold() if isinstance(s.get("thread_name"), str) else ""))

    # Build top_threads rows
    # Top 5 by matched_messages_count desc, tie-break by last_match_ts desc, then thread_id asc
    def top_sort_key(s):
        # matched desc -> negative count, last_ts desc -> use ts_key_desc, tid asc
        return (
            -int(s.get("matched_messages_count", 0)),
            ts_key_desc(s.get("last_match_ts", "")),
            s.get("thread_id", "")
        )

    ranked = sorted(summaries, key=top_sort_key)
    top_n = ranked[:5]

    expected = {
        "contexts": contexts,
        "summaries": summaries,
        "top_threads": []
    }

    # Build expected CSV rows as list of lists (excluding header)
    for s in top_n:
        row = [
            s.get("thread_id", ""),
            s.get("thread_name", ""),
            str(int(s.get("matched_messages_count", 0))),
            s.get("first_match_ts", ""),
            s.get("last_match_ts", ""),
            str(len(s.get("participants", [])))
        ]
        expected["top_threads"].append(row)

    return expected

def read_agent_summary(path):
    data = parse_json_file(path)
    if not isinstance(data, list):
        return None
    return data

def read_agent_contexts(path):
    items = parse_jsonl_file(path)
    if items is None:
        return None
    return items

def read_agent_top_threads_csv(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows
    except Exception:
        return None, None

def compare_summaries(agent, expected):
    # Expect same length and exact objects with only the required keys
    required_keys = {
        "thread_id",
        "thread_name",
        "participants",
        "first_match_ts",
        "last_match_ts",
        "matched_messages_count",
        "keyword_frequency",
        "total_messages_considered"
    }
    if not isinstance(agent, list):
        return False, {"summary_length_match": False, "summary_keys_valid": False, "summary_content_equal": False}
    length_match = len(agent) == len(expected)
    keys_valid = True
    content_equal = True
    # Build comparable normalized versions to ensure deterministic comparison order (expected is already sorted)
    # We cannot rely on agent order being sorted; but spec requires sorted by thread_name; enforce by comparing lists directly
    # So we require exact same order.
    for a, e in zip(agent, expected):
        if not isinstance(a, dict):
            keys_valid = False
            content_equal = False
            continue
        # keys must match exactly
        a_keys = set(a.keys())
        if a_keys != required_keys:
            keys_valid = False
        # Compare values
        if a != e:
            content_equal = False
    return (length_match and keys_valid and content_equal), {
        "summary_length_match": length_match,
        "summary_keys_valid": keys_valid,
        "summary_content_equal": content_equal
    }

def compare_contexts(agent, expected):
    # Expect same length and exact objects with only required keys and required sorting
    req_keys = {"thread_id", "message_id", "keyword", "match_timestamp", "context_before", "context_after"}
    if not isinstance(agent, list):
        return False, {"contexts_length_match": False, "contexts_keys_valid": False, "contexts_content_equal": False, "contexts_sorted": False}
    length_match = len(agent) == len(expected)
    keys_valid = True
    content_equal = True
    # Check sorting: ensure agent is sorted by match_timestamp asc, then thread_id asc, then message_id asc
    sorted_agent = sorted(agent, key=lambda h: (ts_key_asc(h.get("match_timestamp")), h.get("thread_id", ""), h.get("message_id", "")))
    contexts_sorted = (agent == sorted_agent)
    for a in agent:
        if not isinstance(a, dict) or set(a.keys()) != req_keys:
            keys_valid = False
            break
        # Validate context arrays element keys
        for arr_key in ("context_before", "context_after"):
            arr = a.get(arr_key)
            if not isinstance(arr, list):
                keys_valid = False
                break
            for cm in arr:
                if not isinstance(cm, dict):
                    keys_valid = False
                    break
                if set(cm.keys()) != {"id", "timestamp", "sender_display_name", "text"}:
                    keys_valid = False
                    break
            if not keys_valid:
                break
        if not keys_valid:
            break
    if length_match and keys_valid:
        # Compare each object in order to expected
        for a, e in zip(agent, expected):
            if a != e:
                content_equal = False
                break
    else:
        content_equal = False
    return (length_match and keys_valid and content_equal and contexts_sorted), {
        "contexts_length_match": length_match,
        "contexts_keys_valid": keys_valid,
        "contexts_content_equal": content_equal,
        "contexts_sorted": contexts_sorted
    }

def compare_top_threads(agent_header, agent_rows, expected_rows):
    # Header must match exactly these columns:
    expected_header = ["thread_id", "thread_name", "matched_messages_count", "first_match_ts", "last_match_ts", "participants_count"]
    header_ok = agent_header == expected_header
    if not header_ok:
        return False, {"top_threads_header_ok": False, "top_threads_length_match": False, "top_threads_rows_match": False}
    length_match = len(agent_rows) == len(expected_rows)
    rows_match = True
    if length_match:
        for ar, er in zip(agent_rows, expected_rows):
            # Ensure exact field count
            if len(ar) != len(er):
                rows_match = False
                break
            # Compare strings exactly
            if ar != er:
                rows_match = False
                break
    else:
        rows_match = False
    return (header_ok and length_match and rows_match), {
        "top_threads_header_ok": header_ok,
        "top_threads_length_match": length_match,
        "top_threads_rows_match": rows_match
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_summary_file": False,
        "summary_valid_json": False,
        "summary_correct": False,
        "summary_length_match": False,
        "summary_keys_valid": False,
        "summary_content_equal": False,

        "has_top_threads_file": False,
        "top_threads_valid_csv": False,
        "top_threads_correct": False,
        "top_threads_header_ok": False,
        "top_threads_length_match": False,
        "top_threads_rows_match": False,

        "has_contexts_file": False,
        "contexts_valid_jsonl": False,
        "contexts_correct": False,
        "contexts_length_match": False,
        "contexts_keys_valid": False,
        "contexts_content_equal": False,
        "contexts_sorted": False
    }

    expected = build_expected(workspace_root)
    # If inputs invalid, cannot produce expected -> no positive reward
    if expected is None:
        # Print zero reward
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Paths to outputs
    finance_dir = os.path.join(output_dir, "finance")
    summary_path = os.path.join(finance_dir, "summary.json")
    top_threads_path = os.path.join(finance_dir, "top_threads.csv")
    contexts_path = os.path.join(finance_dir, "contexts.jsonl")

    # Check summary.json
    if os.path.isfile(summary_path):
        checks["has_summary_file"] = True
        agent_summary = read_agent_summary(summary_path)
        if isinstance(agent_summary, list):
            checks["summary_valid_json"] = True
            ok, detail = compare_summaries(agent_summary, expected["summaries"])
            checks["summary_correct"] = ok
            checks["summary_length_match"] = detail["summary_length_match"]
            checks["summary_keys_valid"] = detail["summary_keys_valid"]
            checks["summary_content_equal"] = detail["summary_content_equal"]

    # Check top_threads.csv
    if os.path.isfile(top_threads_path):
        checks["has_top_threads_file"] = True
        header, rows = read_agent_top_threads_csv(top_threads_path)
        if header is not None:
            checks["top_threads_valid_csv"] = True
            ok, detail = compare_top_threads(header, rows, expected["top_threads"])
            checks["top_threads_correct"] = ok
            checks["top_threads_header_ok"] = detail["top_threads_header_ok"]
            checks["top_threads_length_match"] = detail["top_threads_length_match"]
            checks["top_threads_rows_match"] = detail["top_threads_rows_match"]

    # Check contexts.jsonl
    if os.path.isfile(contexts_path):
        checks["has_contexts_file"] = True
        agent_contexts = read_agent_contexts(contexts_path)
        if isinstance(agent_contexts, list):
            checks["contexts_valid_jsonl"] = True
            ok, detail = compare_contexts(agent_contexts, expected["contexts"])
            checks["contexts_correct"] = ok
            checks["contexts_length_match"] = detail["contexts_length_match"]
            checks["contexts_keys_valid"] = detail["contexts_keys_valid"]
            checks["contexts_content_equal"] = detail["contexts_content_equal"]
            checks["contexts_sorted"] = detail["contexts_sorted"]

    # Compute reward: average of three main artifact correctness checks
    main_checks = [
        checks["summary_correct"],
        checks["top_threads_correct"],
        checks["contexts_correct"]
    ]
    num = sum(1 for x in main_checks if x)
    denom = len(main_checks)
    reward = (num / denom) if denom > 0 else 0.0

    # If agent produced nothing meaningful (no files or all missing), reward must be exactly 0.0
    if not (checks["has_summary_file"] or checks["has_top_threads_file"] or checks["has_contexts_file"]):
        reward = 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()