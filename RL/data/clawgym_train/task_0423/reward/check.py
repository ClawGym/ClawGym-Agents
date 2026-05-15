import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from typing import List, Dict, Tuple, Any


NUMBER_PATTERN = re.compile(r'\$?\d[\d,]*(?:\.\d+)?%?')


def _safe_read_text(p: Path) -> Tuple[str, bool]:
    try:
        return p.read_text(encoding="utf-8"), True
    except Exception:
        return "", False


def _safe_load_json(p: Path) -> Tuple[Any, bool]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False


def _safe_load_jsonl(p: Path) -> Tuple[List[dict], bool]:
    items = []
    text, ok = _safe_read_text(p)
    if not ok:
        return [], False
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    for ln in lines:
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict):
                items.append(obj)
            else:
                return [], False
        except Exception:
            return [], False
    return items, True


def _safe_load_csv(p: Path) -> Tuple[List[Dict[str, str]], bool]:
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure header exists
            if reader.fieldnames is None:
                return [], False
            return rows, True
    except Exception:
        return [], False


def _is_iso8601(s: str) -> bool:
    try:
        # Accept Z or timezone offset
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _extract_numbers(text: str) -> List[str]:
    if not isinstance(text, str):
        return []
    return NUMBER_PATTERN.findall(text)


def _extract_trailing_hashtags(message: str) -> List[str]:
    # Split by whitespace, gather trailing tokens that start with '#'
    tokens = message.rstrip().split()
    trailing = []
    for tok in reversed(tokens):
        if tok.startswith("#") and len(tok) > 1:
            trailing.append(tok)
        else:
            break
    trailing.reverse()
    return trailing


