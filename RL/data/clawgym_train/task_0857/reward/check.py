import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(dict(row))
            return rows
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_yaml_mappings(path: Path) -> Optional[Dict[str, str]]:
    # Minimal YAML parser for the specific simple structure provided
    try:
        mappings: Dict[str, str] = {}
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        in_mappings = False
        current_indent = None
        for raw_line in lines:
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not in_mappings:
                if stripped.startswith("mappings:"):
                    in_mappings = True
                    # Indentation level of mappings entries determined by next lines
                    continue
                else:
                    # ignore until mappings
                    continue
            # We are inside mappings block
            # Expect "key: value" with some indentation
            if ":" in line:
                # Identify indentation
                if current_indent is None:
                    # first entry's indent
                    current_indent = len(line) - len(line.lstrip(" "))
                indent = len(line) - len(line.lstrip(" "))
                if indent < current_indent:
                    # out of mappings
                    break
                # split on first colon
                parts = line.strip().split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if key and value:
                        mappings[key.lower()] = value
        return mappings
    except Exception:
        return None


def _parse_int_safe(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[List[Dict[str, object]]]:
    # Load inputs
    claims_path = workspace / "input" / "claims.csv"
    evidence_path = workspace / "input" / "evidence.jsonl"
    topic_map_path = workspace / "input" / "topic_map.yaml"

    claims_rows = _read_csv(claims_path)
    evidence_items = _read_jsonl(evidence_path)
    mappings = _load_yaml_mappings(topic_map_path)

    if claims_rows is None or evidence_items is None or mappings is None:
        return None

    # Build evidence topic -> evidence_level
    evidence_by_topic: Dict[str, str] = {}
    for item in evidence_items:
        try:
            t = str(item.get("topic", ""))
            lvl = str(item.get("evidence_level", ""))
            evidence_by_topic[t] = lvl
        except Exception:
            continue

    # Harm and evidence weights
    harm_weight = {"low": 1, "medium": 2, "high": 3}
    evidence_weight = {"supported": 0, "mixed": 1, "unsupported": 2, "unknown": 2}
    verdict_map = {
        "supported": "Supported",
        "mixed": "Mixed/Inconclusive",
        "unsupported": "Unsupported",
        "unknown": "No Evidence",
    }

    expected: List[Dict[str, object]] = []
    for row in claims_rows:
        # Extract fields
        id_str = row.get("id", "").strip()
        claim_text = row.get("claim_text", "")
        topic_hint = row.get("topic_hint", "")
        harm_level = row.get("harm_level", "")
        source_type = row.get("source_type", "")

        id_val = _parse_int_safe(id_str)
        if id_val is None:
            # malformed id; fail the entire expected computation gracefully
            return None

        # Mapping (case-insensitive exact key match)
        canonical_topic = "(no match)"
        evidence_level = "unknown"
        mapped = mappings.get(topic_hint.lower(), None)
        if mapped is not None:
            canonical_topic = mapped
            # Join to evidence.jsonl on topic
            lvl = evidence_by_topic.get(canonical_topic)
            if lvl is not None:
                evidence_level = str(lvl)
            else:
                evidence_level = "unknown"  # mapped but no evidence topic
        else:
            evidence_level = "unknown"

        # Determine verdict
        ev_key = evidence_level.lower()
        verdict = verdict_map.get(ev_key, "No Evidence")
        # priority score
        hw = harm_weight.get(harm_level.lower(), None)
        ew = evidence_weight.get(ev_key, None)
        if hw is None or ew is None:
            # Invalid harm/evidence levels; fail expected gracefully
            return None
        priority_score = (hw * 10) + (ew * 5)

        expected.append({
            "id": id_val,
            "claim_text": claim_text,
            "canonical_topic": canonical_topic,
            "evidence_level": evidence_level,
            "verdict": verdict,
            "harm_level": harm_level,
            "source_type": source_type,
            "priority_score": priority_score,
        })

    # Sort expected by id ascending for reference
    expected.sort(key=lambda r: r["id"])
    return expected


def _load_claims_verified(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames or []
        return rows, headers
    except Exception:
        return None, None


def _load_high_priority(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames or []
        return rows, headers
    except Exception:
        return None, None


def _is_sorted_by_id_asc(rows: List[Dict[str, str]]) -> bool:
    ids: List[int] = []
    for r in rows:
        iv = _parse_int_safe(str(r.get("id", "")).strip())
        if iv is None:
            return False
        ids.append(iv)
    return ids == sorted(ids)


def _summary_contains_label_count(text: str, label: str, count: int) -> bool:
    # Check if summary contains the verdict label and the corresponding count nearby (same line)
    label_pat = re.compile(rf"{re.escape(label)}", re.IGNORECASE)
    count_pat = re.compile(rf"\b{count}\b")
    for line in text.splitlines():
        if label_pat.search(line) and count_pat.search(line):
            return True
    return False


def _find_line_indices_with_substring(lines: List[str], substring: str, ignore_case: bool = True) -> List[int]:
    indices = []
    sub = substring.lower() if ignore_case else substring
    for i, line in enumerate(lines):
        tgt = line.lower() if ignore_case else line
        if sub in tgt:
            indices.append(i)
    return indices


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_directory_exact_three_files": 0.0,
        "claims_verified_columns_and_order": 0.0,
        "claims_verified_row_count_and_sort": 0.0,
        "canonical_topic_mapping_correct": 0.0,
        "evidence_level_and_verdict_correct": 0.0,
        "priority_score_correct": 0.0,
        "high_priority_filtered_and_sorted": 0.0,
        "summary_mentions_inputs_and_method": 0.0,
        "summary_verdict_counts_correct": 0.0,
        "summary_top_priorities_included": 0.0,
        "summary_reproducibility_command": 0.0,
    }

    # Paths
    outputs_dir = workspace / "outputs"
    claims_verified_path = outputs_dir / "claims_verified.csv"
    high_priority_path = outputs_dir / "high_priority.csv"
    summary_path = outputs_dir / "summary.md"

    # Check outputs directory exact files
    if outputs_dir.exists() and outputs_dir.is_dir():
        try:
            files = [p for p in outputs_dir.iterdir() if p.is_file()]
            names = sorted([p.name for p in files])
            expected_names = sorted(["claims_verified.csv", "high_priority.csv", "summary.md"])
            if names == expected_names:
                scores["outputs_directory_exact_three_files"] = 1.0
        except Exception:
            scores["outputs_directory_exact_three_files"] = 0.0

    # Compute expected results from inputs
    expected_rows = _compute_expected(workspace)

    # Load claims_verified
    cv_rows, cv_headers = _load_claims_verified(claims_verified_path)
    # Structure check for claims_verified
    expected_headers = ["id", "claim_text", "canonical_topic", "evidence_level", "verdict", "harm_level", "source_type", "priority_score"]
    if cv_rows is not None and cv_headers is not None:
        if cv_headers == expected_headers:
            scores["claims_verified_columns_and_order"] = 1.0

    # Row count and sort check
    if cv_rows is not None and expected_rows is not None:
        if len(cv_rows) == len(expected_rows) and _is_sorted_by_id_asc(cv_rows):
            scores["claims_verified_row_count_and_sort"] = 1.0

    # Validate values in claims_verified against expected
    if cv_rows is not None and expected_rows is not None:
        ok_map = True
        ok_evidence_verdict = True
        ok_priority = True
        # Build expected by id
        expected_by_id = {r["id"]: r for r in expected_rows}
        for r in cv_rows:
            id_val = _parse_int_safe(str(r.get("id", "")).strip())
            if id_val is None or id_val not in expected_by_id:
                ok_map = False
                ok_evidence_verdict = False
                ok_priority = False
                break
            exp = expected_by_id[id_val]
            # canonical topic mapping
            if r.get("canonical_topic", "") != exp["canonical_topic"]:
                ok_map = False
            # evidence level and verdict
            if r.get("evidence_level", "") != exp["evidence_level"]:
                ok_evidence_verdict = False
            if r.get("verdict", "") != exp["verdict"]:
                ok_evidence_verdict = False
            # check other unchanged fields from inputs as consistency
            if r.get("claim_text", "") != exp["claim_text"]:
                ok_map = False
            if r.get("harm_level", "") != exp["harm_level"]:
                ok_map = False
            if r.get("source_type", "") != exp["source_type"]:
                ok_map = False
            # priority
            ps = _parse_int_safe(str(r.get("priority_score", "")).strip())
            if ps is None or ps != exp["priority_score"]:
                ok_priority = False
        if ok_map:
            scores["canonical_topic_mapping_correct"] = 1.0
        if ok_evidence_verdict:
            scores["evidence_level_and_verdict_correct"] = 1.0
        if ok_priority:
            scores["priority_score_correct"] = 1.0

    # Validate high_priority subset and sorting
    hp_rows, hp_headers = _load_high_priority(high_priority_path)
    if hp_rows is not None and expected_rows is not None:
        # Determine expected filtered set
        expect_filter_labels = {"Unsupported", "Mixed/Inconclusive", "No Evidence"}
        expected_filtered = [r for r in expected_rows if r["verdict"] in expect_filter_labels]
        # Sort expected by priority_score desc then id asc
        expected_filtered_sorted = sorted(expected_filtered, key=lambda r: (-int(r["priority_score"]), int(r["id"])))
        # Validate presence of necessary columns
        has_needed_cols = True
        for col in ["id", "verdict", "priority_score"]:
            if col not in (hp_headers or []):
                has_needed_cols = False
                break
        if has_needed_cols:
            ids_hp = []
            valid_content = True
            for r in hp_rows:
                id_val = _parse_int_safe(str(r.get("id", "")).strip())
                ps_val = _parse_int_safe(str(r.get("priority_score", "")).strip())
                verdict_val = r.get("verdict", "")
                if id_val is None or ps_val is None:
                    valid_content = False
                    break
                ids_hp.append(id_val)
                # Check row exists in expected and is in filtered set
                exp = next((e for e in expected_filtered_sorted if e["id"] == id_val), None)
                if exp is None:
                    valid_content = False
                    break
                # Check verdict and priority_score match expected
                if verdict_val != exp["verdict"]:
                    valid_content = False
                    break
                if ps_val != exp["priority_score"]:
                    valid_content = False
                    break
            # Check that ids set matches expected filtered ids
            expected_ids = [e["id"] for e in expected_filtered_sorted]
            if valid_content and sorted(ids_hp) == sorted(expected_ids):
                # Check sort order (priority desc, id asc)
                # Build tuples
                tuples = [(-_parse_int_safe(str(r.get("priority_score", "")).strip()), _parse_int_safe(str(r.get("id", "")).strip())) for r in hp_rows]
                if tuples == sorted(tuples):
                    scores["high_priority_filtered_and_sorted"] = 1.0

    # Validate summary content
    summary_text = _read_text(summary_path) or ""
    if summary_text:
        # Method & Data Files: mention three input paths and mapping + join, Overview mentions local
        has_inputs = ("input/claims.csv" in summary_text) and ("input/evidence.jsonl" in summary_text) and ("input/topic_map.yaml" in summary_text)
        has_mapping = re.search(r"\bmap\w*\b", summary_text, re.IGNORECASE) is not None
        has_join = re.search(r"\bjoin\w*\b", summary_text, re.IGNORECASE) is not None
        mentions_local = re.search(r"\blocal\b", summary_text, re.IGNORECASE) is not None
        if has_inputs and has_mapping and has_join and mentions_local:
            scores["summary_mentions_inputs_and_method"] = 1.0

        # Verdict counts
        if expected_rows is not None:
            count_map = {"Supported": 0, "Mixed/Inconclusive": 0, "Unsupported": 0, "No Evidence": 0}
            for r in expected_rows:
                v = r["verdict"]
                if v in count_map:
                    count_map[v] += 1
            all_counts_present = True
            for label, cnt in count_map.items():
                if not _summary_contains_label_count(summary_text, label, cnt):
                    all_counts_present = False
                    break
            if all_counts_present:
                scores["summary_verdict_counts_correct"] = 1.0

        # Top priorities (top 3 rows from outputs/high_priority.csv)
        if hp_rows is not None and len(hp_rows) > 0:
            lines = summary_text.splitlines()
            top_n = min(3, len(hp_rows))
            all_top_present = True
            for i in range(top_n):
                row = hp_rows[i]
                # Extract fields
                claim_text = row.get("claim_text", "")
                canonical_topic = row.get("canonical_topic", "")
                verdict = row.get("verdict", "")
                ps = row.get("priority_score", "")
                id_str = row.get("id", "")
                # Check presence around claim_text occurrence
                indices = _find_line_indices_with_substring(lines, claim_text, ignore_case=True) if claim_text else []
                if not indices:
                    all_top_present = False
                    break
                # Check nearby lines for other fields
                found_all_fields = False
                for idx in indices:
                    window_lines = []
                    for j in range(idx, min(idx + 3, len(lines))):
                        window_lines.append(lines[j])
                    window_text = "\n".join(window_lines)
                    cond_topic = canonical_topic.lower() in window_text.lower() if canonical_topic else True
                    cond_verdict = verdict in window_text
                    cond_ps = re.search(rf"\b{re.escape(str(ps))}\b", window_text) is not None
                    cond_id = False
                    try:
                        cond_id = re.search(rf"\b{re.escape(str(id_str))}\b", window_text) is not None
                    except Exception:
                        cond_id = False
                    if cond_topic and cond_verdict and cond_ps and cond_id:
                        found_all_fields = True
                        break
                if not found_all_fields:
                    all_top_present = False
                    break
            if all_top_present:
                scores["summary_top_priorities_included"] = 1.0

        # Reproducibility: exact command used to run script (look for command-like line)
        # Accept lines containing 'python ...' or 'bash ...' or 'sh ...'
        if re.search(r"(?im)^(?:>|\$)?\s*(python|bash|sh)\s+[^\n`]+", summary_text) is not None:
            scores["summary_reproducibility_command"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()