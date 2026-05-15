import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    text, err = _safe_read_text(path)
    if err is not None or text is None:
        return None, err or "unreadable"
    try:
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def _load_posts(posts_dir: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    if not posts_dir.exists():
        return None, f"missing posts dir: {posts_dir}"
    posts: List[Dict[str, Any]] = []
    try:
        for p in sorted(posts_dir.glob("*.json")):
            data, err = _safe_load_json(p)
            if err is not None or not isinstance(data, dict):
                return None, f"malformed post file: {p}"
            posts.append(data)
    except Exception as e:
        return None, str(e)
    return posts, None


def _expected_visible_items_from_workspace(workspace: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    # Per requirements: exact tag match exclusion only with these three tags
    excluded = {"objectified-women", "violent", "adult"}
    posts_dir = workspace / "content" / "posts"
    posts, err = _load_posts(posts_dir)
    if err is not None:
        return None, err
    visible: List[Dict[str, Any]] = []
    for p in posts:
        tags = p.get("tags")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            return None, "invalid tags structure in a post"
        if any(t in excluded for t in tags):
            continue
        visible.append(p)
    items = [{"id": v.get("id"), "title": v.get("title")} for v in visible]
    try:
        items.sort(key=lambda x: x.get("id"))
    except Exception:
        return None, "invalid id types for sorting"
    return items, None


def _analyze_filter_code_for_exact_match_only(code_text: str) -> bool:
    """
    Returns True only if the code appears to implement exact tag matching exclusion
    and does not use substring-based or token-splitting logic.
    """
    lowered = code_text
    # Negative indicators: tokenization and substring checks on tag strings
    negative_patterns = [
        r"\.split\(\s*['\"]-\s*['\"]\s*\)",   # split('-')
        r"\bsplit\(\s*['\"]-\s*['\"]\s*\)",  # split('-') generic
        r"\bbanned_tokens\b",
        r"\bbt\s+in\s+t\b",                  # substring membership pattern
        r"\bin\s+t\s+for\s+bt\s+in\b",       # any(bt in t for bt in ...)
    ]
    for pat in negative_patterns:
        if re.search(pat, lowered):
            return False

    # Positive indicators: exact membership check patterns
    positive = False
    # any(t in exclude_tags for t in tags)
    if re.search(r"any\s*\(\s*[a-zA-Z_]\w*\s+in\s+exclude_tags\s+for\s+[a-zA-Z_]\w*\s+in\s+tags\s*\)", lowered):
        positive = True
    # any(tag in exclude_tags for tag in tags)
    if re.search(r"any\s*\(\s*tag\s+in\s+exclude_tags\s+for\s+tag\s+in\s+tags\s*\)", lowered):
        positive = True
    # set(tags) & set(exclude_tags) or isdisjoint
    if ("set(tags)" in lowered and "set(exclude_tags)" in lowered and ("&" in lowered or "isdisjoint" in lowered)):
        positive = True
    # Using a loop with exact equality check
    if re.search(r"for\s+[a-zA-Z_]\w*\s+in\s+tags\s*:\s*.*\bif\s+[a-zA-Z_]\w*\s*in\s*exclude_tags", lowered, flags=re.DOTALL):
        positive = True

    return positive


def _check_report_sections(text: str) -> Dict[str, bool]:
    t = text.lower()
    return {
        "issue": "issue" in t,
        "impact": "impact" in t,
        "root_cause": ("root cause" in t) or ("root-cause" in t),
        "fix": ("fix" in t) or ("fixed" in t) or ("resolution" in t),
        "verification": ("verification" in t) or ("verify" in t) or ("verification steps" in t),
    }


def _count_action_items(text: str) -> int:
    # Count bullet/numbered list lines that look like action items
    action_verbs = [
        "add", "document", "review", "create", "write", "test", "implement",
        "audit", "check", "enforce", "update", "lint", "monitor", "build",
        "automate", "cover", "refactor", "validate", "verify"
    ]
    bullet_pattern = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
    count = 0
    for line in text.splitlines():
        if bullet_pattern.match(line):
            l = line.strip().lower()
            if any(v in l for v in action_verbs):
                # Require at least a few words to avoid trivial bullets
                if len(re.findall(r"[a-zA-Z]+", l)) >= 3:
                    count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "code_exact_tag_match_only": 0.0,
        "visible_output_exact_match": 0.0,
        "output_includes_and_excludes_required_ids": 0.0,
        "output_fields_and_sorting_correct": 0.0,
        "report_sections_complete": 0.0,
        "report_action_items_sufficient": 0.0,
    }

    # Code analysis: ensure filtering logic is exact-match based only (no substring or token splits)
    script_path = workspace / "scripts" / "filter_posts.py"
    code_text, code_err = _safe_read_text(script_path)
    if code_err is None and code_text is not None:
        if _analyze_filter_code_for_exact_match_only(code_text):
            scores["code_exact_tag_match_only"] = 1.0

    # Expected output computed from workspace posts using exact-match rule
    expected_items, exp_err = _expected_visible_items_from_workspace(workspace)
    out_path = workspace / "build" / "visible_posts.json"
    out_json, out_err = _safe_load_json(out_path)

    # Check exact match of visible_posts.json content to expected_items
    if exp_err is None and out_err is None and isinstance(expected_items, list) and isinstance(out_json, list):
        if out_json == expected_items:
            scores["visible_output_exact_match"] = 1.0

    # Check required inclusion/exclusion of ids: include 1 and 2, exclude 3,4,5, and only those two
    if out_err is None and isinstance(out_json, list):
        try:
            ids = [item.get("id") for item in out_json if isinstance(item, dict)]
            if set(ids) == {1, 2} and len(ids) == 2:
                scores["output_includes_and_excludes_required_ids"] = 1.0
        except Exception:
            pass

    # Check fields and sorting: only when the ids requirement is satisfied to avoid accidental partial credit
    if scores["output_includes_and_excludes_required_ids"] == 1.0:
        all_objs = isinstance(out_json, list) and all(isinstance(x, dict) for x in out_json)
        if all_objs:
            # each object must have exactly id and title keys
            fields_ok = all(set(x.keys()) == {"id", "title"} for x in out_json) and len(out_json) == 2
            # sorted ascending by id
            try:
                ids = [x["id"] for x in out_json]
                sorting_ok = ids == sorted(ids)
            except Exception:
                sorting_ok = False
            if fields_ok and sorting_ok:
                scores["output_fields_and_sorting_correct"] = 1.0

    # Report checks
    report_path = workspace / "build" / "report.md"
    report_text, rep_err = _safe_read_text(report_path)
    if rep_err is None and report_text is not None:
        sec = _check_report_sections(report_text)
        if all(sec.values()):
            scores["report_sections_complete"] = 1.0
        if _count_action_items(report_text) >= 3:
            scores["report_action_items_sufficient"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()