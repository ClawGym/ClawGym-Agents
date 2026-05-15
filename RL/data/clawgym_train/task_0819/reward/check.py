import json
import sys
import csv
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_csv_file(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def parse_env_lines(text: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def recompute_expected_from_dataset(dataset_path: Path) -> Optional[Dict[str, Any]]:
    rows = parse_csv_file(dataset_path)
    if rows is None:
        return None
    required_cols = {"post_id", "platform", "hashtag", "likes", "shares", "comments", "date"}
    # Validate headers present
    if not rows:
        # Empty data not allowed for this task
        return None
    if set(rows[0].keys()) != required_cols:
        # Malformed header
        return None
    total_posts = 0
    total_likes = 0
    total_shares = 0
    total_comments = 0
    hashtag_counts: Dict[str, int] = {}
    for r in rows:
        try:
            likes = int(str(r["likes"]).strip())
            shares = int(str(r["shares"]).strip())
            comments = int(str(r["comments"]).strip())
            hashtag = str(r["hashtag"]).strip()
        except Exception:
            return None
        total_posts += 1
        total_likes += likes
        total_shares += shares
        total_comments += comments
        if hashtag:
            hashtag_counts[hashtag] = hashtag_counts.get(hashtag, 0) + 1
    if total_posts == 0:
        return None
    avg_likes = int(round(total_likes / total_posts))
    # Sort hashtags by count desc then hashtag asc
    sorted_hashtags = sorted(hashtag_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top3 = [{"hashtag": h, "count": c} for (h, c) in sorted_hashtags[:3]]
    return {
        "total_posts": total_posts,
        "total_likes": total_likes,
        "total_shares": total_shares,
        "total_comments": total_comments,
        "avg_likes_per_post": avg_likes,
        "hashtag_counts": hashtag_counts,
        "sorted_hashtags": sorted_hashtags,
        "top3": top3,
    }


def check_initial_env_log(text: str) -> bool:
    # Must contain an error about env file not found at workspace/.env
    # Accept any line starting with "ERROR: env file not found at" and containing "workspace/.env"
    for line in text.splitlines():
        if line.startswith("ERROR: env file not found at") and "workspace/.env" in line:
            return True
    return False


def check_final_env_log(text: str) -> bool:
    # Must contain an "OK:" line with specific content and a "READY" line, and no "ERROR:"
    lines = text.splitlines()
    has_ok = False
    has_ready = False
    for line in lines:
        if line.startswith("ERROR:"):
            return False
        if line.startswith("OK:"):
            if "APP_NAME=tongan-trends-demo" in line and "DATA_PATH=input/posts.csv" in line and "(exists)" in line:
                has_ok = True
        if line.strip() == "READY":
            has_ready = True
    return has_ok and has_ready


def check_env_file_exact(text: str) -> bool:
    # Must have exactly these keys with exactly these values:
    # APP_NAME=tongan-trends-demo
    # DATA_PATH=input/posts.csv
    env = parse_env_lines(text)
    # Only two non-comment key=val lines expected
    if set(env.keys()) != {"APP_NAME", "DATA_PATH"}:
        return False
    if env.get("APP_NAME") != "tongan-trends-demo":
        return False
    if env.get("DATA_PATH") != "input/posts.csv":
        return False
    # Ensure there are exactly two key=value (non-comment) lines
    kv_count = 0
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if "=" in s:
            kv_count += 1
    if kv_count != 2:
        return False
    return True


def validate_metrics_summary_structure(summary: Any) -> bool:
    # Must be a dict with exactly required keys
    required_keys = {"total_posts", "total_likes", "total_shares", "total_comments", "avg_likes_per_post", "top_hashtags"}
    if not isinstance(summary, dict):
        return False
    if set(summary.keys()) != required_keys:
        return False
    # Check integer types
    for k in ["total_posts", "total_likes", "total_shares", "total_comments", "avg_likes_per_post"]:
        if not isinstance(summary.get(k), int):
            return False
    # top_hashtags constraints
    th = summary.get("top_hashtags")
    if not isinstance(th, list):
        return False
    if len(th) != 3:
        return False
    for item in th:
        if not isinstance(item, dict):
            return False
        if set(item.keys()) != {"hashtag", "count"}:
            return False
        if not isinstance(item.get("hashtag"), str):
            return False
        if not isinstance(item.get("count"), int):
            return False
    return True


def validate_metrics_values(summary: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    try:
        if summary["total_posts"] != expected["total_posts"]:
            return False
        if summary["total_likes"] != expected["total_likes"]:
            return False
        if summary["total_shares"] != expected["total_shares"]:
            return False
        if summary["total_comments"] != expected["total_comments"]:
            return False
        if summary["avg_likes_per_post"] != expected["avg_likes_per_post"]:
            return False
        return True
    except Exception:
        return False


def validate_top_hashtags(summary: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    try:
        th = summary["top_hashtags"]
        expected_top3 = expected["top3"]
        # Must match exactly in order and values
        if len(th) != len(expected_top3):
            return False
        for a, b in zip(th, expected_top3):
            if a.get("hashtag") != b.get("hashtag") or a.get("count") != b.get("count"):
                return False
        # Also validate tie-breaking sorted by count desc then hashtag asc
        # Using provided order of summary
        sorted_from_summary = sorted(th, key=lambda x: (-int(x["count"]), x["hashtag"]))
        if th != sorted_from_summary:
            # If the summary ordering does not match required sort
            return False
        return True
    except Exception:
        return False


def validate_hashtag_counts_csv(path: Path, expected_sorted: List[Tuple[str, int]]) -> bool:
    rows = parse_csv_file(path)
    if rows is None:
        return False
    # Validate header columns exactly two: hashtag,count
    # csv.DictReader normalizes header; we can check from rows or re-open file first line
    try:
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
    except Exception:
        return False
    if header_line != "hashtag,count":
        return False
    # Validate there are exactly as many rows as hashtags in expected
    if len(rows) != len(expected_sorted):
        return False
    # Validate ordering and values
    for idx, row in enumerate(rows):
        if set(row.keys()) != {"hashtag", "count"}:
            return False
        hashtag = row.get("hashtag", "")
        count_str = row.get("count", "")
        try:
            count = int(count_str)
        except Exception:
            return False
        exp_hashtag, exp_count = expected_sorted[idx]
        if hashtag != exp_hashtag or count != exp_count:
            return False
    return True


def check_friendly_tone(text: str) -> bool:
    # Minimal heuristic: presence of friendly words or tone indicators
    friendly_terms = [
        "hey", "hi", "hello", "talofa", "malo", "fam", "cousins", "team", "everyone", "cheers", "thanks", "thank you", "😊", "😀", "!", "mate"
    ]
    lower = text.lower()
    return any(term in lower for term in friendly_terms)


def check_demo_setup_note(text: str) -> bool:
    lower = text.lower()
    if "tongan-trends" in lower and "demo" in lower:
        if "set up" in lower or "setup" in lower or "set-up" in lower:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "initial_env_check_logged": 0.0,
        "env_file_created_correct": 0.0,
        "final_env_check_success_log": 0.0,
        "compute_script_exists_and_args": 0.0,
        "metrics_summary_structure_valid": 0.0,
        "metrics_summary_values_correct": 0.0,
        "metrics_top_hashtags_correct": 0.0,
        "hashtag_counts_csv_correct": 0.0,
        "announcement_includes_required_numbers": 0.0,
        "announcement_includes_commands": 0.0,
        "announcement_friendly_tone": 0.0,
        "announcement_mentions_demo_setup": 0.0,
    }

    # Paths
    input_csv_path = workspace / "input" / "posts.csv"
    env_initial_log_path = workspace / "output" / "env_check_initial.log"
    env_file_path = workspace / "workspace" / ".env"
    env_final_log_path = workspace / "output" / "env_check.log"
    compute_script_path = workspace / "scripts" / "compute_metrics.py"
    metrics_summary_path = workspace / "output" / "metrics_summary.json"
    hashtag_counts_path = workspace / "output" / "hashtag_counts.csv"
    announcement_path = workspace / "output" / "announcement_message.txt"

    # Expected from dataset
    expected = None
    if input_csv_path.exists():
        expected = recompute_expected_from_dataset(input_csv_path)

    # 1) Initial env check log
    initial_text = read_text_file(env_initial_log_path)
    if initial_text is not None:
        if check_initial_env_log(initial_text):
            scores["initial_env_check_logged"] = 1.0

    # 2) Env file exact
    env_text = read_text_file(env_file_path)
    if env_text is not None and check_env_file_exact(env_text):
        scores["env_file_created_correct"] = 1.0

    # 3) Final env check success log
    final_text = read_text_file(env_final_log_path)
    if final_text is not None:
        if check_final_env_log(final_text):
            scores["final_env_check_success_log"] = 1.0

    # 4) Compute script existence and argument support hint
    script_text = read_text_file(compute_script_path)
    if script_text is not None:
        # Look for argparse-like --env-file and references to DATA_PATH
        if "--env-file" in script_text and "DATA_PATH" in script_text:
            scores["compute_script_exists_and_args"] = 1.0

    # 5) Metrics summary structure
    summary = load_json_file(metrics_summary_path)
    if summary is not None and validate_metrics_summary_structure(summary):
        scores["metrics_summary_structure_valid"] = 1.0

    # 6) Metrics values correctness (totals and avg)
    if summary is not None and expected is not None:
        if validate_metrics_values(summary, expected):
            scores["metrics_summary_values_correct"] = 1.0

    # 7) Top hashtags correctness
    if summary is not None and expected is not None:
        if validate_top_hashtags(summary, expected):
            scores["metrics_top_hashtags_correct"] = 1.0

    # 8) Hashtag counts CSV correctness
    if expected is not None and hashtag_counts_path.exists():
        if validate_hashtag_counts_csv(hashtag_counts_path, expected["sorted_hashtags"]):
            scores["hashtag_counts_csv_correct"] = 1.0

    # 9-12) Announcement message checks
    ann_text = read_text_file(announcement_path)
    if ann_text is not None and isinstance(summary, dict):
        # Required numbers: total_posts, avg_likes_per_post, top hashtag and its count
        tp = summary.get("total_posts")
        avg = summary.get("avg_likes_per_post")
        th_list = summary.get("top_hashtags")
        has_numbers = False
        has_commands = False
        if isinstance(tp, int) and isinstance(avg, int) and isinstance(th_list, list) and len(th_list) >= 1:
            top = th_list[0]
            if isinstance(top, dict):
                top_tag = str(top.get("hashtag", ""))
                top_count = top.get("count")
                if isinstance(top_tag, str) and isinstance(top_count, int):
                    # Check presence of values
                    if str(tp) in ann_text and str(avg) in ann_text and top_tag in ann_text and str(top_count) in ann_text:
                        has_numbers = True
        if has_numbers:
            scores["announcement_includes_required_numbers"] = 1.0

        # Commands exact lines
        lines = [ln.rstrip("\n") for ln in ann_text.splitlines()]
        cmd1 = "python tools/check_env.py --env-file workspace/.env"
        cmd2 = "python scripts/compute_metrics.py --env-file workspace/.env"
        if cmd1 in lines and cmd2 in lines and lines.count(cmd1) >= 1 and lines.count(cmd2) >= 1:
            scores["announcement_includes_commands"] = 1.0

        # Friendly tone
        if check_friendly_tone(ann_text):
            scores["announcement_friendly_tone"] = 1.0

        # Demo setup note
        if check_demo_setup_note(ann_text):
            scores["announcement_mentions_demo_setup"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()