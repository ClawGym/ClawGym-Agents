import json
import os
import sys
import hashlib
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")

def compress_blank_lines(text: str) -> str:
    # Collapse runs of 2+ blank lines into a single blank line; do not alter non-blank lines
    text = normalize_newlines(text)
    lines = text.split("\n")
    out_lines = []
    prev_blank = False
    for line in lines:
        if line.strip() == "":
            if not prev_blank:
                out_lines.append("")
                prev_blank = True
            else:
                # skip additional blank lines
                continue
        else:
            out_lines.append(line)
            prev_blank = False
    return "\n".join(out_lines)

def extract_anchors_from_log(text: str) -> list:
    text = normalize_newlines(text)
    anchors = []
    for line in text.split("\n"):
        if "[ANCHOR]" in line:
            anchors.append(line.replace("[ANCHOR]", "").strip())
    return anchors

def compute_expected_anchor_blocks(input_anchors_content: str, logs_by_date: dict) -> list:
    # Deduplicate based on first 40 chars existing anywhere in anchors content
    current_content = input_anchors_content if input_anchors_content is not None else ""
    expected_blocks = []
    for date in sorted(logs_by_date.keys()):
        for anchor_text in logs_by_date[date]:
            first40 = anchor_text[:40]
            if first40 and first40 in current_content:
                continue
            block = f"### {date} | Auto-promoted | {anchor_text}\nStatus: Active\n"
            expected_blocks.append(block)
            current_content += block
    return expected_blocks

def parse_appended_blocks_for_dates(anchors_content: str, dates: set) -> list:
    # Find appended blocks for specified dates in content: exact two-line blocks
    anchors_content = normalize_newlines(anchors_content)
    lines = anchors_content.split("\n")
    blocks = []
    for i in range(len(lines) - 1):
        line = lines[i]
        next_line = lines[i+1]
        # Match "### YYYY-MM-DD | Auto-promoted | ..."
        m = re.match(r"^### (\d{4}-\d{2}-\d{2}) \| Auto-promoted \| (.*)$", line)
        if m and next_line == "Status: Active":
            date = m.group(1)
            if date in dates:
                anchor_text = m.group(2)
                block = f"### {date} | Auto-promoted | {anchor_text}\nStatus: Active\n"
                blocks.append(block)
    return blocks

