import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames or []
            return (header, rows)
    except Exception:
        try:
            with path.open("r", newline="") as f:
                reader = csv.DictReader(f)
                rows = [dict(r) for r in reader]
                header = reader.fieldnames or []
                return (header, rows)
        except Exception:
            return None


def _parse_notes_rares(notes_text: str) -> Dict[str, Set[str]]:
    rares: Dict[str, Set[str]] = {}
    current_trail: Optional[str] = None
    for raw_line in notes_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_trail = line[3:].strip()
            if current_trail not in rares:
                rares[current_trail] = set()
            continue
        if current_trail:
            content = line
            if content.startswith("- "):
                content = content[2:].lstrip()
            if content.startswith("RARE:"):
                species = content[len("RARE:"):].strip()
                if species:
                    rares.setdefault(current_trail, set()).add(species)
    # Remove trails with no rares to keep map clean (though safe either way)
    rares = {t: s for t, s in rares.items() if s}
    return rares


def _parse_latest_date(csv_rows: List[Dict[str, str]]) -> Optional[str]:
    dates: List[datetime] = []
    for row in csv_rows:
        d = row.get("date", "").strip()
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            dates.append(dt)
        except Exception:
            return None
    if not dates:
        return None
    latest = max(dates)
    return latest.strftime("%Y-%m-%d")


