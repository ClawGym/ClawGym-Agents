import csv
import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_simple_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Minimal YAML parser for simple mappings with 2-space indent, suitable for provided weights.yaml
    # Supports:
    # key: value
    # key:
    #   child: value
    # Values parsed as int/float where possible, strips quotes from strings
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]

    def parse_val(raw: str) -> Any:
        raw = raw.strip()
        if raw == "" or raw is None:
            return ""
        # Strip quotes
        if len(raw) >= 2 and ((raw[0] == raw[-1] == '"') or (raw[0] == raw[-1] == "'")):
            raw = raw[1:-1]
        # Try int
        try:
            if re.fullmatch(r"-?\d+", raw):
                return int(raw)
        except Exception:
            pass
        # Try float
        try:
            if re.fullmatch(r"-?\d+\.\d+", raw):
                return float(raw)
        except Exception:
            pass
        # Booleans?
        if raw.lower() == "true":
            return True
        if raw.lower() == "false":
            return False
        return raw

    for line in lines:
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key_val = line.strip()
        if ":" not in key_val:
            # Not supported structure
            return None
        key, sep, val = key_val.partition(":")
        key = key.strip()
        val = val.strip()
        # Find parent dict by indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if val == "":
            # New nested dict
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent, new_dict))
        else:
            current[key] = parse_val(val)
    return root


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _min_max_normalize(values: List[float]) -> List[float]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        return [0.0 for _ in values]
    return [(v - vmin) / (vmax - vmin) for v in values]


