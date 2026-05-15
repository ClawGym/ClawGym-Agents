import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def list_input_swift_files(input_dir):
    files = []
    if not os.path.isdir(input_dir):
        return files
    for name in os.listdir(input_dir):
        if name.endswith(".swift.txt"):
            files.append(os.path.join(input_dir, name))
    files.sort()
    return files

def count_try_bang(text):
    return text.count("try!")

def count_iuo_and_force_unwraps(lines):
    iuo_pattern = re.compile(r":\s*[^,=)]+!\b")
    iuo_decls = 0
    force_unwraps = 0
    for line in lines:
        # Count IUO occurrences
        iuo_matches = list(iuo_pattern.finditer(line))
        iuo_decls += len(iuo_matches)
        # Prepare for force unwrap count: remove IUO '!' characters specifically
        def _remove_bang_in_match(m):
            seg = m.group(0)
            return seg.replace("!", "")  # strip the '!' for IUO segments
        processed = iuo_pattern.sub(_remove_bang_in_match, line)
        # Remove '!='
        processed = processed.replace("!=", "")
        # Remove 'try!'
        processed = processed.replace("try!", "")
        # Count remaining '!' characters
        force_unwraps += processed.count("!")
    return iuo_decls, force_unwraps

def find_empty_catch_blocks(text):
    # Find catch { ... } blocks and test if empty (whitespace/comments only)
    count = 0
    i = 0
    n = len(text)
    while True:
        idx = text.find("catch", i)
        if idx == -1:
            break
        # Find next '{' after 'catch'
        bidx = text.find("{", idx)
        if bidx == -1:
            i = idx + 5
            continue
        # Scan to matching '}' with brace counting
        depth = 0
        body_start = None
        j = bidx
        while j < n:
            ch = text[j]
            if ch == "{":
                depth += 1
                if depth == 1:
                    body_start = j + 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    body_end = j
                    # Extract body
                    body = text[body_start:body_end]
                    # Remove single-line comments
                    body = re.sub(r"//.*", "", body)
                    # Remove block comments
                    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
                    # Remove whitespace
                    if body.strip() == "":
                        count += 1
                    j += 1
                    break
            j += 1
        i = idx + 5
    return count

def count_weak_delegate_missing(lines):
    count = 0
    pattern = re.compile(r"\bvar\s+\w*delegate\w*\s*:")
    for line in lines:
        if pattern.search(line) and ("weak" not in line):
            count += 1
    return count

def find_closure_suspects(lines):
    # Heuristic: line with "=\s*{" starts a closure assigned to a property; if within that closure we see 'self'
    # and no [weak self] in same or previous line, count as suspect.
    count = 0
    n = len(lines)
    for i, line in enumerate(lines):
        if re.search(r"=\s*\{", line):
            has_weak = ("[weak self]" in line)
            # check previous non-empty line for capture list
            if not has_weak:
                prev = i - 1
                while prev >= 0 and lines[prev].strip() == "":
                    prev -= 1
                if prev >= 0 and "[weak self]" in lines[prev]:
                    has_weak = True
            if has_weak:
                continue
            # scan closure body to see if 'self' used
            # find starting '{' position in current line
            start_idx_in_line = line.find("{")
            depth = 0
            seen_self = False
            # process characters starting from that '{'
            # Join subsequent lines to simplify scanning while tracking boundaries
            j = i
            k = start_idx_in_line
            while j < n:
                scan_line = lines[j]
                while k < len(scan_line):
                    ch = scan_line[k]
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            # end closure
                            k += 1
                            break
                    # quick scan for 'self'
                    # Only check when inside closure
                    if depth > 0:
                        # naive check for 'self'
                        if scan_line[k:k+4] == "self":
                            seen_self = True
                    k += 1
                if depth == 0:
                    break
                j += 1
                k = 0
            if seen_self and not has_weak:
                count += 1
    return count

