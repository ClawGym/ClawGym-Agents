import csv
import json
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_with_header(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return ([], [])
            rows = []
            for row in reader:
                if len(row) < len(header):
                    row = row + [""] * (len(header) - len(row))
                elif len(row) > len(header):
                    row = row[: len(header)]
                rows.append({h: v for h, v in zip(header, row)})
        return (header, rows)
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    s = s.strip()
    fmts = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _parse_int_strict(s: str) -> Optional[int]:
    if s.strip() == "":
        return None
    try:
        val = float(s.strip())
        if abs(val - round(val)) < 1e-9:
            return int(round(val))
        return None
    except Exception:
        return None


def _floats_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compute_expected_topic_priorities(workspace: Path) -> Optional[Dict[str, Any]]:
    blueprint_path = workspace / "input" / "exam_blueprint.csv"
    performance_path = workspace / "input" / "performance.csv"
    bp = _read_csv_with_header(blueprint_path)
    pf = _read_csv_with_header(performance_path)
    if bp is None or pf is None:
        return None
    bp_header, bp_rows = bp
    pf_header, pf_rows = pf
    if not {"topic", "weight"}.issubset(set(bp_header)) or not {"topic", "exam", "attempt_date", "score"}.issubset(set(pf_header)):
        return None
    blueprint_topics = []
    weight_map: Dict[str, float] = {}
    for row in bp_rows:
        topic = row.get("topic", "").strip()
        w_str = row.get("weight", "").strip()
        w = _parse_float(w_str)
        if topic == "" or w is None:
            return None
        blueprint_topics.append(topic)
        weight_map[topic] = w
    latest_score_by_topic: Dict[str, Optional[int]] = {}
    for topic in blueprint_topics:
        latest_score_by_topic[topic] = None
    per_topic_records: Dict[str, List[Tuple[datetime, int]]] = {}
    for row in pf_rows:
        topic = row.get("topic", "").strip()
        exam = row.get("exam", "").strip()
        if topic not in weight_map:
            continue
        if exam != "NBME":
            continue
        date_str = row.get("attempt_date", "").strip()
        score_str = row.get("score", "").strip()
        dt = _parse_date(date_str)
        try:
            score_val = int(score_str)
        except Exception:
            score_val_i = _parse_int_strict(score_str)
            if score_val_i is None:
                return None
            score_val = score_val_i
        if dt is None:
            return None
        per_topic_records.setdefault(topic, []).append((dt, score_val))
    for topic in blueprint_topics:
        if topic in per_topic_records and per_topic_records[topic]:
            per_topic_records[topic].sort(key=lambda x: x[0])
            latest_score_by_topic[topic] = per_topic_records[topic][-1][1]
        else:
            latest_score_by_topic[topic] = None
    expected_rows: List[Dict[str, Any]] = []
    for topic in blueprint_topics:
        w = weight_map[topic]
        ls = latest_score_by_topic[topic]
        ls_for_calc = 0 if ls is None else ls
        priority_score = (100 - ls_for_calc) * w
        expected_rows.append({
            "topic": topic,
            "latest_score": ls,
            "weight": w,
            "priority_score": priority_score
        })
    def sort_key(row: Dict[str, Any]):
        ps = row["priority_score"]
        ls = 0 if row["latest_score"] is None else row["latest_score"]
        w = row["weight"]
        t = row["topic"]
        return (-ps, ls, -w, t)
    expected_rows_sorted = sorted(expected_rows, key=sort_key)
    ranks: Dict[str, int] = {}
    for idx, row in enumerate(expected_rows_sorted, start=1):
        ranks[row["topic"]] = idx
    expected_map = {
        "topics": blueprint_topics,
        "weights": weight_map,
        "latest_scores": latest_score_by_topic,
        "priority_scores": {row["topic"]: row["priority_score"] for row in expected_rows},
        "ranks": ranks,
        "sorted_topics_by_rank": [row["topic"] for row in expected_rows_sorted],
    }
    return expected_map


def _extract_expected_flashcards(workspace: Path) -> Optional[List[Dict[str, str]]]:
    notes_dir = workspace / "input" / "notes"
    if not notes_dir.exists() or not notes_dir.is_dir():
        return None
    flashcards: List[Dict[str, str]] = []
    try:
        files = sorted([p for p in notes_dir.iterdir() if p.is_file()])
    except Exception:
        return None
    for file in files:
        try:
            content = file.read_text(encoding="utf-8")
        except Exception:
            return None
        lines = content.splitlines()
        for i in range(len(lines) - 1):
            q_line = lines[i]
            a_line = lines[i + 1]
            if q_line.startswith("Q:") and a_line.startswith("A:"):
                question = q_line[2:].strip()
                answer = a_line[2:].strip()
                topic = file.stem
                source_file = f"input/notes/{file.name}"
                flashcards.append({
                    "topic": topic,
                    "question": question,
                    "answer": answer,
                    "source_file": source_file
                })
    return flashcards


def _parse_jsonl(path: Path) -> Optional[List[Any]]:
    try:
        records = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.strip() == "":
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                records.append(obj)
        return records
    except Exception:
        return None


def _parse_emails_sections(content: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_label: Optional[str] = None
    buffer: List[str] = []
    label_pattern = re.compile(r'^\s*#*\s*(Draft\s*1|Draft\s*2)\s*:?\s*$', flags=re.IGNORECASE)
    lines = content.splitlines()
    for line in lines:
        m = label_pattern.match(line)
        if m:
            if current_label is not None:
                sections[current_label] = "\n".join(buffer).strip()
                buffer = []
            label = m.group(1)
            label_norm = " ".join(label.strip().split()).title()
            current_label = label_norm
        else:
            if current_label is not None:
                buffer.append(line)
    if current_label is not None:
        sections[current_label] = "\n".join(buffer).strip()
    return sections


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len([w for w in text.split() if w.strip() != ""])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "topic_priorities_file_exists": 0.0,
        "topic_priorities_header_and_columns": 0.0,
        "topic_priorities_row_count": 0.0,
        "topic_priorities_weights_correct": 0.0,
        "topic_priorities_latest_scores_correct": 0.0,
        "topic_priorities_priority_scores_correct": 0.0,
        "topic_priorities_ranking_correct": 0.0,
        "flashcards_file_exists": 0.0,
        "flashcards_line_count": 0.0,
        "flashcards_schema_valid": 0.0,
        "flashcards_content_match": 0.0,
        "emails_file_exists": 0.0,
        "emails_labels_present": 0.0,
        "emails_draft1_nonempty": 0.0,
        "emails_draft2_nonempty": 0.0,
        "emails_draft1_word_limit": 0.0,
        "emails_draft2_word_limit": 0.0,
    }

    expected_tp = _compute_expected_topic_priorities(workspace)

    tp_path = workspace / "output" / "topic_priorities.csv"
    if tp_path.exists() and tp_path.is_file():
        scores["topic_priorities_file_exists"] = 1.0
        tp_read = _read_csv_with_header(tp_path)
        if tp_read is not None:
            header, rows = tp_read
            required_header = ["topic", "latest_score", "weight", "priority_score", "rank"]
            if header == required_header:
                scores["topic_priorities_header_and_columns"] = 1.0
            if expected_tp is not None:
                expected_topics_set = set(expected_tp["weights"].keys())
                produced_topics_set = set([row.get("topic", "").strip() for row in rows])
                if len(rows) == len(expected_topics_set) and produced_topics_set == expected_topics_set:
                    scores["topic_priorities_row_count"] = 1.0

                    produced_map = {row.get("topic", "").strip(): row for row in rows}

                    weights_ok = True
                    latest_ok = True
                    ps_ok = True
                    for topic in expected_topics_set:
                        row = produced_map.get(topic, {})
                        w_prod = _parse_float(row.get("weight", ""))
                        if w_prod is None or not _floats_close(w_prod, expected_tp["weights"][topic]):
                            weights_ok = False
                        ls_expected = expected_tp["latest_scores"][topic]
                        ls_cell = row.get("latest_score", "")
                        if ls_expected is None:
                            if ls_cell.strip() != "":
                                latest_ok = False
                        else:
                            ls_prod = _parse_int_strict(ls_cell)
                            if ls_prod is None or ls_prod != ls_expected:
                                latest_ok = False
                        ps_prod = _parse_float(row.get("priority_score", ""))
                        ps_expected = expected_tp["priority_scores"][topic]
                        if ps_prod is None or not _floats_close(ps_prod, ps_expected):
                            ps_ok = False
                    scores["topic_priorities_weights_correct"] = 1.0 if weights_ok else 0.0
                    scores["topic_priorities_latest_scores_correct"] = 1.0 if latest_ok else 0.0
                    scores["topic_priorities_priority_scores_correct"] = 1.0 if ps_ok else 0.0

                    ranks_ok = True
                    try:
                        produced_ranks = {}
                        for t, r in produced_map.items():
                            rk = _parse_int_strict(r.get("rank", ""))
                            if rk is None:
                                ranks_ok = False
                                break
                            produced_ranks[t] = rk
                        if ranks_ok:
                            n = len(expected_topics_set)
                            rank_values = list(produced_ranks.values())
                            if sorted(rank_values) != list(range(1, n + 1)):
                                ranks_ok = False
                            else:
                                for topic in expected_topics_set:
                                    if produced_ranks.get(topic) != expected_tp["ranks"][topic]:
                                        ranks_ok = False
                                        break
                    except Exception:
                        ranks_ok = False
                    scores["topic_priorities_ranking_correct"] = 1.0 if ranks_ok else 0.0
                else:
                    scores["topic_priorities_row_count"] = 0.0

    expected_flashcards = _extract_expected_flashcards(workspace)
    fc_path = workspace / "output" / "flashcards.jsonl"
    if fc_path.exists() and fc_path.is_file():
        scores["flashcards_file_exists"] = 1.0
        produced = _parse_jsonl(fc_path)
        if produced is not None and expected_flashcards is not None:
            if len(produced) == len(expected_flashcards):
                scores["flashcards_line_count"] = 1.0
            schema_ok = True
            required_keys = {"topic", "question", "answer", "source_file"}
            for rec in produced:
                if not isinstance(rec, dict):
                    schema_ok = False
                    break
                rec_keys = set(rec.keys())
                if rec_keys != required_keys:
                    schema_ok = False
                    break
                if not all(isinstance(rec[k], str) for k in required_keys):
                    schema_ok = False
                    break
            scores["flashcards_schema_valid"] = 1.0 if schema_ok else 0.0
            if schema_ok:
                expected_set = set((r["topic"], r["question"], r["answer"], r["source_file"]) for r in expected_flashcards)
                produced_set = set((r["topic"], r["question"], r["answer"], r["source_file"]) for r in produced if isinstance(r, dict))
                scores["flashcards_content_match"] = 1.0 if expected_set == produced_set else 0.0

    emails_path = workspace / "output" / "emails_rewritten.md"
    if emails_path.exists() and emails_path.is_file():
        scores["emails_file_exists"] = 1.0
        content = _safe_read_text(emails_path)
        if content is not None:
            sections = _parse_emails_sections(content)
            labels_ok = ("Draft 1" in sections) and ("Draft 2" in sections)
            scores["emails_labels_present"] = 1.0 if labels_ok else 0.0
            if labels_ok:
                d1 = sections.get("Draft 1", "").strip()
                d2 = sections.get("Draft 2", "").strip()
                scores["emails_draft1_nonempty"] = 1.0 if len(d1) > 0 else 0.0
                scores["emails_draft2_nonempty"] = 1.0 if len(d2) > 0 else 0.0
                wc1 = _word_count(d1)
                wc2 = _word_count(d2)
                scores["emails_draft1_word_limit"] = 1.0 if 0 < wc1 <= 120 else 0.0
                scores["emails_draft2_word_limit"] = 1.0 if 0 < wc2 <= 120 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()