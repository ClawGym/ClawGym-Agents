import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        data = path.read_text(encoding="utf-8")
        return json.loads(data)
    except Exception:
        return None


def _find_highest_draft(drafts_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    if not drafts_dir.exists() or not drafts_dir.is_dir():
        return None, None
    highest_version = -1
    highest_path: Optional[Path] = None
    pattern = re.compile(r"^launch_email_v(\d+)\.md$")
    for p in drafts_dir.iterdir():
        if p.is_file():
            m = pattern.match(p.name)
            if m:
                try:
                    v = int(m.group(1))
                except ValueError:
                    continue
                if v > highest_version:
                    highest_version = v
                    highest_path = p
    if highest_path is None:
        return None, None
    # Extract subject line (first non-empty line starting with "Subject:")
    text = _safe_read_text(highest_path)
    if text is None:
        return highest_path, None
    subject_line = None
    for line in text.splitlines():
        if line.strip() == "":
            continue
        if line.startswith("Subject:"):
            subject_line = line.strip()
            break
        else:
            # If first non-empty line is not subject, still record if a later one is subject
            if subject_line is None and line.strip().startswith("Subject:"):
                subject_line = line.strip()
                break
    return highest_path, subject_line


def _parse_tagline(brand_tone_path: Path) -> Optional[str]:
    text = _safe_read_text(brand_tone_path)
    if text is None:
        return None
    # Look for a line "Tagline:" and take the next non-empty line as the tagline
    lines = text.splitlines()
    tagline: Optional[str] = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == "tagline:":
            # find next non-empty, non-whitespace line
            for j in range(idx + 1, len(lines)):
                nxt = lines[j].strip()
                if nxt != "":
                    tagline = nxt
                    break
            break
    return tagline


def _load_catalog(catalog_path: Path) -> Tuple[List[dict], List[dict]]:
    data = _safe_load_json(catalog_path)
    if not isinstance(data, list):
        return [], []
    new_launch = []
    non_new = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("new_launch") is True:
            new_launch.append(item)
        else:
            non_new.append(item)
    return new_launch, non_new


def _get_email_path(workspace: Path, segment: str) -> Path:
    if segment == "retailers":
        return workspace / "output" / "emails" / "retailers_launch_email.md"
    else:
        return workspace / "output" / "emails" / "horeca_launch_email.md"


def _safe_email_text(path: Path) -> Optional[str]:
    return _safe_read_text(path)


def _check_subject(email_text: str, expected_subject: Optional[str]) -> bool:
    if expected_subject is None:
        return False
    # Find first non-empty line
    for line in email_text.splitlines():
        if line.strip() == "":
            continue
        return line.strip() == expected_subject
    return False


def _check_placeholders_replaced(email_text: str) -> bool:
    return ("[PRODUCTS_GO_HERE]" not in email_text) and ("[CTA_GO_HERE]" not in email_text)


def _check_signature_and_tagline(email_text: str, tagline: Optional[str]) -> bool:
    if tagline is None:
        return False
    sig = "— The Bottling Crew"
    has_sig = sig in email_text
    tagline_count = email_text.count(tagline)
    return has_sig and (tagline_count == 1)


def _format_case_summary(pkg: dict) -> Optional[str]:
    try:
        size_ml = pkg["size_ml"]
        pack_type = pkg["pack_type"]
        case_qty = pkg["case_qty"]
        return f"{case_qty} x {size_ml} ml {pack_type}"
    except Exception:
        return None


def _format_packaging_phrase(pkg: dict) -> Optional[str]:
    cs = _format_case_summary(pkg)
    if cs is None:
        return None
    return f"case of {cs}"


def _expected_price_str(prod: dict) -> Optional[str]:
    try:
        currency = prod["currency"]
        price = prod["distributor_price_per_case"]
        return f"{currency} {price}"
    except Exception:
        return None


def _allergens_union(products: List[dict]) -> List[str]:
    s = set()
    for p in products:
        allergens = p.get("allergens", [])
        if isinstance(allergens, list):
            for a in allergens:
                if isinstance(a, str) and a.strip():
                    s.add(a.strip())
    return sorted(s)


def _check_products_presence(email_text: str, products: List[dict]) -> bool:
    # Ensure each product name appears at least once
    for p in products:
        name = p.get("name", "")
        if not name or name not in email_text:
            return False
    return True


def _check_no_nonlaunch_names(email_text: str, non_new_products: List[dict]) -> bool:
    for p in non_new_products:
        name = p.get("name", "")
        if name and name in email_text:
            return False
    return True


def _check_product_details(email_text: str, products: List[dict]) -> bool:
    # For each product, check marketing_blurb, packaging "case of ...", "shelf life: X days", and "CURRENCY PRICE"
    for p in products:
        blurb = p.get("marketing_blurb", "")
        if not blurb or blurb not in email_text:
            return False
        packages = p.get("packages", [])
        if not isinstance(packages, list) or len(packages) == 0 or not isinstance(packages[0], dict):
            return False
        pack_phrase = _format_packaging_phrase(packages[0])
        if pack_phrase is None or pack_phrase not in email_text:
            return False
        sld = p.get("shelf_life_days", None)
        try:
            sld_int = int(sld)
        except Exception:
            return False
        shelf_phrase = f"shelf life: {sld_int} days"
        if shelf_phrase not in email_text:
            return False
        price_str = _expected_price_str(p)
        if price_str is None or price_str not in email_text:
            return False
    return True


def _check_segment_notes(email_text: str, products: List[dict], segment: str) -> bool:
    # Check each product's segment note appears exactly once
    for p in products:
        notes = p.get("segment_notes", {})
        note = notes.get(segment, "")
        if not note:
            return False
        count = email_text.count(note)
        if count != 1:
            return False
    return True


def _check_greeting(email_text: str, expected_segment: str) -> bool:
    # Find the first non-empty line after the subject line
    lines = email_text.splitlines()
    subject_seen = False
    expected_start = None
    for line in lines:
        if line.strip() == "":
            continue
        if not subject_seen:
            # This is the subject
            subject_seen = True
            continue
        expected_start = line.strip()
        break
    if expected_start is None:
        return False
    # Must start with "Dear" and contain segment keyword
    if not expected_start.lower().startswith("dear"):
        return False
    if expected_segment == "retailers":
        return ("retail" in expected_start.lower()) and ("partner" in expected_start.lower())
    else:
        return ("horeca" in expected_start.lower()) and ("partner" in expected_start.lower())


def _check_allergen_advisory(email_text: str, expected_allergens: List[str]) -> bool:
    # If expected_allergens is empty, advisory should not be present; else must be present exactly once and before signature
    sig = "— The Bottling Crew"
    if len(expected_allergens) == 0:
        return ("Allergen advisory:" not in email_text)
    advisory = f"Allergen advisory: contains {', '.join(expected_allergens)}."
    count = email_text.count(advisory)
    if count != 1:
        return False
    # Check order: advisory should appear before signature if signature exists
    sig_idx = email_text.find(sig)
    adv_idx = email_text.find(advisory)
    if sig_idx != -1 and adv_idx != -1:
        return adv_idx < sig_idx
    return True


def _check_no_multiple_exclamations(email_text: str) -> bool:
    return "!!" not in email_text


def _normalize_path_for_compare(path_str: str) -> str:
    # Normalize to posix style
    return Path(path_str).as_posix()


def _endswith_draft_path(provided: str, expected_rel: str) -> bool:
    # Accept absolute or relative; compare by suffix
    p = _normalize_path_for_compare(provided)
    exp = _normalize_path_for_compare(expected_rel)
    return p.endswith(exp)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "retailers_email_present": 0.0,
        "horeca_email_present": 0.0,
        "selection_json_present": 0.0,
        "base_draft_selection_correct": 0.0,
        "subject_preserved_retailers": 0.0,
        "subject_preserved_horeca": 0.0,
        "placeholders_replaced_retailers": 0.0,
        "placeholders_replaced_horeca": 0.0,
        "signature_and_tagline_retailers": 0.0,
        "signature_and_tagline_horeca": 0.0,
        "products_included_retailers": 0.0,
        "products_included_horeca": 0.0,
        "no_nonlaunch_products_retailers": 0.0,
        "no_nonlaunch_products_horeca": 0.0,
        "product_details_complete_retailers": 0.0,
        "product_details_complete_horeca": 0.0,
        "segment_notes_present_retailers": 0.0,
        "segment_notes_present_horeca": 0.0,
        "greeting_segment_appropriate_retailers": 0.0,
        "greeting_segment_appropriate_horeca": 0.0,
        "allergen_advisory_correct_retailers": 0.0,
        "allergen_advisory_correct_horeca": 0.0,
        "selection_json_products_match": 0.0,
        "selection_json_allergen_flag_correct": 0.0,
        "tone_no_multiple_exclamations_retailers": 0.0,
        "tone_no_multiple_exclamations_horeca": 0.0,
    }

    # Expected inputs
    drafts_dir = workspace / "input" / "drafts"
    catalog_path = workspace / "input" / "catalog.json"
    brand_tone_path = workspace / "input" / "brand_tone.md"

    # Determine highest draft and subject
    highest_draft_path, expected_subject = _find_highest_draft(drafts_dir)

    # Parse tagline
    tagline = _parse_tagline(brand_tone_path)

    # Load catalog
    new_launch_products, non_new_products = _load_catalog(catalog_path)

    # Allergens union
    allergens_union = _allergens_union(new_launch_products)
    expected_advisory_present = len(allergens_union) > 0

    # Output files
    retailers_path = _get_email_path(workspace, "retailers")
    horeca_path = _get_email_path(workspace, "horeca")
    selection_json_path = workspace / "output" / "checks" / "selection.json"

    retailers_text = _safe_email_text(retailers_path) if retailers_path.exists() else None
    horeca_text = _safe_email_text(horeca_path) if horeca_path.exists() else None

    if retailers_text is not None:
        scores["retailers_email_present"] = 1.0
    if horeca_text is not None:
        scores["horeca_email_present"] = 1.0
    if selection_json_path.exists() and _safe_load_json(selection_json_path) is not None:
        scores["selection_json_present"] = 1.0

    # Base draft selection correctness
    if highest_draft_path is not None:
        expected_rel = "input/drafts/" + highest_draft_path.name
    else:
        expected_rel = None

    selection_data = _safe_load_json(selection_json_path) if selection_json_path.exists() else None
    if selection_data and isinstance(selection_data, dict) and expected_rel is not None:
        bd_used = selection_data.get("base_draft_used")
        if isinstance(bd_used, str) and _endswith_draft_path(bd_used, expected_rel):
            scores["base_draft_selection_correct"] = 1.0

    # Subject preserved
    if retailers_text is not None and expected_subject is not None:
        if _check_subject(retailers_text, expected_subject):
            scores["subject_preserved_retailers"] = 1.0
    if horeca_text is not None and expected_subject is not None:
        if _check_subject(horeca_text, expected_subject):
            scores["subject_preserved_horeca"] = 1.0

    # Placeholders replaced
    if retailers_text is not None:
        if _check_placeholders_replaced(retailers_text):
            scores["placeholders_replaced_retailers"] = 1.0
    if horeca_text is not None:
        if _check_placeholders_replaced(horeca_text):
            scores["placeholders_replaced_horeca"] = 1.0

    # Signature and tagline
    if retailers_text is not None:
        if _check_signature_and_tagline(retailers_text, tagline):
            scores["signature_and_tagline_retailers"] = 1.0
    if horeca_text is not None:
        if _check_signature_and_tagline(horeca_text, tagline):
            scores["signature_and_tagline_horeca"] = 1.0

    # Products included / excluded
    if retailers_text is not None and new_launch_products:
        if _check_products_presence(retailers_text, new_launch_products):
            scores["products_included_retailers"] = 1.0
        if _check_no_nonlaunch_names(retailers_text, non_new_products):
            scores["no_nonlaunch_products_retailers"] = 1.0
    if horeca_text is not None and new_launch_products:
        if _check_products_presence(horeca_text, new_launch_products):
            scores["products_included_horeca"] = 1.0
        if _check_no_nonlaunch_names(horeca_text, non_new_products):
            scores["no_nonlaunch_products_horeca"] = 1.0

    # Product details completeness
    if retailers_text is not None and new_launch_products:
        if _check_product_details(retailers_text, new_launch_products):
            scores["product_details_complete_retailers"] = 1.0
    if horeca_text is not None and new_launch_products:
        if _check_product_details(horeca_text, new_launch_products):
            scores["product_details_complete_horeca"] = 1.0

    # Segment notes presence
    if retailers_text is not None and new_launch_products:
        if _check_segment_notes(retailers_text, new_launch_products, "retailers"):
            scores["segment_notes_present_retailers"] = 1.0
    if horeca_text is not None and new_launch_products:
        if _check_segment_notes(horeca_text, new_launch_products, "horeca"):
            scores["segment_notes_present_horeca"] = 1.0

    # Greeting checks
    if retailers_text is not None:
        if _check_greeting(retailers_text, "retailers"):
            scores["greeting_segment_appropriate_retailers"] = 1.0
    if horeca_text is not None:
        if _check_greeting(horeca_text, "horeca"):
            scores["greeting_segment_appropriate_horeca"] = 1.0

    # Allergen advisory presence and order
    if retailers_text is not None:
        if _check_allergen_advisory(retailers_text, allergens_union):
            scores["allergen_advisory_correct_retailers"] = 1.0
    if horeca_text is not None:
        if _check_allergen_advisory(horeca_text, allergens_union):
            scores["allergen_advisory_correct_horeca"] = 1.0

    # Tone check - no multiple exclamations
    if retailers_text is not None:
        if _check_no_multiple_exclamations(retailers_text):
            scores["tone_no_multiple_exclamations_retailers"] = 1.0
    if horeca_text is not None:
        if _check_no_multiple_exclamations(horeca_text):
            scores["tone_no_multiple_exclamations_horeca"] = 1.0

    # Selection JSON products match checks
    if selection_data and isinstance(selection_data, dict) and new_launch_products:
        ok = True
        segs = selection_data.get("segments")
        if segs != ["retailers", "horeca"]:
            ok = False
        ip = selection_data.get("included_products")
        if not isinstance(ip, list) or len(ip) != len(new_launch_products):
            ok = False
        else:
            # map by name
            expected_by_name = {p["name"]: p for p in new_launch_products if isinstance(p, dict) and "name" in p}
            for item in ip:
                if not isinstance(item, dict):
                    ok = False
                    break
                name = item.get("name")
                if name not in expected_by_name:
                    ok = False
                    break
                exp = expected_by_name[name]
                # currency
                if item.get("currency") != exp.get("currency"):
                    ok = False
                    break
                # price type and value
                if not isinstance(item.get("distributor_price_per_case"), (int, float)):
                    ok = False
                    break
                if item.get("distributor_price_per_case") != exp.get("distributor_price_per_case"):
                    ok = False
                    break
                # case_summary
                packages = exp.get("packages", [])
                if not packages or not isinstance(packages[0], dict):
                    ok = False
                    break
                expected_case_summary = _format_case_summary(packages[0])
                if item.get("case_summary") != expected_case_summary:
                    ok = False
                    break
                # shelf life
                if item.get("shelf_life_days") != exp.get("shelf_life_days"):
                    ok = False
                    break
                # allergens
                alloys = item.get("allergens")
                if alloys != exp.get("allergens"):
                    ok = False
                    break
                # segments map
                seg_map = item.get("segments")
                if not isinstance(seg_map, dict) or seg_map.get("retailers") is not True or seg_map.get("horeca") is not True:
                    ok = False
                    break
        if ok:
            scores["selection_json_products_match"] = 1.0

        # Allergen advisory flag correctness
        flag = selection_data.get("allergen_advisory_added")
        expected_flag = expected_advisory_present
        if isinstance(flag, bool) and flag == expected_flag:
            scores["selection_json_allergen_flag_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()