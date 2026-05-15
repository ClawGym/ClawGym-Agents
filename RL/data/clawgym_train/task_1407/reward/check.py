import json
import os
import re
import sys

def workspace_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    items.append(json.loads(s))
                except Exception:
                    return None
        return items
    except Exception:
        return None

def strip_yaml_comment(line):
    # remove comments (# ...) unless inside quotes (simple heuristic)
    # If # appears, we cut from first # not within quotes
    s = line
    out = []
    in_single = False
    in_double = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "'" and not in_double:
            in_single = not in_single
            out.append(c)
        elif c == '"' and not in_single:
            in_double = not in_double
            out.append(c)
        elif c == "#" and not in_single and not in_double:
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip("\n")

def parse_bool(val):
    v = str(val).strip().lower()
    if v in ("true", "yes", "on"):
        return True
    if v in ("false", "no", "off"):
        return False
    return None

def parse_scalar(val):
    v = val.strip()
    if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
        return v[1:-1]
    b = parse_bool(v)
    if b is not None:
        return b
    # try number? not needed now
    return v

def parse_providers_yaml(path):
    # Extract keys: has_openai_key (bool), recommended_local_model (str or None), local_models (list of str)
    txt = read_file_text(path)
    result = {"has_openai_key": False, "recommended_local_model": None, "local_models": []}
    if txt is None:
        return result
    lines = [strip_yaml_comment(l.rstrip("\n")) for l in txt.splitlines()]
    # Handle inline dict possibly nested; we will just search patterns
    # has_openai_key
    for l in lines:
        m = re.match(r"^\s*has_openai_key\s*:\s*(.+?)\s*$", l)
        if m:
            b = parse_bool(m.group(1))
            if b is None:
                b = True if m.group(1).strip() else False
            result["has_openai_key"] = bool(b)
    # recommended_local_model
    for l in lines:
        m = re.match(r"^\s*recommended_local_model\s*:\s*(.+?)\s*$", l)
        if m:
            result["recommended_local_model"] = parse_scalar(m.group(1))
    # local_models list
    # Try inline [a, b]
    for l in lines:
        m = re.match(r"^\s*local_models\s*:\s*\[(.*?)\]\s*$", l)
        if m:
            inner = m.group(1).strip()
            if inner:
                parts = [p.strip() for p in inner.split(",")]
                parts = [parse_scalar(p) for p in parts if p]
                result["local_models"] = [p for p in parts if p]
            else:
                result["local_models"] = []
            break
    else:
        # Multi-line list
        lm_idx = None
        for idx, l in enumerate(lines):
            if re.match(r"^\s*local_models\s*:\s*$", l):
                lm_idx = idx
                break
        if lm_idx is not None:
            # collect - item lines after this, until next non-list block (line not starting with spaces then '-' or blank)
            for j in range(lm_idx + 1, len(lines)):
                lj = lines[j]
                if not lj.strip():
                    continue
                if re.match(r"^\s*-\s*(.+?)\s*$", lj):
                    m = re.match(r"^\s*-\s*(.+?)\s*$", lj)
                    if m:
                        item = parse_scalar(m.group(1))
                        if item:
                            result["local_models"].append(item)
                    continue
                # stop when encountering a line that is not a list item and is dedented
                if not lj.startswith(" "):
                    break
    return result

