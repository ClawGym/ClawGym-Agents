import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_records(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            records = [dict(row) for row in reader]
        return records
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple key/value and nested maps based on indentation and colons.
    Supports strings (quoted or unquoted), ints, and floats. Lines starting with '#' or blank are ignored.
    """
    text = _read_text_safe(path)
    if text is None:
        return None

    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        # Strip comments that start with #
        line = raw_line
        # remove comments only if they start the line or are preceded by space
        if "#" in line:
            idx = line.find("#")
            if idx == 0 or (idx > 0 and line[idx - 1].isspace()):
                line = line[:idx]
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if ":" not in content:
            continue
        if content.endswith(":"):
            key = content[:-1].strip()
            value = None
        else:
            key, val = content.split(":", 1)
            key = key.strip()
            value = val.strip()
            # parse value
            if (len(value) >= 2) and ((value[0] == value[-1]) and value[0] in ("'", '"')):
                value = value[1:-1]
            else:
                # try int, then float
                try:
                    if re.fullmatch(r"[+-]?\d+", value):
                        value = int(value)
                    else:
                        value = float(value)
                except Exception:
                    # keep as string
                    pass

        # adjust stack for current indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if value is None:
            new_map: Dict[str, Any] = {}
            parent[key] = new_map
            stack.append((indent, new_map))
        else:
            parent[key] = value
    return root


def _find_note_files(notes_dir: Path) -> List[Path]:
    if not notes_dir.exists():
        return []
    files = [p for p in notes_dir.rglob("*.md") if p.is_file()]
    files.sort(key=lambda p: p.as_posix())
    return files


def _extract_sections_from_note(text: str) -> List[Tuple[str, Dict[str, str]]]:
    """
    Return a list of tuples (topic_id, fields dict) per section found.
    A section is defined by a line 'TopicID: <ID>' and extends until the next 'TopicID:' or EOF.
    Within a section, capture the first 'Question:' line and the first 'Context:' line.
    """
    lines = text.splitlines()
    sections: List[Tuple[str, Dict[str, str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r"^TopicID:\s*(\S+)\s*$", line)
        if m:
            topic_id = m.group(1)
            fields: Dict[str, str] = {}
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if next_line.startswith("TopicID:"):
                    break
                if next_line.startswith("Question:"):
                    if "question" not in fields:
                        fields["question"] = next_line.split(":", 1)[1].strip()
                if next_line.startswith("Context:"):
                    if "context" not in fields:
                        fields["context"] = next_line.split(":", 1)[1].strip()
                j += 1
            sections.append((topic_id, fields))
            i = j
        else:
            i += 1
    return sections


def _build_topic_notes_info(workspace: Path, topic_ids: Set[str]) -> Dict[str, Dict[str, Any]]:
    """
    Returns mapping:
      topic_id -> {
        "files": set of canonical relative paths (data/notes/...),
        "question": str or None (first encountered across files),
        "context": str or None (first encountered across files),
      }
    """
    notes_dir = workspace / "data" / "notes"
    files = _find_note_files(notes_dir)
    info: Dict[str, Dict[str, Any]] = {tid: {"files": set(), "question": None, "context": None} for tid in topic_ids}
    for p in files:
        text = _read_text_safe(p)
        if text is None:
            continue
        sections = _extract_sections_from_note(text)
        for tid, fields in sections:
            if tid in info:
                try:
                    rel = p.relative_to(workspace)
                    rel_str = rel.as_posix()
                except Exception:
                    rel_str = p.as_posix()
                # canonicalize to start with data/notes/
                if "data/notes/" in rel_str:
                    suffix = rel_str.split("data/notes/", 1)[1]
                    rel_str = "data/notes/" + suffix
                info[tid]["files"].add(rel_str)
                if info[tid]["question"] is None and "question" in fields:
                    info[tid]["question"] = fields["question"]
                if info[tid]["context"] is None and "context" in fields:
                    info[tid]["context"] = fields["context"]
    return info


def _canonicalize_source_files_field(s: Optional[str]) -> Set[str]:
    if not s:
        return set()
    parts = [x.strip() for x in s.split("|") if x.strip()]
    canon: Set[str] = set()
    for part in parts:
        part = part.replace("\\", "/")
        if "data/notes/" in part:
            part = "data/notes/" + part.split("data/notes/", 1)[1]
        canon.add(part)
    return canon


def _first_sentence(text: Optional[str]) -> str:
    if not text:
        return ""
    # Split on sentence-ending punctuation. Keep it simple.
    m = re.split(r"[.!?]", text, maxsplit=1)
    if m:
        return m[0].strip()
    return text.strip()


def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _compute_expected_ranking(records: List[Dict[str, str]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    filter_field = None
    filter_value = None
    w_impact = None
    w_urgency = None
    try:
        filter_field = config.get("filter", {}).get("field")
        filter_value = config.get("filter", {}).get("value")
        w_impact = config.get("weights", {}).get("impact")
        w_urgency = config.get("weights", {}).get("urgency")
    except Exception:
        pass

    expected: List[Dict[str, Any]] = []
    for r in records:
        if not filter_field:
            continue
        if r.get(filter_field) != filter_value:
            continue
        topic_id = r.get("topic_id")
        topic_title = r.get("topic")
        urgency = _safe_float(r.get("urgency"))
        impact = _safe_float(r.get("impact"))
        if topic_id is None or topic_title is None or urgency is None or impact is None:
            continue
        if w_impact is None or w_urgency is None:
            continue
        try:
            composite = float(impact) * float(w_impact) + float(urgency) * float(w_urgency)
        except Exception:
            continue
        expected.append({
            "topic_id": topic_id,
            "topic": topic_title,
            "urgency": float(urgency),
            "impact": float(impact),
            "composite_score": float(composite),
        })
    expected.sort(key=lambda x: (-x["composite_score"], -x["impact"], -x["urgency"], x["topic_id"]))
    return expected


def _parse_email_items(text: str, top_n: int) -> List[str]:
    """
    Parse numbered list items 1..top_n from the email. Returns list of block texts (joined lines) in order.
    Recognizes lines starting with the exact index followed by ., ), :, or -.
    """
    lines = text.splitlines()
    blocks: List[str] = []
    current_block_lines: List[str] = []
    expected_index = 1
    pattern = re.compile(r"^\s*(\d+)[\.\):\-]\s*(.*)$")
    for line in lines:
        m = pattern.match(line)
        if m:
            num = int(m.group(1))
            if num == expected_index:
                if current_block_lines:
                    blocks.append("\n".join(current_block_lines).strip())
                    current_block_lines = []
                current_block_lines.append(line)
                expected_index += 1
                continue
        if current_block_lines:
            current_block_lines.append(line)
    if current_block_lines:
        blocks.append("\n".join(current_block_lines).strip())
    return blocks[:top_n]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "rankings_csv_exists_and_columns": 0.0,
        "rankings_csv_row_count": 0.0,
        "rankings_composite_scores_correct": 0.0,
        "rankings_sorted_correct": 0.0,
        "rankings_source_note_files_correct": 0.0,
        "email_exists": 0.0,
        "email_subject_ok": 0.0,
        "email_intro_mentions_weights_impact_urgency": 0.0,
        "email_top_n_blocks_count": 0.0,
        "email_order_matches_rankings": 0.0,
        "email_items_include_id_and_title": 0.0,
        "email_items_include_questions_verbatim": 0.0,
        "email_items_include_context_sentence": 0.0,
        "email_polite_ask_chat_30_min": 0.0,
        "email_invite_recommended_resources": 0.0,
    }

    # Load config and topics for expected computations (no direct scoring for their existence)
    config_path = workspace / "config" / "weights.yaml"
    config = _parse_simple_yaml(config_path) or {}
    topics_path = workspace / "data" / "topics.csv"
    topics_records = _load_csv_records(topics_path) or []

    # Prepare expected ranking and notes info if prerequisites are present
    expected_ranking: List[Dict[str, Any]] = []
    topic_note_info: Dict[str, Dict[str, Any]] = {}
    try:
        # Validate topics schema minimally before computing
        schema_ok = False
        if topics_records:
            fieldnames = set(topics_records[0].keys())
            required_cols = {"topic_id", "topic", "summary", "urgency", "impact", "ask_architect"}
            schema_ok = required_cols.issubset(fieldnames)
        if schema_ok and isinstance(config, dict):
            expected_ranking = _compute_expected_ranking(topics_records, config)
            expected_topic_ids = {r["topic_id"] for r in expected_ranking}
            topic_note_info = _build_topic_notes_info(workspace, expected_topic_ids)
    except Exception:
        expected_ranking = []
        topic_note_info = {}

    # Validate rankings CSV
    rankings_path = workspace / "output" / "topic_rankings.csv"
    rankings_records = _load_csv_records(rankings_path)
    if rankings_records is not None:
        # columns exact
        try:
            with rankings_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
            expected_header = ["topic_id", "topic", "urgency", "impact", "composite_score", "source_note_files"]
            if header == expected_header:
                scores["rankings_csv_exists_and_columns"] = 1.0
        except Exception:
            pass

        # row count should match expected_ranking length
        if expected_ranking:
            if len(rankings_records) == len(expected_ranking):
                scores["rankings_csv_row_count"] = 1.0

        # composite scores, ids, and source_note_files
        if expected_ranking:
            exp_by_id = {r["topic_id"]: r for r in expected_ranking}
            composite_ok = True
            id_set_ok = True
            source_files_ok_all = True

            ids_csv = {r.get("topic_id") for r in rankings_records}
            if ids_csv != set(exp_by_id.keys()):
                id_set_ok = False

            for row in rankings_records:
                tid = row.get("topic_id")
                exp = exp_by_id.get(tid)
                if not exp:
                    composite_ok = False
                    source_files_ok_all = False
                    continue
                u = _safe_float(row.get("urgency"))
                im = _safe_float(row.get("impact"))
                cs = _safe_float(row.get("composite_score"))
                if u is None or im is None or cs is None:
                    composite_ok = False
                else:
                    if abs(u - float(exp["urgency"])) > 1e-6:
                        composite_ok = False
                    if abs(im - float(exp["impact"])) > 1e-6:
                        composite_ok = False
                    if abs(cs - float(exp["composite_score"])) > 1e-6:
                        composite_ok = False
                actual_set = _canonicalize_source_files_field(row.get("source_note_files"))
                expected_files_set = set()
                info = topic_note_info.get(tid, {})
                if info:
                    expected_files_set = set(info.get("files", set()))
                if actual_set != expected_files_set:
                    source_files_ok_all = False

            if composite_ok and id_set_ok:
                scores["rankings_composite_scores_correct"] = 1.0
            if source_files_ok_all and id_set_ok:
                scores["rankings_source_note_files_correct"] = 1.0

        # Order check
        if expected_ranking:
            expected_order = [r["topic_id"] for r in expected_ranking]
            csv_order = [r.get("topic_id") for r in rankings_records]
            if csv_order == expected_order:
                scores["rankings_sorted_correct"] = 1.0

    # Validate email draft
    email_path = workspace / "output" / "email_draft_to_architect.md"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0

        # Subject line requirement
        lines = email_text.splitlines()
        if lines:
            first = lines[0].strip()
            if first.lower().startswith("subject:") and ("prioritized architecture topics" in first.lower()):
                scores["email_subject_ok"] = 1.0

        # Intro mentions weights, impact, urgency, and config path
        body_lower = email_text.lower()
        if ("impact" in body_lower and "urgency" in body_lower and "weights" in body_lower and "config/weights.yaml" in body_lower):
            scores["email_intro_mentions_weights_impact_urgency"] = 1.0

        # Items
        top_n = None
        try:
            top_n = config.get("top_n") if isinstance(config, dict) else None
        except Exception:
            top_n = None
        if isinstance(top_n, int) and top_n > 0:
            blocks = _parse_email_items(email_text, top_n)
            if len(blocks) == top_n:
                scores["email_top_n_blocks_count"] = 1.0

            if expected_ranking and len(blocks) == top_n:
                expected_order = [r["topic_id"] for r in expected_ranking[:top_n]]
                order_ok = True
                id_title_ok = 0
                question_ok = 0
                context_ok = 0
                for idx, block in enumerate(blocks):
                    tid = expected_order[idx]
                    exp_topic = next((r for r in expected_ranking if r["topic_id"] == tid), None)
                    if not exp_topic:
                        order_ok = False
                        continue
                    # id and title
                    has_id = tid in block
                    has_title = isinstance(exp_topic["topic"], str) and (exp_topic["topic"] in block)
                    if has_id and has_title:
                        id_title_ok += 1
                    # question presence
                    info = topic_note_info.get(tid, {})
                    q_text = info.get("question")
                    if isinstance(q_text, str) and q_text and (q_text in block):
                        question_ok += 1
                    # context first sentence presence
                    c_text = info.get("context")
                    first_sent = _first_sentence(c_text) if isinstance(c_text, str) else ""
                    if first_sent and (first_sent in block):
                        context_ok += 1
                if order_ok:
                    scores["email_order_matches_rankings"] = 1.0
                scores["email_items_include_id_and_title"] = id_title_ok / float(top_n)
                scores["email_items_include_questions_verbatim"] = question_ok / float(top_n)
                scores["email_items_include_context_sentence"] = context_ok / float(top_n)

        # Polite ask for 30-minute chat
        txt = email_text.lower()
        if ("chat" in txt and "30" in txt and "minute" in txt):
            scores["email_polite_ask_chat_30_min"] = 1.0

        # Invite recommended resources
        if ("resource" in txt and "recommend" in txt):
            scores["email_invite_recommended_resources"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()