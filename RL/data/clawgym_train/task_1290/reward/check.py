import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def _compute_summary(rows: List[Dict[str, str]]) -> dict:
    # Parse and compute metrics from CSV rows
    total_individuals = 0
    total_sightings = 0
    species_set = set()
    dates = []
    species_counts = {}
    coastal_individuals = 0
    daily_counts = {}

    for row in rows:
        try:
            date = row["date"]
            species = row["species"]
            count = int(row["count"])
            habitat = row["habitat"]
        except Exception:
            # If any row malformed, raise to allow caller to handle as failure
            raise ValueError("Malformed CSV row")

        total_sightings += 1
        total_individuals += count
        species_set.add(species)
        dates.append(date)

        species_counts[species] = species_counts.get(species, 0) + count

        if habitat == "coastal":
            coastal_individuals += count

        daily_counts[date] = daily_counts.get(date, 0) + count

    if total_sightings == 0:
        avg = 0.0
    else:
        avg = round(total_individuals / total_sightings, 2)

    # Date range
    start_date = min(dates) if dates else None
    end_date = max(dates) if dates else None

    # Top species by individuals: 3 entries, sort by total desc, tie by species asc
    sorted_species = sorted(
        species_counts.items(),
        key=lambda kv: (-kv[1], kv[0])
    )
    top3 = [{"species": sp, "count": c} for sp, c in sorted_species[:3]]

    # Coastal share percent rounded to 1 decimal
    coastal_share = round((coastal_individuals / total_individuals * 100) if total_individuals > 0 else 0.0, 1)

    # Daily totals sorted by date ascending
    daily_totals = [{"date": d, "count": daily_counts[d]} for d in sorted(daily_counts.keys())]

    return {
        "total_individuals": total_individuals,
        "total_sightings": total_sightings,
        "unique_species_count": len(species_set),
        "date_range": {"start": start_date, "end": end_date},
        "top_species_by_individuals": top3,
        "coastal_individuals_share_percent": coastal_share,
        "average_count_per_sighting": avg,
        "daily_totals": daily_totals,
        "species_counts_sorted": sorted_species,  # helper for species_counts.csv check
    }