def _compute_expected(workspace: Path) -> Optional[Dict]:
    # Load inputs
    csv_path = workspace / "sightings" / "records.csv"
    notes_path = workspace / "notes" / "trail_notes.md"

    csv_loaded = _read_csv_dicts(csv_path)
    notes_text = _read_text(notes_path)

    if not csv_loaded or notes_text is None:
        return None

    header, rows = csv_loaded
    # Validate required columns in CSV
    required_cols = {"date", "trail", "species", "status"}
    if not set([c.strip() for c in (header or [])]).issuperset(required_cols):
        return None

    # Build sensitive species by trail from CSV
    sensitive_statuses = {"uk bap priority", "protected", "priority"}
    csv_species_by_trail: Dict[str, Dict[str, str]] = {}  # trail -> lower(species) -> canonical species (CSV case)
    trails_from_csv: Set[str] = set()
    for r in rows:
        trail = (r.get("trail") or "").strip()
        species = (r.get("species") or "").strip()
        status = (r.get("status") or "").strip()
        if not trail:
            continue
        trails_from_csv.add(trail)
        if species and status.lower() in sensitive_statuses:
            d = csv_species_by_trail.setdefault(trail, {})
            key = species.lower()
            if key not in d:
                d[key] = species

    # Build sensitive species by trail from notes (RARE)
    notes_rares = _parse_notes_rares(notes_text)
    notes_species_by_trail: Dict[str, Dict[str, str]] = {}
    for trail, species_set in notes_rares.items():
        notes_species_by_trail[trail] = {}
        for sp in species_set:
            notes_species_by_trail[trail][sp.lower()] = sp

    # Union trails: include all trails present in CSV; also include trails present in notes with RARE but not in CSV
    all_trails: Set[str] = set(trails_from_csv) | set(notes_rares.keys())

    # Build union sensitive species per trail and sources
    expected_rows: Dict[str, Dict[str, str]] = {}
    trails_with_rare_note: Dict[str, bool] = {}
    for trail in sorted(all_trails):
        csv_map = csv_species_by_trail.get(trail, {})
        notes_map = notes_species_by_trail.get(trail, {})
        union_keys = set(csv_map.keys()) | set(notes_map.keys())
        # canonical species name: prefer CSV case if present, else notes case
        species_names: List[str] = []
        for key in union_keys:
            name = csv_map.get(key) or notes_map.get(key)
            if name:
                species_names.append(name)
        # Sort alphabetically by common name (case-insensitive)
        species_names_sorted = sorted(species_names, key=lambda s: s.lower())
        sensitive_species_csv_field = ";".join(species_names_sorted)
        sensitive_count = len(species_names_sorted)
        sources_set: Set[str] = set()
        if csv_map:
            # Only include "CSV" if at least one sensitive species came from CSV
            # Determine if any union key originated from CSV
            if any(k in csv_map for k in union_keys):
                sources_set.add("CSV")
        if notes_map:
            if any(k in notes_map for k in union_keys):
                sources_set.add("Notes")
        sources_field = ";".join(sorted(sources_set))
        expected_rows[trail] = {
            "trail": trail,
            "sensitive_species": sensitive_species_csv_field,
            "sensitive_count": str(sensitive_count),
            "sources": sources_field,
        }
        trails_with_rare_note[trail] = bool(notes_map)

    # Latest date
    latest_date = _parse_latest_date(rows)
    if latest_date is None:
        return None

    # N = count of trails with sensitive species (count > 0)
    n_sensitive_trails = sum(1 for t in expected_rows.values() if int(t["sensitive_count"]) > 0)

    # Compute top-3 list by sensitive_count desc, then trail name asc
    # Use expected_rows values
    def _rank_key(item):
        trail_name = item["trail"]
        count = int(item["sensitive_count"])
        return (-count, trail_name.lower())

    ranked = sorted(expected_rows.values(), key=_rank_key)
    top3_trails = [r["trail"] for r in ranked[:3]]

    # Prepare docs bullet expectations: comma-separated alphabetical list
    docs_bullets: Dict[str, str] = {}
    for trail, row in expected_rows.items():
        # build comma-separated alphabetical list from species_names_sorted
        species_csv_field = row["sensitive_species"]
        if species_csv_field.strip() == "":
            species_list_for_docs = "None recorded"
        else:
            items = species_csv_field.split(";")
            # Convert to comma + space separated
            species_list_for_docs = ", ".join(items)
        rare_note_text = "RARE note present" if trails_with_rare_note.get(trail, False) else "No RARE note"
        bullet = f"- {trail} — sensitive species: {species_list_for_docs}; notes: {rare_note_text}"
        docs_bullets[trail] = bullet

    return {
        "expected_rows": expected_rows,  # mapping trail -> fields
        "latest_date": latest_date,
        "n_sensitive_trails": n_sensitive_trails,
        "docs_bullets": docs_bullets,
        "top3": top3_trails,
        "trails_with_rare_note": trails_with_rare_note,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "sensitive_trails_csv_header": 0.0,
        "sensitive_trails_csv_rows": 0.0,
        "brief_date_updated": 0.0,
        "brief_summary_updated": 0.0,
        "brief_trail_bullets_updated": 0.0,
        "meeting_notes_decisions_top3": 0.0,
        "meeting_notes_actions_roles": 0.0,
    }

    expected = _compute_expected(workspace)
    # If expected cannot be computed (missing/malformed inputs), return zeros gracefully
    if expected is None:
        return scores

    expected_rows = expected["expected_rows"]
    expected_header = ["trail", "sensitive_species", "sensitive_count", "sources"]

    # Check output/sensitive_trails.csv
    st_path = workspace / "output" / "sensitive_trails.csv"
    st_loaded = _read_csv_dicts(st_path)
    if st_loaded:
        header, rows = st_loaded
        # Header check: exact match
        if header == expected_header:
            scores["sensitive_trails_csv_header"] = 1.0
        else:
            scores["sensitive_trails_csv_header"] = 0.0

        # Rows check: presence and correctness
        # Build mapping from trail to row (latest occurrence overrides)
        actual_by_trail: Dict[str, Dict[str, str]] = {}
        for r in rows:
            trail = (r.get("trail") or "").strip()
            if not trail:
                continue
            # Normalize keys to expected header set only
            filtered = {k: (r.get(k, "") or "").strip() for k in expected_header}
            actual_by_trail[trail] = filtered

        expected_trails = set(expected_rows.keys())
        actual_trails = set(actual_by_trail.keys())

        if expected_trails != actual_trails:
            # If the set of trails doesn't match exactly, fail the rows check entirely
            scores["sensitive_trails_csv_rows"] = 0.0
        else:
            per_trail_ok = []
            for trail, exp in expected_rows.items():
                act = actual_by_trail.get(trail, {})
                if not act:
                    per_trail_ok.append(0.0)
                    continue
                # Validate sensitive_species exactly
                ok_species = (act.get("sensitive_species", "") == exp["sensitive_species"])
                # Validate sensitive_count as exact int string
                try:
                    ok_count = int(act.get("sensitive_count", "").strip()) == int(exp["sensitive_count"])
                except Exception:
                    ok_count = False
                # Validate sources exact
                ok_sources = (act.get("sources", "") == exp["sources"])
                per_trail_ok.append(1.0 if (ok_species and ok_count and ok_sources) else 0.0)
            if per_trail_ok:
                scores["sensitive_trails_csv_rows"] = sum(per_trail_ok) / len(per_trail_ok)
            else:
                scores["sensitive_trails_csv_rows"] = 0.0
    else:
        scores["sensitive_trails_csv_header"] = 0.0
        scores["sensitive_trails_csv_rows"] = 0.0

    # Check docs/club_brief_draft.md updates
    brief_path = workspace / "docs" / "club_brief_draft.md"
    brief_text = _read_text(brief_path)
    if brief_text is not None:
        lines = brief_text.splitlines()
        # Date line
        expected_date_line = f"Date: {expected['latest_date']}"
        date_ok = any(line.strip() == expected_date_line for line in lines)
        scores["brief_date_updated"] = 1.0 if date_ok else 0.0

        # Summary line: should be "Summary: Based on records through <LATEST_DATE>, <N> trails have sensitive sightings."
        expected_summary_line = f"Summary: Based on records through {expected['latest_date']}, {expected['n_sensitive_trails']} trails have sensitive sightings."
        summary_ok = any(line.strip() == expected_summary_line for line in lines)
        scores["brief_summary_updated"] = 1.0 if summary_ok else 0.0

        # Bullets for trails under review
        # We will check presence of each expected bullet line anywhere in the file
        expected_bullets = expected["docs_bullets"]
        found_count = 0
        for trail, bullet in expected_bullets.items():
            if any(l.strip() == bullet for l in lines):
                found_count += 1
        total_bullets = len(expected_bullets)
        if total_bullets > 0:
            scores["brief_trail_bullets_updated"] = found_count / total_bullets
        else:
            scores["brief_trail_bullets_updated"] = 0.0
    else:
        scores["brief_date_updated"] = 0.0
        scores["brief_summary_updated"] = 0.0
        scores["brief_trail_bullets_updated"] = 0.0

    # Check output/meeting_notes.md
    meeting_path = workspace / "output" / "meeting_notes.md"
    meeting_text = _read_text(meeting_path)
    if meeting_text is not None:
        mlines = meeting_text.splitlines()

        def _extract_section_bullets(lines: List[str], section_title: str) -> List[str]:
            bullets: List[str] = []
            try:
                idx = next(i for i, l in enumerate(lines) if l.strip() == section_title)
            except StopIteration:
                return bullets
            i = idx + 1
            while i < len(lines):
                line = lines[i].rstrip("\n")
                stripped = line.strip()
                if stripped == "":
                    # Stop at blank line to keep section bounded
                    break
                if stripped.endswith(":") and not stripped.startswith("- "):
                    # Next section title likely encountered
                    break
                if stripped.startswith("- "):
                    bullets.append(stripped)
                    i += 1
                    continue
                # If a non-bullet content in section, include it only if it starts with "- "
                i += 1
            return bullets

        decisions_bullets = _extract_section_bullets(mlines, "Decisions Needed:")
        actions_bullets = _extract_section_bullets(mlines, "Action Items:")

        # Expected decisions: "- <TRAIL>"
        expected_top3: List[str] = expected["top3"]
        expected_decisions = [f"- {t}" for t in expected_top3]

        decisions_ok = decisions_bullets == expected_decisions
        scores["meeting_notes_decisions_top3"] = 1.0 if decisions_ok else 0.0

        # Expected actions: with roles
        roles = ["Lead Walker", "Recorder", "Signage Volunteer"]
        expected_actions = []
        for i, t in enumerate(expected_top3):
            role = roles[i] if i < len(roles) else "TBD"
            expected_actions.append(f"- {t}: agree observation protocol and signage (owner: {role})")

        actions_ok = actions_bullets == expected_actions
        scores["meeting_notes_actions_roles"] = 1.0 if actions_ok else 0.0
    else:
        scores["meeting_notes_decisions_top3"] = 0.0
        scores["meeting_notes_actions_roles"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()