def parse_projects_yaml(path):
    # Return list of dicts: {"name": ..., "default_scope": ...}
    txt = read_file_text(path)
    projects = []
    if txt is None:
        return projects
    lines = [strip_yaml_comment(l.rstrip("\n")) for l in txt.splitlines()]
    # Find projects: block
    proj_line_idx = None
    for i, l in enumerate(lines):
        if re.match(r"^\s*projects\s*:\s*$", l):
            proj_line_idx = i
            proj_indent = len(l) - len(l.lstrip(" "))
            break
    if proj_line_idx is None:
        # Attempt flat style: - name: ... under root; parse any list items
        pass
    # Parse list items after projects:
    current = None
    current_indent = None
    started = False
    for j in range((proj_line_idx + 1) if proj_line_idx is not None else 0, len(lines)):
        lj = lines[j]
        if not lj.strip():
            continue
        indent = len(lj) - len(lj.lstrip(" "))
        # If we were in projects block and dedent to <= proj_indent and not a list item, stop
        if proj_line_idx is not None and indent <= proj_indent and not re.match(r"^\s*-\s*", lj):
            # End of projects section
            if current:
                projects.append(current)
                current = None
            break
        # Start of a new list item
        if re.match(r"^\s*-\s*", lj):
            # If there was an existing current, push it
            if current:
                projects.append(current)
            current = {}
            current_indent = indent
            # Parse inline key after "- "
            rest = lj.strip()[1:].strip()
            if rest:
                # could be "name: X" or "default_scope: team"
                mkv = re.match(r"^(\w[\w\-]*)\s*:\s*(.+)$", rest)
                if mkv:
                    k = mkv.group(1)
                    v = parse_scalar(mkv.group(2))
                    current[k] = v
            continue
        # If inside a current item, parse key: value lines with greater indent
        if current is not None and indent >= (current_indent + 1):
            mkv = re.match(r"^\s*(\w[\w\-]*)\s*:\s*(.+)$", lj)
            if mkv:
                k = mkv.group(1)
                v = parse_scalar(mkv.group(2))
                current[k] = v
            continue
        # Else ignore
    if current:
        projects.append(current)
    # Normalize keys, ensure name and default_scope
    norm = []
    for p in projects:
        name = p.get("name")
        default_scope = p.get("default_scope") or p.get("scope")
        if name:
            norm.append({"name": str(name), "default_scope": str(default_scope) if default_scope else None})
    return norm

def compute_expected_chain(providers):
    has_openai = bool(providers.get("has_openai_key"))
    rec_local = providers.get("recommended_local_model")
    local_models = providers.get("local_models") or []
    chain = []
    quality_note = None
    if has_openai and rec_local:
        chain = ["openai", rec_local, "bm25"]
        quality_note = "openai+local"
    elif has_openai and not rec_local and local_models:
        chain = ["openai", local_models[0], "bm25"]
        quality_note = "openai+local"
    elif has_openai and not (rec_local or local_models):
        chain = ["openai", "bm25"]
        quality_note = "openai"
    elif (rec_local or local_models):
        chosen = rec_local or local_models[0]
        chain = [chosen, "bm25"]
        quality_note = "local model"
    else:
        chain = ["bm25"]
        quality_note = "keyword-only"
    return chain, quality_note

def words_from_text(text):
    # Split by whitespace for deterministic 40-word chunking as per spec
    return text.split()

def chunk_count_for_text(text, chunk_size=40):
    words = words_from_text(text)
    if not words:
        return 0
    n = (len(words) + chunk_size - 1) // chunk_size
    return n

def list_docs(input_dir):
    docs_dir = os.path.join(input_dir, "docs")
    doc_files = []
    if os.path.isdir(docs_dir):
        for name in os.listdir(docs_dir):
            if name.lower().endswith(".md"):
                doc_files.append(os.path.join(docs_dir, name))
    return sorted(doc_files)

def load_ingested_index(path):
    data = read_json(path)
    if data is None:
        return None
    # Normalize to a flat list of chunk dicts
    chunks = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and any(k in item for k in ("source", "source_path", "file", "path", "text")):
                chunks.append(item)
            elif isinstance(item, list):
                for sub in item:
                    if isinstance(sub, dict):
                        chunks.append(sub)
    elif isinstance(data, dict):
        # could be mapping from source->list
        for k, v in data.items():
            if isinstance(v, list):
                for sub in v:
                    if isinstance(sub, dict):
                        # ensure a source field exists; if missing add from key
                        if not any(x in sub for x in ("source", "source_path", "file", "path")):
                            sub = dict(sub)
                            sub["source"] = k
                        chunks.append(sub)
            elif isinstance(v, dict):
                chunks.append(v)
    return chunks

