import json
import os
import sys
import re
from datetime import datetime, timezone

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        "search_results_present": False,
        "search_results_correct": False,
        "stats_present": False,
        "stats_correct": False,
        "export_md_present": False,
        "export_heading_present": False,
        "export_sections_ok": False
    }

    # Helper: Read inputs
    memories_path = os.path.join(input_dir, "memories.jsonl")
    queries_path = os.path.join(input_dir, "queries.json")
    stopwords_path = os.path.join(input_dir, "stopwords.txt")

    # Helper: Read outputs
    search_results_path = os.path.join(output_dir, "search_results.json")
    stats_path = os.path.join(output_dir, "stats.json")
    export_md_path = os.path.join(output_dir, "export.md")

    # If output dir missing entirely, reward must be 0.0
    if not os.path.isdir(output_dir):
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Load inputs deterministically, but no positive reward for reading inputs alone
    try:
        stopwords = load_stopwords(stopwords_path)
        memories = load_memories(memories_path)
        queries = load_queries(queries_path)
    except Exception:
        # If inputs are missing or invalid, we cannot verify outputs; reward stays 0.0
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Preprocess tokens for memories and queries
    mem_data = []
    all_token_counts = {}
    earliest_dt = None
    earliest_str = None
    latest_dt = None
    latest_str = None

    for m in memories:
        content = m.get("content", "")
        tokens_list = preprocess_tokens(content, stopwords, as_set=False)
        tokens_set = set(tokens_list)  # unique set for Jaccard
        # Update token counts (duplicates count)
        for t in tokens_list:
            all_token_counts[t] = all_token_counts.get(t, 0) + 1

        t_str = m.get("time_created", "")
        dt = parse_iso8601(t_str)
        ts = dt.timestamp() if dt else 0.0

        # Update earliest/latest
        if dt is not None:
            if earliest_dt is None or dt < earliest_dt:
                earliest_dt = dt
                earliest_str = t_str
            if latest_dt is None or dt > latest_dt:
                latest_dt = dt
                latest_str = t_str

        mem_data.append({
            "id": m.get("id", ""),
            "memory_type": m.get("memory_type", ""),
            "time_created": t_str,
            "dt": dt,
            "timestamp": ts,
            "tokens_set": tokens_set,
            "content": content
        })

    # Compute expected search results per query
    expected_results = {}
    for q in queries:
        qid = q.get("id", "")
        qtext = q.get("text", "")
        q_tokens_set = set(preprocess_tokens(qtext, stopwords, as_set=False))
        scored = []
        for md in mem_data:
            sim = jaccard_similarity(q_tokens_set, md["tokens_set"])
            # Sorting: highest similarity, then newer time_created (later dt wins), then lexicographically smaller id
            # We'll sort by (-sim, -timestamp, id)
            scored.append((sim, md["timestamp"], md["id"]))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        top3 = scored[:3] if len(scored) >= 3 else scored + [(0.0, 0.0, "")] * (3 - len(scored))
        exp = [{"memory_id": mid, "similarity": round(sim, 6)} for (sim, ts, mid) in top3]
        expected_results[qid] = exp

    # Compute expected stats
    counts_by_type = {}
    for m in memories:
        mt = m.get("memory_type", "")
        counts_by_type[mt] = counts_by_type.get(mt, 0) + 1

    # Top tokens: top 5 by overall frequency, ties by alphabetical ascending
    top_tokens_sorted = sorted(all_token_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    expected_top_tokens = [{"token": tok, "count": cnt} for tok, cnt in top_tokens_sorted[:5]]

    # 1) Validate search_results.json
    if os.path.isfile(search_results_path):
        checks["search_results_present"] = True
        try:
            with open(search_results_path, "r", encoding="utf-8") as f:
                sr = json.load(f)
            # For each query in input, verify presence and correctness
            all_ok = True
            for q in queries:
                qid = q.get("id", "")
                if qid not in sr:
                    all_ok = False
                    break
                arr = sr[qid]
                if not isinstance(arr, list) or len(arr) != 3:
                    all_ok = False
                    break
                exp_list = expected_results.get(qid, [])
                for i, item in enumerate(arr):
                    if not isinstance(item, dict):
                        all_ok = False
                        break
                    got_mid = item.get("memory_id", None)
                    got_sim = item.get("similarity", None)
                    exp_mid = exp_list[i]["memory_id"]
                    exp_sim = exp_list[i]["similarity"]
                    if got_mid != exp_mid:
                        all_ok = False
                        break
                    # Accept number or string; compare rounded to 6 decimals
                    if got_sim is None:
                        all_ok = False
                        break
                    try:
                        got_sim_float = float(got_sim)
                    except Exception:
                        all_ok = False
                        break
                    if round(got_sim_float, 6) != exp_sim:
                        all_ok = False
                        break
                if not all_ok:
                    break
            if all_ok:
                checks["search_results_correct"] = True
        except Exception:
            pass

    # 2) Validate stats.json
    if os.path.isfile(stats_path):
        checks["stats_present"] = True
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
            ok = True
            # counts_by_type
            cbt = stats.get("counts_by_type")
            if not isinstance(cbt, dict) or cbt != counts_by_type:
                ok = False
            # earliest_time, latest_time
            et = stats.get("earliest_time")
            lt = stats.get("latest_time")
            exp_et = earliest_str if earliest_str is not None else None
            exp_lt = latest_str if latest_str is not None else None
            if et != exp_et or lt != exp_lt:
                ok = False
            # top_tokens
            tt = stats.get("top_tokens")
            if not isinstance(tt, list):
                ok = False
            else:
                # Normalize tokens to compare strictly
                def norm_list(lst):
                    out = []
                    for obj in lst:
                        if not isinstance(obj, dict):
                            return None
                        tok = obj.get("token")
                        cnt = obj.get("count")
                        out.append({"token": tok, "count": cnt})
                    return out
                tt_norm = norm_list(tt)
                if tt_norm is None or tt_norm != expected_top_tokens:
                    ok = False
            if ok:
                checks["stats_correct"] = True
        except Exception:
            pass

    # 3) Validate export.md
    if os.path.isfile(export_md_path):
        checks["export_md_present"] = True
        try:
            with open(export_md_path, "r", encoding="utf-8") as f:
                export_text = f.read()
            lines = export_text.splitlines()

            # Heading check: line with "# Memory Search Report"
            heading_ok = any(bool(re.match(r'^\s*#\s*Memory Search Report\s*$', ln)) for ln in lines)
            checks["export_heading_present"] = heading_ok

            # Sections check: for each query id, find section containing qid and confirm memory ids from output/search_results.json
            sections_ok = False
            # Need search_results content to verify IDs present per query
            sr_for_export = None
            if checks["search_results_present"]:
                try:
                    with open(search_results_path, "r", encoding="utf-8") as f:
                        sr_for_export = json.load(f)
                except Exception:
                    sr_for_export = None

            if sr_for_export is not None and isinstance(sr_for_export, dict):
                # Build indices of lines containing each query id
                sections_ok = True
                for idx, q in enumerate(queries):
                    qid = q.get("id", "")
                    # Find start line index for this query id
                    start_idx = None
                    for i, ln in enumerate(lines):
                        if qid in ln:
                            start_idx = i
                            break
                    if start_idx is None:
                        sections_ok = False
                        break
                    # Find end index: next occurrence of any subsequent query id
                    end_idx = len(lines)
                    subsequent_ids = [qq.get("id", "") for qq in queries[idx+1:]]
                    for j in range(start_idx + 1, len(lines)):
                        if any(sid and sid in lines[j] for sid in subsequent_ids):
                            end_idx = j
                            break
                    section_text = "\n".join(lines[start_idx:end_idx])
                    # The three memory ids from search_results.json for this qid must appear in section
                    if qid not in sr_for_export or not isinstance(sr_for_export[qid], list) or len(sr_for_export[qid]) != 3:
                        sections_ok = False
                        break
                    mem_ids = [item.get("memory_id") for item in sr_for_export[qid]]
                    if any(mid is None for mid in mem_ids):
                        sections_ok = False
                        break
                    if not all(mid in section_text for mid in mem_ids):
                        sections_ok = False
                        break
            checks["export_sections_ok"] = sections_ok and heading_ok
        except Exception:
            pass

    # Compute reward as weighted sum of dependent checks
    # Weights: search_results_correct 0.6, stats_correct 0.3, export_ok 0.1
    export_ok = checks["export_heading_present"] and checks["export_sections_ok"] and checks["export_md_present"]
    reward = 0.0
    if checks["search_results_present"] and checks["search_results_correct"]:
        reward += 0.6
    if checks["stats_present"] and checks["stats_correct"]:
        reward += 0.3
    if export_ok:
        reward += 0.1

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))


