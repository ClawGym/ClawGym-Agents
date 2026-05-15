import json
import sys
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                if "id" not in obj or "text" not in obj:
                    return None
                if not isinstance(obj["id"], str) or not isinstance(obj["text"], str):
                    return None
                items.append(obj)
    except Exception:
        return None
    return items


def _extract_rules_block(md_text: str) -> Optional[str]:
    # Extract content inside ```yaml name=rules ... ```
    # Use a regex with DOTALL to capture multi-line
    pattern = re.compile(r"```yaml\s+name=rules\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    m = pattern.search(md_text)
    if not m:
        return None
    return m.group(1).strip()


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    # integer?
    if re.fullmatch(r"[+-]?\d+", v):
        try:
            return int(v)
        except Exception:
            pass
    # strip possible surrounding quotes
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    return v


def _parse_simple_yaml(yaml_text: str) -> Optional[Dict[str, Any]]:
    # Minimal YAML subset parser: keys with scalars; keys with list of scalars.
    rules: Dict[str, Any] = {}
    lines = yaml_text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        # key: value or key:
        m = re.match(r'^([A-Za-z0-9_\-]+)\s*:\s*(.*)$', line)
        if not m:
            # invalid line for our simple parser
            return None
        key = m.group(1)
        rest = m.group(2)
        if rest == "" or rest is None:
            # Expect a block list starting on following lines
            lst: List[Any] = []
            i += 1
            while i < n:
                next_line = lines[i].rstrip()
                # Stop if next key begins
                if re.match(r'^[A-Za-z0-9_\-]+\s*:\s*.*$', next_line):
                    break
                if next_line.strip().startswith("- "):
                    item_val = next_line.strip()[2:]
                    lst.append(_parse_scalar(item_val))
                    i += 1
                elif not next_line.strip():
                    i += 1
                else:
                    # Unexpected content in list block
                    return None
            rules[key] = lst
            continue
        else:
            # scalar on same line
            rules[key] = _parse_scalar(rest)
            i += 1
    return rules


class _FeatureHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_feature_li = False
        self._current_text_parts: List[str] = []
        self.features: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "li":
            attrs_dict = dict(attrs)
            class_attr = attrs_dict.get("class", "")
            classes = class_attr.split()
            if "feature" in classes:
                self._in_feature_li = True
                self._current_text_parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "li" and self._in_feature_li:
            text = "".join(self._current_text_parts).strip()
            if text:
                self.features.append(text)
            self._in_feature_li = False
            self._current_text_parts = []

    def handle_data(self, data):
        if self._in_feature_li:
            self._current_text_parts.append(data)


def _extract_features_from_html(html_text: str) -> List[str]:
    parser = _FeatureHTMLParser()
    parser.feed(html_text)
    return parser.features


def _load_rules(style_path: Path) -> Optional[Dict[str, Any]]:
    md = _safe_read_text(style_path)
    if md is None:
        return None
    block = _extract_rules_block(md)
    if block is None:
        return None
    rules = _parse_simple_yaml(block)
    if not isinstance(rules, dict):
        return None
    # Validate required keys exist and types
    required_keys = ["char_limit", "cta_required", "require_feature_mention", "case_insensitive", "allowed_ctas", "banned_words"]
    for k in required_keys:
        if k not in rules:
            return None
    if not isinstance(rules["char_limit"], int):
        return None
    if not isinstance(rules["cta_required"], bool):
        return None
    if not isinstance(rules["require_feature_mention"], bool):
        return None
    if not isinstance(rules["case_insensitive"], bool):
        return None
    if not isinstance(rules["allowed_ctas"], list):
        return None
    if not isinstance(rules["banned_words"], list):
        return None
    # Coerce all list items to strings
    rules["allowed_ctas"] = [str(x) for x in rules["allowed_ctas"]]
    rules["banned_words"] = [str(x) for x in rules["banned_words"]]
    return rules


def _compute_char_count(text: str) -> int:
    return len(text)


def _has_banned_word(text: str, banned: List[str], case_insensitive: bool) -> bool:
    t = text
    if case_insensitive:
        t = t.lower()
        banned = [w.lower() for w in banned]
    for w in banned:
        if w and w in t:
            return True
    return False


def _has_allowed_cta(text: str, allowed: List[str], case_insensitive: bool) -> bool:
    t = text
    if case_insensitive:
        t = t.lower()
        allowed_norm = [a.lower() for a in allowed]
    else:
        allowed_norm = allowed
    for a in allowed_norm:
        if a and a in t:
            return True
    return False


def _count_allowed_ctas(text: str, allowed: List[str], case_insensitive: bool) -> int:
    count = 0
    flags = re.IGNORECASE if case_insensitive else 0
    for phrase in allowed:
        if not phrase:
            continue
        pattern = re.escape(phrase)
        count += len(re.findall(pattern, text, flags))
    return count


def _mentions_any_feature(text: str, features: List[str], case_insensitive: bool) -> bool:
    t = text
    feats = features
    if case_insensitive:
        t = t.lower()
        feats = [f.lower() for f in feats]
    for f in feats:
        if f and f in t:
            return True
    return False


def _compute_should_pass(text: str, rules: Dict[str, Any], features: List[str]) -> Tuple[bool, Dict[str, bool]]:
    char_count = _compute_char_count(text)
    over_char_limit = char_count > int(rules["char_limit"])
    banned = _has_banned_word(text, rules["banned_words"], rules["case_insensitive"])
    cta_present = _has_allowed_cta(text, rules["allowed_ctas"], rules["case_insensitive"]) if rules["cta_required"] else True
    feature_present = _mentions_any_feature(text, features, rules["case_insensitive"]) if rules["require_feature_mention"] else True
    should_pass = (not over_char_limit) and (not banned) and cta_present and feature_present
    details = {
        "over_char_limit": over_char_limit,
        "banned_word": banned,
        "cta_present": cta_present,
        "feature_present": feature_present,
    }
    return should_pass, details


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "validator_script_present": 0.0,
        "validator_cli_args_present": 0.0,
        "features_extraction_correct": 0.0,
        "baseline_report_correct": 0.0,
        "rewritten_messages_valid": 0.0,
        "final_report_all_pass": 0.0,
    }

    # Paths
    style_path = workspace / "input" / "style_guide.md"
    features_html_path = workspace / "input" / "hostel_features.html"
    messages_jsonl_path = workspace / "input" / "messages.jsonl"
    validator_path = workspace / "tests" / "validate_messages.py"
    features_extracted_path = workspace / "output" / "features_extracted.json"
    baseline_report_path = workspace / "output" / "baseline_report.json"
    rewritten_messages_path = workspace / "output" / "rewritten_messages.jsonl"
    final_report_path = workspace / "output" / "final_report.json"

    # Load ground truth rules and features from input files
    rules = _load_rules(style_path)
    html_text = _safe_read_text(features_html_path)
    expected_features: Optional[List[str]] = None
    if html_text is not None:
        feats = _extract_features_from_html(html_text)
        expected_features = sorted(feats)

    # 1) Validator script presence
    if validator_path.exists() and validator_path.is_file():
        scores["validator_script_present"] = 1.0

        # 2) CLI args presence (static heuristic check to avoid execution)
        try:
            validator_src = validator_path.read_text(encoding="utf-8")
            has_messages = "--messages" in validator_src
            has_style = "--style" in validator_src
            has_features = "--features" in validator_src
            has_report = "--report" in validator_src
            if has_messages and has_style and has_features and has_report:
                scores["validator_cli_args_present"] = 1.0
        except Exception:
            pass

    # 3) features_extraction_correct
    if expected_features is not None:
        extracted = _safe_load_json(features_extracted_path)
        if isinstance(extracted, list) and all(isinstance(x, str) for x in extracted):
            # Must match exactly the expected sorted features
            if extracted == expected_features:
                scores["features_extraction_correct"] = 1.0

    # Prepare input messages
    input_messages = _safe_load_jsonl(messages_jsonl_path)

    # 4) baseline_report_correct
    baseline_report = _safe_load_json(baseline_report_path)
    baseline_ok = False
    if rules is not None and expected_features is not None and input_messages is not None and isinstance(baseline_report, dict):
        # Validate structure
        summary = baseline_report.get("summary")
        results = baseline_report.get("results")
        if (
            isinstance(summary, dict)
            and isinstance(results, list)
            and isinstance(summary.get("total"), int)
            and isinstance(summary.get("passed"), int)
            and isinstance(summary.get("failed"), int)
            and summary["total"] == len(results)
        ):
            # Build map id -> result
            result_map: Dict[str, Dict[str, Any]] = {}
            all_results_valid = True
            for r in results:
                if not (isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("pass"), bool) and isinstance(r.get("violations"), list) and isinstance(r.get("char_count"), int)):
                    all_results_valid = False
                    break
                result_map[r["id"]] = r
            if all_results_valid and len(result_map) == len(results):
                # Cross-check with input messages: all IDs present
                input_ids = [m["id"] for m in input_messages]
                if set(input_ids) == set(result_map.keys()):
                    # Compute expected pass/fail and char counts
                    expected_pass_map: Dict[str, bool] = {}
                    expected_char_counts: Dict[str, int] = {}
                    for m in input_messages:
                        should_pass, _details = _compute_should_pass(m["text"], rules, expected_features)
                        expected_pass_map[m["id"]] = should_pass
                        expected_char_counts[m["id"]] = _compute_char_count(m["text"])
                    # Compare
                    ids_all_match = True
                    pass_match = True
                    char_match = True
                    for mid in input_ids:
                        rr = result_map[mid]
                        if expected_pass_map[mid] != rr["pass"]:
                            pass_match = False
                        if expected_char_counts[mid] != rr["char_count"]:
                            char_match = False
                    # Summary consistency
                    calc_passed = sum(1 for v in expected_pass_map.values() if v)
                    calc_failed = len(expected_pass_map) - calc_passed
                    summary_match = (summary["total"] == len(expected_pass_map) and summary["passed"] == calc_passed and summary["failed"] == calc_failed)
                    # For given inputs, expect all three to fail
                    if ids_all_match and pass_match and char_match and summary_match:
                        baseline_ok = True
    if baseline_ok:
        scores["baseline_report_correct"] = 1.0

    # 5) rewritten_messages_valid
    rewritten_messages = _safe_load_jsonl(rewritten_messages_path)
    rewritten_ok = False
    if rules is not None and expected_features is not None and input_messages is not None and rewritten_messages is not None:
        # Same ids set
        input_ids_set = {m["id"] for m in input_messages}
        rewritten_ids_set = {m["id"] for m in rewritten_messages}
        if input_ids_set == rewritten_ids_set and len(rewritten_messages) == len(input_messages):
            # Check each rewritten message meets constraints:
            # - char_count <= char_limit
            # - exactly one allowed CTA (case-insensitive)
            # - mentions at least one feature (exact string, case-insensitive)
            # - no banned words
            limit = int(rules["char_limit"])
            all_good = True
            for m in rewritten_messages:
                text = m["text"]
                char_ok = _compute_char_count(text) <= limit
                cta_count = _count_allowed_ctas(text, rules["allowed_ctas"], rules["case_insensitive"])
                cta_ok = (cta_count == 1)
                feature_ok = _mentions_any_feature(text, expected_features, rules["case_insensitive"])
                banned_ok = not _has_banned_word(text, rules["banned_words"], rules["case_insensitive"])
                if not (char_ok and cta_ok and feature_ok and banned_ok):
                    all_good = False
                    break
            if all_good:
                rewritten_ok = True
    if rewritten_ok:
        scores["rewritten_messages_valid"] = 1.0

    # 6) final_report_all_pass
    final_report = _safe_load_json(final_report_path)
    final_ok = False
    if rules is not None and expected_features is not None and rewritten_messages is not None and isinstance(final_report, dict):
        summary = final_report.get("summary")
        results = final_report.get("results")
        if (
            isinstance(summary, dict)
            and isinstance(results, list)
            and isinstance(summary.get("total"), int)
            and isinstance(summary.get("passed"), int)
            and isinstance(summary.get("failed"), int)
            and summary["total"] == len(results)
        ):
            # Build map id -> result
            result_map: Dict[str, Dict[str, Any]] = {}
            all_results_valid = True
            for r in results:
                if not (isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("pass"), bool) and isinstance(r.get("violations"), list) and isinstance(r.get("char_count"), int)):
                    all_results_valid = False
                    break
                result_map[r["id"]] = r
            if all_results_valid and len(result_map) == len(results):
                # Cross-check IDs match rewritten
                rewritten_ids = [m["id"] for m in rewritten_messages]
                if set(rewritten_ids) == set(result_map.keys()):
                    # Compute expected pass and char counts for rewritten
                    expected_pass_map: Dict[str, bool] = {}
                    expected_char_counts: Dict[str, int] = {}
                    for m in rewritten_messages:
                        should_pass, _details = _compute_should_pass(m["text"], rules, expected_features)
                        expected_pass_map[m["id"]] = should_pass
                        expected_char_counts[m["id"]] = _compute_char_count(m["text"])
                    # All should pass (True)
                    pass_match = all(result_map[mid]["pass"] == expected_pass_map[mid] for mid in expected_pass_map)
                    char_match = all(result_map[mid]["char_count"] == expected_char_counts[mid] for mid in expected_char_counts)
                    summary_match = (summary["total"] == len(rewritten_messages) and summary["failed"] == 0 and summary["passed"] == len(rewritten_messages))
                    if pass_match and char_match and summary_match and all(expected_pass_map.values()):
                        final_ok = True
    if final_ok:
        scores["final_report_all_pass"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()