def get_chunk_source(chunk):
    for key in ("source", "source_path", "file", "path"):
        if key in chunk:
            return chunk[key]
    return None

def get_chunk_text(chunk):
    return chunk.get("text") or chunk.get("snippet") or chunk.get("content") or ""

def group_chunks_by_source(chunks):
    by_src = {}
    for ch in chunks:
        src = get_chunk_source(ch)
        if not src:
            continue
        by_src.setdefault(src, []).append(ch)
    return by_src

def load_search_results(path):
    data = read_json(path)
    if data is None:
        return None
    # Normalize to dict mapping query string -> results list
    qmap = {}
    if isinstance(data, dict):
        # keys may be queries
        for k, v in data.items():
            if isinstance(v, list):
                qmap[str(k)] = v
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                q = item.get("query") or item.get("q") or item.get("text")
                r = item.get("results") or item.get("items") or item.get("hits")
                if isinstance(q, str) and isinstance(r, list):
                    qmap[q] = r
    return qmap

def extract_queries(path):
    data = read_json(path)
    if data is None:
        return None
    queries = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                queries.append({"query": item})
            elif isinstance(item, dict):
                q = item.get("query") or item.get("text") or item.get("q")
                proj = item.get("project")
                if isinstance(q, str):
                    queries.append({"query": q, "project": proj})
    elif isinstance(data, dict):
        # perhaps {"queries":[...]}
        arr = data.get("queries")
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, str):
                    queries.append({"query": item})
                elif isinstance(item, dict):
                    q = item.get("query") or item.get("text") or item.get("q")
                    proj = item.get("project")
                    if isinstance(q, str):
                        queries.append({"query": q, "project": proj})
    return queries

def score_occurrences(query, text):
    if not query or not text:
        return 0
    # Case-insensitive non-overlapping occurrences of exact query string
    q = re.escape(query)
    return len(re.findall(q, text, flags=re.IGNORECASE))

def aggregate_docs_text(docs_paths):
    # returns dict path->text
    out = {}
    for p in docs_paths:
        t = read_file_text(p) or ""
        out[p] = t
    return out

def scope_cascade(entry, project_defaults):
    # explicit scope
    if isinstance(entry, dict):
        if "scope" in entry and entry["scope"]:
            return str(entry["scope"])
        proj = entry.get("project")
        if proj and proj in project_defaults and project_defaults[proj]:
            return str(project_defaults[proj])
    return "team"

def get_result_text_for_scoring(result_item):
    # Use text/snippet/content
    if not isinstance(result_item, dict):
        return ""
    return result_item.get("text") or result_item.get("snippet") or result_item.get("content") or ""

def result_project(result_item):
    if not isinstance(result_item, dict):
        return None
    return result_item.get("project")

def result_source_type(result_item):
    if not isinstance(result_item, dict):
        return None
    st = result_item.get("source_type")
    if isinstance(st, str):
        return st.lower()
    return None

def single_sentence(text):
    if text is None:
        return False
    # Non-empty, a single line when stripping trailing newline
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if len(lines) != 1:
        return False
    # ends with a period helpful but not required
    return True

def check_config(input_dir, output_dir):
    providers_path = os.path.join(input_dir, "providers.yaml")
    out_path = os.path.join(output_dir, "config.json")
    if not os.path.isfile(out_path):
        return False
    providers = parse_providers_yaml(providers_path)
    data = read_json(out_path)
    if not isinstance(data, dict):
        return False
    chain = data.get("chain")
    note = data.get("note") or data.get("quality") or data.get("search_quality")
    if not isinstance(chain, list) or len(chain) == 0:
        return False
    expected_chain, expected_note = compute_expected_chain(providers)
    # Must match expected chain
    if chain != expected_chain:
        # Special relaxed case: if providers.yaml missing then cannot compute; require at least bm25 presence
        if os.path.isfile(providers_path):
            return False
        else:
            if "bm25" not in [str(x).lower() for x in chain]:
                return False
    # Note must align: contains "local" if expected uses local-only or openai+local, "keyword" for bm25 only, "openai" if openai present
    lc_note = (str(note).lower() if note is not None else "")
    if expected_chain == ["bm25"]:
        if "keyword" not in lc_note:
            return False
    else:
        if expected_chain and expected_chain[0] == "openai":
            # expected openai present
            if "openai" not in lc_note:
                return False
        else:
            # local-first
            if "local" not in lc_note:
                return False
    return True