def count_sequential_await_opportunities(lines):
    # Heuristic: two or more 'await' lines within 6 lines, and no 'async let' or 'TaskGroup' between them.
    await_indices = [i for i, l in enumerate(lines) if "await" in l]
    if not await_indices:
        return 0
    count = 0
    # group clusters
    idx = 0
    while idx < len(await_indices):
        cluster = [await_indices[idx]]
        idx2 = idx + 1
        while idx2 < len(await_indices) and (await_indices[idx2] - await_indices[idx2 - 1] <= 6):
            cluster.append(await_indices[idx2])
            idx2 += 1
        # check if cluster has >=2 and span has no async let or TaskGroup
        if len(cluster) >= 2:
            span_start = cluster[0]
            span_end = cluster[-1]
            span_text = "\n".join(lines[span_start:span_end + 1])
            if ("async let" not in span_text) and ("TaskGroup" not in span_text):
                count += 1
        idx = idx2
    return count

def find_actor_scopes(lines):
    # returns list of (start_line_idx, end_line_idx) for actor blocks
    scopes = []
    i = 0
    n = len(lines)
    while i < n:
        if "actor " in lines[i]:
            # find next '{' from here
            j = i
            # possibly the '{' is on same or later line
            found_brace = False
            while j < n:
                if "{" in lines[j]:
                    brace_line = j
                    brace_pos = lines[j].find("{")
                    found_brace = True
                    break
                j += 1
            if not found_brace:
                i += 1
                continue
            depth = 0
            end_idx = None
            # scan from brace_line to find matching '}'
            for k in range(brace_line, n):
                for ch in lines[k]:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end_idx = k
                            break
                if end_idx is not None:
                    break
            if end_idx is not None:
                scopes.append((brace_line, end_idx))
                i = end_idx + 1
                continue
        i += 1
    return scopes

def extract_actor_properties(lines, start, end):
    props = set()
    prop_pattern = re.compile(r"\b(var|let)\s+([A-Za-z_]\w*)")
    for i in range(start, end + 1):
        line = lines[i]
        # skip function declarations
        if "func " in line:
            continue
        m = prop_pattern.search(line)
        if m:
            name = m.group(2)
            # avoid keywords
            if name not in {"var", "let"}:
                props.add(name)
    return props

def count_actor_reentrancy_risks(lines):
    risk = 0
    scopes = find_actor_scopes(lines)
    for (s, e) in scopes:
        props = extract_actor_properties(lines, s, e)
        # scan within scope for guard/if referencing a property then await then assignment to same
        i = s
        while i <= e:
            line = lines[i]
            if ("guard" in line or "if " in line) and any(re.search(r"\b" + re.escape(p) + r"\b", line) for p in props):
                # identify which prop referenced
                referenced = [p for p in props if re.search(r"\b" + re.escape(p) + r"\b", line)]
                # look for 'await' within next 10 lines
                await_line = None
                for j in range(i + 1, min(i + 11, e + 1)):
                    if "await" in lines[j]:
                        await_line = j
                        break
                if await_line is not None:
                    # look for assignment to same property within next 10 lines after await
                    for p in referenced:
                        assign_pat = re.compile(r"\b" + re.escape(p) + r"\b\s*([\+\-\*/]?=)")
                        for k in range(await_line + 1, min(await_line + 11, e + 1)):
                            if assign_pat.search(lines[k]):
                                risk += 1
                                # once counted for this pattern, move forward
                                break
                # move forward
            i += 1
    return risk

def count_missing_sendable_or_unchecked(lines):
    count = 0
    sendable_indices = [i for i, l in enumerate(lines) if "Sendable" in l]
    for idx in sendable_indices:
        if "@unchecked" in lines[idx]:
            count += 1
        else:
            # look for synchronization hints within ±3 lines
            low = max(0, idx - 3)
            high = min(len(lines) - 1, idx + 3)
            window = "\n".join(lines[low:high + 1])
            if not re.search(r"\b(lock|NSLock|DispatchQueue|queue|atomic|OSAllocatedUnfairLock|ManagedCriticalSection)\b", window):
                count += 1
    if not sendable_indices:
        # if boundaries mentioned but no Sendable
        has_boundary = any(("nonisolated" in l) or ("@MainActor" in l) for l in lines)
        if has_boundary:
            count += 1
    return count

