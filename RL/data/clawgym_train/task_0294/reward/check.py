import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


EXPECTED_CONFIG_DEFAULTS = {
    "anonymous_weight": 5,
    "encrypted_contact_penalty": 2,
    "corroboration_bonus": 2,
    "corroboration_cap": 2,
    "documentation_bonus": 1,
    "documentation_cap": 3,
    "min_flag_score": 6,
}


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(p: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        posts: List[Dict[str, Any]] = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                posts.append(json.loads(s))
        return posts
    except Exception:
        return None


def _parse_simple_yaml(p: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple key: value pairs on a single line.
    Supports comments (#), integers, floats, booleans, and quoted strings.
    Returns None on error.
    """
    if not p.exists():
        return None
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:
        return None
    data: Dict[str, Any] = {}
    try:
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            in_single = False
            in_double = False
            # strip inline comments not inside quotes
            for i, ch in enumerate(line):
                if ch == "'" and not in_double:
                    in_single = not in_single
                elif ch == '"' and not in_single:
                    in_double = not in_double
                if ch == "#" and not in_single and not in_double:
                    line = line[:i].rstrip()
                    break
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.strip()
            val = v.strip()
            if not key:
                continue
            # Remove surrounding quotes for simple quoted strings
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val_unq = val[1:-1]
            else:
                val_unq = val
            parsed: Any
            if re.fullmatch(r"[-+]?\d+", val_unq or ""):
                parsed = int(val_unq)
            elif re.fullmatch(r"[-+]?\d+\.\d*", val_unq or ""):
                try:
                    parsed = float(val_unq)
                except Exception:
                    parsed = val_unq
            elif (val_unq or "").lower() in ("true", "false"):
                parsed = True if (val_unq or "").lower() == "true" else False
            else:
                parsed = val_unq
            data[key] = parsed
        return data
    except Exception:
        return None


def _cmp_float(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compute_summary(posts: List[Dict[str, Any]]) -> Dict[str, int]:
    total = len(posts)
    anonymous_sources = 0
    total_sources = 0
    for p in posts:
        srcs = p.get("sources", []) or []
        total_sources += len(srcs)
        for s in srcs:
            if s.get("anonymous"):
                anonymous_sources += 1
    return {
        "posts": total,
        "total_sources": total_sources,
        "anonymous_sources": anonymous_sources,
    }


def _compute_scores(posts: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Returns list of post score dicts:
    {
        "id": str, "title": str, "score": float, "anonymous_sources": int, "total_sources": int
    }
    """
    res: List[Dict[str, Any]] = []
    aw = cfg.get("anonymous_weight", 0)
    ecp = cfg.get("encrypted_contact_penalty", 0)
    cb = cfg.get("corroboration_bonus", 0)
    ccap = cfg.get("corroboration_cap", 0)
    db = cfg.get("documentation_bonus", 0)
    dcap = cfg.get("documentation_cap", 0)
    for p in posts:
        srcs = p.get("sources", []) or []
        total_sources = len(srcs)
        anon_count = sum(1 for s in srcs if s.get("anonymous"))
        score = 0.0
        for s in srcs:
            r = 0.0
            r += aw if s.get("anonymous") else 0.0
            r += ecp if s.get("contact") == "encrypted_only" else 0.0
            try:
                corr = int(s.get("corroboration_count", 0))
            except Exception:
                corr = 0
            try:
                docs = int(s.get("docs", 0))
            except Exception:
                docs = 0
            r -= min(max(corr, 0), ccap) * cb
            r -= min(max(docs, 0), dcap) * db
            score += r
        res.append({
            "id": p.get("id"),
            "title": p.get("title"),
            "score": score,
            "anonymous_sources": anon_count,
            "total_sources": total_sources
        })
    # sort by score desc, tie-breaker by id for determinism
    res.sort(key=lambda x: (-x["score"], str(x.get("id") or "")))
    return res


def _run_pipeline(workspace: Path) -> Tuple[bool, str, str]:
    """
    Runs: python moderation/pipeline.py --in data/posts_sample.jsonl --config config/review.yaml --out_dir output
    Returns (success, stdout, stderr)
    """
    cmd = [
        sys.executable,
        "moderation/pipeline.py",
        "--in",
        "data/posts_sample.jsonl",
        "--config",
        "config/review.yaml",
        "--out_dir",
        "output",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=60,
        )
        success = proc.returncode == 0
        return success, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return False, "", f"TimeoutExpired: {e}"
    except Exception as e:
        return False, "", f"Exception: {e}"


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = [dict(r) for r in reader]
            return headers, rows
    except Exception:
        return None, None


def _extract_section(md_text: str, heading_text: str, all_heading_texts: Optional[List[str]] = None) -> Optional[str]:
    """
    Extracts the section content following a heading line that matches heading_text (ignoring leading '#')
    until the next heading line (starting with '#') or until a line that matches any of all_heading_texts (ignoring '#').
    Returns the section content as a single string or None.
    """
    lines = md_text.splitlines()
    normalized_targets = set()
    if all_heading_texts:
        for h in all_heading_texts:
            normalized_targets.add(h.strip())
    start_idx = None
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("#"):
            htxt = stripped.lstrip("#").strip()
        else:
            htxt = stripped
        if htxt == heading_text.strip():
            start_idx = idx + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        stripped = lines[idx].strip()
        next_heading_text = None
        if stripped.startswith("#"):
            next_heading_text = stripped.lstrip("#").strip()
        else:
            if all_heading_texts and stripped in normalized_targets:
                next_heading_text = stripped
        if next_heading_text is not None:
            end_idx = idx
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_keys_present_defaults": 0.0,
        "pipeline_execution_succeeded": 0.0,
        "summary_json_values_correct": 0.0,
        "flagged_csv_exists_and_header": 0.0,
        "flagged_csv_expected_rows_and_order": 0.0,
        "flags_report_json_structure_and_counts": 0.0,
        "flags_report_includes_expected_scores": 0.0,
        "policy_doc_has_section_and_keys": 0.0,
        "policy_doc_threshold_statement": 0.0,
        "architecture_doc_exists_and_headings": 0.0,
        "architecture_doc_data_flow_references": 0.0,
        "architecture_doc_configuration_keys_listed": 0.0,
    }

    # Load config
    config_path = workspace / "config" / "review.yaml"
    cfg = _parse_simple_yaml(config_path) or {}
    # Check config keys and defaults
    expected_ok = True
    for k, v in EXPECTED_CONFIG_DEFAULTS.items():
        if k not in cfg:
            expected_ok = False
            break
        if cfg.get(k) != v:
            expected_ok = False
            break
    scores["config_keys_present_defaults"] = 1.0 if expected_ok else 0.0

    # Load sample posts and expected scores
    posts_path = workspace / "data" / "posts_sample.jsonl"
    posts = _load_jsonl(posts_path) or []
    expected_scores = _compute_scores(posts, EXPECTED_CONFIG_DEFAULTS) if posts else []
    expected_flagged = [p for p in expected_scores if p["score"] >= EXPECTED_CONFIG_DEFAULTS["min_flag_score"]]

    # Run pipeline
    success, _stdout, _stderr = _run_pipeline(workspace)

    # Paths for outputs
    summary_path = workspace / "output" / "summary.json"
    flagged_csv_path = workspace / "output" / "flagged.csv"
    flags_report_path = workspace / "output" / "flags_report.json"

    # Mark execution succeeded only if process succeeded and required outputs exist
    has_flagged = flagged_csv_path.exists()
    has_report = flags_report_path.exists()
    if success and has_flagged and has_report:
        scores["pipeline_execution_succeeded"] = 1.0

    # Check summary.json only when full pipeline artifacts exist
    if has_flagged and has_report:
        summary = _load_json(summary_path)
        if isinstance(summary, dict) and posts:
            computed_summary = _compute_summary(posts)
            if (
                ("posts" in summary and "total_sources" in summary and "anonymous_sources" in summary)
                and summary.get("posts") == computed_summary["posts"]
                and summary.get("total_sources") == computed_summary["total_sources"]
                and summary.get("anonymous_sources") == computed_summary["anonymous_sources"]
            ):
                scores["summary_json_values_correct"] = 1.0

    # Check flagged.csv
    headers, rows = _read_csv(flagged_csv_path)
    expected_header = [
        "post_id",
        "title",
        "total_sources",
        "anonymous_sources",
        "risk_score",
        "flagged",
    ]
    if headers == expected_header and isinstance(rows, list):
        scores["flagged_csv_exists_and_header"] = 1.0

    # Validate flagged rows content and order
    if isinstance(rows, list):
        exp_ids_order = [p["id"] for p in expected_flagged]
        exp_scores_map = {p["id"]: p["score"] for p in expected_flagged}
        csv_ids = [r.get("post_id") for r in rows]
        csv_scores = []
        valid_score_parse = True
        for r in rows:
            try:
                csv_scores.append(float(r.get("risk_score")))
            except Exception:
                valid_score_parse = False
                break
        if csv_ids == exp_ids_order and valid_score_parse:
            all_scores_match = True
            for r in rows:
                rid = r.get("post_id")
                try:
                    sc = float(r.get("risk_score"))
                except Exception:
                    sc = None
                if rid not in exp_scores_map or sc is None or not _cmp_float(sc, float(exp_scores_map[rid])):
                    all_scores_match = False
                    break
            sorted_desc = all(csv_scores[i] >= csv_scores[i + 1] for i in range(len(csv_scores) - 1)) if len(csv_scores) > 1 else True
            if all_scores_match and sorted_desc:
                scores["flagged_csv_expected_rows_and_order"] = 1.0

    # Check flags_report.json
    flags_report = _load_json(flags_report_path)
    if isinstance(flags_report, dict):
        config_used = flags_report.get("config_used")
        flagged_count = flags_report.get("flagged_count")
        post_scores = flags_report.get("post_scores")

        # Check config_used contains expected keys and values
        config_ok = isinstance(config_used, dict) and all(
            k in config_used and config_used.get(k) == EXPECTED_CONFIG_DEFAULTS[k] for k in EXPECTED_CONFIG_DEFAULTS
        )
        # Check flagged_count equals number of rows in flagged.csv (if available)
        csv_row_count = len(rows) if isinstance(rows, list) else None
        count_ok = isinstance(flagged_count, int) and (csv_row_count is not None and flagged_count == csv_row_count)
        # Ensure post_scores is a list
        post_scores_ok = isinstance(post_scores, list)
        if config_ok and count_ok and post_scores_ok:
            scores["flags_report_json_structure_and_counts"] = 1.0

        # Verify post_scores includes expected flagged posts with correct details
        if isinstance(post_scores, list):
            ps_map = {e.get("id"): e for e in post_scores if isinstance(e, dict) and "id" in e}
            all_expected_present = True
            for ef in expected_flagged:
                rid = ef["id"]
                e_entry = ps_map.get(rid)
                if not e_entry:
                    all_expected_present = False
                    break
                title_ok = (e_entry.get("title") == ef["title"])
                try:
                    score_ok = _cmp_float(float(e_entry.get("score")), float(ef["score"]))
                except Exception:
                    score_ok = False
                anon_ok = (e_entry.get("anonymous_sources") == ef["anonymous_sources"])
                total_ok = (e_entry.get("total_sources") == ef["total_sources"])
                if not (title_ok and score_ok and anon_ok and total_ok):
                    all_expected_present = False
                    break
            if all_expected_present:
                scores["flags_report_includes_expected_scores"] = 1.0

    # Policy documentation checks
    policy_path = workspace / "docs" / "source_policy.md"
    policy_text = _read_text(policy_path) or ""
    section_text = None
    if policy_text:
        known_headings = ["Anonymous Source Credibility Review"]
        section_text = _extract_section(policy_text, "Anonymous Source Credibility Review", known_headings)
    if section_text:
        has_all_keys = True
        for k, v in EXPECTED_CONFIG_DEFAULTS.items():
            if k not in section_text:
                has_all_keys = False
                break
            if not re.search(rf"\b{re.escape(str(v))}\b", section_text):
                has_all_keys = False
                break
        mentions_config_path = "config/review.yaml" in section_text
        mentions_anonymous_and_review = ("anonymous" in section_text.lower()) and ("review" in section_text.lower())
        if has_all_keys and mentions_config_path and mentions_anonymous_and_review:
            scores["policy_doc_has_section_and_keys"] = 1.0

        threshold_phrase_ok = ("risk_score >= min_flag_score" in section_text)
        legal_review_ok = ("legal review" in section_text.lower())
        if threshold_phrase_ok and legal_review_ok:
            scores["policy_doc_threshold_statement"] = 1.0

    # Architecture documentation checks
    arch_path = workspace / "docs" / "credibility_architecture.md"
    arch_text = _read_text(arch_path) or ""
    if arch_text:
        lines = [ln.strip() for ln in arch_text.splitlines()]
        has_title_line = any(ln == "Anonymous Source Credibility Module — Architecture" for ln in lines)
        has_version_line = any(ln == "Architecture Version: 1.0" for ln in lines)
        required_headings = ["Overview", "Data Flow", "Scoring Rules", "Configuration Keys", "Review Workflow"]
        has_all_headings = True
        for h in required_headings:
            found = False
            for raw in lines:
                if raw.startswith("#"):
                    htxt = raw.lstrip("#").strip()
                else:
                    htxt = raw
                if htxt == h:
                    found = True
                    break
            if not found:
                has_all_headings = False
                break
        if has_title_line and has_version_line and has_all_headings:
            scores["architecture_doc_exists_and_headings"] = 1.0

        data_flow_section = _extract_section(arch_text, "Data Flow", ["Overview", "Data Flow", "Scoring Rules", "Configuration Keys", "Review Workflow"])
        if data_flow_section:
            df_ok = all(s in data_flow_section for s in [
                "data/posts_sample.jsonl",
                "config/review.yaml",
                "output/summary.json",
                "output/flagged.csv",
                "output/flags_report.json",
            ])
            if df_ok:
                scores["architecture_doc_data_flow_references"] = 1.0

        cfg_section = _extract_section(arch_text, "Configuration Keys", ["Overview", "Data Flow", "Scoring Rules", "Configuration Keys", "Review Workflow"])
        if cfg_section:
            keys_listed_ok = all(k in cfg_section for k in EXPECTED_CONFIG_DEFAULTS.keys())
            if keys_listed_ok:
                scores["architecture_doc_configuration_keys_listed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()