def check_heartbeat(output_dir):
    hb_path = os.path.join(output_dir, "heartbeat.md")
    if not os.path.isfile(hb_path):
        return False
    txt = read_file_text(hb_path) or ""
    # TASK header
    has_task_header = any(re.match(r"^\s*#\s*TASK:\s*Palaia Maintenance", line) for line in txt.splitlines())
    # Daily line with palaia gc
    has_daily = any(re.match(r"^\s*#?\s*Daily:\s*.*palaia\s+gc\b", line) for line in txt.splitlines())
    # Weekly line with palaia gc --aggressive
    has_weekly = any(re.match(r"^\s*#?\s*Weekly\s*\(Sunday\)\s*:\s*.*palaia\s+gc\s+--aggressive\b", line) for line in txt.splitlines())
    return bool(has_task_header and has_daily and has_weekly)

def check_migration(input_dir, output_dir):
    in_path = os.path.join(input_dir, "legacy_memory.jsonl")
    out_path = os.path.join(output_dir, "migrated.jsonl")
    projects_path = os.path.join(input_dir, "projects.yaml")
    if not os.path.isfile(out_path) or not os.path.isfile(in_path):
        return False
    in_items = read_jsonl(in_path)
    out_items = read_jsonl(out_path)
    if in_items is None or out_items is None:
        return False
    if len(in_items) != len(out_items):
        return False
    # Build project defaults
    proj_defs = {}
    for p in parse_projects_yaml(projects_path):
        if p.get("name"):
            proj_defs[p["name"]] = p.get("default_scope")
    # Check each migrated item has correct scope and tier hot
    for in_item, out_item in zip(in_items, out_items):
        if not isinstance(out_item, dict):
            return False
        expected_scope = scope_cascade(in_item if isinstance(in_item, dict) else {}, proj_defs)
        if out_item.get("scope") != expected_scope:
            return False
        if out_item.get("tier") != "hot":
            return False
    return True

def check_migration_report(input_dir, output_dir):
    report_path = os.path.join(output_dir, "migration_report.json")
    in_path = os.path.join(input_dir, "legacy_memory.jsonl")
    if not os.path.isfile(report_path) or not os.path.isfile(in_path):
        return False
    data = read_json(report_path)
    if not isinstance(data, dict):
        return False
    in_items = read_jsonl(in_path)
    if in_items is None:
        return False
    # accept keys: imported_count, total, count
    count_val = None
    for k in ("imported_count", "total", "count"):
        if k in data and isinstance(data[k], int):
            count_val = data[k]
            break
    if count_val != len(in_items):
        return False
    sources = data.get("sources")
    if not isinstance(sources, list):
        return False
    if "input/legacy_memory.jsonl" not in sources:
        # also accept absolute path ending with input/legacy_memory.jsonl
        if not any(str(s).endswith("input/legacy_memory.jsonl") for s in sources):
            return False
    return True

