import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()  # fallback
        except Exception:
            return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(_read_text(path) or "")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
            return header, rows
    except Exception:
        try:
            with path.open("r", newline="") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames
                rows = list(reader)
                return header, rows
        except Exception:
            return None, None


def _parse_light_a_expected(html_text: str) -> Optional[dict]:
    if not html_text:
        return None
    # Model from <h1> tag
    model_match = re.search(r"<h1>\s*([^<]+)\s*</h1>", html_text, re.IGNORECASE)
    model = model_match.group(1).strip() if model_match else None

    lumens = None
    m = re.search(r"Lumens:\s*(\d+)", html_text, re.IGNORECASE)
    if m:
        lumens = int(m.group(1))

    runtime = None
    m = re.search(r"Runtime:\s*([0-9.\-\s]+)hours", html_text, re.IGNORECASE)
    if m:
        range_text = m.group(1).strip()
        range_text = re.sub(r"\s+", "", range_text)
        if "-" in range_text:
            parts = range_text.split("-")
            runtime = f"{parts[0]}-{parts[1]}"
        else:
            runtime = range_text

    weight_g = None
    m = re.search(r"Weight:\s*(\d+)\s*g", html_text, re.IGNORECASE)
    if m:
        weight_g = int(m.group(1))

    waterproof = None
    m = re.search(r"Waterproof:\s*(IPX\d+)", html_text, re.IGNORECASE)
    if m:
        waterproof = m.group(1)

    warranty_years = None
    m = re.search(r"Warranty:\s*(\d+)\s*years", html_text, re.IGNORECASE)
    if m:
        warranty_years = int(m.group(1))

    price = None
    m = re.search(r"Price:\s*£\s*([0-9]+(?:\.[0-9]+)?)", html_text, re.IGNORECASE)
    if m:
        try:
            price = float(m.group(1))
        except Exception:
            price = None

    charging = None
    m = re.search(r"Charging:\s*([^\n<]+)", html_text, re.IGNORECASE)
    if m:
        charging = m.group(1).strip()

    # Modes from notes: "has steady + pulse"
    modes = []
    if re.search(r"\bsteady\b", html_text, re.IGNORECASE):
        modes.append("steady")
    if re.search(r"\bpulse\b", html_text, re.IGNORECASE):
        modes.append("pulse")
    modes_str = ",".join(modes) if modes else ""

    if None in (model, lumens, runtime, weight_g, waterproof, warranty_years, price, charging):
        return None

    return {
        "model": model,
        "lumens": lumens,
        "runtime_hours_range": runtime,
        "weight_g": weight_g,
        "waterproof_rating": waterproof,
        "warranty_years": warranty_years,
        "price_gbp": price,
        "charging": charging,
        "modes": modes_str,
        "source_file": "input/products/light_a.html",
    }