def count_observation_issues(lines):
    count = 0
    file_text = "\n".join(lines)
    has_bindable = "@Bindable" in file_text
    # A) two-way binding without @Bindable
    for i, l in enumerate(lines):
        if re.search(r"\$\w+", l):
            if not has_bindable:
                count += 1
    # B) @State over custom type
    state_custom_type_pat = re.compile(r"@State\s+var\s+\w+\s*:\s*[A-Z]\w+")
    state_custom_init_pat = re.compile(r"@State\s+var\s+\w+\s*=\s*[A-Z]\w+\(")
    for l in lines:
        if state_custom_type_pat.search(l) or state_custom_init_pat.search(l):
            count += 1
    # C) Nested observable types not marked @Observable
    if "@Observable" in file_text:
        # find properties of type [Type] or Type
        for l in lines:
            m = re.search(r"\bvar\s+\w+\s*:\s*(\[[A-Z][A-Za-z0-9_]+\]|[A-Z][A-Za-z0-9_]+)", l)
            if m:
                type_name = m.group(1).strip("[]")
                if f"@Observable class {type_name}" not in file_text and f"@Observable struct {type_name}" not in file_text:
                    count += 1
    return count

def compute_counts_for_file(path):
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    counts = {
        "try_bang_count": 0,
        "force_unwrap_count": 0,
        "iuo_declarations": 0,
        "empty_catch_blocks": 0,
        "weak_delegate_missing": 0,
        "retain_cycle_closure_suspects": 0,
        "sequential_await_opportunities": 0,
        "actor_reentrancy_risks": 0,
        "missing_sendable_or_unchecked": 0,
        "observation_issues": 0,
    }
    counts["try_bang_count"] = count_try_bang(text)
    iuo_decls, force_unwraps = count_iuo_and_force_unwraps(lines)
    counts["iuo_declarations"] = iuo_decls
    counts["force_unwrap_count"] = force_unwraps
    counts["empty_catch_blocks"] = find_empty_catch_blocks(text)
    counts["weak_delegate_missing"] = count_weak_delegate_missing(lines)
    counts["retain_cycle_closure_suspects"] = find_closure_suspects(lines)
    counts["sequential_await_opportunities"] = count_sequential_await_opportunities(lines)
    counts["actor_reentrancy_risks"] = count_actor_reentrancy_risks(lines)
    counts["missing_sendable_or_unchecked"] = count_missing_sendable_or_unchecked(lines)
    counts["observation_issues"] = count_observation_issues(lines)
    return counts

def sum_counts(files_counts):
    totals = {
        "try_bang_count": 0,
        "force_unwrap_count": 0,
        "iuo_declarations": 0,
        "empty_catch_blocks": 0,
        "weak_delegate_missing": 0,
        "retain_cycle_closure_suspects": 0,
        "sequential_await_opportunities": 0,
        "actor_reentrancy_risks": 0,
        "missing_sendable_or_unchecked": 0,
        "observation_issues": 0,
    }
    for c in files_counts.values():
        for k in totals.keys():
            totals[k] += int(c.get(k, 0))
    return totals

def parse_markdown_sections(md):
    # Return dict of heading(lowercased) -> section text until next heading
    sections = {}
    lines = md.splitlines()
    indices = []
    for i, l in enumerate(lines):
        m = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", l)
        if m:
            indices.append((i, m.group(1).strip()))
    for idx, (line_no, title) in enumerate(indices):
        start = line_no + 1
        end = indices[idx + 1][0] if idx + 1 < len(indices) else len(lines)
        sections[title.lower()] = "\n".join(lines[start:end]).strip()
    return sections

def validate_review_md(review_path, input_file_paths):
    checks = {
        "has_review_md": False,
        "review_has_headings": False,
        "review_lists_files": False,
        "review_has_async_let": False,
        "review_has_references": False,
    }
    content = read_text(review_path)
    if content is None:
        return checks
    checks["has_review_md"] = True
    sections = parse_markdown_sections(content)
    required_headings = ["overview", "files reviewed", "checklist", "findings", "recommendations", "references"]
    if all(h in sections for h in required_headings):
        checks["review_has_headings"] = True
    # Files Reviewed section contains each file name
    files_reviewed_block = sections.get("files reviewed", "")
    file_basenames = [os.path.basename(p) for p in input_file_paths]
    if files_reviewed_block:
        if all(name in files_reviewed_block for name in file_basenames):
            checks["review_lists_files"] = True
    # async let substring anywhere
    if "async let" in content:
        checks["review_has_async_let"] = True
    # References must mention specific file names by name
    refs_block = sections.get("references", "")
    required_refs = ["concurrency.md", "error-handling.md", "common-mistakes.md", "observable.md"]
    if refs_block and all(ref in refs_block for ref in required_refs):
        checks["review_has_references"] = True
    return checks

