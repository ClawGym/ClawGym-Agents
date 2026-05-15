import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _compute_severity_band(amount_usd: int) -> int:
    if amount_usd < 100000:
        return 1
    elif amount_usd <= 1000000:
        return 2
    else:
        return 3


def _compute_impact_band(victims_estimated: int) -> int:
    if victims_estimated < 1000:
        return 0
    elif victims_estimated <= 9999:
        return 1
    else:
        return 2


def _compute_legal_weight(legal_actions: str) -> int:
    la = (legal_actions or "").strip().lower()
    if la in {"indicted", "class_action"}:
        return 2
    if la == "lawsuit":
        return 1
    if la == "none":
        return 0
    # Unknown value -> treat as 0
    return 0


def _compute_open_bonus(status: str) -> int:
    return 1 if (status or "").strip().lower() == "open" else 0


def _compute_priority_score(amount_usd: int, victims_estimated: int, legal_actions: str, corroborated_sources: int, status: str) -> Tuple[int, int, int, int, int]:
    severity_band = _compute_severity_band(amount_usd)
    impact_band = _compute_impact_band(victims_estimated)
    legal_weight = _compute_legal_weight(legal_actions)
    corroboration = min(int(corroborated_sources), 3)
    open_bonus = _compute_open_bonus(status)
    priority = severity_band + impact_band + legal_weight + corroboration + open_bonus
    return priority, severity_band, impact_band, legal_weight, open_bonus


