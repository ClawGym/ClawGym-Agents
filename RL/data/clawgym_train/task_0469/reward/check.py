import sys
import json
import csv
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, True
    except Exception:
        return [], False


def _load_jsonl(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for ln, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return [], False
                items.append(obj)
        return items, True
    except Exception:
        return [], False


def _is_iso8601(s: str) -> bool:
    try:
        if not isinstance(s, str) or not s:
            return False
        s2 = s
        # Handle trailing Z
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        # fromisoformat can parse many ISO-8601-like strings
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _to_int_or_none(v):
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        try:
            return int(s)
        except Exception:
            return "INVALID"
    return "INVALID"


def _is_hex_sha256(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) != 64:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s)


def _extract_host(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # Strip potential credentials and ports
        if "@" in host:
            host = host.split("@")[-1]
        if ":" in host:
            host = host.split(":")[0]
        return host
    except Exception:
        return ""


def _allowed_domain_from_host(host: str) -> bool:
    if not host:
        return False
    host = host.lower()
    # Allowed base domains
    allowed_bases = [
        "britannica.com",
        "bbc.co.uk",
        "loc.gov",
        "si.edu",
        "smithsonianmag.com",
        "nationalgeographic.com",
    ]
    # .edu rule
    if host.endswith(".edu"):
        return True
    for base in allowed_bases:
        if host == base or host.endswith("." + base):
            return True
    return False


def _split_urls(s: str):
    if s is None:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "web_sources_fields_valid": 0.0,
        "web_sources_min_allowed_per_topic": 0.0,
        "web_sources_allowed_sha256_unique_per_topic": 0.0,
        "validated_facts_structure_and_types": 0.0,
        "validated_facts_min_two_sources_and_list_count_match": 0.0,
        "validated_facts_year_range_consistency": 0.0,
        "validated_facts_key_figure_valid": 0.0,
        "mcq_questions_structure_and_fields": 0.0,
        "mcq_questions_exact_two_per_topic": 0.0,
        "mcq_questions_sources_subset_of_validated": 0.0,
        "run_summary_total_topics_line": 0.0,
        "run_summary_topic_lines_present": 0.0,
        "run_summary_allowed_counts_match_jsonl": 0.0,
    }

    # Load input topics to determine expected topics and key_figure requirement
    input_topics_path = workspace / "input" / "game_topics.csv"
    input_rows, input_ok = _read_csv_dicts(input_topics_path)
    expected_topics = []
    key_figure_required = set()
    if input_ok and input_rows:
        for r in input_rows:
            try:
                tid = int(r.get("topic_id", "").strip())
            except Exception:
                continue
            expected_topics.append(tid)
            pf = (r.get("prompt_focus") or "").lower()
            if "key_figure" in pf:
                key_figure_required.add(tid)
    # Ensure deterministic order
    expected_topics = sorted(set(expected_topics))

    # Load web_sources.jsonl
    web_sources_path = workspace / "out" / "web_sources.jsonl"
    web_items, web_ok = _load_jsonl(web_sources_path)

    # Check web_sources_fields_valid
    ws_fields_valid = False
    if web_ok and web_items:
        all_ok = True
        for obj in web_items:
            # Required fields
            required_fields = [
                "topic_id",
                "topic_title",
                "source_url",
                "source_domain",
                "allowed_domain",
                "sha256",
                "extracted_year_start",
                "extracted_year_end",
                "extracted_place",
                "extracted_key_figure",
                "retrieval_timestamp",
            ]
            for f in required_fields:
                if f not in obj:
                    all_ok = False
                    break
            if not all_ok:
                break
            # Type checks
            tid = _to_int_or_none(obj.get("topic_id"))
            if not isinstance(obj.get("topic_title"), str):
                all_ok = False
                break
            if not isinstance(obj.get("source_url"), str) or not obj.get("source_url").strip():
                all_ok = False
                break
            if not isinstance(obj.get("source_domain"), str) or not obj.get("source_domain").strip():
                all_ok = False
                break
            if not isinstance(obj.get("allowed_domain"), bool):
                all_ok = False
                break
            if not _is_hex_sha256(obj.get("sha256")):
                all_ok = False
                break
            ys = _to_int_or_none(obj.get("extracted_year_start"))
            ye = _to_int_or_none(obj.get("extracted_year_end"))
            if ys not in (None, "INVALID") and not isinstance(ys, int):
                all_ok = False
                break
            if ye not in (None, "INVALID") and not isinstance(ye, int):
                all_ok = False
                break
            # extracted_place/key_figure can be empty str, but must be string
            if not isinstance(obj.get("extracted_place"), str):
                all_ok = False
                break
            if not isinstance(obj.get("extracted_key_figure"), str):
                all_ok = False
                break
            # retrieval_timestamp ISO-like
            if not _is_iso8601(obj.get("retrieval_timestamp")):
                all_ok = False
                break
            # Topic id must be int
            if not isinstance(tid, int):
                all_ok = False
                break
        ws_fields_valid = all_ok
    scores["web_sources_fields_valid"] = 1.0 if ws_fields_valid else 0.0

    # Prepare allowed sources by topic and check counts and sha uniqueness
    allowed_by_topic = {}
    if web_ok and web_items:
        for obj in web_items:
            tid = _to_int_or_none(obj.get("topic_id"))
            if not isinstance(tid, int):
                continue
            if obj.get("allowed_domain") is True:
                allowed_by_topic.setdefault(tid, []).append(obj)

    # web_sources_min_allowed_per_topic
    if expected_topics:
        per_topic_pass = 0
        for tid in expected_topics:
            cnt = len(allowed_by_topic.get(tid, []))
            if cnt >= 2:
                per_topic_pass += 1
        scores["web_sources_min_allowed_per_topic"] = per_topic_pass / max(len(expected_topics), 1)
    else:
        scores["web_sources_min_allowed_per_topic"] = 0.0

    # web_sources_allowed_sha256_unique_per_topic
    if expected_topics:
        per_topic_pass = 0
        for tid in expected_topics:
            allowed = allowed_by_topic.get(tid, [])
            sha_set = set()
            dup = False
            for obj in allowed:
                sha = obj.get("sha256")
                if sha in sha_set:
                    dup = True
                    break
                sha_set.add(sha)
            if not dup and len(allowed) >= 2:
                per_topic_pass += 1
        scores["web_sources_allowed_sha256_unique_per_topic"] = per_topic_pass / max(len(expected_topics), 1)
    else:
        scores["web_sources_allowed_sha256_unique_per_topic"] = 0.0

    # Load validated_facts.csv
    vf_path = workspace / "out" / "validated_facts.csv"
    vf_rows, vf_ok = _read_csv_dicts(vf_path)
    vf_by_topic = {}
    vf_cols_ok = False
    if vf_ok and vf_rows:
        # Validate columns
        expected_cols = {"topic_id", "topic_title", "year_start", "year_end", "place", "key_figure", "source_count", "source_urls"}
        header = set(vf_rows[0].keys())
        vf_cols_ok = expected_cols.issubset(header)
        # Index by topic id
        for r in vf_rows:
            tid = _to_int_or_none(r.get("topic_id"))
            if isinstance(tid, int):
                vf_by_topic[tid] = r

    # validated_facts_structure_and_types
    vfst_pass_count = 0
    if expected_topics and vf_cols_ok:
        for tid in expected_topics:
            r = vf_by_topic.get(tid)
            if not r:
                continue
            ys = _to_int_or_none(r.get("year_start"))
            ye = _to_int_or_none(r.get("year_end"))
            sc = _to_int_or_none(r.get("source_count"))
            place = r.get("place")
            if not isinstance(ys, int) or not isinstance(ye, int):
                continue
            if not isinstance(sc, int):
                continue
            if not isinstance(place, str) or not place.strip():
                continue
            # Ensure exactly one row per topic and total rows match expected
            vfst_pass_count += 1
        if len(vf_rows) != len(expected_topics):
            # If the number of rows is not equal to expected topics, consider it a failure by reducing pass count to zero
            vfst_pass_count = 0
        scores["validated_facts_structure_and_types"] = (vfst_pass_count / max(len(expected_topics), 1)) if vfst_pass_count > 0 else 0.0
    else:
        scores["validated_facts_structure_and_types"] = 0.0

    # validated_facts_min_two_sources_and_list_count_match
    vfm2_pass = 0
    if expected_topics and vf_cols_ok:
        for tid in expected_topics:
            r = vf_by_topic.get(tid)
            if not r:
                continue
            sc = _to_int_or_none(r.get("source_count"))
            urls = _split_urls(r.get("source_urls"))
            if isinstance(sc, int) and sc >= 2 and sc == len(urls) and all(isinstance(u, str) and u for u in urls):
                vfm2_pass += 1
        scores["validated_facts_min_two_sources_and_list_count_match"] = vfm2_pass / max(len(expected_topics), 1)
    else:
        scores["validated_facts_min_two_sources_and_list_count_match"] = 0.0

    # validated_facts_year_range_consistency
    vfyr_pass = 0
    if expected_topics and web_ok and web_items and vf_cols_ok:
        # Build year candidates per topic from allowed sources
        years_by_topic = {}
        for tid in expected_topics:
            years_by_topic[tid] = []
        for obj in web_items:
            tid = _to_int_or_none(obj.get("topic_id"))
            if not isinstance(tid, int):
                continue
            if obj.get("allowed_domain") is True and tid in years_by_topic:
                ys = _to_int_or_none(obj.get("extracted_year_start"))
                ye = _to_int_or_none(obj.get("extracted_year_end"))
                if isinstance(ys, int):
                    years_by_topic[tid].append(ys)
                if isinstance(ye, int):
                    years_by_topic[tid].append(ye)
        for tid in expected_topics:
            r = vf_by_topic.get(tid)
            if not r:
                continue
            ys_v = _to_int_or_none(r.get("year_start"))
            ye_v = _to_int_or_none(r.get("year_end"))
            years = years_by_topic.get(tid, [])
            if years:
                if isinstance(ys_v, int) and isinstance(ye_v, int) and ys_v == min(years) and ye_v == max(years):
                    vfyr_pass += 1
            else:
                # No year data to validate against means fail this topic
                pass
        scores["validated_facts_year_range_consistency"] = vfyr_pass / max(len(expected_topics), 1)
    else:
        scores["validated_facts_year_range_consistency"] = 0.0

    # validated_facts_key_figure_valid
    vfkf_pass = 0
    denom = max(len(key_figure_required), 1)
    if expected_topics and web_ok and web_items and vf_cols_ok and key_figure_required:
        # Build non-empty extracted_key_figure values per topic among allowed sources
        kf_values = {}
        for tid in expected_topics:
            kf_values[tid] = set()
        for obj in web_items:
            tid = _to_int_or_none(obj.get("topic_id"))
            if not isinstance(tid, int):
                continue
            if obj.get("allowed_domain") is True and tid in kf_values:
                kf = (obj.get("extracted_key_figure") or "").strip()
                if kf:
                    kf_values[tid].add(kf.lower())
        for tid in key_figure_required:
            r = vf_by_topic.get(tid)
            if not r:
                continue
            kf_v = (r.get("key_figure") or "").strip()
            if kf_v and kf_v.lower() in kf_values.get(tid, set()):
                vfkf_pass += 1
        scores["validated_facts_key_figure_valid"] = vfkf_pass / denom
    else:
        # If there are required topics but missing artifacts, 0.0; if none required, consider pass by definition
        scores["validated_facts_key_figure_valid"] = 1.0 if not key_figure_required else 0.0

    # Load mcq_questions.csv
    mcq_path = workspace / "out" / "mcq_questions.csv"
    mcq_rows, mcq_ok = _read_csv_dicts(mcq_path)

    # mcq_questions_structure_and_fields
    mcq_struct_pass_count = 0
    if mcq_ok and mcq_rows:
        required_cols = {"id", "topic_id", "question", "option_a", "option_b", "option_c", "option_d", "correct_option", "explanation", "source_urls"}
        header = set(mcq_rows[0].keys())
        if required_cols.issubset(header):
            # Check each row fields
            ids = set()
            per_row_pass = 0
            for r in mcq_rows:
                row_ok = True
                rid = r.get("id")
                if rid in ids or not isinstance(rid, str) or not rid.strip():
                    row_ok = False
                ids.add(rid)
                try:
                    int(str(r.get("topic_id", "")).strip())
                except Exception:
                    row_ok = False
                if not (isinstance(r.get("question"), str) and r.get("question").strip()):
                    row_ok = False
                for opt in ["option_a", "option_b", "option_c", "option_d"]:
                    if not (isinstance(r.get(opt), str) and r.get(opt).strip()):
                        row_ok = False
                if r.get("correct_option") not in {"A", "B", "C", "D"}:
                    row_ok = False
                if not (isinstance(r.get("explanation"), str) and r.get("explanation").strip()):
                    row_ok = False
                # source_urls can be empty? The task implies tie to facts; require non-empty
                su = _split_urls(r.get("source_urls"))
                if not su:
                    row_ok = False
                if row_ok:
                    per_row_pass += 1
            mcq_struct_pass_count = per_row_pass / max(len(mcq_rows), 1)
    scores["mcq_questions_structure_and_fields"] = mcq_struct_pass_count if mcq_struct_pass_count else 0.0

    # mcq_questions_exact_two_per_topic
    mcq_two_per_topic_score = 0.0
    if expected_topics and mcq_ok and mcq_rows:
        # Must be exactly 2 per topic and exactly total 2*len(expected_topics)
        expected_total = 2 * len(expected_topics)
        if len(mcq_rows) == expected_total:
            counts = {}
            for r in mcq_rows:
                try:
                    tid = int(str(r.get("topic_id", "")).strip())
                except Exception:
                    tid = None
                if tid is not None:
                    counts[tid] = counts.get(tid, 0) + 1
            per_topic_ok = 0
            for tid in expected_topics:
                if counts.get(tid, 0) == 2:
                    per_topic_ok += 1
            mcq_two_per_topic_score = per_topic_ok / max(len(expected_topics), 1)
        else:
            mcq_two_per_topic_score = 0.0
    else:
        mcq_two_per_topic_score = 0.0
    scores["mcq_questions_exact_two_per_topic"] = mcq_two_per_topic_score

    # mcq_questions_sources_subset_of_validated
    # Build validated sources by topic
    validated_sources_by_topic = {}
    if vf_ok and vf_rows:
        for r in vf_rows:
            try:
                tid = int(str(r.get("topic_id", "")).strip())
            except Exception:
                continue
            vs = set(_split_urls(r.get("source_urls")))
            validated_sources_by_topic[tid] = vs
    mcq_sources_subset_score = 0.0
    if mcq_ok and mcq_rows and validated_sources_by_topic:
        passed = 0
        total = 0
        for r in mcq_rows:
            try:
                tid = int(str(r.get("topic_id", "")).strip())
            except Exception:
                continue
            q_sources = set(_split_urls(r.get("source_urls")))
            if not q_sources:
                total += 1
                continue
            valid_set = validated_sources_by_topic.get(tid, set())
            total += 1
            if q_sources.issubset(valid_set):
                passed += 1
        mcq_sources_subset_score = (passed / total) if total > 0 else 0.0
    scores["mcq_questions_sources_subset_of_validated"] = mcq_sources_subset_score

    # run_summary checks
    run_summary_path = workspace / "out" / "run_summary.txt"
    rs_text = ""
    if run_summary_path.exists():
        try:
            rs_text = run_summary_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            rs_text = ""

    # run_summary_total_topics_line
    rs_total_ok = 0.0
    if rs_text and expected_topics:
        m = re.search(r"TOTAL_TOPICS:\s*(\d+)", rs_text)
        if m:
            try:
                val = int(m.group(1))
                if val == len(expected_topics):
                    rs_total_ok = 1.0
            except Exception:
                rs_total_ok = 0.0
    scores["run_summary_total_topics_line"] = rs_total_ok

    # run_summary_topic_lines_present and run_summary_allowed_counts_match_jsonl
    topic_lines_present_score = 0.0
    allowed_counts_match_score = 0.0
    if rs_text and expected_topics:
        lines = rs_text.splitlines()
        # Build mapping from topic_id -> allowed_sources count in summary
        summary_counts = {}
        for line in lines:
            m = re.match(r"\s*TOPIC\s+(\d+):\s*allowed_sources\s*=\s*(\d+)\s*$", line)
            if m:
                try:
                    tid = int(m.group(1))
                    cnt = int(m.group(2))
                    summary_counts[tid] = cnt
                except Exception:
                    continue
        present = 0
        counts_match = 0
        # Compute allowed counts from jsonl
        allowed_counts = {tid: len(allowed_by_topic.get(tid, [])) for tid in expected_topics}
        for tid in expected_topics:
            if tid in summary_counts:
                present += 1
                if allowed_counts.get(tid, 0) == summary_counts.get(tid):
                    counts_match += 1
        topic_lines_present_score = present / max(len(expected_topics), 1)
        allowed_counts_match_score = counts_match / max(len(expected_topics), 1)
    scores["run_summary_topic_lines_present"] = topic_lines_present_score
    scores["run_summary_allowed_counts_match_jsonl"] = allowed_counts_match_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()