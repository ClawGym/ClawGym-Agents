import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False, ""


def _load_json(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_newsletter_yaml(path: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    ok, content = _read_text(path)
    if not ok:
        return False, None
    # Normalize potential literal "\n" sequences into real newlines
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = content.replace("\\n", "\n")
    lines = content.split("\n")

    result: Dict[str, Any] = {"sender": {}, "limits": {}, "tone": {"positive_keywords": [], "banned_words": []}}
    section: Optional[str] = None
    tone_list_key: Optional[str] = None

    def indent_level(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    for raw in lines:
        if not raw.strip():
            continue
        ind = indent_level(raw)
        line = raw.strip()

        # Top-level sections
        if ind == 0 and line.endswith(":"):
            key = line[:-1].strip()
            if key in ("sender", "limits", "tone"):
                section = key
                tone_list_key = None
            else:
                # Unknown top-level; ignore
                section = None
                tone_list_key = None
            continue

        if section in ("sender", "limits"):
            # Expect "key: value" with indent >= 2
            if ind >= 2 and ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                if v == "":
                    # Not expected for sender/limits in this task; treat as failure
                    return False, None
                v = _strip_quotes(v)
                # Try to cast ints for limits
                if section == "limits":
                    try:
                        result[section][k] = int(v)
                    except ValueError:
                        result[section][k] = v
                else:
                    result[section][k] = v
            else:
                # Structure unexpected
                continue

        elif section == "tone":
            # tone has keys with lists
            if ind == 2 and line.endswith(":"):
                key = line[:-1].strip()
                if key in ("positive_keywords", "banned_words"):
                    tone_list_key = key
                    if tone_list_key not in result["tone"]:
                        result["tone"][tone_list_key] = []
                else:
                    tone_list_key = None
                continue
            if tone_list_key and ind >= 4 and line.startswith("- "):
                item = line[2:].strip()
                item = _strip_quotes(item)
                result["tone"][tone_list_key].append(item)
            # else ignore other lines under tone
        else:
            # Unknown section; ignore
            continue

    # Minimal validation
    if not isinstance(result.get("sender"), dict):
        return False, None
    if not isinstance(result.get("limits"), dict):
        return False, None
    if not isinstance(result.get("tone"), dict):
        return False, None
    return True, result


def _compute_rewrite(text: str, max_words: int, positive_keywords: List[str], banned_words: List[str]) -> str:
    # Mirror src/tone_tools.py logic deterministically based on provided description/content
    t = text.replace("Parkinson's disease", "Parkinson's")
    tokens = t.split()
    lower_banned = set(w.lower() for w in (banned_words or []))
    filtered_tokens = [tok for tok in tokens if tok.lower() not in lower_banned]
    t = " ".join(filtered_tokens)
    lower_t = t.lower()
    has_positive = any(k.lower() in lower_t for k in (positive_keywords or []))
    if not has_positive and positive_keywords:
        t = t.rstrip() + " " + positive_keywords[0].lower()
    words = t.split()
    if len(words) > max_words:
        t = " ".join(words[:max_words])
    return t


def _no_banned_standalone(text: str, banned_words: List[str]) -> bool:
    if not banned_words:
        return True
    lower_banned = set(w.lower() for w in banned_words)
    punct = ",.;:!?\'\""
    for tok in text.split():
        stripped = tok.strip(punct).lower()
        if stripped in lower_banned:
            return False
    return True


def _has_positive_keyword(text: str, positive_keywords: List[str]) -> bool:
    if not positive_keywords:
        return True
    lt = text.lower()
    return any(k.lower() in lt for k in positive_keywords)


def _term_normalized(input_text: str, output_text: str) -> bool:
    # output must not contain "Parkinson's disease". If input had it, output must contain "Parkinson's".
    if "Parkinson's disease" in output_text:
        return False
    if "Parkinson's disease" in input_text and "Parkinson's" not in output_text:
        return False
    return True


def _within_length_limit(text: str, max_words: int) -> bool:
    return len(text.split()) <= max_words


def _compute_expected_results(drafts: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Dict[str, bool]]:
    out: Dict[str, Dict[str, bool]] = {}
    max_words = int(cfg["limits"].get("max_body_words", 0))
    positive = list(cfg["tone"].get("positive_keywords", []))
    banned = list(cfg["tone"].get("banned_words", []))
    for d in drafts:
        did = d.get("id", "")
        text_in = d.get("text", "")
        rewritten = _compute_rewrite(text_in, max_words, positive, banned)
        checks = {
            "term_normalized": _term_normalized(text_in, rewritten),
            "no_banned_words": _no_banned_standalone(rewritten, banned),
            "has_positive_keyword": _has_positive_keyword(rewritten, positive),
            "within_length_limit": _within_length_limit(rewritten, max_words),
        }
        out[did] = checks
    return out


def _validate_report_structure(report: Any) -> Tuple[bool, Optional[int], Optional[int], Optional[int]]:
    if not isinstance(report, dict):
        return False, None, None, None
    if not all(k in report for k in ("total", "passed", "failed", "results")):
        return False, None, None, None
    if not isinstance(report["results"], list):
        return False, None, None, None
    total = report.get("total")
    passed = report.get("passed")
    failed = report.get("failed")
    if not isinstance(total, int) or not isinstance(passed, int) or not isinstance(failed, int):
        return False, None, None, None
    # Validate each result entry
    for item in report["results"]:
        if not isinstance(item, dict):
            return False, None, None, None
        if not all(k in item for k in ("id", "checks", "passed")):
            return False, None, None, None
        if not isinstance(item["id"], str):
            return False, None, None, None
        if not isinstance(item["passed"], bool):
            return False, None, None, None
        checks = item["checks"]
        if not isinstance(checks, dict):
            return False, None, None, None
        req_keys = {"term_normalized", "no_banned_words", "has_positive_keyword", "within_length_limit"}
        if set(checks.keys()) != req_keys:
            return False, None, None, None
        for v in checks.values():
            if not isinstance(v, bool):
                return False, None, None, None
    # Internal consistency
    computed_total = len(report["results"])
    computed_passed = sum(1 for r in report["results"] if bool(r.get("passed")))
    computed_failed = computed_total - computed_passed
    if total != computed_total or passed != computed_passed or failed != computed_failed:
        return False, computed_total, computed_passed, computed_failed
    return True, computed_total, computed_passed, computed_failed


def _parse_drafts(path: Path) -> Tuple[bool, Optional[List[Dict[str, Any]]]]:
    ok, data = _load_json(path)
    if not ok or not isinstance(data, list):
        return False, None
    # Validate basic structure
    for item in data:
        if not isinstance(item, dict):
            return False, None
        if "id" not in item or "text" not in item:
            return False, None
    return True, data


def _compute_config_checks(cfg: Dict[str, Any]) -> Dict[str, bool]:
    sender = cfg.get("sender", {})
    limits = cfg.get("limits", {})
    tone = cfg.get("tone", {})
    sender_from_fields_present = bool(sender.get("from_name")) and bool(sender.get("from_email"))
    from_email_has_at = bool(sender.get("from_email")) and ("@" in str(sender.get("from_email")))
    try:
        msl = int(limits.get("max_subject_length"))
    except Exception:
        msl = None
    try:
        mbw = int(limits.get("max_body_words"))
    except Exception:
        mbw = None
    max_subject_length_in_range = msl is not None and 30 <= msl <= 72
    max_body_words_in_range = mbw is not None and 80 <= mbw <= 200
    pos = tone.get("positive_keywords")
    ban = tone.get("banned_words")
    positive_keywords_count = isinstance(pos, list) and len(pos) >= 2
    banned_words_count = isinstance(ban, list) and len(ban) >= 2
    return {
        "sender_from_fields_present": sender_from_fields_present,
        "from_email_has_at": from_email_has_at,
        "max_subject_length_in_range": max_subject_length_in_range,
        "max_body_words_in_range": max_body_words_in_range,
        "positive_keywords_count": positive_keywords_count,
        "banned_words_count": banned_words_count,
    }


def _validate_manual_rewrites(rewrites: Any, drafts: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Tuple[bool, bool]:
    # returns (structure_ok, all_requirements_met)
    if not isinstance(rewrites, list):
        return False, False
    draft_ids = [d["id"] for d in drafts]
    id_to_text = {d["id"]: d["text"] for d in drafts}
    if len(rewrites) != len(drafts):
        structure_ok = False
    else:
        structure_ok = True
    # Validate presence and fields
    all_reqs = True
    seen_ids = set()
    for item in rewrites:
        if not isinstance(item, dict):
            return False, False
        if "id" not in item or "rewritten_text" not in item:
            return False, False
        did = item["id"]
        seen_ids.add(did)
        rewritten_text = str(item["rewritten_text"])
        if did not in id_to_text:
            all_reqs = False
            continue
        input_text = id_to_text[did]
        # Requirement checks
        term_ok = _term_normalized(input_text, rewritten_text)
        no_banned = _no_banned_standalone(rewritten_text, cfg["tone"].get("banned_words", []))
        has_pos = _has_positive_keyword(rewritten_text, cfg["tone"].get("positive_keywords", []))
        within_limit = _within_length_limit(rewritten_text, int(cfg["limits"].get("max_body_words", 0)))
        if not (term_ok and no_banned and has_pos and within_limit):
            all_reqs = False
    if set(draft_ids) != seen_ids:
        structure_ok = False
    return structure_ok, all_reqs


def _word_count(text: str) -> int:
    return len(text.split())


def _email_mentions_totals(email_text: str, report: Dict[str, Any]) -> bool:
    # look for "<passed> passed out of <total>"
    m = re.search(r"(\d+)\s+passed\s+out\s+of\s+(\d+)", email_text, flags=re.IGNORECASE)
    if not m:
        return False
    passed = int(m.group(1))
    total = int(m.group(2))
    # Validate against report counts
    try:
        return passed == int(report.get("passed")) and total == int(report.get("total"))
    except Exception:
        return False


def _email_config_summary_correct(email_text: str, cfg_report: Dict[str, Any]) -> bool:
    # If config passed, email should indicate it passed (contains "config" and "passed").
    # If failed, email should list which checks failed by name.
    if not isinstance(cfg_report, dict):
        return False
    checks = cfg_report.get("checks", {})
    passed = bool(cfg_report.get("passed"))
    text_low = email_text.lower()
    if passed:
        return ("config" in text_low) and ("passed" in text_low)
    else:
        failing = [k for k, v in checks.items() if not v]
        # Require all failing check names to be present in the email text
        for name in failing:
            if name not in email_text:
                return False
        return len(failing) > 0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "script_exists": 0.0,
        "rewriter_report_exists": 0.0,
        "rewriter_report_structure_valid": 0.0,
        "rewriter_report_checks_correct": 0.0,
        "config_check_exists": 0.0,
        "config_check_structure_valid": 0.0,
        "config_check_values_correct": 0.0,
        "manual_rewrites_exists": 0.0,
        "manual_rewrites_structure_valid": 0.0,
        "manual_rewrites_requirements_met": 0.0,
        "email_exists": 0.0,
        "email_under_word_limit": 0.0,
        "email_mentions_totals": 0.0,
        "email_config_summary_correct": 0.0,
        "email_includes_file_paths": 0.0,
    }

    # Paths
    script_path = workspace / "tests" / "validate_rewriter.py"
    report_path = workspace / "output" / "reports" / "rewriter_validation.json"
    cfg_report_path = workspace / "output" / "reports" / "config_check.json"
    manual_path = workspace / "output" / "rewrites" / "manual.json"
    email_path = workspace / "output" / "drafts" / "email_to_editor.txt"
    cfg_path = workspace / "config" / "newsletter.yaml"
    drafts_path = workspace / "input" / "drafts.json"

    # Existence of script
    if script_path.exists():
        scores["script_exists"] = 1.0

    # Load config
    cfg_ok, cfg = _parse_newsletter_yaml(cfg_path)
    # Load drafts
    drafts_ok, drafts = _parse_drafts(drafts_path)

    # Validate rewriter_validation.json
    ok_report, report_data = _load_json(report_path)
    if ok_report and isinstance(report_data, dict):
        scores["rewriter_report_exists"] = 1.0
        struct_ok, comp_total, comp_passed, comp_failed = _validate_report_structure(report_data)
        if struct_ok:
            scores["rewriter_report_structure_valid"] = 1.0
        # If we can recompute expected checks, compare
        if cfg_ok and drafts_ok and struct_ok:
            expected = _compute_expected_results(drafts, cfg)
            # Map report results by id
            rep_ids = [r.get("id") for r in report_data["results"]]
            # Ensure all draft IDs are present
            if set(expected.keys()) == set(rep_ids):
                checks_match = True
                for r in report_data["results"]:
                    did = r["id"]
                    exp_checks = expected[did]
                    if r["checks"] != exp_checks:
                        checks_match = False
                        break
                    # Also ensure "passed" aligns with all checks True
                    if r["passed"] != all(exp_checks.values()):
                        checks_match = False
                        break
                # Validate top-level counts align with recomputed
                if checks_match:
                    recomputed_passed = sum(1 for v in expected.values() if all(v.values()))
                    if report_data.get("total") == len(expected) and report_data.get("passed") == recomputed_passed and report_data.get("failed") == (len(expected) - recomputed_passed):
                        scores["rewriter_report_checks_correct"] = 1.0
            else:
                # IDs mismatch -> incorrect
                scores["rewriter_report_checks_correct"] = 0.0
        else:
            # Cannot recompute expected -> leave as 0.0
            pass

    # Validate config_check.json
    ok_cfg_report, cfg_report = _load_json(cfg_report_path)
    if ok_cfg_report and isinstance(cfg_report, dict):
        scores["config_check_exists"] = 1.0
        # Structure
        ch = cfg_report.get("checks")
        if isinstance(ch, dict):
            expected_keys = {
                "sender_from_fields_present",
                "from_email_has_at",
                "max_subject_length_in_range",
                "max_body_words_in_range",
                "positive_keywords_count",
                "banned_words_count",
            }
            if set(ch.keys()) == expected_keys and all(isinstance(v, bool) for v in ch.values()) and isinstance(cfg_report.get("passed"), bool):
                # passed must equal all checks True
                if cfg_report["passed"] == all(ch.values()):
                    scores["config_check_structure_valid"] = 1.0
        # Values correctness
        if cfg_ok and scores["config_check_structure_valid"] == 1.0:
            exp = _compute_config_checks(cfg)
            if ch == exp and cfg_report["passed"] == all(exp.values()):
                scores["config_check_values_correct"] = 1.0

    # Validate manual rewrites
    ok_manual, manual_data = _load_json(manual_path)
    if ok_manual:
        scores["manual_rewrites_exists"] = 1.0
        if drafts_ok and cfg_ok:
            struct_ok, all_req = _validate_manual_rewrites(manual_data, drafts, cfg)
            if struct_ok:
                scores["manual_rewrites_structure_valid"] = 1.0
            if all_req:
                scores["manual_rewrites_requirements_met"] = 1.0

    # Validate email
    email_ok, email_text = _read_text(email_path)
    if email_ok:
        scores["email_exists"] = 1.0
        wc = _word_count(email_text)
        if wc <= 150:
            scores["email_under_word_limit"] = 1.0
        # Totals mention
        if ok_report and isinstance(report_data, dict):
            if _email_mentions_totals(email_text, report_data):
                scores["email_mentions_totals"] = 1.0
        # Config summary correctness
        if ok_cfg_report and isinstance(cfg_report, dict):
            if _email_config_summary_correct(email_text, cfg_report):
                scores["email_config_summary_correct"] = 1.0
        # Paths inclusion: must include at least three expected paths
        expected_paths = [
            "tests/validate_rewriter.py",
            "output/reports/rewriter_validation.json",
            "output/reports/config_check.json",
            "output/rewrites/manual.json",
        ]
        found = sum(1 for p in expected_paths if p in email_text)
        if found >= 3:
            scores["email_includes_file_paths"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()