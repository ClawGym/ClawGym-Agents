import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _safe_read_text(p: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return p.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _parse_transcript(path: Path) -> Optional[dict]:
    text, err = _safe_read_text(path)
    if text is None:
        return None
    guest = None
    team = None
    tags_line = None
    # Find header fields
    for line in text.splitlines():
        if line.startswith("Guest:"):
            guest = line[len("Guest:"):].strip()
        elif line.startswith("Team:"):
            team = line[len("Team:"):].strip()
        elif line.startswith("Tags:"):
            tags_line = line[len("Tags:"):].strip()
        # Pull quote appears after "Show Notes" section, but we scan entire file for robustness
    # Parse pull quote line
    # Pattern: Pull quote (timestamp 00:05:12): "Some text"
    pull_quote_match = None
    timestamp = None
    quote_text = None
    for line in text.splitlines():
        m = re.match(r'^Pull quote \(timestamp ([0-9]{2}:[0-9]{2}:[0-9]{2})\):\s*(.*)$', line)
        if m:
            pull_quote_match = line
            timestamp = m.group(1)
            rest = m.group(2).strip()
            # Extract text inside the first and last double quotes
            if '"' in rest:
                first = rest.find('"')
                last = rest.rfind('"')
                if first != -1 and last != -1 and last > first:
                    quote_text = rest[first + 1:last]
                else:
                    # No matching pairs; fallback to rest without surrounding whitespace
                    quote_text = rest
            else:
                quote_text = rest
            break
    if guest is None or team is None or tags_line is None or pull_quote_match is None or quote_text is None or timestamp is None:
        return None
    tags = [t.strip() for t in tags_line.split(";")]
    return {
        "episode_id": path.stem,
        "guest_name": guest,
        "team": team,
        "tags": tags,
        "pull_quote": {
            "text": quote_text,
            "timestamp": timestamp,
        },
        "path": path,
    }


def _discover_transcripts(transcripts_dir: Path) -> Dict[str, dict]:
    results: Dict[str, dict] = {}
    if not transcripts_dir.exists():
        return results
    for p in sorted(transcripts_dir.glob("*.md")):
        parsed = _parse_transcript(p)
        if parsed is not None:
            results[parsed["episode_id"]] = parsed
    return results


def _load_jsonl_by_episode(path: Path) -> Tuple[Optional[Dict[str, dict]], Optional[str], Optional[List[dict]]]:
    text, err = _safe_read_text(path)
    if text is None:
        return None, err, None
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    mapping: Dict[str, dict] = {}
    records: List[dict] = []
    try:
        for ln in lines:
            obj = json.loads(ln)
            if not isinstance(obj, dict):
                return None, "Non-object JSON line", None
            records.append(obj)
            eid = obj.get("episode_id")
            if isinstance(eid, str):
                mapping[eid] = obj
    except Exception as e:
        return None, str(e), None
    return mapping, None, records


def _load_csv_rows(path: Path) -> Tuple[Optional[List[dict]], Optional[str], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None, "Missing header", None
            rows = list(reader)
            return rows, None, fieldnames
    except Exception as e:
        return None, str(e), None


def _extract_quoted_substrings(s: str) -> List[str]:
    # Extract all substrings enclosed in double quotes.
    results = []
    in_quote = False
    buf = []
    for ch in s:
        if ch == '"' and not in_quote:
            in_quote = True
            buf = []
        elif ch == '"' and in_quote:
            in_quote = False
            results.append("".join(buf))
            buf = []
        else:
            if in_quote:
                buf.append(ch)
    return results


def _normalize_path_str(s: str) -> str:
    # Convert to posix-style and strip whitespace
    s = s.strip()
    # Avoid resolving non-existent paths; just normalize separators
    return Path(s).as_posix()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "episodes_summary_file_and_count": 0.0,
        "episodes_summary_values_match": 0.0,
        "audit_list_complete": 0.0,
        "social_posts_structure": 0.0,
        "social_posts_x_requirements": 0.0,
        "social_posts_instagram_requirements": 0.0,
        "social_posts_quote_consistency_with_summary": 0.0,
    }

    # Discover inputs
    transcripts_dir = workspace / "input" / "transcripts"
    transcripts = _discover_transcripts(transcripts_dir)
    expected_episode_ids = sorted(transcripts.keys())

    # Expected summary data from transcripts
    expected_summary: Dict[str, dict] = {}
    for eid, info in transcripts.items():
        expected_summary[eid] = {
            "episode_id": eid,
            "guest_name": info["guest_name"],
            "team": info["team"],
            "tags": info["tags"],
            "pull_quote": {
                "text": info["pull_quote"]["text"],
                "timestamp": info["pull_quote"]["timestamp"],
            },
        }

    # Load descriptions (for social posts expectations)
    descriptions_path = workspace / "input" / "descriptions.csv"
    desc_rows, desc_err, desc_fields = _load_csv_rows(descriptions_path)
    expected_episodes_from_desc: List[str] = []
    if desc_rows is not None:
        for row in desc_rows:
            eid = row.get("episode_id")
            if isinstance(eid, str) and eid.strip():
                expected_episodes_from_desc.append(eid.strip())

    # 1) Validate episodes_summary.jsonl
    summary_path = workspace / "output" / "episodes_summary.jsonl"
    summary_map, summary_err, summary_records = _load_jsonl_by_episode(summary_path)
    if summary_map is not None and summary_records is not None:
        # Check line count equals number of transcripts, and set equality
        present_ids = sorted(summary_map.keys())
        if len(summary_records) == len(expected_episode_ids) and set(present_ids) == set(expected_episode_ids):
            scores["episodes_summary_file_and_count"] = 1.0
        else:
            scores["episodes_summary_file_and_count"] = 0.0

        # Check values match for each episode
        total = len(expected_episode_ids)
        correct = 0
        for eid in expected_episode_ids:
            expected = expected_summary.get(eid)
            actual = summary_map.get(eid)
            if not isinstance(actual, dict):
                continue
            # Structure and type checks
            ok = True
            # Required keys
            required_keys = ["episode_id", "guest_name", "team", "tags", "pull_quote"]
            for k in required_keys:
                if k not in actual:
                    ok = False
                    break
            if not ok:
                continue
            # Episode ID exact
            if actual.get("episode_id") != expected.get("episode_id"):
                ok = False
            # Guest, team exact
            if actual.get("guest_name") != expected.get("guest_name"):
                ok = False
            if actual.get("team") != expected.get("team"):
                ok = False
            # Tags array of strings, exact order
            tags = actual.get("tags")
            if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                ok = False
            else:
                if tags != expected.get("tags"):
                    ok = False
            # pull_quote object with text and timestamp strings
            pq = actual.get("pull_quote")
            if not isinstance(pq, dict):
                ok = False
            else:
                if not isinstance(pq.get("text"), str) or not isinstance(pq.get("timestamp"), str):
                    ok = False
                else:
                    if pq.get("text") != expected["pull_quote"]["text"]:
                        ok = False
                    if pq.get("timestamp") != expected["pull_quote"]["timestamp"]:
                        ok = False
            if ok:
                correct += 1
        if total > 0:
            scores["episodes_summary_values_match"] = correct / total
        else:
            # No transcripts to check; treat as 0.0 to avoid awarding when nothing to do
            scores["episodes_summary_values_match"] = 0.0
    else:
        scores["episodes_summary_file_and_count"] = 0.0
        scores["episodes_summary_values_match"] = 0.0

    # 3) Validate audit/inspected_transcripts.txt
    audit_path = workspace / "output" / "audit" / "inspected_transcripts.txt"
    audit_text, audit_err = _safe_read_text(audit_path)
    if audit_text is not None:
        lines = [ln.rstrip("\n").strip() for ln in audit_text.splitlines() if ln.strip() != ""]
        if len(lines) >= 1:
            total_line = lines[-1]
            path_lines = lines[:-1]
            # Verify TOTAL
            m = re.match(r'^TOTAL=(\d+)$', total_line)
            if m:
                total_num = int(m.group(1))
                # Normalize listed paths
                normalized_listed = set()
                for ln in path_lines:
                    normalized_listed.add(_normalize_path_str(ln))
                # Build expected set (accept both relative and absolute forms, but compare using relative posix)
                expected_paths_rel = set()
                for eid in expected_episode_ids:
                    p = transcripts[eid]["path"]
                    # Relative path from workspace
                    rel = p.relative_to(workspace).as_posix() if p.is_absolute() and str(p).startswith(str(workspace)) else p.as_posix()
                    # Standard expected relative form
                    expected_paths_rel.add((workspace / "input" / "transcripts" / f"{eid}.md").as_posix())
                    # Ensure rel is posix
                    expected_paths_rel.add(rel)
                # We should accept if the set of normalized paths equals the set of expected canonical relative forms
                # To be strict but flexible, accept any of the canonical relative paths set. We'll build the canonical set:
                canonical_expected = set((workspace / "input" / "transcripts" / f"{eid}.md").as_posix() for eid in expected_episode_ids)
                # Some users may list relative without workspace prefix; also accept "input/transcripts/epX.md"
                alt_expected = set(Path("input/transcripts") .joinpath(f"{eid}.md").as_posix() for eid in expected_episode_ids)
                # Accept if listed equals canonical or alt set
                paths_ok = False
                if normalized_listed == canonical_expected or normalized_listed == alt_expected:
                    paths_ok = True
                # Also accept if they listed absolute paths exactly matching the absolute files
                abs_expected = set(transcripts[eid]["path"].resolve().as_posix() for eid in expected_episode_ids)
                if normalized_listed == abs_expected:
                    paths_ok = True
                # Or if they mixed forms but represent the same files: check filenames set
                if not paths_ok:
                    listed_basenames = set(Path(p).name for p in normalized_listed)
                    expected_basenames = set(f"{eid}.md" for eid in expected_episode_ids)
                    if listed_basenames == expected_basenames and len(normalized_listed) == len(expected_basenames):
                        paths_ok = True
                # Count check
                count_ok = (total_num == len(expected_episode_ids)) and (len(path_lines) == len(expected_episode_ids))
                if paths_ok and count_ok:
                    scores["audit_list_complete"] = 1.0
                else:
                    scores["audit_list_complete"] = 0.0
            else:
                scores["audit_list_complete"] = 0.0
        else:
            scores["audit_list_complete"] = 0.0
    else:
        scores["audit_list_complete"] = 0.0

    # 2) Validate social_posts.csv
    social_path = workspace / "output" / "social_posts.csv"
    social_rows, social_err, social_fields = _load_csv_rows(social_path)
    # Build expected episodes from descriptions
    expected_posts_eps = expected_episodes_from_desc
    expected_posts_set = set(expected_posts_eps)
    # Build mapping for guest names and quotes expected
    guest_by_ep = {eid: transcripts[eid]["guest_name"] for eid in transcripts}
    quote_by_ep = {eid: transcripts[eid]["pull_quote"]["text"] for eid in transcripts}
    # Structure check
    if social_rows is not None and social_fields is not None and desc_rows is not None:
        # Header must be exactly: episode_id, platform, post_text
        header_ok = social_fields == ["episode_id", "platform", "post_text"]
        # Number of rows must be 2 per episode in descriptions
        rows_ok = len(social_rows) == (2 * len(expected_posts_eps))
        # Platforms must be exactly X and Instagram for each expected episode, and no others
        allowed_platforms = {"X", "Instagram"}
        per_ep_platforms: Dict[str, List[str]] = {}
        extra_episodes_present = False
        only_allowed_platforms = True
        for row in social_rows:
            eid = (row.get("episode_id") or "").strip()
            plat = (row.get("platform") or "").strip()
            if plat not in allowed_platforms:
                only_allowed_platforms = False
            if eid not in expected_posts_set:
                extra_episodes_present = True
            per_ep_platforms.setdefault(eid, []).append(plat)
        platforms_per_ep_ok = True
        missing_posts = False
        for eid in expected_posts_eps:
            plats = per_ep_platforms.get(eid, [])
            if sorted(plats) != ["Instagram", "X"]:
                platforms_per_ep_ok = False
            if len(plats) != 2:
                missing_posts = True
        # Ensure no extra episodes included
        no_extra_eps_ok = not extra_episodes_present
        if header_ok and rows_ok and platforms_per_ep_ok and only_allowed_platforms and no_extra_eps_ok and not missing_posts:
            scores["social_posts_structure"] = 1.0
        else:
            scores["social_posts_structure"] = 0.0
    else:
        scores["social_posts_structure"] = 0.0

    # Content checks for X and Instagram
    # We'll evaluate per expected episode and platform; missing rows count as failures.
    if desc_rows is not None:
        # Organize social rows by (episode_id, platform)
        posts_by_key: Dict[Tuple[str, str], str] = {}
        if social_rows is not None:
            for row in social_rows:
                eid = (row.get("episode_id") or "").strip()
                plat = (row.get("platform") or "").strip()
                post_text = (row.get("post_text") or "")
                posts_by_key[(eid, plat)] = post_text

        # Load summary for quote consistency check
        summary_for_consistency: Dict[str, str] = {}
        if summary_map is not None:
            for eid, obj in summary_map.items():
                if isinstance(obj, dict):
                    pq = obj.get("pull_quote")
                    if isinstance(pq, dict):
                        t = pq.get("text")
                        if isinstance(t, str):
                            summary_for_consistency[eid] = t

        # X requirements
        total_x_expected = len(expected_posts_eps)
        x_pass = 0
        for eid in expected_posts_eps:
            post_text = posts_by_key.get((eid, "X"))
            if not isinstance(post_text, str):
                continue
            # Length <= 280
            ok = True
            if len(post_text) > 280:
                ok = False
            # Include team name
            if "River City Rockets" not in post_text:
                ok = False
            # Include guest name (exact from transcript)
            guest_name = guest_by_ep.get(eid)
            if not guest_name or guest_name not in post_text:
                ok = False
            # Include pull quote text exactly enclosed in double quotes
            quoted_segments = _extract_quoted_substrings(post_text)
            expected_quote = quote_by_ep.get(eid)
            if not expected_quote or expected_quote not in quoted_segments:
                ok = False
            # Include CTA phrase "Listen now" or "Tune in"
            if ("Listen now" not in post_text) and ("Tune in" not in post_text):
                ok = False
            if ok:
                x_pass += 1
        if total_x_expected > 0:
            scores["social_posts_x_requirements"] = x_pass / total_x_expected
        else:
            scores["social_posts_x_requirements"] = 0.0

        # Instagram requirements
        total_ig_expected = len(expected_posts_eps)
        ig_pass = 0
        for eid in expected_posts_eps:
            post_text = posts_by_key.get((eid, "Instagram"))
            if not isinstance(post_text, str):
                continue
            ok = True
            if len(post_text) > 300:
                ok = False
            if "River City Rockets" not in post_text:
                ok = False
            guest_name = guest_by_ep.get(eid)
            if not guest_name or guest_name not in post_text:
                ok = False
            quoted_segments = _extract_quoted_substrings(post_text)
            expected_quote = quote_by_ep.get(eid)
            if not expected_quote or expected_quote not in quoted_segments:
                ok = False
            # Hashtags
            if "#RCRockets" not in post_text or "#ClubhouseChats" not in post_text:
                ok = False
            if ok:
                ig_pass += 1
        if total_ig_expected > 0:
            scores["social_posts_instagram_requirements"] = ig_pass / total_ig_expected
        else:
            scores["social_posts_instagram_requirements"] = 0.0

        # Quote consistency with summary file
        total_posts_expected = 2 * len(expected_posts_eps)
        consistency_pass = 0
        counted = 0
        if social_rows is not None and summary_map is not None:
            for eid in expected_posts_eps:
                for plat in ["X", "Instagram"]:
                    post_text = posts_by_key.get((eid, plat))
                    counted += 1
                    if not isinstance(post_text, str):
                        continue
                    quoted_segments = _extract_quoted_substrings(post_text)
                    summary_quote = summary_for_consistency.get(eid)
                    if isinstance(summary_quote, str) and summary_quote in quoted_segments:
                        consistency_pass += 1
        if total_posts_expected > 0:
            scores["social_posts_quote_consistency_with_summary"] = consistency_pass / total_posts_expected
        else:
            scores["social_posts_quote_consistency_with_summary"] = 0.0
    else:
        # Cannot validate posts without descriptions
        scores["social_posts_x_requirements"] = 0.0
        scores["social_posts_instagram_requirements"] = 0.0
        scores["social_posts_quote_consistency_with_summary"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()