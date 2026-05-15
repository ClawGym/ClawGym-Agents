import json
import os
import re
import sys

def build_path(*parts):
    return os.path.join(*parts)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def list_md_files(directory):
    try:
        return [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f)) and f.endswith(".md")]
    except Exception:
        return []

def safe_json_load(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None

def find_single_md_file_path(directory):
    files = list_md_files(directory)
    if len(files) == 1:
        return os.path.join(directory, files[0])
    return None

def extract_candidate_tokens(text, min_len=4, max_tokens=20):
    # Remove markdown formatting and simple punctuation
    # Extract alpha-numeric words, avoid typical stopwords and secret-like tokens
    stopwords = {
        "the","and","that","with","this","from","into","your","have","been","will","they","them","for","you","are",
        "was","were","what","when","where","why","how","then","else","about","more","less","just","only","also",
        "task","goal","note","context","memory","event","events","reminders","recent","history","current","session",
        "user","profile","long","term","sensory","working","conversational","episodic","system","profile","data",
        "date","time","today","tomorrow","yesterday","todo","list","summary","summarize","summary","location","weather",
        "utc","gmt","am","pm","mon","tue","wed","thu","fri","sat","sun"
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{%d,}" % (min_len-1), text)
    candidates = []
    seen = set()
    secret_pat = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
    keyname_pat = re.compile(r"(?i)\b(api|access|secret|private)[_-]?key\b|\bsecret[_-]?token\b")
    for t in tokens:
        tl = t.lower()
        if tl in seen:
            continue
        if tl in stopwords:
            continue
        if secret_pat.search(t):
            continue
        if keyname_pat.search(t):
            continue
        seen.add(tl)
        candidates.append(t)
        if len(candidates) >= max_tokens:
            break
    return candidates

def contains_any_fragment(haystack, fragments):
    h = haystack.lower()
    for frag in fragments:
        if frag and frag.lower() in h:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = build_path(workspace_root, "input")
    output_dir = build_path(workspace_root, "output")
    memory_dir = build_path(output_dir, "memory")

    # Initialize checks dict with all checks set to False
    checks = {
        "dir_long_term_exists": False,
        "dir_episodic_exists": False,
        "dir_sensory_exists": False,
        "dir_conversational_exists": False,
        "dir_working_exists": False,

        "one_md_long_term": False,
        "one_md_episodic": False,
        "one_md_sensory": False,
        "one_md_conversational": False,
        "one_md_working": False,

        "context_exists": False,
        "context_wrapper_single": False,
        "context_security_notice": False,
        "context_headings_ordered": False,
        "redaction_no_unredacted_keys": False,
        "redaction_key_values_masked": False,
        "includes_long_term_fragment": False,
        "includes_episodic_fragment": False,
        "includes_sensory_fragment": False,
        "includes_convo_fragment": False,
        "includes_working_fragment": False,
        "context_length_ok": False,

        "stats_json_valid": False,
        "stats_keys_exact": False,
        "stats_file_count_ok": False,
        "stats_char_count_positive": False,

        "mapping_json_valid": False,
        "mapping_keys_exact": False,
        "mapping_paths_correct": False,
    }

    # Layer directories
    layer_dirs = {
        "long-term": build_path(memory_dir, "long-term"),
        "episodic": build_path(memory_dir, "episodic"),
        "sensory": build_path(memory_dir, "sensory"),
        "conversational": build_path(memory_dir, "conversational"),
        "working": build_path(memory_dir, "working"),
    }

    # Check directories exist
    for lname, lpath in layer_dirs.items():
        if os.path.isdir(lpath):
            checks[f"dir_{lname.replace('-', '_')}_exists"] = True

    # Check exactly one .md file exists in each layer
    layer_md_paths = {}
    for lname, lpath in layer_dirs.items():
        if os.path.isdir(lpath):
            md_files = list_md_files(lpath)
            if len(md_files) == 1:
                checks[f"one_md_{lname.replace('-', '_')}"] = True
                layer_md_paths[lname] = os.path.join(lpath, md_files[0])

    # Context file checks
    context_path = build_path(output_dir, "context.txt")
    context_content = ""
    if os.path.isfile(context_path):
        checks["context_exists"] = True
        context_content = read_text(context_path)

        # Exactly one opening and one closing tag
        open_count = context_content.count("<mmag_memory_context>")
        close_count = context_content.count("</mmag_memory_context>")
        if open_count == 1 and close_count == 1:
            checks["context_wrapper_single"] = True

        # Security notice presence
        if "SECURITY NOTICE FOR AGENT" in context_content:
            checks["context_security_notice"] = True

        # Headings order
        headings = [
            "### LONG-TERM USER PROFILE [system]",
            "### EPISODIC MEMORY — Events & Reminders",
            "### SENSORY CONTEXT — Environment",
            "### CONVERSATIONAL HISTORY",
            "### WORKING MEMORY — Current Session",
        ]
        positions = [context_content.find(h) for h in headings]
        if all(p >= 0 for p in positions) and positions == sorted(positions):
            checks["context_headings_ordered"] = True

        # Redaction rule a: no unredacted tokens like sk-<...>
        secret_token_re = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
        if secret_token_re.search(context_content) is None:
            checks["redaction_no_unredacted_keys"] = True

        # Redaction rule b: key-value masking for key names with : or =
        # Ensure that any line with key name has first value token as [REDACTED]
        masked_ok = True
        keyvalue_re = re.compile(r"(?i)\b(api[_-]?key|access[_-]?key|secret[_-]?key|private[_-]?key|secret[_-]?token)\s*[:=]\s*(.+)")
        for line in context_content.splitlines():
            m = keyvalue_re.search(line)
            if m:
                rhs = m.group(2).strip()
                # Take the first token on RHS
                m2 = re.match(r"(\[REDACTED\])", rhs)
                if not m2:
                    masked_ok = False
                    break
        if masked_ok:
            checks["redaction_key_values_masked"] = True

        # Context length <= 2000 or ends with ... [TRUNCATED]
        if len(context_content) <= 2000 or context_content.rstrip().endswith("... [TRUNCATED]"):
            checks["context_length_ok"] = True

    # Representative content checks
    # Load input files (if present)
    input_files = {
        "long_term.txt": build_path(input_dir, "long_term.txt"),
        "episodic.csv": build_path(input_dir, "episodic.csv"),
        "sensory.yaml": build_path(input_dir, "sensory.yaml"),
        "convo.md": build_path(input_dir, "convo.md"),
        "working.txt": build_path(input_dir, "working.txt"),
    }

    # Check presence of fragments from inputs in context
    if checks["context_exists"]:
        # Long-term
        lt_text = read_text(input_files["long_term.txt"])
        lt_tokens = extract_candidate_tokens(lt_text, min_len=4, max_tokens=20)
        if lt_tokens and contains_any_fragment(context_content, lt_tokens):
            checks["includes_long_term_fragment"] = True

        # Episodic
        epi_text = read_text(input_files["episodic.csv"])
        # Try to include some non-date tokens
        epi_tokens = extract_candidate_tokens(epi_text, min_len=4, max_tokens=20)
        if epi_tokens and contains_any_fragment(context_content, epi_tokens):
            checks["includes_episodic_fragment"] = True

        # Sensory
        sens_text = read_text(input_files["sensory.yaml"])
        sens_tokens = extract_candidate_tokens(sens_text, min_len=4, max_tokens=20)
        if sens_tokens and contains_any_fragment(context_content, sens_tokens):
            checks["includes_sensory_fragment"] = True

        # Conversational
        convo_text = read_text(input_files["convo.md"])
        convo_tokens = extract_candidate_tokens(convo_text, min_len=4, max_tokens=20)
        if convo_tokens and contains_any_fragment(context_content, convo_tokens):
            checks["includes_convo_fragment"] = True

        # Working
        working_text = read_text(input_files["working.txt"])
        working_tokens = extract_candidate_tokens(working_text, min_len=4, max_tokens=20)
        if working_tokens and contains_any_fragment(context_content, working_tokens):
            checks["includes_working_fragment"] = True

    # Stats.json checks
    stats_path = build_path(output_dir, "stats.json")
    stats_obj = safe_json_load(stats_path)
    if isinstance(stats_obj, dict):
        checks["stats_json_valid"] = True
        expected_stats_keys = {"long-term", "episodic", "sensory", "conversational", "working"}
        if set(stats_obj.keys()) == expected_stats_keys:
            checks["stats_keys_exact"] = True

            # File count must be 1 for each, and char_count positive integer
            file_counts_ok = True
            char_counts_pos = True
            for lname in ["long-term", "episodic", "sensory", "conversational", "working"]:
                entry = stats_obj.get(lname)
                if not isinstance(entry, dict):
                    file_counts_ok = False
                    char_counts_pos = False
                    break
                fc = entry.get("file_count", None)
                cc = entry.get("char_count", None)
                # Check file_count exactly 1
                if fc != 1:
                    file_counts_ok = False
                # Check char_count is a positive integer
                if not isinstance(cc, int) or cc <= 0:
                    char_counts_pos = False
            if file_counts_ok:
                checks["stats_file_count_ok"] = True
            if char_counts_pos:
                checks["stats_char_count_positive"] = True

    # Mapping.json checks
    mapping_path = build_path(output_dir, "mapping.json")
    mapping_obj = safe_json_load(mapping_path)
    if isinstance(mapping_obj, dict):
        checks["mapping_json_valid"] = True
        expected_mapping_keys = {"long_term.txt", "episodic.csv", "sensory.yaml", "convo.md", "working.txt"}
        if set(mapping_obj.keys()) == expected_mapping_keys:
            checks["mapping_keys_exact"] = True

            # Validate mapped paths exist, end with .md, and reside in correct layer directory
            expected_layer_for_input = {
                "long_term.txt": "long-term",
                "episodic.csv": "episodic",
                "sensory.yaml": "sensory",
                "convo.md": "conversational",
                "working.txt": "working",
            }
            paths_ok = True
            for in_name, out_rel in mapping_obj.items():
                # out_rel can be relative to output_dir; make absolute to check
                out_abs = out_rel
                if not os.path.isabs(out_abs):
                    out_abs = build_path(output_dir, out_rel.lstrip("/"))
                # It must exist and be an .md under the right layer directory
                if not (os.path.isfile(out_abs) and out_abs.endswith(".md")):
                    paths_ok = False
                    break
                expected_layer = expected_layer_for_input[in_name]
                expected_dir = build_path(memory_dir, expected_layer)
                # Normalize paths
                try:
                    out_abs_norm = os.path.realpath(out_abs)
                    expected_dir_norm = os.path.realpath(expected_dir)
                    if not out_abs_norm.startswith(expected_dir_norm + os.sep):
                        paths_ok = False
                        break
                except Exception:
                    paths_ok = False
                    break
            if paths_ok:
                checks["mapping_paths_correct"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # No-op baseline: if output dir missing or empty key artifacts, many checks false -> reward 0.0; enforce exact zero if nothing relevant exists
    # If no output dir or no memory dir and no context/stats/mapping, force 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        # If there are no required files at all, force 0.0
        required_any = any([
            checks["dir_long_term_exists"],
            checks["dir_episodic_exists"],
            checks["dir_sensory_exists"],
            checks["dir_conversational_exists"],
            checks["dir_working_exists"],
            checks["context_exists"],
            os.path.isfile(stats_path),
            os.path.isfile(mapping_path),
        ])
        if not required_any:
            reward = 0.0

    # Print single JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()