def _single_sentence(text: str) -> bool:
    # Consider '.', '!' or '?' as sentence terminators
    # Count non-empty segments when splitting on these
    # Ignore trailing hashtags in determination
    msg = text
    # Remove trailing hashtags chunk
    ht = _extract_trailing_hashtags(text)
    if ht:
        joined = " ".join(ht)
        if text.endswith(" " + joined):
            msg = text[:-(len(joined) + 1)]
        elif text.endswith(joined):
            msg = text[:-(len(joined))]
    parts = re.split(r'[.!?]+', msg)
    non_empty = [p for p in parts if p.strip() != ""]
    return len(non_empty) <= 1


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cleaned_files_exist": 0.0,
        "cleaned_records_structure": 0.0,
        "ids_and_channels_match_inputs": 0.0,
        "brevity_enforced_and_reduction_accuracy": 0.0,
        "channel_caps_and_newsletter_rules_enforced": 0.0,
        "numeric_integrity_enforced": 0.0,
        "tags_rules_enforced": 0.0,
        "per_file_metrics_valid": 0.0,
        "global_summary_valid": 0.0,
    }

    inbox_dir = workspace / "inbox"
    out_cleaned_dir = workspace / "out" / "cleaned"
    out_metrics_dir = workspace / "out" / "metrics"
    global_csv_path = out_metrics_dir / "global_summary.csv"

    # Discover inbox jsonl files
    if not inbox_dir.exists():
        inbox_files = []
    else:
        inbox_files = sorted([p for p in inbox_dir.glob("*.jsonl") if p.is_file()])

    # Load inputs
    inputs_by_file: Dict[str, Tuple[List[dict], bool]] = {}
    for p in inbox_files:
        items, ok = _safe_load_jsonl(p)
        inputs_by_file[p.name] = (items, ok)

    # Check existence of cleaned outputs for each inbox file
    total_inbox = len(inbox_files)
    have_cleaned = 0
    cleaned_by_file: Dict[str, Tuple[List[dict], bool]] = {}
    for p in inbox_files:
        cleaned_path = out_cleaned_dir / p.name
        posts, ok = _safe_load_jsonl(cleaned_path)
        cleaned_by_file[p.name] = (posts, ok)
        if ok:
            have_cleaned += 1

    if total_inbox > 0:
        scores["cleaned_files_exist"] = have_cleaned / total_inbox
    else:
        scores["cleaned_files_exist"] = 0.0

    # Validate cleaned records structure and ids/channels match
    structure_total = 0
    structure_ok = 0
    ids_total = 0
    ids_ok = 0

    # For downstream checks
    all_posts_info: List[Tuple[str, dict, dict]] = []  # (file_name, input_post, cleaned_post)

    for p in inbox_files:
        fname = p.name
        input_posts, input_ok = inputs_by_file.get(fname, ([], False))
        cleaned_posts, cleaned_ok = cleaned_by_file.get(fname, ([], False))
        if not (input_ok and cleaned_ok):
            continue

        # Index input by id
        input_by_id = {}
        for ip in input_posts:
            if isinstance(ip, dict) and "id" in ip:
                input_by_id[ip["id"]] = ip

        # Structure checks per cleaned record
        for cp in cleaned_posts:
            structure_total += 1
            # Required fields
            required_fields = [
                "id",
                "channel",
                "original_length_chars",
                "rewritten_length_chars",
                "reduction_percent",
                "rewritten_message",
                "tags_used",
                "valid",
                "violations",
            ]
            missing = any(k not in cp for k in required_fields)
            types_ok = (
                isinstance(cp.get("id"), str)
                and isinstance(cp.get("channel"), str)
                and cp.get("channel") in {"linkedin", "x", "newsletter"}
                and isinstance(cp.get("original_length_chars"), int)
                and isinstance(cp.get("rewritten_length_chars"), int)
                and isinstance(cp.get("reduction_percent"), (int, float))
                and isinstance(cp.get("rewritten_message"), str)
                and isinstance(cp.get("tags_used"), list)
                and isinstance(cp.get("valid"), bool)
                and isinstance(cp.get("violations"), list)
            )
            # tags_used items must be strings if present
            if types_ok:
                if any(not isinstance(t, str) for t in cp.get("tags_used", [])):
                    types_ok = False
            if not missing and types_ok:
                # If input post available, check original_length_chars matches input message length
                ip = input_by_id.get(cp["id"])
                if ip and isinstance(ip.get("message"), str):
                    ol = len(ip["message"])
                    if ol != cp["original_length_chars"]:
                        types_ok = False
                # Check rewritten_length_chars matches actual length
                rl = len(cp.get("rewritten_message", ""))
                if rl != cp["rewritten_length_chars"]:
                    types_ok = False
            if not missing and types_ok:
                structure_ok += 1

        # IDs/Channels matching and counts
        ids_total += len(input_posts)
        # Build cleaned index by id
        cleaned_by_id = {}
        for cp in cleaned_posts:
            if isinstance(cp, dict) and "id" in cp:
                cleaned_by_id[cp["id"]] = cp
        # All input ids must be present in cleaned and channels match
        for ip in input_posts:
            cid_match = False
            cp = cleaned_by_id.get(ip.get("id"))
            if cp is not None and cp.get("channel") == ip.get("channel"):
                cid_match = True
            if cid_match:
                ids_ok += 1
                all_posts_info.append((fname, ip, cp))

    scores["cleaned_records_structure"] = (structure_ok / structure_total) if structure_total > 0 else 0.0
    scores["ids_and_channels_match_inputs"] = (ids_ok / ids_total) if ids_total > 0 else 0.0

    # If we have aligned posts, proceed with rule enforcement checks
    # Brevity and reduction accuracy
    brevity_total = 0
    brevity_ok = 0
    # Channel caps and newsletter single sentence
    caps_total = 0
    caps_ok = 0
    # Numeric integrity
    numeric_total = 0
    numeric_ok = 0
    # Tags rules
    tags_total = 0
    tags_ok = 0

    for fname, ip, cp in all_posts_info:
        original_msg = ip.get("message", "")
        tags = ip.get("tags", []) if isinstance(ip.get("tags"), list) else []
        channel = ip.get("channel")
        rewritten = cp.get("rewritten_message", "")
        valid_flag = cp.get("valid", False)

        # Brevity and reduction accuracy
        ol = len(original_msg) if isinstance(original_msg, str) else 0
        rl = len(rewritten) if isinstance(rewritten, str) else 0
        brevity_total += 1
        red_calc = 0.0
        if ol > 0:
            red_calc = 100.0 * (ol - rl) / ol
        # Check reduction_percent close
        red_field = float(cp.get("reduction_percent", 0.0)) if isinstance(cp.get("reduction_percent"), (int, float)) else 0.0
        red_ok = abs(red_field - red_calc) <= 0.5
        brevity_pass = (ol > 0 and rl <= 0.9 * ol)
        # Enforcement: if brevity fails or red mismatch, valid must be False; else pass
        if brevity_pass and red_ok:
            brevity_ok += 1
        else:
            if not valid_flag:
                brevity_ok += 1

        # Channel caps and newsletter rules
        caps_total += 1
        caps_pass = True
        if channel == "x":
            if rl > 280:
                caps_pass = False
        elif channel == "linkedin":
            if rl > 700:
                caps_pass = False
        elif channel == "newsletter":
            if rl > 200:
                caps_pass = False
            if not _single_sentence(rewritten):
                caps_pass = False
        if caps_pass:
            caps_ok += 1
        else:
            if not valid_flag:
                caps_ok += 1

        # Numeric integrity
        numeric_total += 1
        orig_nums = _extract_numbers(original_msg)
        rew_nums = _extract_numbers(rewritten)
        orig_set = set(orig_nums)
        rew_set = set(rew_nums)
        # Each original number must appear in rewritten; no new numbers
        missing_nums = [n for n in orig_set if n not in rew_set]
        new_nums = [n for n in rew_set if n not in orig_set]
        numeric_pass = (len(missing_nums) == 0 and len(new_nums) == 0)
        if numeric_pass:
            numeric_ok += 1
        else:
            if not valid_flag:
                numeric_ok += 1

        # Tags rules
        tags_total += 1
        tags_used = cp.get("tags_used", [])
        trailing_hashtags = _extract_trailing_hashtags(rewritten)
        expected = ["#" + t for t in tags[:2]]
        if channel in {"x", "linkedin"}:
            tags_used_ok = isinstance(tags_used, list) and tags_used == expected
            trailing_ok = trailing_hashtags == expected
            tags_pass = tags_used_ok and trailing_ok
        else:
            tags_pass = isinstance(tags_used, list) and len(tags_used) == 0 and len(trailing_hashtags) == 0
        if tags_pass:
            tags_ok += 1
        else:
            if not valid_flag:
                tags_ok += 1

    scores["brevity_enforced_and_reduction_accuracy"] = (brevity_ok / brevity_total) if brevity_total > 0 else 0.0
    scores["channel_caps_and_newsletter_rules_enforced"] = (caps_ok / caps_total) if caps_total > 0 else 0.0
    scores["numeric_integrity_enforced"] = (numeric_ok / numeric_total) if numeric_total > 0 else 0.0
    scores["tags_rules_enforced"] = (tags_ok / tags_total) if tags_total > 0 else 0.0

    # Metrics per file
    metrics_total = 0
    metrics_ok = 0
    for p in inbox_files:
        fname = p.name
        input_posts, input_ok = inputs_by_file.get(fname, ([], False))
        cleaned_posts, cleaned_ok = cleaned_by_file.get(fname, ([], False))
        if not (input_ok and cleaned_ok):
            continue
        metrics_path = out_metrics_dir / fname.replace(".jsonl", ".json")
        metrics, m_ok = _safe_load_json(metrics_path)
        metrics_total += 1
        if not m_ok or not isinstance(metrics, dict):
            continue
        # Required fields
        req_fields = [
            "file_name",
            "total_posts",
            "posts_by_channel",
            "avg_original_length_chars",
            "avg_rewritten_length_chars",
            "avg_reduction_percent",
            "top_tags",
            "invalid_posts",
            "processed_at",
        ]
        if any(k not in metrics for k in req_fields):
            continue
        if not isinstance(metrics.get("file_name"), str):
            continue
        if metrics.get("file_name") != fname:
            continue
        if not isinstance(metrics.get("total_posts"), int):
            continue
        if not isinstance(metrics.get("posts_by_channel"), dict):
            continue
        if not isinstance(metrics.get("avg_original_length_chars"), (int, float)):
            continue
        if not isinstance(metrics.get("avg_rewritten_length_chars"), (int, float)):
            continue
        if not isinstance(metrics.get("avg_reduction_percent"), (int, float)):
            continue
        if not isinstance(metrics.get("top_tags"), list):
            continue
        if not isinstance(metrics.get("invalid_posts"), int):
            continue
        if not isinstance(metrics.get("processed_at"), str) or not _is_iso8601(metrics.get("processed_at")):
            continue

        # Recompute expected values
        input_by_id = {ip["id"]: ip for ip in input_posts if isinstance(ip, dict) and "id" in ip}
        pbc_expected = {"linkedin": 0, "x": 0, "newsletter": 0}
        for ip in input_posts:
            ch = ip.get("channel")
            if ch in pbc_expected:
                pbc_expected[ch] += 1
        total_posts_expected = len(input_posts)
        original_lengths = []
        rewritten_lengths = []
        reduction_percents = []
        invalid_count = 0
        for cp in cleaned_posts:
            cid = cp.get("id")
            ip = input_by_id.get(cid)
            if not ip:
                continue
            original_lengths.append(cp.get("original_length_chars", 0))
            rewritten_lengths.append(cp.get("rewritten_length_chars", 0))
            rp = float(cp.get("reduction_percent", 0.0)) if isinstance(cp.get("reduction_percent"), (int, float)) else 0.0
            reduction_percents.append(rp)
            if cp.get("valid") is False:
                invalid_count += 1
        avg_ol = _mean(original_lengths)
        avg_rl = _mean(rewritten_lengths)
        avg_rp = _mean(reduction_percents)

        tag_counter = Counter()
        for ip in input_posts:
            tags = ip.get("tags", [])
            if isinstance(tags, list):
                for t in tags:
                    if isinstance(t, str):
                        tag_counter[t] += 1
        top5 = sorted(tag_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        top5_list = [t for t, _ in top5]

        tol = 0.5
        if metrics.get("total_posts") != total_posts_expected:
            continue
        pbc = metrics.get("posts_by_channel", {})
        if set(pbc.keys()) != set(pbc_expected.keys()):
            continue
        if any(pbc.get(k) != v for k, v in pbc_expected.items()):
            continue
        if abs(float(metrics.get("avg_original_length_chars")) - avg_ol) > tol:
            continue
        if abs(float(metrics.get("avg_rewritten_length_chars")) - avg_rl) > tol:
            continue
        if abs(float(metrics.get("avg_reduction_percent")) - avg_rp) > tol:
            continue
        if metrics.get("top_tags") != top5_list:
            continue
        if metrics.get("invalid_posts") != invalid_count:
            continue

        metrics_ok += 1

    scores["per_file_metrics_valid"] = (metrics_ok / metrics_total) if metrics_total > 0 else 0.0

    # Global summary CSV
    cleaned_all: List[dict] = []
    for fname in cleaned_by_file:
        posts, ok = cleaned_by_file[fname]
        if ok:
            cleaned_all.extend(posts)
    agg = defaultdict(lambda: {"total": 0, "ol": [], "rl": [], "rp": []})
    for cp in cleaned_all:
        ch = cp.get("channel")
        if ch not in {"linkedin", "x", "newsletter"}:
            continue
        agg[ch]["total"] += 1
        if isinstance(cp.get("original_length_chars"), int):
            agg[ch]["ol"].append(cp.get("original_length_chars"))
        if isinstance(cp.get("rewritten_length_chars"), int):
            agg[ch]["rl"].append(cp.get("rewritten_length_chars"))
        if isinstance(cp.get("reduction_percent"), (int, float)):
            agg[ch]["rp"].append(float(cp.get("reduction_percent")))
    rows, csv_ok = _safe_load_csv(global_csv_path)
    if csv_ok and rows:
        header = None
        try:
            with global_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        header_ok = header == ["channel", "total_posts", "avg_original_length_chars", "avg_rewritten_length_chars", "avg_reduction_percent"]
        csv_map = {}
        for r in rows:
            ch = r.get("channel")
            if ch:
                csv_map[ch] = r
        expected_channels = {ch for ch, data in agg.items() if data["total"] > 0}
        if expected_channels:
            channels_ok = (set(csv_map.keys()) == expected_channels)
            tol = 0.5
            per_chan_ok = True
            for ch in expected_channels:
                r = csv_map.get(ch)
                if r is None:
                    per_chan_ok = False
                    break
                try:
                    total_posts_csv = int(r.get("total_posts"))
                    avg_ol_csv = float(r.get("avg_original_length_chars"))
                    avg_rl_csv = float(r.get("avg_rewritten_length_chars"))
                    avg_rp_csv = float(r.get("avg_reduction_percent"))
                except Exception:
                    per_chan_ok = False
                    break
                total_expected = agg[ch]["total"]
                avg_ol_expected = _mean(agg[ch]["ol"])
                avg_rl_expected = _mean(agg[ch]["rl"])
                avg_rp_expected = _mean(agg[ch]["rp"])
                if total_posts_csv != total_expected:
                    per_chan_ok = False
                    break
                if abs(avg_ol_csv - avg_ol_expected) > tol or abs(avg_rl_csv - avg_rl_expected) > tol or abs(avg_rp_csv - avg_rp_expected) > tol:
                    per_chan_ok = False
                    break
            scores["global_summary_valid"] = 1.0 if (header_ok and channels_ok and per_chan_ok) else 0.0
        else:
            scores["global_summary_valid"] = 0.0
    else:
        scores["global_summary_valid"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()