def _parse_light_b_expected(md_text: str) -> Optional[dict]:
    if not md_text:
        return None
    # Model from first heading
    model_match = re.search(r"^#\s*([^\n]+)", md_text, re.MULTILINE)
    model = model_match.group(1).strip() if model_match else None

    lumens = None
    m = re.search(r"Lumens:\s*(\d+)", md_text, re.IGNORECASE)
    if m:
        lumens = int(m.group(1))

    runtime = None
    m = re.search(r"Runtime:\s*([0-9.]+)\s*-\s*([0-9.]+)\s*hours", md_text, re.IGNORECASE)
    if m:
        runtime = f"{m.group(1)}-{m.group(2)}"

    weight_g = None
    m = re.search(r"Weight:\s*(\d+)\s*g?", md_text, re.IGNORECASE)
    if m:
        weight_g = int(m.group(1))

    waterproof = None
    m = re.search(r"Waterproof\s*rating:\s*(IPX\d+)", md_text, re.IGNORECASE)
    if m:
        waterproof = m.group(1)

    warranty_years = None
    m = re.search(r"Warranty:\s*(\d+)\s*years", md_text, re.IGNORECASE)
    if m:
        warranty_years = int(m.group(1))

    price = None
    m = re.search(r"Price\s*\(GBP\):\s*([0-9]+(?:\.[0-9]+)?)", md_text, re.IGNORECASE)
    if m:
        try:
            price = float(m.group(1))
        except Exception:
            price = None

    charging = None
    m = re.search(r"Charging:\s*([^\n]+)", md_text, re.IGNORECASE)
    if m:
        charging = m.group(1).strip()

    modes_str = ""
    m = re.search(r"Modes:\s*([^\n]+)", md_text, re.IGNORECASE)
    if m:
        modes_raw = m.group(1).strip()
        # Normalize to comma-separated terms
        tokens = re.split(r"[\/\+\-,]\s*", modes_raw.replace("+", ",").replace("/", ","))
        tokens = [t.strip().lower() for t in tokens if t.strip()]
        # Remove duplicates while keeping order
        seen = set()
        norm = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                norm.append(t)
        modes_str = ",".join(norm)

    if None in (model, lumens, runtime, weight_g, waterproof, warranty_years, price, charging):
        return None

    return {
        "model": model,
        "lumens": lumens,
        "runtime_hours_range": runtime,
        "weight_g": weight_g,
        "waterproof_rating": waterproof,
        "warranty_years": warranty_years,
        "price_gbp": price,
        "charging": charging,
        "modes": modes_str,
        "source_file": "input/products/light_b.md",
    }


def _compute_commute_summary_expected(csv_text: str) -> Optional[dict]:
    if not csv_text:
        return None
    try:
        rows = []
        reader = csv.DictReader(csv_text.splitlines())
        for r in reader:
            rows.append(r)
    except Exception:
        return None
    total = len(rows)
    after_dark = 0
    rain = 0
    vis = 0
    notes_list = []
    seen_notes = set()
    for r in rows:
        tod = (r.get("time_of_day") or "").strip()
        cond = (r.get("conditions") or "").strip()
        issues = (r.get("issues") or "").strip()
        if tod.lower() != "day":
            after_dark += 1
        if "rain" in cond.lower():
            rain += 1
        iss_lower = issues.lower()
        if ("invisible" in iss_lower) or ("pulled out" in iss_lower):
            vis += 1
        if issues:
            if issues not in seen_notes:
                seen_notes.add(issues)
                notes_list.append(issues)
    return {
        "total_rides": total,
        "after_dark_rides": after_dark,
        "rain_rides": rain,
        "visibility_incident_rides": vis,
        "notes": notes_list,
    }


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!?\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _sentence_mentions_budget(sentence: str) -> bool:
    if re.search(r"\bbudget\b", sentence, re.IGNORECASE):
        if re.search(r"\b(under|within|meets|below|over|exceed|exceeds|above)\b", sentence, re.IGNORECASE):
            return True
    return False


def _sentence_mentions_weight(sentence: str) -> bool:
    # consider variations that indicate weight evaluation
    if re.search(r"\b(weight|weighs?|grams?|g|lighter|heavier|light|heavy)\b", sentence, re.IGNORECASE):
        return True
    return False