def _expected_filtered_and_ranked(rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    filtered = []
    for r in rows:
        year = _parse_int(r.get("year", ""))
        corroborated_sources = _parse_int(r.get("corroborated_sources", ""))
        amount_usd = _parse_int(r.get("amount_usd", ""))
        victims_estimated = _parse_int(r.get("victims_estimated", ""))
        if None in (year, corroborated_sources, amount_usd, victims_estimated):
            # Skip rows with malformed required fields
            continue
        if corroborated_sources >= 2 and year >= 2015:
            priority, severity_band, impact_band, legal_weight, open_bonus = _compute_priority_score(
                amount_usd, victims_estimated, r.get("legal_actions", ""), corroborated_sources, r.get("status", "")
            )
            filtered.append({
                "incident_id": r.get("incident_id", ""),
                "company": r.get("company", ""),
                "year": year,
                "category": r.get("category", ""),
                "region": r.get("region", ""),
                "amount_usd": amount_usd,
                "corroborated_sources": corroborated_sources,
                "legal_actions": r.get("legal_actions", ""),
                "status": r.get("status", ""),
                "victims_estimated": victims_estimated,
                "priority_score": priority,
                "severity_band": severity_band,
                "impact_band": impact_band,
                "legal_weight": legal_weight,
                "open_bonus": open_bonus,
            })
    # Sort by priority_score desc, then corroborated_sources desc, then amount_usd desc
    filtered.sort(key=lambda x: (x["priority_score"], x["corroborated_sources"], x["amount_usd"]), reverse=True)
    return filtered


def _extract_section_lines(text: str, heading_name: str, all_headings: List[str]) -> List[str]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    # Find start index for the heading (case-insensitive contains)
    start_idx = None
    hnorm = heading_name.lower()
    for i, ln in enumerate(lines):
        if hnorm in ln.lower():
            start_idx = i
            break
    if start_idx is None:
        return []
    # Determine end at next heading occurrence of any heading (excluding current line)
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if any(h.lower() in lines[j].lower() for h in all_headings):
            end_idx = j
            break
    return lines[start_idx + 1:end_idx]


def _line_contains_all_tokens(line: str, tokens: List[str]) -> bool:
    s = line
    return all(t in s for t in tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ranking_file_header_and_columns": 0.0,
        "ranking_filtered_ids_and_count": 0.0,
        "ranking_derived_fields_correct": 0.0,
        "ranking_sorted_order": 0.0,
        "briefing_has_required_headings": 0.0,
        "briefing_status_metrics_correct": 0.0,
        "briefing_top_cases_correct": 0.0,
        "briefing_category_region_counts_correct": 0.0,
        "briefing_method_rules_covered": 0.0,
        "briefing_appendix_ids_ordered": 0.0,
        "email_subject_and_reference": 0.0,
        "email_word_limit_and_apology": 0.0,
        "email_top_cases_sentence": 0.0,
        "email_forbidden_phrases_absent": 0.0,
    }

    input_csv_path = workspace / "input" / "incidents.csv"
    email_draft_path = workspace / "input" / "email_draft.txt"
    ranking_path = workspace / "output" / "incident_ranking.csv"
    briefing_path = workspace / "output" / "briefing_report.md"
    email_rewrite_path = workspace / "output" / "email_rewrite.txt"

    # Load input incidents
    incidents_data = _safe_read_csv(input_csv_path)
    expected_filtered_ranked: List[Dict[str, object]] = []
    total_records = None
    if incidents_data is not None:
        in_header, in_rows = incidents_data
        total_records = len(in_rows)
        expected_filtered_ranked = _expected_filtered_and_ranked(in_rows)

    # 1) Validate output/incident_ranking.csv
    ranking_data = _safe_read_csv(ranking_path)
    required_columns = [
        "incident_id",
        "company",
        "year",
        "category",
        "region",
        "amount_usd",
        "corroborated_sources",
        "legal_actions",
        "status",
        "victims_estimated",
        "priority_score",
        "severity_band",
        "impact_band",
        "legal_weight",
        "open_bonus",
    ]
    if ranking_data is not None:
        out_header, out_rows = ranking_data
        # Check header exact match
        if out_header == required_columns:
            scores["ranking_file_header_and_columns"] = 1.0

        # Check filtered ids and count equal to expected
        if incidents_data is not None:
            expected_ids = [r["incident_id"] for r in expected_filtered_ranked]
            got_ids = [r.get("incident_id", "") for r in out_rows]
            if got_ids == expected_ids and len(out_rows) == len(expected_filtered_ranked):
                scores["ranking_filtered_ids_and_count"] = 1.0

        # Check derived fields correctness for each row
        derived_ok = True
        for r in out_rows:
            try:
                amount = _parse_int(r.get("amount_usd", ""))
                victims = _parse_int(r.get("victims_estimated", ""))
                year = _parse_int(r.get("year", ""))
                sources = _parse_int(r.get("corroborated_sources", ""))
                legal = r.get("legal_actions", "")
                status = r.get("status", "")
                if None in (amount, victims, year, sources):
                    derived_ok = False
                    break
                prio, sev, imp, lw, ob = _compute_priority_score(amount, victims, legal, sources, status)
                if (
                    _parse_int(r.get("priority_score", "")) != prio or
                    _parse_int(r.get("severity_band", "")) != sev or
                    _parse_int(r.get("impact_band", "")) != imp or
                    _parse_int(r.get("legal_weight", "")) != lw or
                    _parse_int(r.get("open_bonus", "")) != ob
                ):
                    derived_ok = False
                    break
            except Exception:
                derived_ok = False
                break
        if derived_ok and len(out_rows) > 0:
            scores["ranking_derived_fields_correct"] = 1.0

        # Check sorted order strictly
        if incidents_data is not None and len(out_rows) == len(expected_filtered_ranked):
            # Compare exact id order to expected
            got_ids = [r.get("incident_id", "") for r in out_rows]
            expected_ids = [r["incident_id"] for r in expected_filtered_ranked]
            if got_ids == expected_ids:
                scores["ranking_sorted_order"] = 1.0

    # 2) Validate output/briefing_report.md
    briefing_text = _safe_read_text(briefing_path)
    headings = [
        "Status Update",
        "Top Cases",
        "Category and Region Summary",
        "Method",
        "Appendix: Filtered Incidents",
    ]
    if briefing_text is not None:
        # Has required headings
        has_all = all(h.lower() in briefing_text.lower() for h in headings)
        if has_all:
            scores["briefing_has_required_headings"] = 1.0

        # Status metrics
        status_lines = _extract_section_lines(briefing_text, "Status Update", headings)
        if total_records is not None and expected_filtered_ranked:
            # Check total records, filtered count, earliest and latest year present in the section
            status_blob = "\n".join(status_lines)
            got_total = str(total_records) in status_blob
            filtered_count = len(expected_filtered_ranked)
            got_filtered = str(filtered_count) in status_blob
            years = [int(r["year"]) for r in expected_filtered_ranked]
            earliest = min(years)
            latest = max(years)
            got_earliest = str(earliest) in status_blob
            got_latest = str(latest) in status_blob
            if all([got_total, got_filtered, got_earliest, got_latest]):
                scores["briefing_status_metrics_correct"] = 1.0

        # Top cases listing correctness
        top_lines = _extract_section_lines(briefing_text, "Top Cases", headings)
        top_correct = True
        if expected_filtered_ranked:
            top5 = expected_filtered_ranked[:5]
            for entry in top5:
                tokens = [
                    str(entry["incident_id"]),
                    str(entry["company"]),
                    str(entry["category"]),
                    str(entry["region"]),
                    str(entry["year"]),
                    str(entry["priority_score"]),
                ]
                # Find a line in the section that contains all tokens
                if not any(_line_contains_all_tokens(ln, tokens) for ln in top_lines):
                    top_correct = False
                    break
            if top_correct:
                scores["briefing_top_cases_correct"] = 1.0

        # Category and Region Summary counts
        cr_lines = _extract_section_lines(briefing_text, "Category and Region Summary", headings)
        if expected_filtered_ranked:
            # Compute expected counts
            cat_counts: Dict[str, int] = {}
            reg_counts: Dict[str, int] = {}
            for r in expected_filtered_ranked:
                cat = str(r["category"])
                reg = str(r["region"])
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                reg_counts[reg] = reg_counts.get(reg, 0) + 1
            # Validate each expected category count appears in some line as "name ... count"
            cats_ok = True
            for cat, cnt in cat_counts.items():
                found = False
                for ln in cr_lines:
                    if cat.lower() in ln.lower():
                        nums = re.findall(r"\d+", ln)
                        if any(int(n) == cnt for n in nums):
                            found = True
                            break
                if not found:
                    cats_ok = False
                    break
            regs_ok = True
            for reg, cnt in reg_counts.items():
                found = False
                for ln in cr_lines:
                    if reg.lower() in ln.lower():
                        nums = re.findall(r"\d+", ln)
                        if any(int(n) == cnt for n in nums):
                            found = True
                            break
                if not found:
                    regs_ok = False
                    break
            if cats_ok and regs_ok:
                scores["briefing_category_region_counts_correct"] = 1.0

        # Method coverage of rules
        method_lines = _extract_section_lines(briefing_text, "Method", headings)
        method_blob = "\n".join(method_lines)
        if method_blob:
            groups_total = 7
            groups_hit = 0
            # Group A: filter corroborated_sources >=2
            if re.search(r"corroborated_sources[^.\n]*(>=\s*2|at least\s+2)", method_blob, flags=re.IGNORECASE):
                groups_hit += 1
            # Group A2: year >= 2015 (or wording)
            if re.search(r"year[^.\n]*(>=\s*2015|2015\s*or\s*later|since\s*2015)", method_blob, flags=re.IGNORECASE):
                groups_hit += 1
            # Group B: severity band with 100000 and 1000000
            if (re.search(r"severity", method_blob, flags=re.IGNORECASE) and
                "100000" in method_blob and "1000000" in method_blob):
                groups_hit += 1
            # Group C: impact band with victims and thresholds
            if (re.search(r"victims(_estimated)?", method_blob, flags=re.IGNORECASE) and
                ("1000" in method_blob) and ("10000" in method_blob)):
                groups_hit += 1
            # Group D: legal weight tokens
            if (re.search(r"indicted", method_blob, flags=re.IGNORECASE) and
                re.search(r"class_action", method_blob, flags=re.IGNORECASE) and
                re.search(r"lawsuit", method_blob, flags=re.IGNORECASE) and
                re.search(r"\bnone\b", method_blob, flags=re.IGNORECASE)):
                groups_hit += 1
            # Group E: corroboration cap at 3
            if re.search(r"(min|capped)[^.\n]*3", method_blob, flags=re.IGNORECASE):
                groups_hit += 1
            # Group F: open bonus
            if (re.search(r"open", method_blob, flags=re.IGNORECASE) and
                re.search(r"\b1\b", method_blob)):
                groups_hit += 1
            scores["briefing_method_rules_covered"] = groups_hit / groups_total

        # Appendix: filtered incidents in ranking order, comma-separated single line
        appendix_lines = _extract_section_lines(briefing_text, "Appendix: Filtered Incidents", headings)
        if expected_filtered_ranked and appendix_lines:
            target_ids = [r["incident_id"] for r in expected_filtered_ranked]
            # Find a line that is a comma-separated list of IDs matching exactly
            matched = False
            for ln in appendix_lines:
                if re.match(r"^[A-Za-z0-9,\s]+$", ln.strip()):
                    items = [x.strip() for x in ln.strip().split(",") if x.strip()]
                    if items == target_ids:
                        matched = True
                        break
            if matched:
                scores["briefing_appendix_ids_ordered"] = 1.0

    # 3) Validate output/email_rewrite.txt
    email_text = _safe_read_text(email_rewrite_path)
    if email_text is not None:
        lines = email_text.splitlines()
        # Subject and briefing reference
        subj_ok = len(lines) >= 1 and lines[0].startswith("Subject: ")
        ref_ok = "output/briefing_report.md" in email_text
        if subj_ok and ref_ok:
            scores["email_subject_and_reference"] = 1.0

        # Word limit (body only) and apology
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        # Count words as sequences of non-whitespace
        words = re.findall(r"\S+", body)
        word_limit_ok = len(words) <= 180
        apology_ok = (re.search(r"\bI.?m sorry\b", email_text, flags=re.IGNORECASE) is not None) or \
                     (re.search(r"\bI regret\b", email_text, flags=re.IGNORECASE) is not None)
        if word_limit_ok and apology_ok:
            scores["email_word_limit_and_apology"] = 1.0

        # Top cases sentence with top 3 IDs from computed ranking
        top3_ok = False
        if expected_filtered_ranked and len(expected_filtered_ranked) >= 3:
            top3 = [r["incident_id"] for r in expected_filtered_ranked[:3]]
            pattern = r"Top cases: \(" + re.escape(top3[0]) + r", " + re.escape(top3[1]) + r", " + re.escape(top3[2]) + r"\)\.?"
            if re.search(pattern, email_text):
                top3_ok = True
        if top3_ok:
            scores["email_top_cases_sentence"] = 1.0

        # Forbidden phrases absent
        forbidden = [
            "acted within policy",
            "legal advised",
            "no wrongdoing found",
        ]
        forbidden_present = any(f.lower() in email_text.lower() for f in forbidden)
        if not forbidden_present:
            scores["email_forbidden_phrases_absent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()