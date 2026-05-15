import json
import csv
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter

# Helper functions

def parse_iso8601(s: str) -> datetime:
    if s is None:
        raise ValueError("None timestamp")
    s = s.strip()
    # Support trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def load_jsonl(path: Path):
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                lines.append(obj)
        return lines
    except Exception:
        return None

def load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames if reader.fieldnames is not None else []
            return header, rows
    except Exception:
        return None, None

def load_audience_weights(path: Path):
    header, rows = load_csv_rows(path)
    if header is None or rows is None:
        return None
    weights = {}
    for r in rows:
        topic = r.get("topic")
        w = r.get("weight")
        if topic is None or w is None:
            return None
        try:
            weights[topic] = float(w)
        except Exception:
            return None
    return weights

def load_reference_time(path: Path):
    # Minimal YAML parser for "reference_time: <iso>"
    text = safe_read_text(path)
    if not text:
        return None
    ref = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if key == "reference_time":
            # Remove possible quotes
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            try:
                ref = parse_iso8601(val)
            except Exception:
                return None
            break
    return ref

def priority_to_boost(priority: str) -> float:
    mapping = {"high": 1.0, "normal": 0.5, "low": 0.0}
    return mapping.get((priority or "").strip().lower(), 0.0)

def compute_scores_for_story(story: dict, ref_time: datetime, weights: dict) -> dict:
    ts = parse_iso8601(story["timestamp"])
    hours_since = (ref_time - ts).total_seconds() / 3600.0
    if hours_since < 0:
        hours_since = 0.0  # should not happen for eligible, but guard
    recency_score = max(0.0, 1.0 - (hours_since / 48.0))
    pr_boost = priority_to_boost(story.get("priority", ""))
    topic = story.get("topic", "")
    audience_weight = weights.get(topic, 0.5)
    lineup_score = 0.6 * audience_weight + 0.3 * pr_boost + 0.1 * recency_score
    return {
        "hours_since": hours_since,
        "recency_score": recency_score,
        "priority_boost": pr_boost,
        "audience_weight": audience_weight,
        "lineup_score": lineup_score,
    }

def float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol

def try_parse_float(s):
    try:
        return float(s)
    except Exception:
        return None

def try_parse_int(s):
    try:
        return int(s)
    except Exception:
        return None

