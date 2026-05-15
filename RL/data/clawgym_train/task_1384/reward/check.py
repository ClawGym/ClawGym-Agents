import json
import csv
import re
import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from runpy import run_path


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_site_config(workspace: Path) -> Optional[Dict[str, Any]]:
    try:
        cfg_path = workspace / "scripts" / "site_config.py"
        if not cfg_path.exists():
            return None
        data = run_path(str(cfg_path))
        required = ["SUPPORTED_CHANNELS", "CHANNEL_LIMITS", "PRIMARY_TAGS"]
        for k in required:
            if k not in data:
                return None
        # Validate types
        if not isinstance(data["SUPPORTED_CHANNELS"], list):
            return None
        if not isinstance(data["CHANNEL_LIMITS"], dict):
            return None
        if not isinstance(data["PRIMARY_TAGS"], list):
            return None
        return {
            "SUPPORTED_CHANNELS": list(data["SUPPORTED_CHANNELS"]),
            "CHANNEL_LIMITS": dict(data["CHANNEL_LIMITS"]),
            "PRIMARY_TAGS": list(data["PRIMARY_TAGS"]),
        }
    except Exception:
        return None


def _parse_inline_list(value: str) -> Optional[List[str]]:
    # Attempt to parse a YAML/JSON-like inline list, e.g., ["a", "b"]
    try:
        parsed = ast.literal_eval(value.strip())
        if isinstance(parsed, list):
            # Normalize to strings
            return [str(x) for x in parsed]
        return None
    except Exception:
        # Attempt to parse without quotes (simple comma-separated)
        try:
            value2 = value.strip().strip("[]")
            if not value2:
                return []
            items = [v.strip().strip('"').strip("'") for v in value2.split(",")]
            return items
        except Exception:
            return None