def load_stopwords(path):
    sw = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            token = line.strip().lower()
            if token:
                sw.add(token)
    return sw

def load_memories(path):
    mems = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            mems.append(json.loads(line))
    return mems

def load_queries(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Expect a list of {id, text}
    if not isinstance(data, list):
        raise ValueError("queries.json must be a list")
    return data

_non_alnum_re = re.compile(r'[^a-z0-9]+')

def preprocess_tokens(text, stopwords, as_set=False):
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    s = text.lower()
    s = _non_alnum_re.sub(" ", s)
    parts = s.split()
    tokens = []
    for tok in parts:
        if len(tok) < 2:
            continue
        if tok in stopwords:
            continue
        tokens.append(tok)
    if as_set:
        return set(tokens)
    return tokens

def parse_iso8601(s):
    if not isinstance(s, str) or not s:
        return None
    # Normalize 'Z' to '+00:00'
    ss = s
    if ss.endswith("Z"):
        ss = ss[:-1] + "+00:00"
    # Attempt to parse with fromisoformat
    try:
        dt = datetime.fromisoformat(ss)
        return dt
    except Exception:
        # Try common fallback formats
        fmts = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]
        for fmt in fmts:
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None

def jaccard_similarity(set_a, set_b):
    if not isinstance(set_a, set):
        set_a = set(set_a)
    if not isinstance(set_b, set):
        set_b = set(set_b)
    if not set_a and not set_b:
        return 0.0
    inter = set_a.intersection(set_b)
    uni = set_a.union(set_b)
    if not uni:
        return 0.0
    return len(inter) / len(uni)


if __name__ == "__main__":
    main()