def build_expected_outputs(workspace: Path):
    # Load inputs
    headlines_path = workspace / "input" / "headlines.jsonl"
    weights_path = workspace / "input" / "audience_weights.csv"
    ref_path = workspace / "input" / "reference.yaml"

    headlines = load_jsonl(headlines_path)
    weights = load_audience_weights(weights_path)
    ref_time = load_reference_time(ref_path)

    if headlines is None or weights is None or ref_time is None:
        return None

    # Eligibility
    eligible = []
    for h in headlines:
        try:
            ts = parse_iso8601(h.get("timestamp"))
            embargo = parse_iso8601(h.get("embargo_until"))
        except Exception:
            # Malformed time in input; treat as non-eligible by failing to compute expected
            return None
        if ts <= ref_time and embargo <= ref_time:
            eligible.append(h)

    # Deduplication by title (trimmed, case-insensitive)
    def dedup_key(h):
        title = h.get("title", "")
        return title.strip().lower()

    chosen = {}
    for h in eligible:
        key = dedup_key(h)
        current = chosen.get(key)
        if current is None:
            chosen[key] = h
        else:
            # Compare: most recent timestamp; if tie, higher priority; if tie, lexicographically smallest source
            try:
                ts_new = parse_iso8601(h["timestamp"])
                ts_old = parse_iso8601(current["timestamp"])
            except Exception:
                return None
            if ts_new > ts_old:
                chosen[key] = h
            elif ts_new == ts_old:
                pr_new = priority_to_boost(h.get("priority", ""))
                pr_old = priority_to_boost(current.get("priority", ""))
                if pr_new > pr_old:
                    chosen[key] = h
                elif pr_new == pr_old:
                    src_new = (h.get("source") or "")
                    src_old = (current.get("source") or "")
                    if src_new < src_old:
                        chosen[key] = h
                    # else keep old
            # else keep old

    deduped = list(chosen.values())

    # Compute scores
    expected_rows = []
    for h in deduped:
        scores = compute_scores_for_story(h, ref_time, weights)
        # Keep useful parsed timestamps for sorting
        row = {
            "id": h.get("id"),
            "title": h.get("title"),
            "source": h.get("source"),
            "topic": h.get("topic"),
            "region": h.get("region"),
            "timestamp": h.get("timestamp"),
            "embargo_until": h.get("embargo_until"),
            "priority": h.get("priority"),
            "hours_since": scores["hours_since"],
            "recency_score": scores["recency_score"],
            "audience_weight": scores["audience_weight"],
            "priority_boost": scores["priority_boost"],
            "lineup_score": scores["lineup_score"],
            "_timestamp_dt": parse_iso8601(h.get("timestamp")),
        }
        expected_rows.append(row)

    # Sort for eligible_stories.csv: lineup_score desc then timestamp desc
    expected_eligible_sorted = sorted(
        expected_rows,
        key=lambda r: (r["lineup_score"], r["_timestamp_dt"]),
        reverse=True,
    )

    # Compute top_lineup selection: sort by lineup_score desc, break ties by recency_score desc, then title asc
    ranking_sorted = sorted(
        expected_rows,
        key=lambda r: (r["lineup_score"], r["recency_score"], r["title"]),
        reverse=True,
    )
    # Apply per-topic cap of 3 and keep top 10
    topic_counts = defaultdict(int)
    selected = []
    for r in ranking_sorted:
        if topic_counts[r["topic"]] < 3:
            selected.append(r)
            topic_counts[r["topic"]] += 1
        if len(selected) >= 10:
            break

    # Build summary_by_topic from eligible and selected
    by_topic = defaultdict(list)
    for r in expected_rows:
        by_topic[r["topic"]].append(r)
    selected_by_topic = defaultdict(int)
    for r in selected:
        selected_by_topic[r["topic"]] += 1

    summary_expected = {}
    for topic, rows in by_topic.items():
        eligible_count = len(rows)
        selected_count = selected_by_topic.get(topic, 0)
        avg_lineup = sum(r["lineup_score"] for r in rows) / eligible_count if eligible_count else 0.0
        avg_title_len = sum(len(r["title"] or "") for r in rows) / eligible_count if eligible_count else 0.0
        # most_common_source: highest count among eligible for that topic; break ties alphabetically
        sources = [r["source"] or "" for r in rows]
        counts = Counter(sources)
        max_count = max(counts.values()) if counts else 0
        candidates = [src for src, cnt in counts.items() if cnt == max_count]
        most_common_source = min(candidates) if candidates else ""
        summary_expected[topic] = {
            "topic": topic,
            "eligible_count": eligible_count,
            "selected_count": selected_count,
            "avg_lineup_score": avg_lineup,
            "avg_title_length": avg_title_len,
            "most_common_source": most_common_source,
        }

    return {
        "eligible_sorted": expected_eligible_sorted,
        "selected": selected,
        "summary": summary_expected,
    }

