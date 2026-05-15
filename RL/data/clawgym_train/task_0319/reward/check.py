import json
import csv
import hashlib
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = path.read_text(encoding="utf-8")
        return data, None
    except Exception as e:
        return None, str(e)


def safe_read_json(path: Path) -> Tuple[Optional[object], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def parse_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def load_manifest(path: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    manifest, err = safe_read_json(path)
    if err is not None or not isinstance(manifest, list):
        return None, "manifest not list or unreadable"
    return manifest, None


def contains_in_order(text: str, phrases: List[str]) -> bool:
    idx = 0
    lower = text.lower()
    for p in phrases:
        pos = lower.find(p.lower(), idx)
        if pos == -1:
            return False
        idx = pos + 1
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "resources_pdfs_present": 0.0,
        "resources_texts_present": 0.0,
        "manifest_json_valid_structure": 0.0,
        "manifest_checksums_match": 0.0,
        "manifest_source_domains_types_valid": 0.0,
        "manifest_snippets_quality": 0.0,
        "plan_csv_header_and_row_count": 0.0,
        "plan_themes_valid": 0.0,
        "plan_source_ids_valid_and_min_counts": 0.0,
        "plan_exercise_titles_source_based": 0.0,
        "plan_descriptions_length_valid": 0.0,
        "plan_prompts_address_names_and_strength": 0.0,
        "plan_rule_incorporated": 0.0,
        "printable_guide_sections_and_intro_rules": 0.0,
        "printable_guide_weekly_plan_and_sources": 0.0,
        "inventory_lists_all_artifacts_with_sizes": 0.0,
        "validation_report_values_consistent": 0.0,
    }

    # Paths
    input_pref_path = workspace / "input" / "preferences.json"
    input_intro_path = workspace / "input" / "intro.md"
    downloads_dir = workspace / "downloads" / "resources"
    outputs_dir = workspace / "outputs"

    ist_pdf = downloads_dir / "i_statement.pdf"
    al_pdf = downloads_dir / "active_listening.pdf"
    ist_txt = downloads_dir / "i_statement.txt"
    al_txt = downloads_dir / "active_listening.txt"
    manifest_path = downloads_dir / "manifest.json"

    plan_csv = outputs_dir / "plan.csv"
    printable_guide = outputs_dir / "printable_guide.md"
    inventory_txt = outputs_dir / "inventory.txt"
    validation_report = outputs_dir / "validation_report.txt"

    # Preferences and intro
    preferences, pref_err = safe_read_json(input_pref_path)
    intro_text, intro_err = safe_read_text(input_intro_path)

    # Resource presence checks
    if ist_pdf.exists() and al_pdf.exists():
        scores["resources_pdfs_present"] = 1.0

    if ist_txt.exists() and al_txt.exists():
        # Also ensure non-empty
        ist_content, _ = safe_read_text(ist_txt)
        al_content, _ = safe_read_text(al_txt)
        if ist_content and al_content and ist_content.strip() and al_content.strip():
            scores["resources_texts_present"] = 1.0

    # Manifest structure validation
    manifest, man_err = load_manifest(manifest_path)
    manifest_by_id = {}
    if manifest is not None:
        # Check two entries and exact ids
        required_fields = {
            "id",
            "downloaded_from_domain",
            "source_type",
            "original_title",
            "file_name",
            "sha256",
            "extracted_snippets",
        }
        ids = set()
        struct_ok = True
        for obj in manifest:
            if not isinstance(obj, dict):
                struct_ok = False
                break
            if set(obj.keys()) != required_fields:
                struct_ok = False
                break
            ids.add(obj.get("id"))
        if struct_ok and ids == {"i_statement", "active_listening"} and len(manifest) == 2:
            # File names must correspond
            names_ok = True
            for obj in manifest:
                if obj["id"] == "i_statement" and obj["file_name"] != "i_statement.pdf":
                    names_ok = False
                if obj["id"] == "active_listening" and obj["file_name"] != "active_listening.pdf":
                    names_ok = False
            if names_ok:
                scores["manifest_json_valid_structure"] = 1.0
                manifest_by_id = {obj["id"]: obj for obj in manifest}

    # Manifest checksums
    if scores["manifest_json_valid_structure"] == 1.0:
        ist_sha = compute_sha256(ist_pdf)
        al_sha = compute_sha256(al_pdf)
        if ist_sha and al_sha:
            checksums_ok = (
                manifest_by_id["i_statement"]["sha256"] == ist_sha
                and manifest_by_id["active_listening"]["sha256"] == al_sha
            )
            if checksums_ok:
                scores["manifest_checksums_match"] = 1.0

    # Manifest domains and types
    if scores["manifest_json_valid_structure"] == 1.0:
        def domain_type_ok(domain: str, stype: str) -> bool:
            if not isinstance(domain, str) or not domain or "://" in domain or "/" in domain:
                return False
            domain_l = domain.lower()
            if domain_l.endswith(".gov") and stype == ".gov":
                return True
            if domain_l.endswith(".edu") and stype == ".edu":
                return True
            return False

        m_i = manifest_by_id.get("i_statement", {})
        m_a = manifest_by_id.get("active_listening", {})
        if domain_type_ok(m_i.get("downloaded_from_domain", ""), m_i.get("source_type", "")) and domain_type_ok(
            m_a.get("downloaded_from_domain", ""), m_a.get("source_type", "")
        ):
            scores["manifest_source_domains_types_valid"] = 1.0

    # Manifest snippets quality
    if scores["manifest_json_valid_structure"] == 1.0:
        ist_text, _ = safe_read_text(ist_txt)
        al_text, _ = safe_read_text(al_txt)
        snip_ok = False
        if ist_text and al_text:
            def snippets_check(entry: dict, text: str) -> bool:
                snips = entry.get("extracted_snippets")
                if not isinstance(snips, list) or len(snips) < 3:
                    return False
                t_low = text.lower()
                for s in snips:
                    if not isinstance(s, str):
                        return False
                    if len(s) > 140:
                        return False
                    if s.strip() == "":
                        return False
                    if s.lower() not in t_low:
                        return False
                return True

            snip_ok = snippets_check(manifest_by_id["i_statement"], ist_text) and snippets_check(
                manifest_by_id["active_listening"], al_text
            )
        if snip_ok:
            scores["manifest_snippets_quality"] = 1.0

    # Plan CSV checks
    header, rows = parse_csv_with_header(plan_csv)
    weeks_pref = None
    challenges = set()
    strengths = []
    rules = []
    if preferences and isinstance(preferences, dict):
        try:
            weeks_pref = int(preferences.get("schedule", {}).get("weeks"))
        except Exception:
            weeks_pref = None
        challenges = set(preferences.get("current_challenges", [])) if isinstance(preferences.get("current_challenges", []), list) else set()
        strengths = preferences.get("strengths", []) if isinstance(preferences.get("strengths", []), list) else []
        rules = preferences.get("communication_rules", []) if isinstance(preferences.get("communication_rules", []), list) else []

    expected_header = ["week", "theme", "exercise_title", "description", "source_id", "at_home_prompt"]
    if header is not None and rows is not None and header == expected_header and weeks_pref is not None and len(rows) == weeks_pref:
        scores["plan_csv_header_and_row_count"] = 1.0

    # Themes subset check
    if rows is not None:
        themes_ok = True
        for r in rows:
            theme = r.get("theme", "")
            if theme not in challenges:
                themes_ok = False
                break
        if weeks_pref is not None and len(rows) == weeks_pref and themes_ok:
            scores["plan_themes_valid"] = 1.0

    # Source IDs valid and min counts
    if rows is not None and len(rows) > 0:
        ids_ok = True
        counts = {"i_statement": 0, "active_listening": 0}
        for r in rows:
            sid = r.get("source_id", "")
            if sid not in counts:
                ids_ok = False
                break
            counts[sid] += 1
        if ids_ok and counts["i_statement"] >= 2 and counts["active_listening"] >= 2:
            scores["plan_source_ids_valid_and_min_counts"] = 1.0

    # Exercise title from original_title or extracted text heading/substrings
    if rows is not None and scores["manifest_json_valid_structure"] == 1.0:
        # Load extracted texts
        ist_text, _ = safe_read_text(ist_txt)
        al_text, _ = safe_read_text(al_txt)
        et_ok = True
        for r in rows:
            sid = r.get("source_id", "")
            etitle = r.get("exercise_title", "")
            manifest_entry = manifest_by_id.get(sid)
            if not manifest_entry or not isinstance(etitle, str) or etitle.strip() == "":
                et_ok = False
                break
            orig_title = manifest_entry.get("original_title", "")
            # Case-insensitive equality or substring of extracted text
            if etitle.strip().lower() == str(orig_title).strip().lower():
                continue
            # else check substring in corresponding text
            if sid == "i_statement":
                base_text = ist_text or ""
            else:
                base_text = al_text or ""
            if etitle.strip().lower() not in (base_text.lower()):
                et_ok = False
                break
        if et_ok:
            scores["plan_exercise_titles_source_based"] = 1.0

    # Description length and non-empty
    if rows is not None and len(rows) > 0:
        desc_ok = True
        for r in rows:
            d = r.get("description", "")
            if not isinstance(d, str) or d.strip() == "" or len(d) > 240:
                desc_ok = False
                break
        if desc_ok:
            scores["plan_descriptions_length_valid"] = 1.0

    # Prompts address names and reflect at least one strength
    if rows is not None and len(rows) > 0 and strengths:
        prompts_ok = True
        for r in rows:
            p = r.get("at_home_prompt", "")
            if not isinstance(p, str):
                prompts_ok = False
                break
            low = p.lower()
            if "alex" not in p or "jordan" not in p:
                prompts_ok = False
                break
            # check any strength substring appears (case-insensitive)
            if not any(s.lower() in low for s in strengths if isinstance(s, str)):
                prompts_ok = False
                break
        if prompts_ok:
            scores["plan_prompts_address_names_and_strength"] = 1.0

    # Rule incorporated in at least one row (look for exact rule substring in description or prompt)
    if rows is not None and rules:
        has_rule = False
        for r in rows:
            d = r.get("description", "") or ""
            p = r.get("at_home_prompt", "") or ""
            dlow = d.lower()
            plow = p.lower()
            for rule in rules:
                if isinstance(rule, str) and rule.strip():
                    if rule.lower() in dlow or rule.lower() in plow:
                        has_rule = True
                        break
            if has_rule:
                break
        if has_rule:
            scores["plan_rule_incorporated"] = 1.0

    # Printable guide checks
    guide_text, guide_err = safe_read_text(printable_guide)
    if guide_text is not None and isinstance(guide_text, str) and guide_text.strip():
        # Sections in order
        if contains_in_order(guide_text, ["Intro", "Rules We Agree On", "Weekly Plan", "Sources & Checksums"]):
            # Intro verbatim and rules listed
            intro_ok = False
            rules_ok = False
            if intro_text and intro_text in guide_text:
                intro_ok = True
            if rules and all((isinstance(r, str) and r in guide_text) for r in rules):
                rules_ok = True
            if intro_ok and rules_ok:
                scores["printable_guide_sections_and_intro_rules"] = 1.0

        # Weekly Plan enumerated with checkboxes and sources listed with domain and sha
        plan_sources_ok = False
        if rows is not None and manifest is not None:
            # Checkbox count
            checkbox_count = len(re.findall(r"\[\s*\]", guide_text))
            checkboxes_ok = checkbox_count >= len(rows)
            # For each row, ensure exercise_title and at_home_prompt appear
            rows_ok = True
            for r in rows:
                et = r.get("exercise_title", "") or ""
                ah = r.get("at_home_prompt", "") or ""
                if et.strip() == "" or ah.strip() == "" or (et not in guide_text) or (ah not in guide_text):
                    rows_ok = False
                    break
            # Sources & Checksums list includes original_title, domain, sha256 for each entry
            sources_ok = True
            for obj in manifest:
                ot = obj.get("original_title", "") or ""
                dom = obj.get("downloaded_from_domain", "") or ""
                sha = obj.get("sha256", "") or ""
                if not (ot and dom and sha and (ot in guide_text) and (dom in guide_text) and (sha in guide_text)):
                    sources_ok = False
                    break
            if checkboxes_ok and rows_ok and sources_ok:
                plan_sources_ok = True
        if plan_sources_ok:
            scores["printable_guide_weekly_plan_and_sources"] = 1.0

    # Inventory checks: must include filenames and sizes for downloads/resources and outputs
    inv_text, inv_err = safe_read_text(inventory_txt)
    if inv_text is not None and inv_text.strip():
        # For each expected file path ensure it's mentioned and some size digits are present on that line
        expected_files = [
            str(Path("downloads/resources/i_statement.pdf").as_posix()),
            str(Path("downloads/resources/active_listening.pdf").as_posix()),
            str(Path("downloads/resources/i_statement.txt").as_posix()),
            str(Path("downloads/resources/active_listening.txt").as_posix()),
            str(Path("downloads/resources/manifest.json").as_posix()),
            str(Path("outputs/plan.csv").as_posix()),
            str(Path("outputs/printable_guide.md").as_posix()),
            str(Path("outputs/inventory.txt").as_posix()),
            str(Path("outputs/validation_report.txt").as_posix()),
        ]
        lines = inv_text.splitlines()

        def line_has_size(l: str) -> bool:
            return re.search(r"\d+", l) is not None

        all_listed = True
        for ef in expected_files:
            found = False
            for ln in lines:
                if ef in ln and line_has_size(ln):
                    found = True
                    break
            if not found:
                all_listed = False
                break
        if all_listed:
            scores["inventory_lists_all_artifacts_with_sizes"] = 1.0

    # Validation report checks
    val_text, val_err = safe_read_text(validation_report)
    if val_text is not None and val_text.strip():
        # Recompute expected metrics
        # weeks
        weeks_val_ok = False
        if weeks_pref is not None:
            if str(weeks_pref) in val_text:
                weeks_val_ok = True
        # total rows
        total_rows_ok = False
        if rows is not None:
            if str(len(rows)) in val_text:
                total_rows_ok = True
        # counts per source_id
        counts_ok = False
        if rows is not None:
            cnts = {"i_statement": 0, "active_listening": 0}
            for r in rows:
                sid = r.get("source_id", "")
                if sid in cnts:
                    cnts[sid] += 1
            # find numbers next to labels
            def find_count(label: str, expected: int) -> bool:
                pattern = re.compile(rf"{re.escape(label)}[^\d]*([0-9]+)", flags=re.IGNORECASE)
                m = pattern.search(val_text)
                if not m:
                    return False
                try:
                    return int(m.group(1)) == expected
                except Exception:
                    return False

            counts_ok = find_count("i_statement", cnts["i_statement"]) and find_count("active_listening", cnts["active_listening"])
        # booleans for theme subset, both appear twice, rule included
        booleans_ok = False
        theme_subset_bool = scores["plan_themes_valid"] == 1.0
        both_twice_bool = scores["plan_source_ids_valid_and_min_counts"] == 1.0
        rule_included_bool = scores["plan_rule_incorporated"] == 1.0

        def bool_present(label_keywords: List[str], value: bool) -> bool:
            # find a line containing all label keywords and the boolean word
            target = "true" if value else "false"
            for line in val_text.splitlines():
                low = line.lower()
                if all(k in low for k in label_keywords) and target in low:
                    return True
            return False

        b1 = bool_present(["theme"], theme_subset_bool) or bool_present(["themes"], theme_subset_bool)
        b2 = bool_present(["source", "twice"], both_twice_bool)
        b3 = bool_present(["rule"], rule_included_bool) or bool_present(["rules"], rule_included_bool)
        if weeks_val_ok and total_rows_ok and counts_ok and (b1 and b2 and b3):
            scores["validation_report_values_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()