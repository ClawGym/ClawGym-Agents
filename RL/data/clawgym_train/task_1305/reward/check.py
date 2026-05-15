import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def split_sentences(text: str) -> List[str]:
    # Normalize whitespace
    normalized = re.sub(r'\s+', ' ', text).strip()
    if not normalized:
        return []
    # Split on sentence-ending punctuation followed by space
    parts = re.split(r'(?<=[.!?])\s+', normalized)
    # Clean parts
    return [p.strip() for p in parts if p.strip()]


def is_excerpt_1_or_2_sentences_from_remarks(excerpt: str, remarks: str) -> bool:
    if not excerpt or not remarks:
        return False
    excerpt_norm = re.sub(r'\s+', ' ', excerpt).strip()
    remarks_norm = re.sub(r'\s+', ' ', remarks).strip()
    if excerpt_norm not in remarks_norm:
        return False
    sentences = split_sentences(excerpt_norm)
    return 1 <= len(sentences) <= 2


def round1(x: float) -> float:
    return round(x * 10) / 10.0


def parse_percent_value(val) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if s.endswith("%"):
            s = s[:-1].strip()
        return float(s)
    except Exception:
        return None


def compute_topic_counts(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in rows:
        topic = r.get("topic")
        if topic is None:
            # Malformed row causes failure in checks using this computation
            return {}
        counts[topic] = counts.get(topic, 0) + 1
    return counts


def compute_sentiment_counts(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        s = r.get("sentiment")
        if s not in counts:
            # Malformed sentiment value leads to failure
            return {}
        counts[s] += 1
    return counts


def get_opening_after_subject(email_text: str) -> str:
    lines = email_text.splitlines()
    if not lines:
        return ""
    # Assume first line is subject
    body_lines = lines[1:]
    opening_lines: List[str] = []
    for line in body_lines:
        if line.strip() == "":
            break
        opening_lines.append(line)
    opening = " ".join(opening_lines).strip()
    if not opening:
        # If no blank-separated opening paragraph, fallback to first few sentences from body
        body = " ".join(body_lines).strip()
        sentences = split_sentences(body)
        opening = " ".join(sentences[:3]).strip()
    return opening


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "topic_summary_structure": 0.0,
        "topic_summary_values": 0.0,
        "sentiment_summary_structure": 0.0,
        "sentiment_summary_values": 0.0,
        "total_comments_consistency": 0.0,
        "training_plan_structure": 0.0,
        "training_plan_top_topics_correctness": 0.0,
        "training_plan_modules_topics_and_titles": 0.0,
        "training_plan_durations_correctness": 0.0,
        "training_plan_references_excerpt_validity": 0.0,
        "volunteer_invite_structure": 0.0,
        "volunteer_invite_opening_references": 0.0,
        "volunteer_invite_top_topics_summary": 0.0,
        "volunteer_invite_schedule_outline": 0.0,
        "volunteer_invite_rsvp_call": 0.0,
    }

    # Load inputs
    comments_path = workspace / "input" / "comments.csv"
    remarks_path = workspace / "input" / "remarks.txt"
    comments_rows, comments_fields = parse_csv(comments_path)
    remarks_text = read_text(remarks_path)

    # If inputs missing or malformed, many checks will fail gracefully
    if comments_rows is None or comments_fields is None or remarks_text is None:
        return scores

    total_comments = len(comments_rows)
    topic_counts = compute_topic_counts(comments_rows)
    sentiment_counts = compute_sentiment_counts(comments_rows)

    if not topic_counts or not sentiment_counts:
        # Malformed input rows
        return scores

    # Validate topic_summary.csv
    topic_summary_path = workspace / "output" / "stats" / "topic_summary.csv"
    ts_rows, ts_fields = parse_csv(topic_summary_path)
    if ts_rows is not None and ts_fields is not None:
        expected_fields = ["topic", "total_count", "percent_of_all"]
        if ts_fields == expected_fields:
            # Structure: must include every topic present in input and no extras (strict equality)
            ts_topics = [r.get("topic") for r in ts_rows if r.get("topic") is not None]
            if len(ts_topics) == len(set(ts_topics)) and set(ts_topics) == set(topic_counts.keys()):
                scores["topic_summary_structure"] = 1.0

            # Values correctness: counts and percents match computed, for all topics
            all_ok = True
            for r in ts_rows:
                t = r.get("topic")
                cnt_str = r.get("total_count")
                pct_str = r.get("percent_of_all")
                if t is None or cnt_str is None or pct_str is None:
                    all_ok = False
                    break
                try:
                    cnt = int(cnt_str)
                except Exception:
                    all_ok = False
                    break
                pct = parse_percent_value(pct_str)
                if pct is None:
                    all_ok = False
                    break
                expected_cnt = topic_counts.get(t)
                if expected_cnt is None or expected_cnt != cnt:
                    all_ok = False
                    break
                expected_pct = round1(expected_cnt * 100.0 / total_comments) if total_comments > 0 else 0.0
                if round1(pct) != expected_pct:
                    all_ok = False
                    break
            if all_ok:
                scores["topic_summary_values"] = 1.0

    # Validate sentiment_summary.json
    sentiment_summary_path = workspace / "output" / "stats" / "sentiment_summary.json"
    ss_json = load_json(sentiment_summary_path)
    if ss_json is not None and isinstance(ss_json, dict):
        struct_ok = True
        if not isinstance(ss_json.get("total_comments"), int):
            struct_ok = False
        counts_obj = ss_json.get("counts")
        if not isinstance(counts_obj, dict):
            struct_ok = False
        else:
            for k in ("positive", "neutral", "negative"):
                if not isinstance(counts_obj.get(k), int):
                    struct_ok = False
        percentages_obj = ss_json.get("percentages")
        if not isinstance(percentages_obj, dict):
            struct_ok = False
        else:
            for k in ("positive", "neutral", "negative"):
                pv = percentages_obj.get(k)
                if parse_percent_value(pv) is None:
                    struct_ok = False
        if struct_ok:
            scores["sentiment_summary_structure"] = 1.0

        # Values correctness
        values_ok = True
        if ss_json.get("total_comments") != total_comments:
            values_ok = False
        else:
            exp_pos = sentiment_counts.get("positive")
            exp_neu = sentiment_counts.get("neutral")
            exp_neg = sentiment_counts.get("negative")
            if exp_pos is None or exp_neu is None or exp_neg is None:
                values_ok = False
            else:
                if counts_obj.get("positive") != exp_pos or counts_obj.get("neutral") != exp_neu or counts_obj.get("negative") != exp_neg:
                    values_ok = False
                else:
                    exp_pos_pct = round1(exp_pos * 100.0 / total_comments) if total_comments > 0 else 0.0
                    exp_neu_pct = round1(exp_neu * 100.0 / total_comments) if total_comments > 0 else 0.0
                    exp_neg_pct = round1(exp_neg * 100.0 / total_comments) if total_comments > 0 else 0.0
                    pos_pct = parse_percent_value(percentages_obj.get("positive"))
                    neu_pct = parse_percent_value(percentages_obj.get("neutral"))
                    neg_pct = parse_percent_value(percentages_obj.get("negative"))
                    if pos_pct is None or neu_pct is None or neg_pct is None:
                        values_ok = False
                    else:
                        if round1(pos_pct) != exp_pos_pct or round1(neu_pct) != exp_neu_pct or round1(neg_pct) != exp_neg_pct:
                            values_ok = False
        if values_ok:
            scores["sentiment_summary_values"] = 1.0

    # Validate training_plan.json
    training_plan_path = workspace / "output" / "curriculum" / "training_plan.json"
    tp_json = load_json(training_plan_path)
    top3_expected: List[Tuple[str, int, float]] = []
    if ts_rows is not None and ts_fields is not None and ts_fields == ["topic", "total_count", "percent_of_all"]:
        # Compute top 3 from topic_summary.csv (as required)
        try:
            summary_counts = {}
            summary_perc = {}
            for r in ts_rows:
                t = r["topic"]
                cnt = int(r["total_count"])
                pct = parse_percent_value(r["percent_of_all"])
                if pct is None:
                    raise ValueError("bad percent")
                summary_counts[t] = cnt
                summary_perc[t] = round1(pct)
            # Sort by count desc, then topic name asc for determinism
            sorted_topics = sorted(summary_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            top3_expected = [(t, summary_counts[t], summary_perc[t]) for t, _ in sorted_topics[:3]]
        except Exception:
            top3_expected = []

    if tp_json is not None and isinstance(tp_json, dict):
        struct_ok = True
        # Required fields
        if not isinstance(tp_json.get("total_comments"), int):
            struct_ok = False
        top_topics = tp_json.get("top_topics")
        modules = tp_json.get("modules")
        if not (isinstance(top_topics, list) and len(top_topics) == 3 and all(isinstance(x, dict) for x in top_topics)):
            struct_ok = False
        else:
            for x in top_topics:
                if not all(k in x for k in ("topic", "count", "percent")):
                    struct_ok = False
                if not isinstance(x.get("topic"), str):
                    struct_ok = False
                # count should be int; percent can be number or str convertible
                if not isinstance(x.get("count"), int):
                    struct_ok = False
                if parse_percent_value(x.get("percent")) is None:
                    struct_ok = False
        if not (isinstance(modules, list) and len(modules) == 4):
            struct_ok = False
        else:
            for m in modules:
                if not isinstance(m, dict):
                    struct_ok = False
                    break
                for k in ("id", "title", "topic", "duration_minutes", "learning_objectives", "content_outline", "references"):
                    if k not in m:
                        struct_ok = False
                if not isinstance(m.get("id"), str) or not m.get("id"):
                    struct_ok = False
                if not isinstance(m.get("title"), str) or not m.get("title"):
                    struct_ok = False
                if not isinstance(m.get("topic"), str):
                    struct_ok = False
                if not isinstance(m.get("duration_minutes"), int):
                    struct_ok = False
                lo = m.get("learning_objectives")
                co = m.get("content_outline")
                if not (isinstance(lo, list) and 3 <= len(lo) <= 5 and all(isinstance(s, str) and s.strip() for s in lo)):
                    struct_ok = False
                if not (isinstance(co, list) and 4 <= len(co) <= 8 and all(isinstance(s, str) and s.strip() for s in co)):
                    struct_ok = False
                refs = m.get("references")
                if not isinstance(refs, dict):
                    struct_ok = False
                else:
                    if refs.get("comments_source") != "input/comments.csv":
                        struct_ok = False
                    if not isinstance(refs.get("official_dismissal_excerpt"), str) or not refs.get("official_dismissal_excerpt").strip():
                        struct_ok = False
        if struct_ok:
            scores["training_plan_structure"] = 1.0

        # total_comments consistency across outputs
        ss_total = None
        if ss_json is not None and isinstance(ss_json, dict):
            ss_total = ss_json.get("total_comments")
        if isinstance(ss_total, int) and tp_json.get("total_comments") == total_comments and ss_total == total_comments:
            scores["total_comments_consistency"] = 1.0

        # Top topics correctness vs topic_summary.csv
        if top3_expected and isinstance(top_topics, list):
            expected_topics_set = {t for t, _, _ in top3_expected}
            actual_topics_set = {tt.get("topic") for tt in top_topics if isinstance(tt, dict)}
            topics_ok = actual_topics_set == expected_topics_set
            counts_pcts_ok = True
            if topics_ok:
                # Verify counts and percents match exactly for those topics
                exp_map = {t: (cnt, pct) for t, cnt, pct in top3_expected}
                for tt in top_topics:
                    t = tt.get("topic")
                    cnt = tt.get("count")
                    pct_val = parse_percent_value(tt.get("percent"))
                    if t not in exp_map or not isinstance(cnt, int) or pct_val is None:
                        counts_pcts_ok = False
                        break
                    exp_cnt, exp_pct = exp_map[t]
                    if cnt != exp_cnt or round1(pct_val) != exp_pct:
                        counts_pcts_ok = False
                        break
            else:
                counts_pcts_ok = False
            if topics_ok and counts_pcts_ok:
                scores["training_plan_top_topics_correctness"] = 1.0

        # Modules topics and titles, including Case Study module
        modules_ok = False
        if isinstance(modules, list) and top3_expected:
            expected_top_topics = {t for t, _, _ in top3_expected}
            # One module per top topic with title mapping to topic (title contains topic)
            has_top_modules = True
            for t in expected_top_topics:
                found = False
                for m in modules:
                    if isinstance(m, dict) and m.get("topic") == t:
                        title = m.get("title", "")
                        if isinstance(title, str) and t.lower() in title.lower():
                            found = True
                            break
                if not found:
                    has_top_modules = False
                    break
            # Additional Case Study module with topic dismissal_response
            case_modules = [m for m in modules if isinstance(m, dict) and m.get("topic") == "dismissal_response" and isinstance(m.get("title"), str) and "case study" in m.get("title").lower()]
            has_case_study = len(case_modules) >= 1
            # Exactly 4 modules total
            modules_ok = has_top_modules and has_case_study and len(modules) == 4
        if modules_ok:
            scores["training_plan_modules_topics_and_titles"] = 1.0

        # Module durations correctness
        durations_ok = False
        if isinstance(modules, list):
            ok = True
            for m in modules:
                t = m.get("topic")
                dur = m.get("duration_minutes")
                if t is None or not isinstance(dur, int):
                    ok = False
                    break
                cnt_for_topic = topic_counts.get(t)
                if cnt_for_topic is None:
                    ok = False
                    break
                expected_dur = 20 + 5 * cnt_for_topic
                if dur != expected_dur:
                    ok = False
                    break
            durations_ok = ok
        if durations_ok:
            scores["training_plan_durations_correctness"] = 1.0

        # References excerpt validity (1–2 sentences direct excerpt from remarks)
        refs_ok = False
        if isinstance(modules, list) and isinstance(remarks_text, str):
            ok = True
            for m in modules:
                refs = m.get("references")
                if not isinstance(refs, dict):
                    ok = False
                    break
                excerpt = refs.get("official_dismissal_excerpt")
                if not isinstance(excerpt, str) or not is_excerpt_1_or_2_sentences_from_remarks(excerpt, remarks_text):
                    ok = False
                    break
            refs_ok = ok
        if refs_ok:
            scores["training_plan_references_excerpt_validity"] = 1.0

    # Validate volunteer_invite.txt
    invite_path = workspace / "output" / "messaging" / "volunteer_invite.txt"
    invite_text = read_text(invite_path)
    if invite_text is not None:
        lines = invite_text.splitlines()
        if len(lines) >= 1 and lines[0].strip().startswith("Training Invite:"):
            scores["volunteer_invite_structure"] = 1.0

        # Opening paragraph: 2–3 sentences referencing accountability and incident drawn from remarks
        opening = get_opening_after_subject(invite_text)
        opening_sentences = split_sentences(opening)
        has_2_to_3 = 2 <= len(opening_sentences) <= 3
        mentions_accountability = "accountability" in opening.lower()
        # Check opening contains a direct excerpt fragment from remarks (any sentence substring)
        remarks_sentences = split_sentences(remarks_text)
        opening_contains_excerpt = False
        for rs in remarks_sentences:
            rs_norm = re.sub(r'\s+', ' ', rs).strip()
            if rs_norm and rs_norm in re.sub(r'\s+', ' ', opening).strip():
                opening_contains_excerpt = True
                break
        if has_2_to_3 and mentions_accountability and opening_contains_excerpt:
            scores["volunteer_invite_opening_references"] = 1.0

        # Top topics summary: list each topic with its count and percent_of_all from topic_summary.csv
        top_topics_for_email_ok = False
        if ts_rows is not None and top3_expected:
            # Build expected strings
            email_text_norm = invite_text
            ok = True
            for t, cnt, pct in top3_expected:
                # topic name must appear; count must appear; percent value must appear (with or without %)
                topic_present = t in email_text_norm
                count_present = str(cnt) in email_text_norm
                pct_present = (f"{pct}%" in email_text_norm) or (str(pct) in email_text_norm)
                if not (topic_present and count_present and pct_present):
                    ok = False
                    break
            top_topics_for_email_ok = ok
        if top_topics_for_email_ok:
            scores["volunteer_invite_top_topics_summary"] = 1.0

        # Schedule outline: list each module title with its duration_minutes
        schedule_ok = False
        if tp_json is not None and isinstance(tp_json.get("modules"), list):
            modules = tp_json["modules"]
            lines_lower = [l.lower() for l in lines]
            ok = True
            for m in modules:
                title = m.get("title")
                dur = m.get("duration_minutes")
                if not isinstance(title, str) or not isinstance(dur, int):
                    ok = False
                    break
                # Find a line containing the title (case-insensitive) and the duration integer
                found = False
                for idx, line in enumerate(lines):
                    if title.lower() in lines_lower[idx] and str(dur) in line:
                        found = True
                        break
                if not found:
                    ok = False
                    break
            schedule_ok = ok
        if schedule_ok:
            scores["volunteer_invite_schedule_outline"] = 1.0

        # Clear call to RSVP by replying to the email
        rsvp_present = ("rsvp" in invite_text.lower()) and ("reply" in invite_text.lower())
        if rsvp_present:
            scores["volunteer_invite_rsvp_call"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()