def _load_audiences_yaml(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    # Minimal YAML parser for expected audience.yaml structure
    path = workspace / "config" / "audience.yaml"
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    audiences: List[Dict[str, Any]] = []
    in_audiences = False
    current: Optional[Dict[str, Any]] = None
    try:
        for raw in lines:
            line = raw.rstrip()
            if not line.strip():
                continue
            if not in_audiences:
                if line.strip().startswith("audiences:"):
                    in_audiences = True
                continue
            # We are inside audiences list
            stripped = line.lstrip()
            if stripped.startswith("- "):
                # Start a new audience entry
                # Flush previous
                if current:
                    audiences.append(current)
                current = {}
                after_dash = stripped[2:]
                if after_dash.strip():
                    # e.g., "id: GradStudents"
                    if ":" in after_dash:
                        key, val = after_dash.split(":", 1)
                        key = key.strip()
                        val = val.strip()
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                        current[key] = val
            else:
                # Continuation lines for current audience
                if current is None:
                    continue
                # Expect "key: value"
                if ":" in stripped:
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key == "interests":
                        lst = _parse_inline_list(val)
                        if lst is None:
                            return None
                        current[key] = lst
                    else:
                        # Remove wrapping quotes
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                        current[key] = val
        if current:
            audiences.append(current)
        # Validate entries
        valid = True
        for a in audiences:
            if "id" not in a or "interests" not in a:
                valid = False
                break
            if not isinstance(a["interests"], list):
                valid = False
                break
        if not valid:
            return None
        return audiences
    except Exception:
        return None


def _load_cadence_yaml(workspace: Path) -> Optional[Dict[str, Any]]:
    # Minimal YAML parser for cadence.yaml with weekly_slots and rules
    path = workspace / "config" / "cadence.yaml"
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    weekly_slots: List[str] = []
    rules: Dict[str, Any] = {}
    state = None  # None, 'weekly_slots', 'rules'
    try:
        for raw in lines:
            line = raw.rstrip()
            if not line.strip():
                continue
            if line.strip().startswith("weekly_slots:"):
                state = "weekly_slots"
                continue
            if line.strip().startswith("rules:"):
                state = "rules"
                continue
            if state == "weekly_slots":
                stripped = line.lstrip()
                if stripped.startswith("- "):
                    val = stripped[2:].strip()
                    # remove quotes
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    weekly_slots.append(val)
                else:
                    # End of list
                    state = None
            elif state == "rules":
                stripped = line.strip()
                if ":" in stripped and not stripped.startswith("- "):
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    # try to parse int
                    try:
                        ival = int(val)
                        rules[key] = ival
                    except Exception:
                        # keep as string without quotes
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                        if val.startswith("'") and val.endswith("'"):
                            val = val[1:-1]
                        rules[key] = val
                else:
                    # end of rules block
                    state = None
            else:
                continue
        if not weekly_slots:
            return None
        return {"weekly_slots": weekly_slots, "rules": rules}
    except Exception:
        return None


def _parse_front_matter(md_text: str) -> Dict[str, Any]:
    # Extract YAML front matter between '---' lines at top and parse minimal keys
    result: Dict[str, Any] = {}
    lines = md_text.splitlines()
    if len(lines) < 3:
        return result
    if lines[0].strip() != "---":
        return result
    # find closing '---'
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return result
    fm_lines = lines[1:end_idx]
    for raw in fm_lines:
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if key == "tags":
            lst = _parse_inline_list(val)
            if isinstance(lst, list):
                result[key] = lst
        else:
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            result[key] = val
    return result


def _inventory_posts(workspace: Path) -> Dict[str, Dict[str, Any]]:
    posts_dir = workspace / "content" / "posts"
    inventory: Dict[str, Dict[str, Any]] = {}
    if not posts_dir.exists():
        return inventory
    for p in posts_dir.rglob("*.md"):
        text = _safe_read_text(p)
        if text is None:
            continue
        meta = _parse_front_matter(text)
        tags = meta.get("tags", [])
        rel = str(p.relative_to(workspace))
        inventory[rel] = {"path": p, "tags": tags, "meta": meta}
    return inventory


def _load_csv_strict(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        # Use csv reader to avoid newline/quotes subtleties
        rows: List[Dict[str, str]] = []
        reader = csv.reader(text.splitlines())
        header = next(reader, None)
        if header is None:
            return None
        # Build dict rows preserving header order
        for r in reader:
            # pad or trim to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            if len(r) > len(header):
                r = r[: len(header)]
            rows.append({header[i]: r[i] for i in range(len(header))})
        return header, rows
    except Exception:
        return None


def _parse_channel_schedule_yaml(workspace: Path) -> Optional[Dict[str, Any]]:
    path = workspace / "outputs" / "channel_schedule.yaml"
    text = _safe_read_text(path)
    if text is None:
        return None
    # Minimal hierarchical parser for expected structure:
    # W1:
    #   total_items: 2
    #   channel_counts:
    #     Blog: 2
    #     Mastodon: 1
    # ...
    try:
        result: Dict[str, Any] = {}
        lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() != ""]
        current_week: Optional[str] = None
        in_channel_counts = False
        for i, raw in enumerate(lines):
            indent = len(raw) - len(raw.lstrip(" "))
            line = raw.strip()
            if not line:
                continue
            if not raw.startswith(" "):  # top-level key
                if not line.endswith(":"):
                    return None
                current_week = line[:-1]
                result[current_week] = {}
                in_channel_counts = False
                continue
            if current_week is None:
                return None
            # inner level
            if indent >= 2:
                # e.g., "total_items: 2" or "channel_counts:"
                if line.startswith("channel_counts:"):
                    result[current_week]["channel_counts"] = {}
                    in_channel_counts = True
                    continue
                if ":" in line and not in_channel_counts:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    try:
                        val_num = int(val)
                        result[current_week][key] = val_num
                    except Exception:
                        # allow zero or missing
                        result[current_week][key] = val
                    continue
                if in_channel_counts and ":" in line:
                    # parse channel count
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    try:
                        val_num = int(val)
                    except Exception:
                        val_num = None
                    result[current_week]["channel_counts"][key] = val_num
        return result
    except Exception:
        return None


def _split_channels(field: str) -> List[str]:
    parts = [p.strip() for p in field.split(";") if p.strip()]
    # Deduplicate while preserving order
    seen = set()
    out = []
    for c in parts:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def _count_words(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def _count_sentences(text: str) -> int:
    # Rough sentence split on . ! ? while avoiding multiple splits for ellipses
    # Count non-empty segments
    parts = re.split(r"[.!?]+", text)
    count = sum(1 for p in parts if p.strip())
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "content_plan_exists_and_header": 0.0,
        "content_plan_row_count_and_weeks_slots": 0.0,
        "content_plan_slot_values_per_week": 0.0,
        "content_plan_topic_types_and_source_post_rules": 0.0,
        "content_plan_min_repurposed": 0.0,
        "content_plan_unique_primary_tags": 0.0,
        "content_plan_audience_valid_and_interest_match": 0.0,
        "content_plan_new_topics_tag_in_site_tags": 0.0,
        "content_plan_channels_valid_and_blog_included": 0.0,
        "content_plan_weekly_channel_limits_respected": 0.0,
        "channel_schedule_exists_and_structure": 0.0,
        "channel_schedule_counts_match_csv": 0.0,
        "channel_schedule_respects_limits": 0.0,
        "outreach_email_exists_and_length": 0.0,
        "outreach_email_references_plan_and_themes": 0.0,
        "outreach_email_nod_to_greats": 0.0,
        "outreach_email_no_personal_names": 0.0,
        "slack_announcement_exists_and_sentences": 0.0,
        "slack_announcement_references_plan_and_feedback": 0.0,
    }

    # Load configurations
    site_cfg = _load_site_config(workspace)
    cadence = _load_cadence_yaml(workspace)
    audiences_list = _load_audiences_yaml(workspace)
    audiences_by_id: Dict[str, Dict[str, Any]] = {}
    if audiences_list:
        audiences_by_id = {a["id"]: a for a in audiences_list if "id" in a}

    # Inventory posts for repurpose checks
    posts = _inventory_posts(workspace)

    # Prepare expected header
    expected_header = [
        "week",
        "slot",
        "topic_title",
        "topic_type",
        "source_post",
        "primary_tag",
        "primary_audience",
        "distribution_channels",
        "rationale",
    ]

    # Load content_plan.csv
    plan_path = workspace / "outputs" / "content_plan.csv"
    plan_loaded = _load_csv_strict(plan_path)
    header: Optional[List[str]] = None
    rows: List[Dict[str, str]] = []
    if plan_loaded:
        header, rows = plan_loaded

    # Check header existence and exact match
    if header == expected_header and rows is not None:
        scores["content_plan_exists_and_header"] = 1.0

    # Only proceed with further plan checks if header is valid
    if header == expected_header and rows is not None:
        # Validate row count and week coverage
        weeks = [r["week"].strip() for r in rows]
        week_counts: Dict[str, int] = {}
        for w in weeks:
            week_counts[w] = week_counts.get(w, 0) + 1
        weeks_ok = (
            len(rows) == 8
            and set(weeks) == {"W1", "W2", "W3", "W4"}
            and all(week_counts.get(w, 0) == 2 for w in ["W1", "W2", "W3", "W4"])
        )
        # Validate slot values per week: should match cadence weekly_slots
        slots_ok = False
        if cadence and "weekly_slots" in cadence and isinstance(cadence["weekly_slots"], list):
            weekly_slots = cadence["weekly_slots"]
            # per week slots equal to the set of weekly_slots (exactly once each)
            per_week_slots_ok = True
            for wk in ["W1", "W2", "W3", "W4"]:
                slots = [r["slot"].strip() for r in rows if r["week"].strip() == wk]
                # Exact multiset match: two items where each from weekly_slots and both unique and cover list
                per_week_slots_ok = per_week_slots_ok and sorted(slots) == sorted(weekly_slots)
            slots_ok = per_week_slots_ok
        if weeks_ok:
            scores["content_plan_row_count_and_weeks_slots"] = 1.0
        if slots_ok:
            scores["content_plan_slot_values_per_week"] = 1.0

        # Topic types and source_post rules
        repurpose_valid = True
        new_valid = True
        repurpose_count = 0
        repurpose_source_tag_ok = True
        for r in rows:
            ttype = r["topic_type"].strip()
            spath = r["source_post"].strip()
            ptag = r["primary_tag"].strip()
            if ttype == "repurpose":
                repurpose_count += 1
                # source_post must be non-empty and point into content/posts
                if not spath:
                    repurpose_valid = False
                else:
                    src_abs = (workspace / spath).resolve()
                    # Must exist and be under content/posts
                    if not src_abs.exists():
                        repurpose_valid = False
                    else:
                        try:
                            # Ensure under content/posts
                            content_posts = (workspace / "content" / "posts").resolve()
                            if content_posts not in src_abs.parents and src_abs != content_posts:
                                repurpose_valid = False
                        except Exception:
                            repurpose_valid = False
                    # primary_tag must be one of that file's tags
                    rel = str(Path(spath))
                    rel_norm = rel.replace("\\", "/")
                    # Normalize to workspace-relative string used in inventory
                    # Attempt to find matching inventory key
                    matched_key = None
                    for key in posts.keys():
                        if key.replace("\\", "/") == rel_norm:
                            matched_key = key
                            break
                    if matched_key is None:
                        repurpose_valid = False
                    else:
                        tags = posts[matched_key].get("tags", [])
                        if ptag not in tags:
                            repurpose_source_tag_ok = False
            elif ttype == "new":
                # source_post should be empty
                if spath:
                    new_valid = False
            else:
                new_valid = False
        if repurpose_valid and new_valid and repurpose_source_tag_ok:
            scores["content_plan_topic_types_and_source_post_rules"] = 1.0
        if cadence and isinstance(cadence.get("rules", {}).get("min_repurposed_items"), int):
            min_required = cadence["rules"]["min_repurposed_items"]
            if repurpose_count >= min_required:
                scores["content_plan_min_repurposed"] = 1.0
        else:
            # Without rules, still enforce at least 2 as per task text
            if repurpose_count >= 2:
                scores["content_plan_min_repurposed"] = 1.0

        # Unique primary tags across all rows
        primary_tags = [r["primary_tag"].strip() for r in rows]
        if len(primary_tags) == len(set(primary_tags)) and len(primary_tags) == 8:
            scores["content_plan_unique_primary_tags"] = 1.0

        # Audience validity and interest match
        audience_ok = True
        for r in rows:
            aud = r["primary_audience"].strip()
            tag = r["primary_tag"].strip()
            if aud not in audiences_by_id:
                audience_ok = False
                break
            interests = audiences_by_id[aud].get("interests", [])
            if tag not in interests:
                audience_ok = False
                break
        if audience_ok and len(audiences_by_id) > 0:
            scores["content_plan_audience_valid_and_interest_match"] = 1.0

        # New topics primary_tag must be from PRIMARY_TAGS and not already used (unique already checked)
        new_tags_ok = True
        if site_cfg:
            allowed_tags = set(site_cfg["PRIMARY_TAGS"])
            for r in rows:
                if r["topic_type"].strip() == "new":
                    tag = r["primary_tag"].strip()
                    if tag not in allowed_tags:
                        new_tags_ok = False
                        break
        else:
            new_tags_ok = False
        if new_tags_ok:
            scores["content_plan_new_topics_tag_in_site_tags"] = 1.0

        # Distribution channels validity and Blog included; rationale <= 200 chars
        channels_ok = True
        rationale_ok = True
        if site_cfg:
            supported = set(site_cfg["SUPPORTED_CHANNELS"])
            for r in rows:
                chs = _split_channels(r["distribution_channels"])
                if "Blog" not in chs:
                    channels_ok = False
                    break
                if not all(c in supported for c in chs):
                    channels_ok = False
                    break
                # rationale length
                rationale = r.get("rationale", "")
                if rationale is None:
                    rationale = ""
                if len(rationale) > 200:
                    rationale_ok = False
            if channels_ok and rationale_ok:
                scores["content_plan_channels_valid_and_blog_included"] = 1.0
        else:
            channels_ok = False

        # Weekly channel limits respected
        weekly_limits_ok = True
        if site_cfg:
            limits = dict(site_cfg["CHANNEL_LIMITS"])
            # Initialize counts per week per channel
            for wk in ["W1", "W2", "W3", "W4"]:
                wk_rows = [r for r in rows if r["week"].strip() == wk]
                ch_counts: Dict[str, int] = {c: 0 for c in site_cfg["SUPPORTED_CHANNELS"]}
                for r in wk_rows:
                    chs = _split_channels(r["distribution_channels"])
                    for c in chs:
                        ch_counts[c] = ch_counts.get(c, 0) + 1
                for c, cnt in ch_counts.items():
                    lim = limits.get(c)
                    if lim is not None and cnt > lim:
                        weekly_limits_ok = False
                        break
                if not weekly_limits_ok:
                    break
        else:
            weekly_limits_ok = False
        if weekly_limits_ok:
            scores["content_plan_weekly_channel_limits_respected"] = 1.0

    # Channel schedule checks
    schedule = _parse_channel_schedule_yaml(workspace)
    if schedule is not None and isinstance(schedule, dict) and schedule:
        # Validate structure
        has_weeks = set(schedule.keys()) == {"W1", "W2", "W3", "W4"}
        structure_ok = True
        if site_cfg:
            expected_channels = set(site_cfg["SUPPORTED_CHANNELS"])
        else:
            expected_channels = set()
        for wk, data in schedule.items():
            if not isinstance(data, dict):
                structure_ok = False
                break
            if "total_items" not in data or "channel_counts" not in data:
                structure_ok = False
                break
            if not isinstance(data["channel_counts"], dict):
                structure_ok = False
                break
            # Check channel_counts includes all supported channels if we have config
            if expected_channels:
                if set(data["channel_counts"].keys()) != expected_channels:
                    structure_ok = False
                    break
        if has_weeks and structure_ok:
            scores["channel_schedule_exists_and_structure"] = 1.0

        # Counts match CSV and limits not exceeded
        if header == expected_header and rows is not None and site_cfg:
            # Compute from CSV
            computed: Dict[str, Dict[str, int]] = {}
            total_items_by_week: Dict[str, int] = {}
            limits = site_cfg["CHANNEL_LIMITS"]
            counts_match = True
            limits_ok = True
            for wk in ["W1", "W2", "W3", "W4"]:
                wk_rows = [r for r in rows if r["week"].strip() == wk]
                total_items_by_week[wk] = len(wk_rows)
                ch_counts: Dict[str, int] = {c: 0 for c in site_cfg["SUPPORTED_CHANNELS"]}
                for r in wk_rows:
                    chs = _split_channels(r["distribution_channels"])
                    for c in chs:
                        ch_counts[c] = ch_counts.get(c, 0) + 1
                computed[wk] = ch_counts
            # Compare with schedule
            for wk in ["W1", "W2", "W3", "W4"]:
                data = schedule.get(wk, {})
                if not data:
                    counts_match = False
                    break
                if data.get("total_items") != total_items_by_week[wk]:
                    counts_match = False
                    break
                sc_counts = data.get("channel_counts", {})
                for c in site_cfg["SUPPORTED_CHANNELS"]:
                    if sc_counts.get(c) != computed[wk].get(c):
                        counts_match = False
                        break
                # Check limits
                for c, cnt in computed[wk].items():
                    lim = limits.get(c)
                    if lim is not None and cnt > lim:
                        limits_ok = False
                        break
                if not counts_match:
                    break
            if counts_match:
                scores["channel_schedule_counts_match_csv"] = 1.0
            if limits_ok:
                scores["channel_schedule_respects_limits"] = 1.0

    # Outreach email checks
    email_path = workspace / "outputs" / "message_drafts" / "outreach_email.md"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        wc = _count_words(email_text)
        if 150 <= wc <= 250:
            scores["outreach_email_exists_and_length"] = 1.0
        # References plan and themes (reproducibility and performance/HPC)
        ref_plan = "outputs/content_plan.csv" in email_text
        text_lower = email_text.lower()
        mentions_repro = "reproducibility" in text_lower
        mentions_perf_or_hpc = ("performance" in text_lower) or ("hpc" in text_lower)
        if ref_plan and mentions_repro and mentions_perf_or_hpc:
            scores["outreach_email_references_plan_and_themes"] = 1.0
        # Nod to scientific greats
        greats_terms = [
            "turing",
            "noether",
            "feynman",
            "shannon",
            "curie",
            "newton",
            "gauss",
            "giants",
            "shoulders of giants",
        ]
        if any(term in text_lower for term in greats_terms):
            scores["outreach_email_nod_to_greats"] = 1.0
        # Free of real names: avoid "Dear <Name>", "Dr. <Name>", "Prof. <Name>"
        patterns = [
            r"\bDear\s+[A-Z][a-z]+",
            r"\bDr\.\s+[A-Z][a-z]+",
            r"\bProf\.\s+[A-Z][a-z]+",
        ]
        if not any(re.search(pat, email_text) for pat in patterns):
            scores["outreach_email_no_personal_names"] = 1.0

    # Slack announcement checks
    slack_path = workspace / "outputs" / "message_drafts" / "lab_slack_announcement.txt"
    slack_text = _safe_read_text(slack_path)
    if slack_text is not None:
        sent_count = _count_sentences(slack_text)
        if 3 <= sent_count <= 5:
            scores["slack_announcement_exists_and_sentences"] = 1.0
        ref_plan = "outputs/content_plan.csv" in slack_text
        lower = slack_text.lower()
        asks_feedback = any(k in lower for k in ["feedback", "contribute", "contributions", "suggestions", "PR", "pull request".lower()])
        mentions_month_or_plan = ("month" in lower) or ("w1" in lower) or ("w2" in lower) or ("w3" in lower) or ("w4" in lower) or ("plan" in lower)
        if ref_plan and asks_feedback and mentions_month_or_plan:
            scores["slack_announcement_references_plan_and_feedback"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()