def _parse_species_counts_csv(p: Path) -> Optional[List[Tuple[str, int]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    if header != ["species", "total_count"]:
        return None
    out = []
    for r in rows[1:]:
        if len(r) != 2:
            return None
        sp = r[0]
        try:
            cnt = int(r[1])
        except Exception:
            return None
        out.append((sp, cnt))
    return out


def _find_front_matter_indices(lines: List[str]) -> Optional[Tuple[int, int]]:
    first = None
    second = None
    for i, line in enumerate(lines):
        # Consider line equal to '---' even with newline endings
        if line.strip() == "---":
            if first is None:
                first = i
            else:
                second = i
                break
    if first is None or second is None:
        return None
    return first, second


def _count_words(text: str) -> int:
    words = re.findall(r"\b\w+\b", text, flags=re.UNICODE)
    return len(words)


def _find_contiguous_bullet_block(lines: List[str], length_required: int) -> Optional[Tuple[int, int, List[str]]]:
    # Find a contiguous block of lines starting with "- " of the given length
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].lstrip().startswith("- "):
            # start collecting
            block = []
            j = i
            while j < n and lines[j].lstrip().startswith("- "):
                block.append(lines[j].rstrip("\r\n"))
                j += 1
            if len(block) == length_required:
                return i, j - 1, block
            # else continue search from j
            i = j
        else:
            i += 1
    return None


def _line_contains_species_and_count(line: str, species: str, count: int) -> bool:
    if species in line:
        # Look for the count near the species name (on same line)
        # Accept formats like "(23)" or "23" following species
        # Ensure digits appear after species occurrence
        idx = line.find(species)
        tail = line[idx + len(species):]
        return re.search(rf"\(?\b{count}\b\)?", tail) is not None
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_csv = workspace / "input" / "bird_sightings.csv"
    input_field_notes = workspace / "input" / "field_notes.md"
    input_sms = workspace / "input" / "draft_sms.txt"

    out_summary = workspace / "output" / "summary.json"
    out_species_counts = workspace / "output" / "species_counts.csv"
    out_field_notes = workspace / "output" / "field_notes_edited.md"
    out_email = workspace / "output" / "email_to_group.md"
    out_sms = workspace / "output" / "sms_rewritten.txt"

    scores = {
        "summary_json_parsed": 0.0,
        "summary_totals": 0.0,
        "summary_unique_species_and_dates": 0.0,
        "summary_top_species": 0.0,
        "summary_percent_and_average": 0.0,
        "summary_daily_totals": 0.0,
        "species_counts_csv": 0.0,
        "field_notes_front_matter_preserved": 0.0,
        "field_notes_bullets_and_placeholder": 0.0,
        "field_notes_heading_and_cartography_paragraph": 0.0,
        "email_subject_includes_range_and_region": 0.0,
        "email_body_includes_metrics_and_attachments": 0.0,
        "email_top_species_listed": 0.0,
        "email_word_limit": 0.0,
        "sms_content_and_length": 0.0,
    }

    # Load input CSV and compute expected
    rows = _safe_read_csv_dicts(input_csv)
    expected = None
    if rows is not None:
        try:
            expected = _compute_summary(rows)
        except Exception:
            expected = None

    # summary.json checks
    summary_obj = _safe_load_json(out_summary)
    if summary_obj is not None:
        scores["summary_json_parsed"] = 1.0

    if expected is not None and summary_obj is not None:
        # totals
        if (
            isinstance(summary_obj.get("total_individuals"), int)
            and isinstance(summary_obj.get("total_sightings"), int)
            and summary_obj["total_individuals"] == expected["total_individuals"]
            and summary_obj["total_sightings"] == expected["total_sightings"]
        ):
            scores["summary_totals"] = 1.0

        # unique species and date range
        dr = summary_obj.get("date_range")
        if (
            isinstance(summary_obj.get("unique_species_count"), int)
            and isinstance(dr, dict)
            and dr.get("start") == expected["date_range"]["start"]
            and dr.get("end") == expected["date_range"]["end"]
            and summary_obj["unique_species_count"] == expected["unique_species_count"]
        ):
            scores["summary_unique_species_and_dates"] = 1.0

        # top species by individuals
        ts = summary_obj.get("top_species_by_individuals")
        if (
            isinstance(ts, list)
            and len(ts) == 3
            and all(isinstance(e, dict) and "species" in e and "count" in e for e in ts)
            and ts == expected["top_species_by_individuals"]
        ):
            scores["summary_top_species"] = 1.0

        # coastal share percent and average
        csp = summary_obj.get("coastal_individuals_share_percent")
        avg = summary_obj.get("average_count_per_sighting")
        if (
            isinstance(csp, (int, float))
            and isinstance(avg, (int, float))
            and float(csp) == expected["coastal_individuals_share_percent"]
            and round(float(avg), 2) == expected["average_count_per_sighting"]
        ):
            scores["summary_percent_and_average"] = 1.0

        # daily totals
        dt = summary_obj.get("daily_totals")
        if (
            isinstance(dt, list)
            and all(isinstance(e, dict) and "date" in e and "count" in e for e in dt)
            and dt == expected["daily_totals"]
        ):
            scores["summary_daily_totals"] = 1.0

    # species_counts.csv check
    sc = _parse_species_counts_csv(out_species_counts)
    if sc is not None and expected is not None:
        # expected species counts sorted by total desc, then species asc
        exp_sc = [(sp, cnt) for sp, cnt in expected["species_counts_sorted"]]
        if sc == exp_sc:
            scores["species_counts_csv"] = 1.0

    # field_notes_edited.md checks
    in_notes_text = _safe_read_text(input_field_notes)
    out_notes_text = _safe_read_text(out_field_notes)
    if in_notes_text is not None and out_notes_text is not None:
        in_lines = in_notes_text.splitlines(keepends=True)
        out_lines = out_notes_text.splitlines(keepends=True)
        in_indices = _find_front_matter_indices(in_lines)
        out_indices = _find_front_matter_indices(out_lines)
        fm_ok = False
        if in_indices is not None and out_indices is not None:
            # Check front-matter preserved exactly and at same position (line indices)
            (in_first, in_second) = in_indices
            (out_first, out_second) = out_indices
            in_block = in_lines[in_first + 1: in_second]
            out_block = out_lines[out_first + 1: out_second]
            if in_first == 0 and out_first == 0 and in_second == out_second and in_block == out_block:
                fm_ok = True
        scores["field_notes_front_matter_preserved"] = 1.0 if fm_ok else 0.0

        # bullets and placeholder replacement
        body_lines = out_lines[out_indices[1] + 1:] if out_indices else out_lines
        body_text = "".join(body_lines)
        placeholder_removed = "[SUMMARY WILL GO HERE]" not in out_notes_text

        bullets_ok = False
        if expected is not None:
            block_info = _find_contiguous_bullet_block(body_lines, length_required=7)
            if block_info:
                _, _, block = block_info
                # Build expected bullet lines exactly (without newline characters)
                start = expected["date_range"]["start"]
                end = expected["date_range"]["end"]
                t3 = expected["top_species_by_individuals"]
                line1 = f"- Total individuals: {expected['total_individuals']}"
                line2 = f"- Total sightings: {expected['total_sightings']}"
                line3 = f"- Unique species: {expected['unique_species_count']}"
                line4 = f"- Date range: {start} to {end}"
                line5 = f"- Top 3 species by individuals: 1) {t3[0]['species']} ({t3[0]['count']}), 2) {t3[1]['species']} ({t3[1]['count']}), 3) {t3[2]['species']} ({t3[2]['count']})"
                line6 = f"- Coastal individuals share: {expected['coastal_individuals_share_percent']}%"
                # Ensure average formatted to 2 decimals
                avg_str = f"{expected['average_count_per_sighting']:.2f}"
                line7 = f"- Average count per sighting: {avg_str}"
                expected_block = [line1, line2, line3, line4, line5, line6, line7]
                bullets_ok = (block == expected_block)

        scores["field_notes_bullets_and_placeholder"] = 1.0 if (placeholder_removed and bullets_ok) else 0.0

        # Heading kept and cartography paragraph <=70 words linking interest to mapping
        heading_ok = "# Summer Bird Notes" in out_notes_text
        # Find paragraph with both 'cartograph' and 'map' substrings and <= 70 words
        paras = [p.strip() for p in re.split(r"\n\s*\n", body_text) if p.strip()]
        carto_ok = False
        for p in paras:
            low = p.lower()
            if "cartograph" in low and "map" in low:
                if _count_words(p) <= 70:
                    carto_ok = True
                    break
        scores["field_notes_heading_and_cartography_paragraph"] = 1.0 if (heading_ok and carto_ok) else 0.0

    # email_to_group.md checks
    email_text = _safe_read_text(out_email)
    if email_text is not None and expected is not None:
        lines = email_text.splitlines()
        # Subject line with date range and region phrase
        subj_line = None
        for ln in lines:
            if ln.strip().lower().startswith("subject:"):
                subj_line = ln.strip()
                break
        subj_ok = False
        if subj_line:
            if (expected["date_range"]["start"] + " to " + expected["date_range"]["end"]) in subj_line and "Wellington & coastal NZ" in subj_line:
                subj_ok = True
        scores["email_subject_includes_range_and_region"] = 1.0 if subj_ok else 0.0

        # Body includes recipients reference, metrics, attachments, mapping/cartography
        body_lines = [ln for ln in lines if not ln.strip().lower().startswith("subject:")]
        body_text = "\n".join(body_lines)
        recipient_ok = ("Kāpiti Shorebird Trust" in body_text and "coordinator" in body_text.lower())
        metrics_ok = (
            str(expected["total_individuals"]) in body_text
            and str(expected["unique_species_count"]) in body_text
            and (expected["date_range"]["start"] + " to " + expected["date_range"]["end"]) in body_text
            and f"{expected['coastal_individuals_share_percent']}%" in body_text
        )
        attachments_ok = ("output/summary.json" in body_text and "output/species_counts.csv" in body_text)
        mapping_ok = ("map" in body_text.lower() and "cartograph" in body_text.lower())
        body_ok = recipient_ok and metrics_ok and attachments_ok and mapping_ok
        scores["email_body_includes_metrics_and_attachments"] = 1.0 if body_ok else 0.0

        # Top 3 species with counts in body (same line presence)
        t3 = expected["top_species_by_individuals"]
        species_lines_ok = True
        for sp in t3:
            spname = sp["species"]
            spcount = sp["count"]
            found = any(_line_contains_species_and_count(ln, spname, spcount) for ln in body_lines)
            if not found:
                species_lines_ok = False
                break
        scores["email_top_species_listed"] = 1.0 if species_lines_ok else 0.0

        # Word count <= 250 words
        word_count = _count_words(email_text)
        scores["email_word_limit"] = 1.0 if word_count <= 250 else 0.0

    # sms_rewritten.txt checks
    sms_text = _safe_read_text(out_sms)
    if sms_text is not None and expected is not None:
        sms_len_ok = len(sms_text) <= 200
        date_range_str = expected["date_range"]["start"] + " to " + expected["date_range"]["end"]
        date_ok = date_range_str in sms_text
        top1 = expected["top_species_by_individuals"][0]
        top1_ok = f"{top1['species']} ({top1['count']})" in sms_text
        scores["sms_content_and_length"] = 1.0 if (sms_len_ok and date_ok and top1_ok) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()