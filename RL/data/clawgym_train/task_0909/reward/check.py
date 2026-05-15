import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict]]:
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


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = s.lower()
    remove_chars = ".,;:'\"!?()[]"
    trans = {ord(ch): None for ch in remove_chars}
    s = s.translate(trans)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_key(s: str) -> str:
    return (s or "").strip().casefold()


def _compute_expected_verification(workspace: Path) -> Optional[Dict[str, Dict[str, str]]]:
    claims_path = workspace / "input" / "claims.jsonl"
    refs_path = workspace / "input" / "sources" / "reference_facts.csv"
    claims = _safe_load_jsonl(claims_path)
    refs = _safe_read_csv(refs_path)
    if claims is None or refs is None:
        return None

    ref_index: Dict[str, List[Dict[str, str]]] = {}
    for r in refs:
        region = _norm_key(r.get("region", ""))
        topic = _norm_key(r.get("topic", ""))
        key = f"{region}|{topic}"
        ref_index.setdefault(key, []).append(r)

    expected: Dict[str, Dict[str, str]] = {}
    for c in claims:
        cid = c.get("id", "")
        region = c.get("region", "")
        topic = c.get("topic", "")
        claim_text = c.get("claim_text", "")
        key = f"{_norm_key(region)}|{_norm_key(topic)}"
        claim_norm = _normalize_text(claim_text)

        verdict = "insufficient"
        matched_ref_id = ""
        supported_matches: List[Dict[str, str]] = []
        contradicted_matches: List[Dict[str, str]] = []

        refs_for_key = ref_index.get(key, [])
        for r in refs_for_key:
            stance = (r.get("stance") or "").strip().casefold()
            ref_norm = (r.get("reference_norm") or "").strip().casefold()
            if claim_norm == ref_norm:
                if stance == "supported":
                    supported_matches.append(r)
                elif stance == "contradicted":
                    contradicted_matches.append(r)

        if supported_matches:
            verdict = "supported"
            matched_ref_id = supported_matches[0].get("ref_id", "")
        elif contradicted_matches:
            verdict = "contradicted"
            matched_ref_id = contradicted_matches[0].get("ref_id", "")
        else:
            verdict = "insufficient"
            matched_ref_id = ""

        expected[cid] = {
            "id": cid,
            "region": region,
            "topic": topic,
            "verdict": verdict,
            "matched_ref_id": matched_ref_id,
        }
    return expected