def _contains_keywords_near_number(text: str, number: int, keywords: List[str], window: int = 30) -> bool:
    # search for digits and keywords within a window
    if not text:
        return False
    text_l = text.lower()
    # find all positions of the number in text
    num_str = str(number)
    positions = [m.start() for m in re.finditer(re.escape(num_str), text_l)]
    if not positions:
        return False
    # for each position, check if any keyword exists within +/- window
    for pos in positions:
        start = max(0, pos - window)
        end = min(len(text_l), pos + window)
        snippet = text_l[start:end]
        for kw in keywords:
            if kw.lower() in snippet:
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_csv_exists": 0.0,
        "extracted_csv_header_exact": 0.0,
        "extracted_csv_row_count_two": 0.0,
        "extracted_csv_light_a_values": 0.0,
        "extracted_csv_light_b_values": 0.0,
        "extracted_csv_modes_light_a_included": 0.0,
        "extracted_csv_modes_light_b_included": 0.0,
        "summary_json_exists": 0.0,
        "summary_json_counts_correct": 0.0,
        "summary_json_notes_correct": 0.0,
        "recommendation_exists": 0.0,
        "recommendation_mentions_both_models": 0.0,
        "recommendation_budget_statements_per_model": 0.0,
        "recommendation_weight_statements_per_model": 0.0,
        "recommendation_tradeoffs_brightness": 0.0,
        "recommendation_tradeoffs_waterproof": 0.0,
        "recommendation_tradeoffs_warranty": 0.0,
        "recommendation_references_commute_counts": 0.0,
        "recommendation_verdict_line_valid": 0.0,
        "whatsapp_exists": 0.0,
        "whatsapp_length_valid": 0.0,
        "whatsapp_includes_chosen_model": 0.0,
        "whatsapp_references_commute_counts": 0.0,
        "whatsapp_no_links": 0.0,
        "cross_consistency_message_verdict_match": 0.0,
    }

    # Expected product values derived from input files
    light_a_path = workspace / "input" / "products" / "light_a.html"
    light_b_path = workspace / "input" / "products" / "light_b.md"
    light_a_text = _read_text(light_a_path)
    light_b_text = _read_text(light_b_path)
    expected_a = _parse_light_a_expected(light_a_text) if light_a_text is not None else None
    expected_b = _parse_light_b_expected(light_b_text) if light_b_text is not None else None

    # Check extracted CSV
    csv_path = workspace / "output" / "extracted" / "lights.csv"
    header, rows = _read_csv_dicts(csv_path)
    if header is not None and rows is not None:
        scores["extracted_csv_exists"] = 1.0
        expected_header = [
            "model",
            "lumens",
            "runtime_hours_range",
            "weight_g",
            "waterproof_rating",
            "warranty_years",
            "price_gbp",
            "charging",
            "modes",
            "source_file",
        ]
        if header == expected_header:
            scores["extracted_csv_header_exact"] = 1.0
        if len(rows) == 2:
            scores["extracted_csv_row_count_two"] = 1.0

        # Map by model for validation (exact match)
        by_model = {r.get("model", ""): r for r in rows if r.get("model")}
        # Validate Light A
        if expected_a is not None and expected_a.get("model") in by_model:
            ra = by_model[expected_a["model"]]
            try:
                ok = True
                ok = ok and int(ra.get("lumens", "")) == expected_a["lumens"]
                ok = ok and (ra.get("runtime_hours_range", "") == expected_a["runtime_hours_range"])
                ok = ok and int(ra.get("weight_g", "")) == expected_a["weight_g"]
                ok = ok and (ra.get("waterproof_rating", "") == expected_a["waterproof_rating"])
                ok = ok and int(ra.get("warranty_years", "")) == expected_a["warranty_years"]
                ok = ok and _float_equal(float(ra.get("price_gbp", "")), expected_a["price_gbp"])
                ok = ok and (ra.get("charging", "") == expected_a["charging"])
                ok = ok and (ra.get("source_file", "") == expected_a["source_file"])
                # modes check separately
                if ok:
                    scores["extracted_csv_light_a_values"] = 1.0
                # Modes: require inclusion if mentioned in input
                modes_a = ra.get("modes", "").lower().replace(" ", "")
                expected_modes_a = expected_a["modes"]
                if expected_modes_a:
                    # must contain both steady and pulse, and not strobe
                    if ("steady" in modes_a) and ("pulse" in modes_a) and ("strobe" not in modes_a):
                        scores["extracted_csv_modes_light_a_included"] = 1.0
                else:
                    # if not mentioned expectedly, allow blank
                    if modes_a == "":
                        scores["extracted_csv_modes_light_a_included"] = 1.0
            except Exception:
                pass

        # Validate Light B
        if expected_b is not None and expected_b.get("model") in by_model:
            rb = by_model[expected_b["model"]]
            try:
                ok = True
                ok = ok and int(rb.get("lumens", "")) == expected_b["lumens"]
                ok = ok and (rb.get("runtime_hours_range", "") == expected_b["runtime_hours_range"])
                ok = ok and int(rb.get("weight_g", "")) == expected_b["weight_g"]
                ok = ok and (rb.get("waterproof_rating", "") == expected_b["waterproof_rating"])
                ok = ok and int(rb.get("warranty_years", "")) == expected_b["warranty_years"]
                ok = ok and _float_equal(float(rb.get("price_gbp", "")), expected_b["price_gbp"])
                ok = ok and (rb.get("charging", "") == expected_b["charging"])
                ok = ok and (rb.get("source_file", "") == expected_b["source_file"])
                if ok:
                    scores["extracted_csv_light_b_values"] = 1.0
                # modes check: should include expected terms
                modes_b = rb.get("modes", "").lower().replace(" ", "")
                needed = ["high", "med", "low", "strobe"]
                if all(n in modes_b for n in needed):
                    scores["extracted_csv_modes_light_b_included"] = 1.0
            except Exception:
                pass

    # Check summary JSON
    summary_path = workspace / "output" / "analysis" / "commute_summary.json"
    summary_obj = _load_json(summary_path)
    if summary_obj is not None and isinstance(summary_obj, dict):
        scores["summary_json_exists"] = 1.0
        # compute expected from input
        commute_csv_path = workspace / "input" / "rides" / "commute_log.csv"
        commute_csv_text = _read_text(commute_csv_path)
        expected_summary = _compute_commute_summary_expected(commute_csv_text) if commute_csv_text is not None else None
        required_keys = {"total_rides", "after_dark_rides", "rain_rides", "visibility_incident_rides", "notes"}
        if expected_summary is not None and set(summary_obj.keys()) >= required_keys:
            counts_ok = (
                summary_obj.get("total_rides") == expected_summary["total_rides"]
                and summary_obj.get("after_dark_rides") == expected_summary["after_dark_rides"]
                and summary_obj.get("rain_rides") == expected_summary["rain_rides"]
                and summary_obj.get("visibility_incident_rides") == expected_summary["visibility_incident_rides"]
            )
            if counts_ok:
                scores["summary_json_counts_correct"] = 1.0
            notes_ok = summary_obj.get("notes") == expected_summary["notes"]
            if notes_ok:
                scores["summary_json_notes_correct"] = 1.0

    # Recommendation text checks
    rec_path = workspace / "output" / "review" / "light_recommendation.txt"
    rec_text = _read_text(rec_path)
    chosen_model = None
    if rec_text is not None:
        scores["recommendation_exists"] = 1.0
        # Mentions both models
        if expected_a and expected_b:
            if (expected_a["model"] in rec_text) and (expected_b["model"] in rec_text):
                scores["recommendation_mentions_both_models"] = 1.0

        # Budget and weight statements for each model
        sentences = _split_sentences(rec_text)
        budget_mentions = {expected_a["model"]: False, expected_b["model"]: False} if (expected_a and expected_b) else {}
        weight_mentions = {expected_a["model"]: False, expected_b["model"]: False} if (expected_a and expected_b) else {}
        for s in sentences:
            for m in list(budget_mentions.keys()):
                if m in s and _sentence_mentions_budget(s):
                    budget_mentions[m] = True
            for m in list(weight_mentions.keys()):
                if m in s and _sentence_mentions_weight(s):
                    weight_mentions[m] = True
        if budget_mentions:
            if all(budget_mentions.values()):
                scores["recommendation_budget_statements_per_model"] = 1.0
        if weight_mentions:
            if all(weight_mentions.values()):
                scores["recommendation_weight_statements_per_model"] = 1.0

        # Trade-offs mentions
        if re.search(r"\blumens\b|\bbright\b|\bbrighter\b|\bbrightness\b|800|1000", rec_text, re.IGNORECASE):
            scores["recommendation_tradeoffs_brightness"] = 1.0
        if re.search(r"\bIPX5\b|\bIPX6\b|\bwaterproof\b", rec_text, re.IGNORECASE):
            scores["recommendation_tradeoffs_waterproof"] = 1.0
        if re.search(r"\bwarranty\b|\byears?\b", rec_text, re.IGNORECASE):
            scores["recommendation_tradeoffs_warranty"] = 1.0

        # References commute counts: accept if at least one key count with keyword present
        # Compute expected counts if possible
        after_dark_count = None
        rain_count = None
        if summary_obj and isinstance(summary_obj, dict):
            after_dark_count = summary_obj.get("after_dark_rides")
            rain_count = summary_obj.get("rain_rides")
        else:
            commute_csv_path = workspace / "input" / "rides" / "commute_log.csv"
            commute_csv_text = _read_text(commute_csv_path)
            expected_summary = _compute_commute_summary_expected(commute_csv_text) if commute_csv_text is not None else None
            if expected_summary:
                after_dark_count = expected_summary["after_dark_rides"]
                rain_count = expected_summary["rain_rides"]
        cited = False
        if isinstance(after_dark_count, int):
            if _contains_keywords_near_number(rec_text, after_dark_count, ["after dark", "after-dark", "night", "dawn"]):
                cited = True
        if not cited and isinstance(rain_count, int):
            if _contains_keywords_near_number(rec_text, rain_count, ["rain", "rainy"]):
                cited = True
        if cited:
            scores["recommendation_references_commute_counts"] = 1.0

        # Verdict line
        lines = [ln.strip() for ln in rec_text.splitlines() if ln.strip()]
        if lines:
            last_line = lines[-1]
            verdict_match = re.match(r"^Verdict:\s*(.+)$", last_line)
            if verdict_match:
                model = verdict_match.group(1).strip()
                if expected_a and expected_b and model in (expected_a["model"], expected_b["model"]):
                    chosen_model = model
                    scores["recommendation_verdict_line_valid"] = 1.0

    # WhatsApp message checks
    wa_path = workspace / "output" / "messages" / "whatsapp_message.txt"
    wa_text = _read_text(wa_path)
    if wa_text is not None:
        scores["whatsapp_exists"] = 1.0
        # Length in words <= 120
        words = re.findall(r"\S+", wa_text.strip())
        if len(words) <= 120:
            scores["whatsapp_length_valid"] = 1.0
        # Include chosen model
        if chosen_model and chosen_model in wa_text:
            scores["whatsapp_includes_chosen_model"] = 1.0
        # References commute counts (at least one)
        # Use same detection as recommendation but broader keywords
        cited = False
        # Compute counts
        after_dark_count = None
        rain_count = None
        vis_count = None
        total_count = None
        if summary_obj and isinstance(summary_obj, dict):
            after_dark_count = summary_obj.get("after_dark_rides")
            rain_count = summary_obj.get("rain_rides")
            vis_count = summary_obj.get("visibility_incident_rides")
            total_count = summary_obj.get("total_rides")
        else:
            commute_csv_path = workspace / "input" / "rides" / "commute_log.csv"
            commute_csv_text = _read_text(commute_csv_path)
            expected_summary = _compute_commute_summary_expected(commute_csv_text) if commute_csv_text is not None else None
            if expected_summary:
                after_dark_count = expected_summary["after_dark_rides"]
                rain_count = expected_summary["rain_rides"]
                vis_count = expected_summary["visibility_incident_rides"]
                total_count = expected_summary["total_rides"]
        if isinstance(after_dark_count, int) and _contains_keywords_near_number(wa_text, after_dark_count, ["after dark", "after-dark", "night", "dawn", "rides"]):
            cited = True
        if isinstance(rain_count, int) and _contains_keywords_near_number(wa_text, rain_count, ["rain", "rainy", "rides"]):
            cited = True or cited
        if isinstance(vis_count, int) and _contains_keywords_near_number(wa_text, vis_count, ["visibility", "invisible", "pulled", "rides"]):
            cited = True or cited
        if isinstance(total_count, int) and _contains_keywords_near_number(wa_text, total_count, ["rides"]):
            cited = True or cited
        if cited:
            scores["whatsapp_references_commute_counts"] = 1.0
        # No links
        if not re.search(r"http[s]?://|www\.", wa_text, re.IGNORECASE):
            scores["whatsapp_no_links"] = 1.0

        # Consistency with verdict
        if chosen_model and chosen_model in wa_text:
            scores["cross_consistency_message_verdict_match"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()