def _is_close(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def _compute_scores(eng_rows: List[Dict[str, str]], weights: Dict[str, Any], today_dt: datetime) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    # Returns map topic_id -> computed fields and ordered list of topic_ids
    # Extract metrics
    ctrs: List[float] = []
    times: List[float] = []
    inv_bounces: List[float] = []
    conversions: List[float] = []
    recency_scores: List[float] = []
    weeks_since_last_list: List[int] = []
    parsed_dates: List[Optional[datetime]] = []

    for r in eng_rows:
        ctrs.append(float(r["click_through_rate"]))
        times.append(float(r["avg_time_seconds"]))
        inv_bounces.append(1.0 - float(r["bounce_rate"]))
        conversions.append(float(r["conversions"]))
        lp = _parse_date(r["last_published_date"])
        parsed_dates.append(lp)
        if lp is None:
            weeks_since_last_list.append(0)
            recency_scores.append(0.0)
        else:
            days = (today_dt - lp).days
            weeks_since = days // 7 if days >= 0 else 0
            weeks_since_last_list.append(weeks_since)
            recency = 1.0 - min(weeks_since / 12.0, 1.0)
            recency_scores.append(recency)

    norm_ctr = _min_max_normalize(ctrs)
    norm_time = _min_max_normalize(times)
    norm_inv_bounce = _min_max_normalize(inv_bounces)
    norm_conv = _min_max_normalize(conversions)
    norm_recency = _min_max_normalize(recency_scores)

    # Weights
    w = weights.get("weights", {})
    w_ctr = float(w.get("click_through_rate", 0.0))
    w_time = float(w.get("avg_time_seconds", 0.0))
    w_invb = float(w.get("inverse_bounce", 0.0))
    w_conv = float(w.get("conversions", 0.0))
    w_rec = float(w.get("recency", 0.0))
    stage_bonus_map = w.get("pipeline_stage_bonus", {}) if isinstance(w.get("pipeline_stage_bonus", {}), dict) else {}
    # Compute finals
    topic_map: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for i, r in enumerate(eng_rows):
        tid = r["topic_id"]
        stage = r.get("pipeline_stage", "")
        bonus = float(stage_bonus_map.get(stage, 0.0)) if isinstance(stage_bonus_map, dict) else 0.0
        score = (
            norm_ctr[i] * w_ctr
            + norm_time[i] * w_time
            + norm_inv_bounce[i] * w_invb
            + norm_conv[i] * w_conv
            + norm_recency[i] * w_rec
            + bonus
        )
        topic_map[tid] = {
            "topic_id": tid,
            "topic": r["topic"],
            "persona": r["persona"],
            "channel": r["channel"],
            "pipeline_stage": stage,
            "last_published_date": r["last_published_date"],
            "norm_ctr": norm_ctr[i],
            "norm_time": norm_time[i],
            "norm_inv_bounce": norm_inv_bounce[i],
            "norm_conversions": norm_conv[i],
            "norm_recency": norm_recency[i],
            "pipeline_stage_bonus": bonus,
            "final_score": score,
        }
        order.append(tid)
    return topic_map, order


def _extract_sections(md_text: str) -> Dict[str, Tuple[int, int]]:
    # Returns mapping of lowercased section name keyword to (start_line_idx, end_line_idx_exclusive)
    lines = md_text.splitlines()
    # Identify headings by presence of known keywords
    headings = [
        "inputs summary",
        "scoring method",
        "top 5 topics by final_score",
        "scheduling decisions",
        "risks/assumptions",
    ]
    positions: Dict[str, int] = {}
    for i, line in enumerate(lines):
        low = line.strip().lower()
        for h in headings:
            if h in low and h not in positions:
                positions[h] = i
    sections: Dict[str, Tuple[int, int]] = {}
    # Determine end index for each as next heading or end of file
    for h in headings:
        if h in positions:
            start = positions[h]
            # Find next start
            later_positions = [positions[h2] for h2 in headings if h2 in positions and positions[h2] > start]
            end = min(later_positions) if later_positions else len(lines)
            sections[h] = (start, end)
    return sections


def _get_numbers_in_text(text: str) -> List[float]:
    nums: List[float] = []
    for m in re.finditer(r"[-+]?\d*\.\d+|[-+]?\d+", text):
        try:
            nums.append(float(m.group()))
        except Exception:
            continue
    return nums


def _get_end_of_window(start_date: datetime, weeks: int) -> datetime:
    last_week_start = start_date + timedelta(days=7 * (weeks - 1))
    end_date = last_week_start + timedelta(days=6)
    return end_date


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "scored_topics_file_exists_and_schema": 0.0,
        "scored_topics_row_count_matches_input": 0.0,
        "scored_topics_values_correct": 0.0,
        "calendar_file_exists_and_schema": 0.0,
        "calendar_weeks_and_capacity_exact": 0.0,
        "calendar_channels_match_input_and_unique_topics": 0.0,
        "calendar_feature_tie_in_labels_valid": 0.0,
        "calendar_persona_coverage_all_personas": 0.0,
        "calendar_feature_tie_in_deadlines_met": 0.0,
        "summary_sections_present": 0.0,
        "summary_mentions_window_and_allocations": 0.0,
        "summary_top5_list_with_scores": 0.0,
        "email_includes_window_counts_top3_and_tiein": 0.0,
        "pm_message_features_topics_weeks": 0.0,
    }

    # Load inputs
    input_dir = workspace / "input"
    eng_path = input_dir / "engagement.csv"
    features_path = input_dir / "features.json"
    channels_path = input_dir / "channels.json"
    weights_path = input_dir / "weights.yaml"

    eng_header, eng_rows = _load_csv(eng_path)
    features = _load_json(features_path)
    channels = _load_json(channels_path)
    weights_text = _read_text(weights_path)
    weights = _parse_simple_yaml(weights_text) if weights_text is not None else None

    inputs_ok = eng_header is not None and eng_rows is not None and features is not None and channels is not None and weights is not None
    if inputs_ok:
        # Parse today and schedule window
        today_str = weights.get("today")
        schedule_cfg = weights.get("schedule", {}) if isinstance(weights.get("schedule", {}), dict) else {}
        start_date_str = schedule_cfg.get("start_date")
        weeks = schedule_cfg.get("weeks")
        today_dt = _parse_date(today_str) if isinstance(today_str, str) else None
        start_dt = _parse_date(start_date_str) if isinstance(start_date_str, str) else None
        weeks_int = int(weeks) if isinstance(weeks, int) or (isinstance(weeks, (str, float)) and str(weeks).strip().isdigit()) else None
        if today_dt is None or start_dt is None or weeks_int is None or weeks_int <= 0:
            inputs_ok = False

    # Precompute scores
    computed_scores: Dict[str, Dict[str, Any]] = {}
    topic_order: List[str] = []
    personas_set: set = set()
    channel_caps: Dict[str, int] = {}
    features_list: List[Dict[str, Any]] = []
    if inputs_ok:
        # Cast numerics in engagement for robustness
        for r in eng_rows:
            # ensure keys exist
            pass
        computed_scores, topic_order = _compute_scores(eng_rows, weights, today_dt)  # type: ignore
        personas_set = set([r["persona"] for r in eng_rows])
        for c in channels:
            channel_caps[c["channel"]] = int(c["weekly_slots"])
        features_list = features.get("features", [])

    # Load outputs
    out_dir = workspace / "output"
    scored_path = out_dir / "scored_topics.csv"
    cal_path = out_dir / "calendar.csv"
    summary_path = out_dir / "summary.md"
    drafts_dir = out_dir / "drafts"
    email_path = drafts_dir / "email_to_marketing_team.txt"
    pm_msg_path = drafts_dir / "message_to_product_manager.txt"

    scored_header, scored_rows = _load_csv(scored_path)
    cal_header, cal_rows = _load_csv(cal_path)
    summary_text = _read_text(summary_path)
    email_text = _read_text(email_path)
    pm_text = _read_text(pm_msg_path)

    # 1) scored_topics.csv checks
    required_scored_cols = [
        "topic_id",
        "topic",
        "persona",
        "channel",
        "pipeline_stage",
        "last_published_date",
        "norm_ctr",
        "norm_time",
        "norm_inv_bounce",
        "norm_conversions",
        "norm_recency",
        "pipeline_stage_bonus",
        "final_score",
    ]
    if scored_header is not None and scored_rows is not None:
        if scored_header == required_scored_cols:
            scores["scored_topics_file_exists_and_schema"] = 1.0
        # Row count matches input rows
        if inputs_ok and len(scored_rows) == len(eng_rows):
            scores["scored_topics_row_count_matches_input"] = 1.0
        # Values correctness
        if inputs_ok:
            # Map scored rows by topic_id
            out_map = {r["topic_id"]: r for r in scored_rows}
            ok = True
            for tid, comp in computed_scores.items():
                if tid not in out_map:
                    ok = False
                    break
                r = out_map[tid]
                # Check textual fields
                src = next((e for e in eng_rows if e["topic_id"] == tid), None)
                if not src:
                    ok = False
                    break
                if not (r["topic"] == src["topic"] and r["persona"] == src["persona"] and r["channel"] == src["channel"] and r["pipeline_stage"] == src["pipeline_stage"] and r["last_published_date"] == src["last_published_date"]):
                    ok = False
                    break
                # Check numeric fields
                for key in ["norm_ctr", "norm_time", "norm_inv_bounce", "norm_conversions", "norm_recency", "pipeline_stage_bonus", "final_score"]:
                    parsed = _safe_float(r.get(key, ""))
                    if parsed is None or not _is_close(parsed, float(comp[key]), rel_tol=1e-5, abs_tol=1e-6):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                scores["scored_topics_values_correct"] = 1.0

    # 2) calendar.csv checks
    required_calendar_cols = ["week_start", "channel", "topic_id", "topic", "persona", "feature_tie_in", "final_score"]
    if cal_header is not None and cal_rows is not None:
        if cal_header == required_calendar_cols:
            scores["calendar_file_exists_and_schema"] = 1.0

        if inputs_ok:
            # Build week starts
            weeks = int(weights["schedule"]["weeks"])
            start_dt = _parse_date(weights["schedule"]["start_date"])
            week_starts = [start_dt + timedelta(days=7 * i) for i in range(weeks)]  # type: ignore
            week_start_strs = [d.strftime("%Y-%m-%d") for d in week_starts]
            # Capacity per week
            weekly_total_slots = sum(channel_caps.values())
            # Check each week has exact rows equals sum of weekly slots
            week_groups: Dict[str, List[Dict[str, str]]] = {}
            for r in cal_rows:
                ws = r["week_start"]
                week_groups.setdefault(ws, []).append(r)
            weeks_ok = True
            # Exactly same set of week_start values
            if set(week_groups.keys()) != set(week_start_strs):
                weeks_ok = False
            else:
                for ws in week_start_strs:
                    rows_w = week_groups.get(ws, [])
                    if len(rows_w) != weekly_total_slots:
                        weeks_ok = False
                        break
                    # Per channel capacity within week
                    chan_counts: Dict[str, int] = {}
                    for rr in rows_w:
                        chan = rr["channel"]
                        chan_counts[chan] = chan_counts.get(chan, 0) + 1
                    for ch, cap in channel_caps.items():
                        if chan_counts.get(ch, 0) != cap:
                            weeks_ok = False
                            break
                    if not weeks_ok:
                        break
            if weeks_ok:
                scores["calendar_weeks_and_capacity_exact"] = 1.0

            # Channels match and topics unique
            unique_ok = True
            seen_topics: set = set()
            for r in cal_rows:
                tid = r["topic_id"]
                chan = r["channel"]
                # Topic must exist in input and be of that channel
                src = next((e for e in eng_rows if e["topic_id"] == tid), None)
                if not src:
                    unique_ok = False
                    break
                if src["channel"] != chan:
                    unique_ok = False
                    break
                if tid in seen_topics:
                    unique_ok = False
                    break
                seen_topics.add(tid)
                # persona and topic name should match input
                if r["topic"] != src["topic"] or r["persona"] != src["persona"]:
                    unique_ok = False
                    break
                # final_score matches scored value
                comp = computed_scores.get(tid)
                parsed_fs = _safe_float(r.get("final_score", ""))
                if comp is None or parsed_fs is None or not _is_close(parsed_fs, float(comp["final_score"]), rel_tol=1e-5, abs_tol=1e-6):
                    unique_ok = False
                    break
            if unique_ok:
                scores["calendar_channels_match_input_and_unique_topics"] = 1.0

            # Feature tie-in label validity
            # Build topic_id -> list of feature names
            topic_to_features: Dict[str, List[str]] = {}
            for f in features_list:
                fname = f.get("name", "")
                for tid in f.get("associated_topics", []):
                    topic_to_features.setdefault(tid, []).append(fname)
            label_ok = True
            for r in cal_rows:
                tid = r["topic_id"]
                label = r.get("feature_tie_in", "")
                if tid in topic_to_features:
                    # label must be one of names
                    if label not in topic_to_features[tid]:
                        label_ok = False
                        break
                else:
                    if label.strip() != "":
                        label_ok = False
                        break
            if label_ok:
                scores["calendar_feature_tie_in_labels_valid"] = 1.0

            # Persona coverage: each persona in input appears at least once
            personas_sched = set([r["persona"] for r in cal_rows])
            if personas_set.issubset(personas_sched):
                scores["calendar_persona_coverage_all_personas"] = 1.0

            # Feature tie-in deadlines met
            deadlines_ok = True
            # Window dates
            window_start = start_dt  # type: ignore
            window_end = _get_end_of_window(window_start, weeks)  # type: ignore
            # Precompute scheduled weeks per topic_id
            tid_to_week: Dict[str, datetime] = {}
            for r in cal_rows:
                wsd = _parse_date(r["week_start"])
                if wsd is not None:
                    tid_to_week[r["topic_id"]] = wsd
            for f in features_list:
                launch_str = f.get("launch_date")
                launch_dt = _parse_date(launch_str) if isinstance(launch_str, str) else None
                if launch_dt is None:
                    continue
                # Check if launch within window (inclusive)
                if window_start <= launch_dt <= window_end:
                    # At least one associated topic scheduled no later than the week that starts strictly before (launch_date - 7 days)
                    threshold = launch_dt - timedelta(days=7)
                    # find the latest week_start that is strictly before threshold
                    week_starts = sorted([_parse_date(ws) for ws in set([r["week_start"] for r in cal_rows]) if _parse_date(ws) is not None])
                    latest_allowed = None
                    for ws in week_starts:
                        if ws < threshold:
                            latest_allowed = ws
                    if latest_allowed is None:
                        # if no week starts before threshold, then cannot schedule as per rule; fail if any associated scheduled?
                        # Rule requires at least one scheduled no later than that; impossible -> fail
                        deadlines_ok = False
                        break
                    # check any associated topic scheduled at or before latest_allowed
                    assoc = f.get("associated_topics", [])
                    satisfied = False
                    for tid in assoc:
                        w = tid_to_week.get(tid)
                        if w is not None and w <= latest_allowed:
                            satisfied = True
                            break
                    if not satisfied:
                        deadlines_ok = False
                        break
            if deadlines_ok:
                scores["calendar_feature_tie_in_deadlines_met"] = 1.0

    # 3) summary.md checks
    if summary_text is not None and inputs_ok:
        sections = _extract_sections(summary_text)
        required_sections = [
            "inputs summary",
            "scoring method",
            "top 5 topics by final_score",
            "scheduling decisions",
            "risks/assumptions",
        ]
        if all(h in sections for h in required_sections):
            scores["summary_sections_present"] = 1.0

        # Mentions window dates and per-channel allocations
        start_date_str = weights["schedule"]["start_date"]  # type: ignore
        weeks = int(weights["schedule"]["weeks"])  # type: ignore
        window_start = _parse_date(start_date_str)
        window_end = _get_end_of_window(window_start, weeks) if window_start else None
        mentions_ok = True
        if window_start is None or window_end is None:
            mentions_ok = False
        else:
            if (start_date_str not in summary_text) or (window_end.strftime("%Y-%m-%d") not in summary_text):
                mentions_ok = False
        # per-channel slot allocation
        for ch, cap in channel_caps.items():
            if (ch not in summary_text) or (str(cap) not in summary_text):
                mentions_ok = False
                break
        if mentions_ok:
            scores["summary_mentions_window_and_allocations"] = 1.0

        # Top 5 topics by final_score listed with scores
        top5 = sorted(computed_scores.values(), key=lambda x: x["final_score"], reverse=True)[:5]
        top5_ok = True
        sec = sections.get("top 5 topics by final_score")
        if sec is None:
            top5_ok = False
        else:
            start, end = sec
            sec_text = "\n".join(summary_text.splitlines()[start:end])
            # Check each of the top 5 topics appears by title or id and numbers close to scores exist
            all_present = True
            scores_present_count = 0
            nums = _get_numbers_in_text(sec_text)
            for item in top5:
                title = item["topic"]
                tid = item["topic_id"]
                if (title not in sec_text) and (tid not in sec_text):
                    all_present = False
                    break
                # Find a number close to final score
                fs = float(item["final_score"])
                if any(_is_close(n, fs, rel_tol=1e-2, abs_tol=0.02) for n in nums):
                    scores_present_count += 1
            if not all_present or scores_present_count < 3:
                top5_ok = False
        if top5_ok:
            scores["summary_top5_list_with_scores"] = 1.0

    # 4) Draft communications
    # Email to marketing team
    if email_text is not None and cal_rows is not None and inputs_ok:
        email_ok = True
        # Window dates
        start_date_str = weights["schedule"]["start_date"]  # type: ignore
        weeks = int(weights["schedule"]["weeks"])  # type: ignore
        window_start = _parse_date(start_date_str)
        window_end = _get_end_of_window(window_start, weeks) if window_start else None
        if window_start is None or window_end is None:
            email_ok = False
        else:
            if (start_date_str not in email_text) or (window_end.strftime("%Y-%m-%d") not in email_text):
                email_ok = False
        # Total number scheduled assets
        total_assets = len(cal_rows)
        if str(total_assets) not in email_text:
            email_ok = False
        # Per-channel counts
        cal_channel_counts: Dict[str, int] = {}
        for r in cal_rows:
            cal_channel_counts[r["channel"]] = cal_channel_counts.get(r["channel"], 0) + 1
        for ch, cnt in cal_channel_counts.items():
            if (ch not in email_text) or (str(cnt) not in email_text):
                email_ok = False
                break
        # Top 3 topics by score
        top3 = sorted(computed_scores.values(), key=lambda x: x["final_score"], reverse=True)[:3]
        for item in top3:
            if (item["topic"] not in email_text) and (item["topic_id"] not in email_text):
                email_ok = False
                break
        # Mention Automated QC Module specifically
        if "Automated QC Module" not in email_text:
            email_ok = False
        if email_ok:
            scores["email_includes_window_counts_top3_and_tiein"] = 1.0

    # Message to product manager
    if pm_text is not None and cal_rows is not None and inputs_ok:
        pm_ok = True
        # Build feature -> associated topics
        feat_to_topics: Dict[str, List[str]] = {}
        for f in features_list:
            fname = f.get("name", "")
            feat_to_topics[fname] = f.get("associated_topics", [])
        # Build topic_id -> (title, week_start)
        tid_to_week: Dict[str, str] = {}
        tid_to_title: Dict[str, str] = {}
        for r in cal_rows:
            tid_to_week[r["topic_id"]] = r["week_start"]
            tid_to_title[r["topic_id"]] = r["topic"]
        # For each feature that has at least one scheduled topic
        for fname, tids in feat_to_topics.items():
            scheduled_for_feature = [tid for tid in tids if tid in tid_to_week]
            if not scheduled_for_feature:
                continue
            # Require mention of feature name
            if fname not in pm_text:
                pm_ok = False
                break
            # Require at least one topic title and its week date
            found_any = False
            for tid in scheduled_for_feature:
                title = tid_to_title.get(tid, "")
                week = tid_to_week.get(tid, "")
                if title and week and (title in pm_text) and (week in pm_text):
                    found_any = True
                    break
            if not found_any:
                pm_ok = False
                break
        if pm_ok:
            scores["pm_message_features_topics_weeks"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()