def validate_risk_summary(risk_path, input_file_paths, ground_truth_counts):
    checks = {
        "risk_json_exists": False,
        "risk_json_valid": False,
        "risk_json_has_keys": False,
        "risk_json_files_has_all": False,
        "risk_per_file_match_ground_truth": False,
        "risk_totals_match_sum": False,
        "risk_totals_match_ground_truth": False,
    }
    text = read_text(risk_path)
    if text is None:
        return checks
    checks["risk_json_exists"] = True
    try:
        data = json.loads(text)
        checks["risk_json_valid"] = True
    except Exception:
        return checks
    required_keys = [
        "try_bang_count",
        "force_unwrap_count",
        "iuo_declarations",
        "empty_catch_blocks",
        "weak_delegate_missing",
        "retain_cycle_closure_suspects",
        "sequential_await_opportunities",
        "actor_reentrancy_risks",
        "missing_sendable_or_unchecked",
        "observation_issues",
        "files",
    ]
    if all(k in data for k in required_keys):
        # Verify types are ints for top-level counts
        top_ok = True
        for k in required_keys:
            if k == "files":
                continue
            if not isinstance(data.get(k), int):
                top_ok = False
                break
        if top_ok and isinstance(data.get("files"), dict):
            checks["risk_json_has_keys"] = True
    # files mapping contains all input files
    files_map = data.get("files") if isinstance(data.get("files"), dict) else {}
    if files_map:
        input_keys = ["input/" + os.path.basename(p) for p in input_file_paths]
        if all(k in files_map for k in input_keys):
            # verify per-file objects have keys and int values
            perfile_ok = True
            for k in input_keys:
                obj = files_map.get(k, {})
                for kk in required_keys:
                    if kk == "files":
                        continue
                    if kk not in obj or not isinstance(obj.get(kk), int):
                        perfile_ok = False
                        break
                if not perfile_ok:
                    break
            if perfile_ok:
                checks["risk_json_files_has_all"] = True
    # Compare per-file counts with ground truth
    perfile_match = True
    for p in input_file_paths:
        key = "input/" + os.path.basename(p)
        gt = ground_truth_counts.get(p, {})
        reported = files_map.get(key, {})
        for kk in [
            "try_bang_count",
            "force_unwrap_count",
            "iuo_declarations",
            "empty_catch_blocks",
            "weak_delegate_missing",
            "retain_cycle_closure_suspects",
            "sequential_await_opportunities",
            "actor_reentrancy_risks",
            "missing_sendable_or_unchecked",
            "observation_issues",
        ]:
            if kk not in reported or int(reported.get(kk)) != int(gt.get(kk, 0)):
                perfile_match = False
                break
        if not perfile_match:
            break
    if perfile_match and checks["risk_json_files_has_all"]:
        checks["risk_per_file_match_ground_truth"] = True
    # Top-level totals vs sum of per-file map
    if checks["risk_json_has_keys"] and checks["risk_json_files_has_all"]:
        sum_totals = {k: 0 for k in [
            "try_bang_count",
            "force_unwrap_count",
            "iuo_declarations",
            "empty_catch_blocks",
            "weak_delegate_missing",
            "retain_cycle_closure_suspects",
            "sequential_await_opportunities",
            "actor_reentrancy_risks",
            "missing_sendable_or_unchecked",
            "observation_issues",
        ]}
        for fname, obj in files_map.items():
            for k in sum_totals.keys():
                if isinstance(obj, dict) and isinstance(obj.get(k), int):
                    sum_totals[k] += obj.get(k)
        totals_match = all(int(data.get(k, -9999)) == sum_totals[k] for k in sum_totals.keys())
        if totals_match:
            checks["risk_totals_match_sum"] = True
    # Totals equal ground truth sums
    gt_sum = sum_counts(ground_truth_counts)
    gt_match = True
    for k, v in gt_sum.items():
        if int(data.get(k, -9999)) != int(v):
            gt_match = False
            break
    if gt_match:
        checks["risk_totals_match_ground_truth"] = True
    return checks

