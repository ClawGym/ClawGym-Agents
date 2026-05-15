import json
import csv
import sys
from pathlib import Path
from datetime import datetime


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Validate required columns
        required = {"parent_id", "grade", "topic", "question_en", "timestamp"}
        if not rows and reader.fieldnames is None:
            return None
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            return None
        return rows
    except Exception:
        return None


def _load_json_array(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _count_lines(path: Path):
    txt = _read_text(path)
    if txt is None:
        return None
    return len(txt.splitlines())


def _list_input_filenames(input_dir: Path):
    if not input_dir.exists() or not input_dir.is_dir():
        return None
    files = []
    try:
        for p in input_dir.iterdir():
            if p.is_file():
                files.append(p.name)
        return sorted(files)
    except Exception:
        return None


def _compute_topic_ranking(rows):
    counts = {}
    for r in rows:
        topic = (r.get("topic") or "").strip()
        if topic == "":
            continue
        counts[topic] = counts.get(topic, 0) + 1
    ranking = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return ranking


def _parse_ts(ts_str):
    try:
        return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _select_top_questions(rows, topic, k=2):
    # Group by question_en with frequency and earliest timestamp
    items = {}
    for r in rows:
        if (r.get("topic") or "").strip() != topic:
            continue
        q = (r.get("question_en") or "").strip()
        ts = _parse_ts((r.get("timestamp") or "").strip())
        if q == "" or ts is None:
            continue
        if q not in items:
            items[q] = {"count": 0, "earliest": ts}
        items[q]["count"] += 1
        if ts < items[q]["earliest"]:
            items[q]["earliest"] = ts
    ranked = sorted(items.items(), key=lambda x: (-x[1]["count"], x[1]["earliest"]))
    return [q for q, _meta in ranked[:k]]


def _select_top_tips(tips, topic, k=3):
    subset = []
    for t in tips:
        if not isinstance(t, dict):
            continue
        if (t.get("topic") or "").strip() != topic:
            continue
        tip_en = (t.get("tip_en") or "").strip()
        ev = t.get("evidence_level")
        if tip_en == "" or not isinstance(ev, int):
            continue
        subset.append((tip_en, ev))
    ranked = sorted(subset, key=lambda x: (-x[1], x[0]))
    return [tip for tip, _ev in ranked[:k]]


def _find_line_index(lines, target, start_idx=0):
    for i in range(start_idx, len(lines)):
        if lines[i] == target:
            return i
    return -1


def _is_spanish_line(line: str) -> bool:
    return line.startswith("[ES]")


def _parse_bullet_text(line: str):
    if line.startswith("- "):
        return line[2:]
    if line.startswith("* "):
        return line[2:]
    return None


def _safe_read_lines(path: Path):
    txt = _read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "processing_report_file_list": 0.0,
        "processing_report_counts": 0.0,
        "processing_report_tone_line": 0.0,
        "topic_ranking_correct": 0.0,
        "faq_title_structure": 0.0,
        "faq_disclaimers_pairs": 0.0,
        "faq_topic_1_section": 0.0,
        "faq_topic_2_section": 0.0,
        "faq_topic_3_section": 0.0,
    }

    # Paths
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    pq_csv = input_dir / "parent_questions.csv"
    tips_json = input_dir / "eye_health_tips.json"
    style_md = input_dir / "style_guide.md"

    proc_report = output_dir / "processing_report.txt"
    topic_rank_csv = output_dir / "topic_ranking.csv"
    faq_md = output_dir / "faq_en_es.md"

    # Gather inputs
    input_filenames = _list_input_filenames(input_dir) or []
    rows = _load_csv_rows(pq_csv) if pq_csv.exists() else None
    tips = _load_json_array(tips_json) if tips_json.exists() else None
    style_lines = _safe_read_lines(style_md) if style_md.exists() else None

    # Compute expected pieces
    # Processing report expectations
    expected_files = set(input_filenames)
    expected_csv_rows = len(rows) if rows is not None else None
    expected_json_items = len(tips) if tips is not None else None
    expected_md_lines = len(style_lines) if style_lines is not None else None
    expected_tone_line = None
    expected_disclaimers = []
    if style_lines is not None:
        for line in style_lines:
            if line.startswith("Tone note:"):
                expected_tone_line = line
            if line.startswith("Disclaimer (English):"):
                expected_disclaimers.append(line)

    # 1) processing_report checks
    report_lines = _safe_read_lines(proc_report)
    if report_lines is not None:
        # files list: ensure each input filename appears as a standalone line
        if expected_files:
            present_all = True
            for fn in expected_files:
                if fn not in report_lines:
                    present_all = False
                    break
            if present_all:
                scores["processing_report_file_list"] = 1.0
        else:
            # If there are no input files, we cannot validate; keep as 0.0
            pass

        # counts: ensure that lines include filename and correct count
        counts_ok = True
        # CSV rows
        if expected_csv_rows is None:
            counts_ok = False
        else:
            found = any(("parent_questions.csv" in ln and str(expected_csv_rows) in ln) for ln in report_lines)
            if not found:
                counts_ok = False
        # JSON items
        if expected_json_items is None:
            counts_ok = False
        else:
            found = any(("eye_health_tips.json" in ln and str(expected_json_items) in ln) for ln in report_lines)
            if not found:
                counts_ok = False
        # MD lines
        if expected_md_lines is None:
            counts_ok = False
        else:
            found = any(("style_guide.md" in ln and str(expected_md_lines) in ln) for ln in report_lines)
            if not found:
                counts_ok = False
        if counts_ok:
            scores["processing_report_counts"] = 1.0

        # tone line verbatim
        if expected_tone_line is not None and expected_tone_line in report_lines:
            scores["processing_report_tone_line"] = 1.0

    # 2) topic_ranking.csv correctness
    expected_ranking = None
    if rows is not None:
        ranking = _compute_topic_ranking(rows)
        expected_ranking = ranking

    if expected_ranking is not None and topic_rank_csv.exists():
        try:
            with topic_rank_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                header_ok = reader.fieldnames == ["topic", "question_count"]
                parsed = []
                for r in reader:
                    topic = (r.get("topic") or "").strip()
                    qc = (r.get("question_count") or "").strip()
                    parsed.append((topic, qc))
            if header_ok and len(parsed) == len(expected_ranking):
                all_ok = True
                for (exp_topic, exp_count), (got_topic, got_count) in zip(expected_ranking, parsed):
                    if got_topic != exp_topic:
                        all_ok = False
                        break
                    try:
                        if int(got_count) != int(exp_count):
                            all_ok = False
                            break
                    except Exception:
                        all_ok = False
                        break
                if all_ok:
                    scores["topic_ranking_correct"] = 1.0
        except Exception:
            pass

    # 3) faq_en_es.md structure and content
    faq_lines = _safe_read_lines(faq_md)
    if faq_lines is not None and len(faq_lines) >= 2:
        # Title structure
        first = faq_lines[0]
        second = faq_lines[1]
        if first.strip() != "" and not _is_spanish_line(first) and _is_spanish_line(second):
            scores["faq_title_structure"] = 1.0

        # Disclaimers presence with Spanish pairs in order
        if expected_disclaimers and len(expected_disclaimers) >= 2:
            # Find first disclaimer
            idx1 = _find_line_index(faq_lines, expected_disclaimers[0], 0)
            ok = False
            if idx1 != -1 and idx1 + 1 < len(faq_lines) and _is_spanish_line(faq_lines[idx1 + 1]):
                idx2 = _find_line_index(faq_lines, expected_disclaimers[1], idx1 + 2)
                if idx2 != -1 and idx2 + 1 < len(faq_lines) and _is_spanish_line(faq_lines[idx2 + 1]):
                    ok = True
            if ok:
                scores["faq_disclaimers_pairs"] = 1.0

        # Topics sections
        if expected_ranking is not None and tips is not None:
            # Determine top 3 topics
            top_topics = [t for t, c in expected_ranking[:3]]
            # Build expected questions and tips per topic
            topic_questions = {}
            for t in top_topics:
                topic_questions[t] = _select_top_questions(rows, t, k=2)
            topic_tips = {}
            for t in top_topics:
                topic_tips[t] = _select_top_tips(tips, t, k=3)

            # Scan faq lines sequentially to validate 3 sections in order
            start_idx = 0
            section_scores = [0.0, 0.0, 0.0]
            for idx_topic, topic in enumerate(top_topics):
                # Find topic heading
                heading = f"Topic: {topic}"
                h_idx = _find_line_index(faq_lines, heading, start_idx)
                good = True
                if h_idx == -1 or h_idx + 1 >= len(faq_lines) or not _is_spanish_line(faq_lines[h_idx + 1]):
                    good = False
                else:
                    k = h_idx + 2
                    # Two question bullets
                    exp_questions = topic_questions.get(topic, [])
                    if len(exp_questions) < 2:
                        good = False
                    else:
                        for q in exp_questions[:2]:
                            if k >= len(faq_lines):
                                good = False
                                break
                            eng_bullet_text = _parse_bullet_text(faq_lines[k])
                            if eng_bullet_text is None or eng_bullet_text != q:
                                good = False
                                break
                            if k + 1 >= len(faq_lines) or not _is_spanish_line(faq_lines[k + 1]):
                                good = False
                                break
                            k += 2
                    # Tips subheading
                    if good:
                        if k >= len(faq_lines) or faq_lines[k] != "Tips":
                            good = False
                        else:
                            if k + 1 >= len(faq_lines) or not _is_spanish_line(faq_lines[k + 1]):
                                good = False
                            else:
                                k += 2
                    # Tips bullets
                    if good:
                        exp_tips = topic_tips.get(topic, [])
                        # Up to 3 tips expected
                        if len(exp_tips) == 0:
                            good = False
                        else:
                            for tip in exp_tips:
                                if k >= len(faq_lines):
                                    good = False
                                    break
                                eng_bullet_text = _parse_bullet_text(faq_lines[k])
                                if eng_bullet_text is None or eng_bullet_text != tip:
                                    good = False
                                    break
                                if k + 1 >= len(faq_lines) or not _is_spanish_line(faq_lines[k + 1]):
                                    good = False
                                    break
                                k += 2
                    if good:
                        start_idx = k
                section_scores[idx_topic] = 1.0 if good else 0.0

            # Assign per-section scores
            if len(section_scores) >= 1:
                scores["faq_topic_1_section"] = section_scores[0]
            if len(section_scores) >= 2:
                scores["faq_topic_2_section"] = section_scores[1]
            if len(section_scores) >= 3:
                scores["faq_topic_3_section"] = section_scores[2]

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()