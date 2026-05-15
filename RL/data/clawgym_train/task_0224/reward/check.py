import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def _indent_level(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _unescape_quoted_yaml(value: str) -> str:
    # Remove surrounding quotes if any and unescape \n inside double-quoted strings
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    # Replace escaped newline sequences with actual newline
    v = v.replace("\\n", "\n")
    return v


def _parse_simple_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser tailored to the provided config structure.
    Supports:
      - top-level keys
      - nested dicts
      - lists indicated by '- '
      - simple key: value pairs
      - signatures with quoted strings including \n
      - ignores rewrite.style block scalars
    """
    text = _safe_read_text(path)
    if text is None:
        return None

    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    config: Dict[str, Any] = {}
    i = 0
    n = len(lines)

    def is_top_level_key(idx: int) -> bool:
        if idx < 0 or idx >= n:
            return False
        s = lines[idx]
        if not s.strip():
            return False
        if _indent_level(s) != 0:
            return False
        return bool(re.match(r"^[A-Za-z0-9_]+:\s*$", s) or re.match(r"^[A-Za-z0-9_]+:\s*.+$", s))

    # Helper to parse a simple mapping block indented under a key
    def parse_mapping_block(start_idx: int, parent_indent: int) -> Tuple[Dict[str, Any], int]:
        result: Dict[str, Any] = {}
        idx = start_idx
        while idx < n:
            line = lines[idx]
            if not line.strip():
                idx += 1
                continue
            indent = _indent_level(line)
            if indent <= parent_indent:
                break
            stripped = line.strip()
            # key: value or key:
            m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", stripped)
            if not m:
                # Not a key-value; possibly list or something else; break
                idx += 1
                continue
            key, val = m.group(1), m.group(2)
            if val == "" or val is None:
                # Nested block
                # Determine if the next lines are list or mapping
                # Peek next non-empty line
                j = idx + 1
                while j < n and (not lines[j].strip()):
                    j += 1
                if j < n and _indent_level(lines[j]) > indent and lines[j].strip().startswith("- "):
                    # list block
                    lst, end_idx = parse_list_block(j, indent)
                    result[key] = lst
                    idx = end_idx
                else:
                    # mapping block
                    submap, end_idx = parse_mapping_block(idx + 1, indent)
                    result[key] = submap
                    idx = end_idx
            else:
                # Scalar value
                result[key] = _unescape_quoted_yaml(val)
                idx += 1
        return result, idx

    def parse_list_block(start_idx: int, parent_indent: int) -> Tuple[List[Any], int]:
        lst: List[Any] = []
        idx = start_idx
        while idx < n:
            line = lines[idx]
            if not line.strip():
                idx += 1
                continue
            indent = _indent_level(line)
            if indent <= parent_indent:
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                item_val = stripped[2:].strip()
                # If item is "name: ..." etc, treat as inline mapping start
                if re.match(r"^[A-Za-z0-9_]+:\s*.*$", item_val):
                    # Build a synthetic mapping from this line and possible nested blocks
                    # Treat current item as a mapping starting this line
                    # We'll parse a mapping with this line as first entry
                    # Collect this line by converting "- key: val" to "key: val" and then parse following nested
                    # Build a temporary list of lines for this item block
                    item_indent = indent
                    # Start with this line transformed
                    temp_lines = [" " * indent + item_val]
                    j = idx + 1
                    while j < n:
                        next_line = lines[j]
                        if not next_line.strip():
                            temp_lines.append(next_line)
                            j += 1
                            continue
                        next_indent = _indent_level(next_line)
                        if next_indent <= item_indent:
                            break
                        temp_lines.append(next_line)
                        j += 1
                    # Parse temp_lines as a mapping block
                    # Temporarily adjust global lines for parsing
                    saved_lines = lines.copy()
                    # Replace content with temp_lines to parse mapping from index 0
                    try:
                        # Parse mapping block starting at 0 with parent indent = item_indent - treat stripped mapping
                        nonlocal_lines = temp_lines
                        # re-implement small parser for this temporary content
                        def parse_temp_mapping(temp: List[str]) -> Dict[str, Any]:
                            res: Dict[str, Any] = {}
                            ti = 0
                            tlen = len(temp)
                            while ti < tlen:
                                tline = temp[ti]
                                if not tline.strip():
                                    ti += 1
                                    continue
                                tindent = _indent_level(tline)
                                m = re.match(r"^\s*([A-Za-z0-9_]+):\s*(.*)$", tline)
                                if not m:
                                    ti += 1
                                    continue
                                k, v = m.group(1), m.group(2)
                                if v == "" or v is None:
                                    # look ahead: list or mapping
                                    tj = ti + 1
                                    while tj < tlen and (not temp[tj].strip()):
                                        tj += 1
                                    if tj < tlen and _indent_level(temp[tj]) > tindent and temp[tj].strip().startswith("- "):
                                        # list
                                        # parse list
                                        lres: List[Any] = []
                                        tk = tj
                                        while tk < tlen:
                                            tline2 = temp[tk]
                                            if not tline2.strip():
                                                tk += 1
                                                continue
                                            if _indent_level(tline2) <= tindent:
                                                break
                                            tstr2 = tline2.strip()
                                            if tstr2.startswith("- "):
                                                lval = tstr2[2:].strip()
                                                lres.append(_unescape_quoted_yaml(lval))
                                            tk += 1
                                        res[k] = lres
                                        ti = tk
                                    else:
                                        # nested mapping
                                        # collect until dedent
                                        tk = ti + 1
                                        sub_temp: List[str] = []
                                        while tk < tlen:
                                            if not temp[tk].strip():
                                                sub_temp.append(temp[tk])
                                                tk += 1
                                                continue
                                            if _indent_level(temp[tk]) <= tindent:
                                                break
                                            sub_temp.append(temp[tk])
                                            tk += 1
                                        res[k] = parse_temp_mapping(sub_temp)
                                        ti = tk
                                else:
                                    res[k] = _unescape_quoted_yaml(v)
                                    ti += 1
                            return res
                        item_map = parse_temp_mapping(temp_lines)
                        lst.append(item_map)
                    finally:
                        lines[:] = saved_lines
                    idx = j
                else:
                    # Simple scalar list item
                    lst.append(_unescape_quoted_yaml(item_val))
                    idx += 1
            else:
                break
        return lst, idx

    # Build a simple parser for known sections
    # We'll specifically parse categories, output, rewrite.tones, rewrite.signatures
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not is_top_level_key(i):
            i += 1
            continue
        stripped = line.strip()
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", stripped)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2)
        if key == "categories":
            # parse list of category objects
            # Expect a list of items with "- name:" and "keywords:" list
            # Move to next line
            i += 1
            categories: List[Dict[str, Any]] = []
            while i < n:
                l2 = lines[i]
                if not l2.strip():
                    i += 1
                    continue
                if is_top_level_key(i):
                    break
                if l2.strip().startswith("- "):
                    # start category object
                    # Convert this item and its nested lines into a mapping
                    # Use parse_list_block to parse list of mappings
                    lst, new_i = parse_list_block(i, _indent_level(line))
                    # lst may contain multiple items parsed; but we hit until dedent
                    # However we want to consume as many list items as contiguous
                    categories.extend(lst)
                    i = new_i
                else:
                    i += 1
            # Normalize categories: ensure each item has 'name' and 'keywords'
            norm_categories: List[Dict[str, Any]] = []
            for item in categories:
                if isinstance(item, dict) and "name" in item:
                    kws = item.get("keywords", [])
                    if not isinstance(kws, list):
                        kws = []
                    norm_categories.append({"name": item["name"], "keywords": [str(k).strip() for k in kws]})
            config["categories"] = norm_categories
            continue
        elif key == "output":
            # parse mapping block
            mapping, new_i = parse_mapping_block(i + 1, _indent_level(line))
            config["output"] = mapping
            i = new_i
            continue
        elif key == "rewrite":
            # parse mapping under rewrite
            rewrite_map, new_i = parse_mapping_block(i + 1, _indent_level(line))
            # We only need tones and signatures
            rewrite: Dict[str, Any] = {}
            tones = rewrite_map.get("tones", [])
            if isinstance(tones, list):
                rewrite["tones"] = [str(t) for t in tones]
            else:
                rewrite["tones"] = []
            sigs = rewrite_map.get("signatures", {})
            if isinstance(sigs, dict):
                # Ensure unescape \n in values
                rewrite["signatures"] = {k: _unescape_quoted_yaml(str(v)) for k, v in sigs.items()}
            else:
                rewrite["signatures"] = {}
            config["rewrite"] = rewrite
            i = new_i
            continue
        else:
            # other keys not needed
            i += 1

    # Basic validation: ensure keys exist
    if "output" not in config:
        config["output"] = {}
    if "rewrite" not in config:
        config["rewrite"] = {"tones": [], "signatures": {}}
    if "categories" not in config:
        config["categories"] = []
    return config


def _compute_note_category(note: Dict[str, Any], categories: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    text = str(note.get("text", ""))
    tags = note.get("tags", [])
    tags_texts = " ".join([str(t) for t in tags]) if isinstance(tags, list) else str(tags)
    haystacks = [text.lower(), tags_texts.lower()]

    for cat in categories:
        cat_name = cat.get("name", "")
        keywords = [str(k).lower() for k in cat.get("keywords", [])]
        matched = []
        for kw in keywords:
            kw_l = kw.lower()
            found = False
            for hay in haystacks:
                if kw_l in hay:
                    found = True
                    break
            if found:
                matched.append(kw)
        if matched:
            # Unique in order of keywords
            seen = set()
            uniq = []
            for m in matched:
                if m not in seen:
                    uniq.append(m)
                    seen.add(m)
            return cat_name, uniq
    return "Uncategorized", []


def _parse_matched_keywords_field(value: str) -> List[str]:
    if value is None:
        return []
    s = value.strip()
    if s == "":
        return []
    parts = [p.strip() for p in s.split(";")]
    # remove empty and deduplicate preserving order
    seen = set()
    out = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _word_count_excluding_signature(body: str, signature: str) -> int:
    if body.endswith(signature):
        content = body[: len(body) - len(signature)]
    else:
        content = body
    # Remove trailing whitespace
    content = content.rstrip()
    # Split on whitespace
    words = re.findall(r"\b\w[\w'-]*\b", content)
    return len(words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "memory_index_csv_exists": 0.0,
        "memory_index_csv_header_and_row_count": 0.0,
        "memory_index_per_note_correctness": 0.0,
        "tag_summary_json_exists": 0.0,
        "tag_summary_consistency_with_csv": 0.0,
        "revised_messages_jsonl_exists": 0.0,
        "revised_messages_per_message_two_tones": 0.0,
        "revised_messages_signatures_correct": 0.0,
        "revised_messages_subjects_nonempty": 0.0,
        "rewritten_formal_within_target_words": 0.0,
        "rewritten_friendly_within_target_words": 0.0,
    }

    # Load config
    config_path = workspace / "config" / "config.yaml"
    config = _parse_simple_yaml_config(config_path)
    if not config:
        return scores

    # Paths from config
    memory_csv_rel = config.get("output", {}).get("memory_index_csv")
    tag_summary_rel = config.get("output", {}).get("tag_summary_json")
    revised_msgs_rel = config.get("output", {}).get("rewritten_messages_jsonl") or config.get("output", {}).get("revised_messages_jsonl")
    # The config shows "rewritten_messages_jsonl: output/revised_messages.jsonl"
    # Try both keys to be robust to name mismatch; prefer rewritten_messages_jsonl
    if not revised_msgs_rel:
        revised_msgs_rel = config.get("output", {}).get("rewritten_messages_jsonl", None)

    categories_cfg = config.get("categories", [])
    tones_cfg = config.get("rewrite", {}).get("tones", [])
    signatures_cfg = config.get("rewrite", {}).get("signatures", {})

    # Load inputs
    notes_input_path = workspace / "input" / "notes.jsonl"
    messages_input_path = workspace / "input" / "messages.jsonl"
    notes = _safe_load_jsonl(notes_input_path)
    messages = _safe_load_jsonl(messages_input_path)

    # Memory index CSV checks
    csv_path = workspace / memory_csv_rel if memory_csv_rel else None
    csv_header: Optional[List[str]] = None
    csv_rows: Optional[List[Dict[str, str]]] = None
    if csv_path and csv_path.exists():
        parsed = _safe_load_csv_dicts(csv_path)
        if parsed:
            header, rows = parsed
            csv_header = header
            csv_rows = rows
            scores["memory_index_csv_exists"] = 1.0
        else:
            scores["memory_index_csv_exists"] = 0.0
    else:
        scores["memory_index_csv_exists"] = 0.0

    # Header and row count/id consistency
    expected_header = ["id", "date", "title", "category", "matched_keywords"]
    if csv_rows is not None and csv_header is not None and notes is not None:
        header_ok = csv_header == expected_header
        ids_csv = [row.get("id", "") for row in csv_rows]
        ids_notes = [str(n.get("id", "")) for n in notes]
        row_count_ok = len(csv_rows) == len(notes)
        id_set_ok = set(ids_csv) == set(ids_notes) and len(set(ids_csv)) == len(ids_csv)
        header_and_count_ok = header_ok and row_count_ok and id_set_ok
        scores["memory_index_csv_header_and_row_count"] = 1.0 if header_and_count_ok else 0.0
    else:
        scores["memory_index_csv_header_and_row_count"] = 0.0

    # Per-note correctness: date/title/category/matched_keywords set equality
    if csv_rows is not None and notes is not None and categories_cfg:
        rows_by_id = {row.get("id", ""): row for row in csv_rows}
        correct = 0
        total = len(notes)
        for note in notes:
            nid = str(note.get("id", ""))
            row = rows_by_id.get(nid)
            if not row:
                continue
            date_ok = str(row.get("date", "")) == str(note.get("date", ""))
            title_ok = str(row.get("title", "")) == str(note.get("title", ""))
            expected_category, expected_keywords = _compute_note_category(note, categories_cfg)
            category_ok = str(row.get("category", "")) == expected_category
            # parse matched_keywords
            got_keywords = _parse_matched_keywords_field(row.get("matched_keywords", ""))
            # compare sets case-insensitive
            got_set = set([g.lower() for g in got_keywords])
            exp_set = set([k.lower() for k in expected_keywords])
            keywords_ok = got_set == exp_set
            if date_ok and title_ok and category_ok and keywords_ok:
                correct += 1
        scores["memory_index_per_note_correctness"] = (correct / total) if total > 0 else 0.0
    else:
        scores["memory_index_per_note_correctness"] = 0.0

    # Tag summary JSON checks
    tag_path = workspace / tag_summary_rel if tag_summary_rel else None
    tag_data: Optional[Dict[str, Any]] = None
    if tag_path and tag_path.exists():
        data = _safe_load_json(tag_path)
        if isinstance(data, dict):
            tag_data = data
            scores["tag_summary_json_exists"] = 1.0
        else:
            scores["tag_summary_json_exists"] = 0.0
    else:
        scores["tag_summary_json_exists"] = 0.0

    # Tag summary consistency with CSV
    if tag_data is not None and csv_rows is not None:
        # Build counts from CSV
        csv_counts: Dict[str, List[str]] = {}
        for row in csv_rows:
            cat = row.get("category", "")
            nid = row.get("id", "")
            csv_counts.setdefault(cat, []).append(nid)
        # Expected categories: all categories in config plus "Uncategorized"
        expected_cats = [c.get("name", "") for c in categories_cfg] if categories_cfg else []
        if "Uncategorized" not in expected_cats:
            expected_cats.append("Uncategorized")
        # Compute score as average over expected categories that must be present in JSON
        total_cats = len(expected_cats)
        good = 0
        for cat in expected_cats:
            json_entry = tag_data.get(cat)
            csv_ids = csv_counts.get(cat, [])
            csv_count = len(csv_ids)
            if not isinstance(json_entry, dict):
                continue
            j_count = json_entry.get("count")
            j_ids = json_entry.get("ids")
            if not isinstance(j_count, int) or not isinstance(j_ids, list):
                continue
            # Compare counts and ids (order-insensitive)
            ids_ok = set(map(str, j_ids)) == set(map(str, csv_ids)) and len(j_ids) == len(set(j_ids))
            if j_count == csv_count and ids_ok:
                good += 1
        scores["tag_summary_consistency_with_csv"] = (good / total_cats) if total_cats > 0 else 0.0
    else:
        scores["tag_summary_consistency_with_csv"] = 0.0

    # Revised messages JSONL checks
    revised_msgs_path: Optional[Path] = None
    if revised_msgs_rel:
        revised_msgs_path = workspace / revised_msgs_rel
    revised_msgs: Optional[List[Dict[str, Any]]] = None
    if revised_msgs_path and revised_msgs_path.exists():
        parsed = _safe_load_jsonl(revised_msgs_path)
        if isinstance(parsed, list):
            revised_msgs = parsed
            scores["revised_messages_jsonl_exists"] = 1.0
        else:
            scores["revised_messages_jsonl_exists"] = 0.0
    else:
        scores["revised_messages_jsonl_exists"] = 0.0

    # Messages per-message two tones
    if messages is not None and revised_msgs is not None and tones_cfg:
        # Group by id
        by_id: Dict[str, List[Dict[str, Any]]] = {}
        for obj in revised_msgs:
            mid = str(obj.get("id", ""))
            by_id.setdefault(mid, []).append(obj)
        correct = 0
        total = len(messages)
        # Determine required tones: exactly "formal" and "friendly" per config order or names
        required_tones = set([t.strip().lower() for t in tones_cfg])
        for msg in messages:
            mid = str(msg.get("id", ""))
            outs = by_id.get(mid, [])
            tone_set = set([str(o.get("tone", "")).strip().lower() for o in outs])
            if len(outs) == 2 and tone_set == required_tones:
                correct += 1
        scores["revised_messages_per_message_two_tones"] = (correct / total) if total > 0 else 0.0
    else:
        scores["revised_messages_per_message_two_tones"] = 0.0

    # Signatures correctness and subjects non-empty, word count targets
    if messages is not None and revised_msgs is not None and signatures_cfg:
        formal_sig = signatures_cfg.get("formal", "")
        friendly_sig = signatures_cfg.get("friendly", "")
        # Filter only outputs corresponding to input messages
        input_ids = set([str(m.get("id", "")) for m in messages])
        outputs = [o for o in revised_msgs if str(o.get("id", "")) in input_ids]
        # signatures
        sig_correct = 0
        sig_total = 0
        subj_nonempty = 0
        subj_total = 0
        formal_wc_ok = 0
        formal_wc_total = 0
        friendly_wc_ok = 0
        friendly_wc_total = 0
        for o in outputs:
            tone = str(o.get("tone", "")).strip().lower()
            body = str(o.get("body", ""))
            subject = o.get("subject", "")
            # subject non-empty string
            subj_total += 1
            if isinstance(subject, str) and subject.strip() != "":
                subj_nonempty += 1
            # signature check
            if tone == "formal":
                sig_total += 1
                if body.endswith(formal_sig):
                    sig_correct += 1
                # word count target 60–120 (soft check)
                wc = _word_count_excluding_signature(body, formal_sig)
                formal_wc_total += 1
                if 60 <= wc <= 120:
                    formal_wc_ok += 1
            elif tone == "friendly":
                sig_total += 1
                if body.endswith(friendly_sig):
                    sig_correct += 1
                wc = _word_count_excluding_signature(body, friendly_sig)
                friendly_wc_total += 1
                if 30 <= wc <= 80:
                    friendly_wc_ok += 1
            else:
                # unknown tone; count towards subject total only
                pass
        scores["revised_messages_signatures_correct"] = (sig_correct / sig_total) if sig_total > 0 else 0.0
        scores["revised_messages_subjects_nonempty"] = (subj_nonempty / subj_total) if subj_total > 0 else 0.0
        scores["rewritten_formal_within_target_words"] = (formal_wc_ok / formal_wc_total) if formal_wc_total > 0 else 0.0
        scores["rewritten_friendly_within_target_words"] = (friendly_wc_ok / friendly_wc_total) if friendly_wc_total > 0 else 0.0
    else:
        scores["revised_messages_signatures_correct"] = 0.0
        scores["revised_messages_subjects_nonempty"] = 0.0
        scores["rewritten_formal_within_target_words"] = 0.0
        scores["rewritten_friendly_within_target_words"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()