def _compute_counts(expected_verification: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    overall = {"supported": 0, "contradicted": 0, "insufficient": 0}
    per_region: Dict[str, Dict[str, int]] = {}
    for rec in expected_verification.values():
        region = rec["region"]
        verdict = rec["verdict"]
        if region not in per_region:
            per_region[region] = {"supported": 0, "contradicted": 0, "insufficient": 0}
        if verdict in overall:
            overall[verdict] += 1
            per_region[region][verdict] += 1
    return {"overall": overall, "per_region": per_region}


def _compute_missing_topics(workspace: Path) -> Optional[List[Dict[str, str]]]:
    claims_path = workspace / "input" / "claims.jsonl"
    refs_path = workspace / "input" / "sources" / "reference_facts.csv"
    claims = _safe_load_jsonl(claims_path)
    refs = _safe_read_csv(refs_path)
    if claims is None or refs is None:
        return None
    claim_pairs = {(c.get("region", "").strip(), c.get("topic", "").strip()) for c in claims}
    ref_pairs = {(r.get("region", "").strip(), r.get("topic", "").strip()) for r in refs}
    missing = []
    for region, topic in sorted(claim_pairs):
        if (region, topic) not in ref_pairs:
            missing.append({"region": region, "topic": topic})
    return missing


def _parse_csv_verification(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames
        if header is None:
            return None
        return rows
    except Exception:
        return None


def _find_section_lines(text: str, header_phrase: str) -> List[str]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if header_phrase.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return []
    section_lines: List[str] = []
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s*#\s*", lines[j]):
            break
        section_lines.append(lines[j])
    return section_lines


def _extract_paths_from_section(lines: List[str]) -> List[str]:
    text = "\n".join(lines)
    candidates = re.findall(r"input/[^\s\)\],;]+", text)
    cleaned = [c.rstrip(").,;") for c in candidates]
    return list(dict.fromkeys(cleaned))


def _list_input_files(workspace: Path) -> List[str]:
    files = []
    base = workspace / "input"
    if base.exists():
        for p in base.rglob("*"):
            if p.is_file():
                rel = p.relative_to(workspace).as_posix()
                files.append(rel)
    return sorted(files)


def _counts_in_text(text: str) -> Dict[str, int]:
    counts = {}
    for label in ["supported", "contradicted", "insufficient"]:
        m = re.search(rf"{label}\s*:\s*(\d+)", text, flags=re.IGNORECASE)
        if m:
            try:
                counts[label.lower()] = int(m.group(1))
            except Exception:
                pass
    return counts


def _find_overall_counts_in_section(section_lines: List[str], regions: List[str]) -> Optional[Dict[str, int]]:
    for i, line in enumerate(section_lines):
        line_lc = line.lower()
        if any(r.lower() in line_lc for r in regions):
            continue
        counts = _counts_in_text(line)
        if set(counts.keys()) >= {"supported", "contradicted", "insufficient"}:
            return counts
    joined = "\n".join([l for l in section_lines if not any(r.lower() in l.lower() for r in regions)])
    counts = _counts_in_text(joined)
    if set(counts.keys()) >= {"supported", "contradicted", "insufficient"}:
        return counts
    return None


def _find_region_counts_in_section(section_lines: List[str], region: str) -> Optional[Dict[str, int]]:
    for idx, line in enumerate(section_lines):
        if region.lower() in line.lower():
            window = "\n".join(section_lines[idx: idx + 4])
            counts = _counts_in_text(window)
            if set(counts.keys()) >= {"supported", "contradicted", "insufficient"}:
                return counts
    return None


def _count_sentences(text: str) -> int:
    cleaned_lines = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    count = 0
    for p in parts:
        if re.search(r"[A-Za-z]", p):
            if re.search(r"[.!?]\s*$", p.strip()):
                count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_files_present": 0.0,
        "outputs_verification_report_header": 0.0,
        "outputs_verification_report_content": 0.0,
        "outputs_revised_message_word_limit": 0.0,
        "outputs_revised_message_phrase_and_counts": 0.0,
        "outputs_status_inputs_inspected_section": 0.0,
        "outputs_status_verdict_counts_overall": 0.0,
        "outputs_status_verdict_counts_by_region": 0.0,
        "outputs_status_topics_missing_listed": 0.0,
        "outputs_status_summary_sentences_minimum": 0.0,
    }

    out_dir = workspace / "outputs"
    vr_path = out_dir / "verification_report.csv"
    rm_path = out_dir / "revised_message.txt"
    ss_path = out_dir / "status_summary.md"

    if out_dir.exists() and vr_path.exists() and rm_path.exists() and ss_path.exists():
        scores["outputs_files_present"] = 1.0

    expected_verif = _compute_expected_verification(workspace)
    expected_counts = None
    missing_pairs = None
    if expected_verif is not None:
        expected_counts = _compute_counts(expected_verif)
        missing_pairs = _compute_missing_topics(workspace)

    if vr_path.exists():
        try:
            with vr_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
            expected_header = ["id", "region", "topic", "verdict", "matched_ref_id"]
            if header == expected_header:
                scores["outputs_verification_report_header"] = 1.0
        except Exception:
            pass

        if expected_verif is not None:
            rows = _parse_csv_verification(vr_path)
            if rows is not None:
                expected_ids = set(expected_verif.keys())
                got_ids = {r.get("id", "") for r in rows}
                ids_match = (expected_ids == got_ids) and (len(rows) == len(expected_ids))
                content_ok = True
                if not ids_match:
                    content_ok = False
                else:
                    for r in rows:
                        cid = r.get("id", "")
                        exp = expected_verif.get(cid)
                        if exp is None:
                            content_ok = False
                            break
                        if r.get("region", "") != exp["region"]:
                            content_ok = False
                            break
                        if r.get("topic", "") != exp["topic"]:
                            content_ok = False
                            break
                        if r.get("verdict", "") != exp["verdict"]:
                            content_ok = False
                            break
                        mr = r.get("matched_ref_id", "")
                        if exp["verdict"] == "insufficient":
                            if mr != "":
                                content_ok = False
                                break
                        else:
                            if mr != exp["matched_ref_id"]:
                                content_ok = False
                                break
                if content_ok:
                    scores["outputs_verification_report_content"] = 1.0

    if rm_path.exists() and expected_counts is not None:
        text = _safe_read_text(rm_path) or ""
        words = re.findall(r"\b\w+\b", text)
        if len(words) <= 180 and len(words) > 0:
            scores["outputs_revised_message_word_limit"] = 1.0
        phrase_count = text.count("cabin crew insights")
        overall = expected_counts["overall"]
        pattern = rf"\(supported:\s*{overall['supported']},\s*contradicted:\s*{overall['contradicted']},\s*insufficient:\s*{overall['insufficient']}\)"
        has_counts = re.search(pattern, text) is not None
        if phrase_count == 1 and has_counts:
            scores["outputs_revised_message_phrase_and_counts"] = 1.0

    if ss_path.exists():
        ss_text = _safe_read_text(ss_path) or ""
        input_files = _list_input_files(workspace)
        sec_lines = _find_section_lines(ss_text, "Inputs inspected")
        listed_paths = _extract_paths_from_section(sec_lines) if sec_lines else []
        if input_files:
            all_listed = all(p in listed_paths for p in input_files)
            if all_listed and len(listed_paths) >= len(input_files):
                scores["outputs_status_inputs_inspected_section"] = 1.0

        if expected_counts is not None:
            vc_lines = _find_section_lines(ss_text, "Verdict counts")
            if vc_lines:
                regions = sorted(expected_counts["per_region"].keys())
                overall_counts_found = _find_overall_counts_in_section(vc_lines, regions)
                if overall_counts_found is not None:
                    exp_ov = expected_counts["overall"]
                    if (overall_counts_found.get("supported") == exp_ov["supported"] and
                        overall_counts_found.get("contradicted") == exp_ov["contradicted"] and
                        overall_counts_found.get("insufficient") == exp_ov["insufficient"]):
                        scores["outputs_status_verdict_counts_overall"] = 1.0
                per_region_ok = True
                for region, cnts in expected_counts["per_region"].items():
                    rc = _find_region_counts_in_section(vc_lines, region)
                    if rc is None:
                        per_region_ok = False
                        break
                    if not (rc.get("supported") == cnts["supported"] and
                            rc.get("contradicted") == cnts["contradicted"] and
                            rc.get("insufficient") == cnts["insufficient"]):
                        per_region_ok = False
                        break
                if per_region_ok and regions:
                    scores["outputs_status_verdict_counts_by_region"] = 1.0

        if expected_verif is not None and missing_pairs is not None:
            tm_lines = _find_section_lines(ss_text, "Topics missing from references")
            if tm_lines:
                all_present = True
                for pair in missing_pairs:
                    region = pair["region"]
                    topic = pair["topic"]
                    found = False
                    for line in tm_lines:
                        if region.lower() in line.lower() and topic.lower() in line.lower():
                            found = True
                            break
                    if not found:
                        all_present = False
                        break
                if all_present:
                    scores["outputs_status_topics_missing_listed"] = 1.0

        sent_count = _count_sentences(ss_text)
        if sent_count >= 2:
            scores["outputs_status_summary_sentences_minimum"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()