def check_projects_created(input_dir, output_dir):
    out_path = os.path.join(output_dir, "projects_created.json")
    if not os.path.isfile(out_path):
        return False
    data = read_json(out_path)
    if data is None:
        return False
    # expected projects from input
    expected = parse_projects_yaml(os.path.join(input_dir, "projects.yaml"))
    exp_map = {p["name"]: p.get("default_scope") for p in expected if p.get("name")}
    # Normalize output to list
    out_list = []
    if isinstance(data, list):
        out_list = data
    elif isinstance(data, dict):
        if "projects" in data and isinstance(data["projects"], list):
            out_list = data["projects"]
        else:
            # maybe mapping name->scope
            for k, v in data.items():
                out_list.append({"name": k, "default_scope": v})
    out_map = {}
    for it in out_list:
        if isinstance(it, dict) and "name" in it:
            out_map[str(it["name"])] = it.get("default_scope")
    # Compare names sets
    if set(out_map.keys()) != set(exp_map.keys()):
        return False
    # Compare scopes
    for name, scope in exp_map.items():
        if (out_map.get(name) or None) != (scope or None):
            return False
    return True

def check_ingested_index(input_dir, output_dir):
    out_path = os.path.join(output_dir, "ingested_index.json")
    if not os.path.isfile(out_path):
        return False
    chunks = load_ingested_index(out_path)
    if chunks is None:
        return False
    # Expect for each doc file under input/docs/
    docs = list_docs(input_dir)
    if not docs:
        # If no docs in input, then expect no chunks
        return len(chunks) == 0
    # Group by source
    by_src = group_chunks_by_source(chunks)
    ok_all = True
    for doc_abs in docs:
        # required source path should be relative path "input/docs/filename"
        rel = os.path.join("input", "docs", os.path.basename(doc_abs))
        # Accept either relative path or absolute path ending with rel
        # Collect chunks whose source matches
        src_chunks = []
        for src, lst in by_src.items():
            s = str(src)
            if s == rel or s.endswith(rel):
                src_chunks.extend(lst)
        # If exact key not grouped, also scan all chunks
        if not src_chunks:
            # fallback scan
            for ch in chunks:
                s = get_chunk_source(ch) or ""
                if s == rel or s.endswith(rel):
                    src_chunks.append(ch)
        # Compute expected chunk count
        text = read_file_text(doc_abs) or ""
        expected_count = chunk_count_for_text(text, 40)
        # Filter chunks with numeric chunk_id for this file
        # Ensure chunk_id sequence 1..N
        ids = []
        for ch in src_chunks:
            cid = ch.get("chunk_id") or ch.get("id")
            if isinstance(cid, int):
                ids.append(cid)
        ids_sorted = sorted(ids)
        # Check presence of required fields: source path, chunk_id, text
        fields_ok = all(get_chunk_text(ch) != "" and (ch.get("chunk_id") or ch.get("id")) for ch in src_chunks)
        if len(src_chunks) != expected_count or not fields_ok or ids_sorted != list(range(1, expected_count + 1)):
            ok_all = False
    return ok_all

def check_search_results(input_dir, output_dir):
    # Combined check for count + sorting + doc_chunk presence and project restriction
    results_path = os.path.join(output_dir, "search_results.json")
    ingested_path = os.path.join(output_dir, "ingested_index.json")
    migrated_path = os.path.join(output_dir, "migrated.jsonl")
    queries_path = os.path.join(input_dir, "queries.json")
    if not (os.path.isfile(results_path) and os.path.isfile(queries_path)):
        return False
    qmap = load_search_results(results_path)
    queries = extract_queries(queries_path)
    if qmap is None or queries is None:
        return False
    # Load docs content to check for doc presence requirement
    docs_paths = list_docs(input_dir)
    docs_texts = aggregate_docs_text(docs_paths)
    # For project restriction and score we only need to validate results structure and sorting
    all_ok = True
    for qobj in queries:
        qtext = qobj.get("query")
        proj = qobj.get("project")
        if qtext not in qmap:
            all_ok = False
            continue
        results = qmap[qtext]
        if not isinstance(results, list) or len(results) != 3:
            all_ok = False
            continue
        # Sorting check by keyword score over result text/snippet
        scores = [score_occurrences(qtext, get_result_text_for_scoring(r)) for r in results]
        if scores != sorted(scores, reverse=True):
            all_ok = False
        # Project restriction if provided
        if proj:
            for r in results:
                if result_project(r) != proj:
                    all_ok = False
                    break
        # Doc presence: if the term appears in any docs content, ensure at least one result is doc_chunk
        appears_in_docs = any(score_occurrences(qtext, t) > 0 for t in docs_texts.values())
        if appears_in_docs:
            if not any((result_source_type(r) == "doc_chunk") for r in results):
                all_ok = False
    return all_ok