def chunk_text(text: str, source: str, chunk_size=400, chunk_overlap=80):
    text = normalize_newlines(text)
    lines = text.split("\n")
    chunks = []
    current = []
    current_len = 0
    section = "general"
    for line in lines:
        if line.startswith("## ") or line.startswith("### "):
            section = line.lstrip("#").strip()
        current.append(line)
        current_len += len(line) + 1
        if current_len >= chunk_size:
            ct = "\n".join(current)
            chunk_id = hashlib.md5(ct.encode("utf-8")).hexdigest()[:8]
            chunks.append({"text": ct, "source": source, "section": section, "chunk_id": chunk_id})
            # build overlap
            overlap = []
            olen = 0
            for l in reversed(current):
                olen += len(l) + 1
                overlap.insert(0, l)
                if olen >= chunk_overlap:
                    break
            current = overlap
            current_len = olen
    if current:
        ct = "\n".join(current)
        if ct != "":
            chunk_id = hashlib.md5(ct.encode("utf-8")).hexdigest()[:8]
            chunks.append({"text": ct, "source": source, "section": section, "chunk_id": chunk_id})
    return chunks

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    in_memory_dir = os.path.join(input_dir, "memory")
    out_memory_dir = os.path.join(output_dir, "memory")
    in_anchors_path = os.path.join(in_memory_dir, "ANCHORS.md")
    out_anchors_path = os.path.join(out_memory_dir, "ANCHORS.md")
    log_dates = ["2026-04-12", "2026-04-13"]
    in_log_paths = {d: os.path.join(in_memory_dir, f"{d}.md") for d in log_dates}
    out_log_paths = {d: os.path.join(out_memory_dir, f"{d}.md") for d in log_dates}
    in_schema_files = [
        os.path.join(in_memory_dir, "schemas", "personal-health.md"),
        os.path.join(in_memory_dir, "schemas", "project-demo.md"),
    ]
    expected_files_sorted = ["schemas/personal-health.md", "schemas/project-demo.md"]
    out_vector_index_path = os.path.join(output_dir, "vector_index.json")
    out_index_meta_path = os.path.join(output_dir, "index_meta.json")
    out_report_path = os.path.join(output_dir, "report.json")

    checks = {
        "anchors_file_present": False,
        "anchors_appends_correct": False,
        "anchors_no_extra_appended": False,
        "log_2026_04_12_compressed_correct": False,
        "log_2026_04_13_compressed_correct": False,
        "vector_index_valid_structure": False,
        "vector_index_chunks_match": False,
        "index_meta_valid": False,
        "report_valid": False,
    }

    # Compute expected anchors to append
    in_anchors_content = read_text(in_anchors_path)
    logs_by_date = {}
    for d in log_dates:
        t = read_text(in_log_paths[d])
        if t is None:
            logs_by_date[d] = []
        else:
            logs_by_date[d] = extract_anchors_from_log(t)

    expected_anchor_blocks = compute_expected_anchor_blocks(
        in_anchors_content if in_anchors_content is not None else "",
        logs_by_date
    )
    expected_anchors_promoted_count = len(expected_anchor_blocks)

    # Check anchors output
    if os.path.isfile(out_anchors_path):
        checks["anchors_file_present"] = True
        out_anchors_content = read_text(out_anchors_path)
        if out_anchors_content is None:
            out_anchors_content = ""
        # Verify all expected blocks are present
        all_present = True
        for block in expected_anchor_blocks:
            if block not in out_anchors_content:
                all_present = False
                break
        checks["anchors_appends_correct"] = all_present
        # Verify no extra appended blocks for the target dates beyond the expected set
        found_blocks = parse_appended_blocks_for_dates(out_anchors_content, set(log_dates))
        # Compare as multisets by counting occurrences
        from collections import Counter
        c_found = Counter(found_blocks)
        c_expected = Counter(expected_anchor_blocks)
        checks["anchors_no_extra_appended"] = (c_found == c_expected)
    else:
        # Missing anchors output keeps related checks False
        pass

    # Check logs compressed correctly
    for d in log_dates:
        out_path = out_log_paths[d]
        in_path = in_log_paths[d]
        if not os.path.isfile(out_path) or not os.path.isfile(in_path):
            # If missing, keep False
            continue
        out_text = normalize_newlines(read_text(out_path) or "")
        in_text = read_text(in_path) or ""
        expected_compressed = compress_blank_lines(in_text)
        # Compare ignoring trailing newline differences
        if out_text.rstrip("\n") == expected_compressed.rstrip("\n"):
            if d == "2026-04-12":
                checks["log_2026_04_12_compressed_correct"] = True
            elif d == "2026-04-13":
                checks["log_2026_04_13_compressed_correct"] = True

    # Build expected chunks from schemas
    expected_chunks = []
    for schema_path in in_schema_files:
        if os.path.isfile(schema_path):
            schema_rel = os.path.relpath(schema_path, in_memory_dir).replace("\\", "/")
            schema_text = read_text(schema_path) or ""
            expected_chunks.extend(chunk_text(schema_text, schema_rel))
        else:
            # If a schema file is missing, expected will simply omit its chunks
            pass

    # Check vector_index.json
    vector_index = None
    if os.path.isfile(out_vector_index_path):
        vector_index = load_json(out_vector_index_path)
        if isinstance(vector_index, list):
            # Validate structure: each item must have exactly text, source, section, chunk_id
            structure_ok = True
            for item in vector_index:
                if not isinstance(item, dict):
                    structure_ok = False
                    break
                keys = set(item.keys())
                if keys != {"text", "source", "section", "chunk_id"}:
                    structure_ok = False
                    break
                if not all(isinstance(item[k], str) for k in ["text", "source", "section", "chunk_id"]):
                    structure_ok = False
                    break
            checks["vector_index_valid_structure"] = structure_ok

            # Compare chunks as sets of tuples to ignore order
            if checks["vector_index_valid_structure"]:
                def canon_list(lst):
                    return sorted(
                        [(e["text"], e["source"], e["section"], e["chunk_id"]) for e in lst],
                        key=lambda x: (x[1], x[3], hashlib.md5(x[0].encode("utf-8")).hexdigest())
                    )
                try:
                    exp_canon = canon_list(expected_chunks)
                    out_canon = canon_list(vector_index)
                    checks["vector_index_chunks_match"] = (exp_canon == out_canon)
                except Exception:
                    checks["vector_index_chunks_match"] = False
        else:
            checks["vector_index_valid_structure"] = False

    # Check index_meta.json
    if os.path.isfile(out_index_meta_path) and vector_index is not None and isinstance(vector_index, list):
        meta = load_json(out_index_meta_path)
        if isinstance(meta, dict):
            chunk_count_ok = ("chunk_count" in meta and isinstance(meta["chunk_count"], int) and meta["chunk_count"] == len(vector_index))
            files_ok = ("files" in meta and isinstance(meta["files"], list) and meta["files"] == expected_files_sorted)
            checks["index_meta_valid"] = (chunk_count_ok and files_ok)

    # Check report.json
    if os.path.isfile(out_report_path) and vector_index is not None and isinstance(vector_index, list):
        report = load_json(out_report_path)
        if isinstance(report, dict):
            ap_ok = ("anchors_promoted" in report and isinstance(report["anchors_promoted"], int) and report["anchors_promoted"] == expected_anchors_promoted_count)
            lp_ok = ("logs_processed" in report and report["logs_processed"] == 2)
            cc_ok = ("chunk_count" in report and isinstance(report["chunk_count"], int) and report["chunk_count"] == len(vector_index))
            files_match = ("files" in report and isinstance(report["files"], list))
            if files_match:
                files_match = (report["files"] == expected_files_sorted)
            # Also enforce consistency with index_meta.json if it exists
            if os.path.isfile(out_index_meta_path):
                meta2 = load_json(out_index_meta_path)
                if isinstance(meta2, dict) and "files" in meta2:
                    files_match = files_match and (report.get("files") == meta2.get("files"))
            checks["report_valid"] = (ap_ok and lp_ok and cc_ok and files_match)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0
    # Ensure 0.0 if no artifacts (no-op baseline)
    required_artifacts = [
        out_anchors_path,
        out_log_paths["2026-04-12"],
        out_log_paths["2026-04-13"],
        out_vector_index_path,
        out_index_meta_path,
        out_report_path,
    ]
    if not any(os.path.isfile(p) for p in required_artifacts):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()