def load_output_csv(path: Path):
    header, rows = load_csv_rows(path)
    if header is None or rows is None:
        return None, None
    return header, rows

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "eligible_stories_file_header": 0.0,
        "eligible_stories_set_correct": 0.0,
        "eligible_stories_computed_fields_correct": 0.0,
        "eligible_stories_sorting_correct": 0.0,
        "top_lineup_file_header": 0.0,
        "top_lineup_selection_and_order_correct": 0.0,
        "top_lineup_topic_cap_enforced": 0.0,
        "summary_by_topic_file_header": 0.0,
        "summary_by_topic_content_correct": 0.0,
        "cross_file_consistency": 0.0,
    }

    expected = build_expected_outputs(workspace)
    # If inputs malformed, we cannot compute expected; all checks will remain 0.0
    if expected is None:
        return scores

    eligible_expected = expected["eligible_sorted"]
    selected_expected = expected["selected"]
    summary_expected = expected["summary"]

    # Load outputs
    elig_path = workspace / "output" / "eligible_stories.csv"
    top_path = workspace / "output" / "top_lineup.csv"
    summ_path = workspace / "output" / "summary_by_topic.csv"

    # Eligible stories checks
    elig_header, elig_rows = load_output_csv(elig_path)
    expected_elig_header = [
        "id", "title", "source", "topic", "region", "timestamp", "embargo_until", "priority",
        "hours_since", "recency_score", "audience_weight", "priority_boost", "lineup_score"
    ]
    if elig_header == expected_elig_header and elig_rows is not None:
        scores["eligible_stories_file_header"] = 1.0

    if elig_rows is not None:
        # Set correctness by IDs
        actual_ids = {r.get("id") for r in elig_rows if "id" in r}
        expected_ids = {r["id"] for r in eligible_expected}
        if actual_ids == expected_ids and len(actual_ids) == len(eligible_expected):
            scores["eligible_stories_set_correct"] = 1.0

        # Computed fields correct
        computed_ok = True
        # Build map from id to row for actual
        actual_by_id = {}
        for r in elig_rows:
            rid = r.get("id")
            if rid is not None:
                actual_by_id[rid] = r

        for exp in eligible_expected:
            rid = exp["id"]
            act = actual_by_id.get(rid)
            if act is None:
                computed_ok = False
                break
            # Check basic fields
            for k in ["title", "source", "topic", "region", "priority"]:
                if (act.get(k) or "") != (exp.get(k) or ""):
                    computed_ok = False
                    break
            if not computed_ok:
                break
            # Check timestamps: parse and compare equality
            try:
                act_ts = parse_iso8601(act.get("timestamp", ""))
                exp_ts = parse_iso8601(exp.get("timestamp", ""))
                if act_ts != exp_ts:
                    computed_ok = False
                    break
                act_emb = parse_iso8601(act.get("embargo_until", ""))
                exp_emb = parse_iso8601(exp.get("embargo_until", ""))
                if act_emb != exp_emb:
                    computed_ok = False
                    break
            except Exception:
                computed_ok = False
                break
            # Check numeric fields with tolerance
            for k in ["hours_since", "recency_score", "audience_weight", "priority_boost", "lineup_score"]:
                val = try_parse_float(act.get(k))
                if val is None or not float_eq(val, float(exp[k]), tol=1e-6):
                    computed_ok = False
                    break
            if not computed_ok:
                break
        if computed_ok and len(elig_rows) == len(eligible_expected):
            scores["eligible_stories_computed_fields_correct"] = 1.0

        # Sorting correct: compare ordered sequence of IDs
        actual_order_ids = [r.get("id") for r in elig_rows]
        expected_order_ids = [r["id"] for r in eligible_expected]
        if actual_order_ids == expected_order_ids:
            scores["eligible_stories_sorting_correct"] = 1.0

    # Top lineup checks
    top_header, top_rows = load_output_csv(top_path)
    expected_top_header = ["rank", "id", "title", "topic", "source", "lineup_score", "recency_score", "priority", "region"]
    if top_header == expected_top_header and top_rows is not None:
        scores["top_lineup_file_header"] = 1.0

    if top_rows is not None:
        # Check rank sequence and selection/order
        expected_ids_seq = [r["id"] for r in selected_expected]
        actual_ids_seq = [r.get("id") for r in top_rows]
        # Enforce rank 1..N sequential
        ranks_ok = True
        for idx, r in enumerate(top_rows, 1):
            rank_val = try_parse_int(r.get("rank"))
            if rank_val != idx:
                ranks_ok = False
                break
        selection_ok = (actual_ids_seq == expected_ids_seq)
        if ranks_ok and selection_ok and len(top_rows) == len(selected_expected):
            scores["top_lineup_selection_and_order_correct"] = 1.0

        # Topic cap enforced (<=3 per topic)
        topic_counts = defaultdict(int)
        cap_ok = True
        for r in top_rows:
            t = r.get("topic")
            topic_counts[t] += 1
            if topic_counts[t] > 3:
                cap_ok = False
                break
        if cap_ok:
            scores["top_lineup_topic_cap_enforced"] = 1.0

    # Summary by topic checks
    summ_header, summ_rows = load_output_csv(summ_path)
    expected_summ_header = ["topic", "eligible_count", "selected_count", "avg_lineup_score", "avg_title_length", "most_common_source"]
    if summ_header == expected_summ_header and summ_rows is not None:
        scores["summary_by_topic_file_header"] = 1.0

    if summ_rows is not None:
        # Compare content regardless of order
        summ_by_topic = {}
        try:
            for r in summ_rows:
                topic = r.get("topic")
                if topic is None:
                    summ_by_topic = None
                    break
                elig_cnt = try_parse_int(r.get("eligible_count"))
                sel_cnt = try_parse_int(r.get("selected_count"))
                avg_lineup = try_parse_float(r.get("avg_lineup_score"))
                avg_title_len = try_parse_float(r.get("avg_title_length"))
                mcs = r.get("most_common_source")
                if None in (elig_cnt, sel_cnt, avg_lineup, avg_title_len) or mcs is None:
                    summ_by_topic = None
                    break
                summ_by_topic[topic] = {
                    "eligible_count": elig_cnt,
                    "selected_count": sel_cnt,
                    "avg_lineup_score": avg_lineup,
                    "avg_title_length": avg_title_len,
                    "most_common_source": mcs,
                }
        except Exception:
            summ_by_topic = None

        if summ_by_topic is not None:
            topics_expected = set(summary_expected.keys())
            topics_actual = set(summ_by_topic.keys())
            content_ok = True
            if topics_actual != topics_expected:
                content_ok = False
            else:
                for topic in topics_expected:
                    exp = summary_expected[topic]
                    act = summ_by_topic[topic]
                    if act["eligible_count"] != exp["eligible_count"]:
                        content_ok = False
                        break
                    if act["selected_count"] != exp["selected_count"]:
                        content_ok = False
                        break
                    if not float_eq(act["avg_lineup_score"], exp["avg_lineup_score"], tol=1e-6):
                        content_ok = False
                        break
                    if not float_eq(act["avg_title_length"], exp["avg_title_length"], tol=1e-6):
                        content_ok = False
                        break
                    if act["most_common_source"] != exp["most_common_source"]:
                        content_ok = False
                        break
            if content_ok:
                scores["summary_by_topic_content_correct"] = 1.0

    # Cross-file consistency: summary counts align with eligible/top_lineup
    if elig_rows is not None and top_rows is not None and summ_rows is not None and len(elig_rows) > 0 and len(summ_rows) > 0:
        try:
            # Build counts from actual files
            elig_topic_counts = defaultdict(int)
            for r in elig_rows:
                t = r.get("topic")
                if t is None:
                    raise ValueError("Missing topic in eligible row")
                elig_topic_counts[t] += 1
            top_topic_counts = defaultdict(int)
            for r in top_rows:
                t = r.get("topic")
                if t is None:
                    raise ValueError("Missing topic in top lineup row")
                top_topic_counts[t] += 1
            consistent = True
            for r in summ_rows:
                t = r.get("topic")
                if t is None:
                    consistent = False
                    break
                e_cnt = try_parse_int(r.get("eligible_count"))
                s_cnt = try_parse_int(r.get("selected_count"))
                if e_cnt is None or s_cnt is None:
                    consistent = False
                    break
                if elig_topic_counts.get(t, 0) != e_cnt:
                    consistent = False
                    break
                if top_topic_counts.get(t, 0) != s_cnt:
                    consistent = False
                    break
            if consistent:
                scores["cross_file_consistency"] = 1.0
        except Exception:
            scores["cross_file_consistency"] = 0.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()