def check_setup_summary(input_dir, output_dir):
    path = os.path.join(output_dir, "setup_summary.txt")
    if not os.path.isfile(path):
        return False
    txt = read_file_text(path)
    if not single_sentence(txt):
        return False
    # Evaluate content requirements
    # Search quality descriptor: local model / keyword-only / openai
    providers = parse_providers_yaml(os.path.join(input_dir, "providers.yaml"))
    expected_chain, expected_note = compute_expected_chain(providers)
    lc = txt.lower()
    if expected_chain == ["bm25"]:
        if "keyword" not in lc:
            return False
    else:
        if expected_chain and expected_chain[0] == "openai":
            if "openai" not in lc:
                return False
        else:
            if "local" not in lc:
                return False
    # Migration status: X entries imported or fresh start
    mig_path = os.path.join(output_dir, "migrated.jsonl")
    migrated_items = read_jsonl(mig_path) if os.path.isfile(mig_path) else []
    count = len(migrated_items) if migrated_items is not None else 0
    if count > 0:
        # Must mention the number and "imported"
        if ("import" not in lc) or (str(count) not in txt):
            return False
    else:
        if "fresh start" not in lc:
            return False
    # Projects status: configured / not used
    projects = parse_projects_yaml(os.path.join(input_dir, "projects.yaml"))
    projects_created = read_json(os.path.join(output_dir, "projects_created.json")) or []
    # Determine configured if any project present in output list
    configured = False
    if isinstance(projects_created, list):
        configured = len(projects_created) > 0
    elif isinstance(projects_created, dict) and "projects" in projects_created and isinstance(projects_created["projects"], list):
        configured = len(projects_created["projects"]) > 0
    elif isinstance(projects_created, dict):
        configured = len(projects_created.keys()) > 0
    # Evaluate sentence contains correct phrase
    if configured:
        if "configured" not in lc:
            return False
    else:
        if "not used" not in lc:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    checks = {
        "config_ok": False,
        "heartbeat_ok": False,
        "migrated_ok": False,
        "migration_report_ok": False,
        "projects_created_ok": False,
        "ingested_index_ok": False,
        "search_results_ok": False,
        "setup_summary_ok": False,
    }

    # Initialize all to False (no vacuous pass). Only set True after positive verification.
    try:
        if os.path.isdir(output_dir):
            if check_config(input_dir, output_dir):
                checks["config_ok"] = True
            if check_heartbeat(output_dir):
                checks["heartbeat_ok"] = True
            if check_migration(input_dir, output_dir):
                checks["migrated_ok"] = True
            if check_migration_report(input_dir, output_dir):
                checks["migration_report_ok"] = True
            if check_projects_created(input_dir, output_dir):
                checks["projects_created_ok"] = True
            if check_ingested_index(input_dir, output_dir):
                checks["ingested_index_ok"] = True
            if check_search_results(input_dir, output_dir):
                checks["search_results_ok"] = True
            if check_setup_summary(input_dir, output_dir):
                checks["setup_summary_ok"] = True
    except Exception:
        # Do not raise; keep checks as is
        pass

    total = 8
    passed = sum(1 for k, v in checks.items() if v)
    reward = passed / total if total > 0 else 0.0
    # No-op baseline: if output missing or nothing produced, ensure reward 0.0 (already achieved since checks False)
    final = {"reward": round(reward, 6)}
    final.update(checks)
    print(json.dumps(final))

if __name__ == "__main__":
    main()