def validate_checklist_csv(path):
    checks = {
        "checklist_exists": False,
        "checklist_header_valid": False,
        "checklist_has_11_rows": False,
        "checklist_covers_all_items": False,
        "checklist_status_values_valid": False,
    }
    txt = read_text(path)
    if txt is None:
        return checks
    checks["checklist_exists"] = True
    lines = [l for l in txt.splitlines() if l.strip() != ""]
    if not lines:
        return checks
    header = lines[0].strip()
    if header == "item,status,notes":
        checks["checklist_header_valid"] = True
    rows = lines[1:]
    if len(rows) == 11:
        checks["checklist_has_11_rows"] = True
    # Validate coverage of required items
    required_items = [
        "No force unwraps on runtime data",
        "Closures stored as properties use [weak self]",
        "Delegate properties are weak",
        "Independent async operations use async let or TaskGroup",
        "Long-running Tasks check Task.isCancelled",
        "Actors have mutable state to protect",
        "Sendable types are truly thread-safe (beware @unchecked)",
        "Errors handled explicitly (no empty catch blocks)",
        "Custom errors conform to LocalizedError",
        "Nested @Observable objects are also marked @Observable",
        "@Bindable used for two-way bindings",
    ]
    items_ok = True
    statuses_ok = True
    allowed_status = {"PASS", "FAIL", "N/A"}
    found = [False] * len(required_items)
    for row in rows:
        parts = row.split(",", 2)
        if len(parts) != 3:
            items_ok = False
            break
        item = parts[0].strip()
        status = parts[1].strip()
        if status not in allowed_status:
            statuses_ok = False
        for idx, req in enumerate(required_items):
            if req.lower() in item.lower():
                found[idx] = True
    if all(found):
        checks["checklist_covers_all_items"] = True
    if statuses_ok:
        checks["checklist_status_values_valid"] = True
    return checks

def validate_patches_jsonl(path, input_file_paths):
    checks = {
        "patches_exists": False,
        "patches_min_count": False,
        "patches_lines_valid": False,
    }
    txt = read_text(path)
    if txt is None:
        return checks
    checks["patches_exists"] = True
    lines = [l for l in txt.splitlines() if l.strip() != ""]
    if len(lines) >= 8:
        checks["patches_min_count"] = True
    valid_files = set("input/" + os.path.basename(p) for p in input_file_paths)
    all_valid = True
    for l in lines:
        try:
            obj = json.loads(l)
        except Exception:
            all_valid = False
            break
        required_keys = ["file", "line", "issue", "before", "after", "rationale"]
        if not all(k in obj for k in required_keys):
            all_valid = False
            break
        if obj["file"] not in valid_files:
            all_valid = False
            break
        if not isinstance(obj["line"], int) or obj["line"] <= 0:
            all_valid = False
            break
        if not (isinstance(obj["issue"], str) and obj["issue"].strip()):
            all_valid = False
            break
        for text_key in ["before", "after", "rationale"]:
            if not (isinstance(obj[text_key], str) and obj[text_key].strip()):
                all_valid = False
                break
        if not all_valid:
            break
    if all_valid and lines:
        checks["patches_lines_valid"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Collect input swift files
    input_files = list_input_swift_files(input_dir)

    # Compute ground truth counts per file
    ground_truth = {}
    for p in input_files:
        counts = compute_counts_for_file(p)
        if counts is None:
            continue
        ground_truth[p] = counts

    # Validate outputs
    review_checks = validate_review_md(os.path.join(output_dir, "review.md"), input_files)
    risk_checks = validate_risk_summary(os.path.join(output_dir, "risk_summary.json"), input_files, ground_truth)
    checklist_checks = validate_checklist_csv(os.path.join(output_dir, "checklist.csv"))
    patches_checks = validate_patches_jsonl(os.path.join(output_dir, "patches.jsonl"), input_files)

    # Aggregate checks
    checks = {}
    checks.update(review_checks)
    checks.update(risk_checks)
    checks.update(checklist_checks)
    checks.update(patches_checks)

    # Compute reward as fraction of passed checks
    # Ensure baseline no-op yields 0.0 (all checks depend on outputs)
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update({k: bool(v) for k, v in checks.items()})
    print(json.dumps(result))

if __name__ == "__main__":
    main()