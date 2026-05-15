import csv
import json
import math
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_yaml_simple(path: Path) -> Optional[Dict[str, str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*"(.*)"\s*$', line)
        if m:
            key, val = m.group(1), m.group(2)
            data[key] = val
        else:
            # Try unquoted simple values
            m2 = re.match(r'^([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$', line)
            if m2:
                key, val = m2.group(1), m2.group(2)
                data[key] = val.strip()
    return data


def _safe_read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"\b\w+\b", text.lower())


def _word_count(text: str) -> int:
    return len(_tokenize_words(text))


def _split_sentences(text: str) -> List[str]:
    # Simple sentence split on ., !, ?
    parts = re.split(r"[.!?]", text)
    sentences = [s.strip() for s in parts if re.search(r"\w", s)]
    return sentences


def _parse_report_sections(md_text: str) -> Tuple[List[str], Dict[str, str]]:
    """
    Returns (ordered_titles_lower, sections_dict_lower_to_content)
    """
    lines = md_text.splitlines()
    sections: Dict[str, List[str]] = {}
    order: List[str] = []
    current_title: Optional[str] = None
    for line in lines:
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", line)
        if m:
            title = m.group(1).strip()
            title_lower = title.lower()
            current_title = title_lower
            if title_lower not in sections:
                sections[title_lower] = []
                order.append(title_lower)
            continue
        if current_title is not None:
            sections[current_title].append(line)
    content_strs: Dict[str, str] = {k: "\n".join(v).strip() for k, v in sections.items()}
    return order, content_strs


def _group_scene_metrics(rows: List[Dict[str, str]]) -> Dict[Tuple[str, int], List[Dict[str, str]]]:
    groups: Dict[Tuple[str, int], List[Dict[str, str]]] = {}
    for r in rows:
        try:
            film = r["film"]
            year = int(r["year"])
            asl = float(r["avg_shot_length_sec"])
            color = float(r["color_temp_k"])
            sat = float(r["saturation"])
            bri = float(r["brightness"])
            sent = float(r["dialog_sentiment"])
            interior_exterior = r["interior_exterior"]
        except Exception:
            # Skip malformed row entirely
            continue
        key = (film, year)
        r2 = {
            "film": film,
            "year": year,
            "avg_shot_length_sec": asl,
            "color_temp_k": color,
            "saturation": sat,
            "brightness": bri,
            "dialog_sentiment": sent,
            "interior_exterior": interior_exterior,
        }
        groups.setdefault(key, []).append(r2)
    return groups


def _mean(vals: List[float]) -> float:
    if not vals:
        return float("nan")
    return sum(vals) / len(vals)


def _std_pop(vals: List[float]) -> float:
    n = len(vals)
    if n == 0:
        return float("nan")
    mu = _mean(vals)
    return math.sqrt(sum((x - mu) ** 2 for x in vals) / n)


def _std_sample(vals: List[float]) -> float:
    n = len(vals)
    if n <= 1:
        return 0.0
    mu = _mean(vals)
    return math.sqrt(sum((x - mu) ** 2 for x in vals) / (n - 1))


def _round_half_up(n: float) -> int:
    d = Decimal(str(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def _compute_expected_summary(groups: Dict[Tuple[str, int], List[Dict[str, str]]]) -> Dict[Tuple[str, int], Dict[str, object]]:
    expected: Dict[Tuple[str, int], Dict[str, object]] = {}
    for key, items in groups.items():
        asls = [it["avg_shot_length_sec"] for it in items]
        inter_asls = [it["avg_shot_length_sec"] for it in items if str(it["interior_exterior"]).lower().startswith("interior")]
        exter_asls = [it["avg_shot_length_sec"] for it in items if str(it["interior_exterior"]).lower().startswith("exterior")]
        colors = [it["color_temp_k"] for it in items]
        sats = [it["saturation"] for it in items]
        bris = [it["brightness"] for it in items]
        sents = [it["dialog_sentiment"] for it in items]

        mean_asl = round(_mean(asls), 2)
        std_asl_pop = round(_std_pop(asls), 2)
        std_asl_sample = round(_std_sample(asls), 2)
        inter_mean = round(_mean(inter_asls), 2) if inter_asls else float("nan")
        exter_mean = round(_mean(exter_asls), 2) if exter_asls else float("nan")
        mean_color = _mean(colors)
        mean_color_bankers = int(round(mean_color))
        mean_color_halfup = _round_half_up(mean_color)
        mean_sat = round(_mean(sats), 2)
        mean_bri = round(_mean(bris), 2)
        mean_sent = round(_mean(sents), 2)
        expected[key] = {
            "film": key[0],
            "year": key[1],
            "n_scenes": len(items),
            "mean_shot_length_sec": mean_asl,
            "std_shot_length_sec_pop": std_asl_pop,
            "std_shot_length_sec_sample": std_asl_sample,
            "interior_mean_shot_length_sec": inter_mean,
            "exterior_mean_shot_length_sec": exter_mean,
            "mean_color_temp_k_bankers": mean_color_bankers,
            "mean_color_temp_k_halfup": mean_color_halfup,
            "mean_saturation": mean_sat,
            "mean_brightness": mean_bri,
            "mean_dialog_sentiment": mean_sent,
        }
    return expected


def _parse_summary_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    return _safe_read_csv_dicts(path)


def _parse_bullets(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        if re.match(r"^\s*([-*•])\s+", line):
            bullets.append(line.strip())
    return bullets


def _find_specific_bullet(bullets: List[str], kind: str) -> List[Tuple[str, str, str]]:
    """
    kind: 'shortest_asl' or 'highest_color'
    Returns list of tuples (full_line, film, value_str)
    """
    found = []
    if kind == "shortest_asl":
        pat = re.compile(r"^\s*[-*•]\s*Shortest mean shot length:\s*(.+?)\s*\(\s*([0-9]+(?:\.[0-9]+)?)s\s*\)\s*$", re.IGNORECASE)
    else:
        pat = re.compile(r"^\s*[-*•]\s*Highest mean color temperature:\s*(.+?)\s*\(\s*([0-9]+)K\s*\)\s*$", re.IGNORECASE)
    for b in bullets:
        m = pat.match(b)
        if m:
            film = m.group(1).strip()
            val = m.group(2).strip()
            found.append((b, film, val))
    return found


def _float_eq(a: float, b: float, tol: float = 1e-2) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_csv_structure": 0.0,
        "summary_grouping_and_coverage": 0.0,
        "summary_values_accuracy": 0.0,
        "report_section_order": 0.0,
        "abstract_length_and_originality": 0.0,
        "methods_description_quality": 0.0,
        "results_bullet_count": 0.0,
        "results_shortest_mean_shot_length_correct": 0.0,
        "results_highest_mean_color_temp_correct": 0.0,
        "results_additional_quantitative_bullets": 0.0,
        "interpretation_length": 0.0,
        "email_address_and_length": 0.0,
        "email_deadline_and_request": 0.0,
        "email_headline_and_attachment": 0.0,
    }

    # Paths
    input_scene_csv = workspace / "input" / "scene_metrics.csv"
    input_notes = workspace / "input" / "critic_notes.txt"
    input_email_yaml = workspace / "input" / "email_context.yaml"
    output_summary_csv = workspace / "outputs" / "film_style_summary.csv"
    output_report_md = workspace / "outputs" / "report.md"
    output_email_txt = workspace / "outputs" / "email_draft.txt"

    # Load input scenes
    scene_data = _safe_read_csv_dicts(input_scene_csv)
    if scene_data is not None:
        scene_headers, scene_rows = scene_data
        groups = _group_scene_metrics(scene_rows)
        expected = _compute_expected_summary(groups)
    else:
        scene_headers, scene_rows, groups, expected = None, [], {}, {}

    # 1) Summary CSV structure
    summary_data = _parse_summary_csv(output_summary_csv)
    expected_cols = [
        "film",
        "year",
        "n_scenes",
        "mean_shot_length_sec",
        "std_shot_length_sec",
        "interior_mean_shot_length_sec",
        "exterior_mean_shot_length_sec",
        "mean_color_temp_k",
        "mean_saturation",
        "mean_brightness",
        "mean_dialog_sentiment",
    ]
    if summary_data is not None:
        summary_headers, summary_rows = summary_data
        if summary_headers == expected_cols:
            scores["summary_csv_structure"] = 1.0

    # 1b) Grouping and coverage
    if scene_data is not None and summary_data is not None:
        # Build set of (film, year) from input
        input_groups = set(groups.keys())
        # Build set of (film, year) from summary csv
        summary_groups: set = set()
        per_group_counts: Dict[Tuple[str, int], int] = {}
        valid = True
        for row in summary_rows:
            try:
                film = row["film"]
                year = int(row["year"])
            except Exception:
                valid = False
                break
            summary_groups.add((film, year))
            per_group_counts[(film, year)] = per_group_counts.get((film, year), 0) + 1
        if valid and input_groups == summary_groups and all(c == 1 for c in per_group_counts.values()):
            scores["summary_grouping_and_coverage"] = 1.0

    # 1c) Values accuracy
    if scene_data is not None and summary_data is not None and scores["summary_csv_structure"] == 1.0:
        all_ok = True
        # Build a lookup map for summary rows by (film, year)
        sum_map: Dict[Tuple[str, int], Dict[str, str]] = {}
        for r in summary_rows:
            try:
                k = (r["film"], int(r["year"]))
            except Exception:
                all_ok = False
                break
            sum_map[k] = r
        if all_ok and expected:
            for key, exp in expected.items():
                if key not in sum_map:
                    all_ok = False
                    break
                row = sum_map[key]
                # n_scenes
                try:
                    n_scenes_val = int(row["n_scenes"])
                except Exception:
                    all_ok = False
                    break
                if n_scenes_val != exp["n_scenes"]:
                    all_ok = False
                    break
                # mean_shot_length_sec
                try:
                    mean_asl_val = float(row["mean_shot_length_sec"])
                    std_asl_val = float(row["std_shot_length_sec"])
                    inter_mean_val = float(row["interior_mean_shot_length_sec"])
                    exter_mean_val = float(row["exterior_mean_shot_length_sec"])
                    mean_color_val = int(row["mean_color_temp_k"])
                    mean_sat_val = float(row["mean_saturation"])
                    mean_bri_val = float(row["mean_brightness"])
                    mean_sent_val = float(row["mean_dialog_sentiment"])
                except Exception:
                    all_ok = False
                    break
                if not _float_eq(mean_asl_val, exp["mean_shot_length_sec"]):
                    all_ok = False
                    break
                # std: accept either population or sample rounding
                std_ok = _float_eq(std_asl_val, exp["std_shot_length_sec_pop"]) or _float_eq(std_asl_val, exp["std_shot_length_sec_sample"])
                if not std_ok:
                    all_ok = False
                    break
                if not _float_eq(inter_mean_val, exp["interior_mean_shot_length_sec"]):
                    all_ok = False
                    break
                if not _float_eq(exter_mean_val, exp["exterior_mean_shot_length_sec"]):
                    all_ok = False
                    break
                # mean_color_temp_k: accept either bankers or half-up
                if mean_color_val not in (exp["mean_color_temp_k_bankers"], exp["mean_color_temp_k_halfup"]):
                    all_ok = False
                    break
                if not _float_eq(mean_sat_val, exp["mean_saturation"]):
                    all_ok = False
                    break
                if not _float_eq(mean_bri_val, exp["mean_brightness"]):
                    all_ok = False
                    break
                if not _float_eq(mean_sent_val, exp["mean_dialog_sentiment"]):
                    all_ok = False
                    break
        else:
            all_ok = False
        if all_ok:
            scores["summary_values_accuracy"] = 1.0

    # 3) Report sections and content
    report_text = _safe_read_text(output_report_md)
    if report_text is not None:
        order, sections = _parse_report_sections(report_text)
        expected_order = ["abstract", "methods", "results", "interpretation"]
        # Check presence and order
        has_all = all(sec in sections for sec in expected_order)
        in_order = has_all and [sec for sec in order if sec in expected_order] == expected_order
        if in_order:
            scores["report_section_order"] = 1.0

        # Abstract checks: length 120-150 and originality vs notes
        abstract_text = sections.get("abstract", "")
        notes_text = _safe_read_text(input_notes) or ""
        abstract_wc = _word_count(abstract_text)
        length_ok = 120 <= abstract_wc <= 150
        # No reuse of >15 consecutive words from notes
        originality_ok = True
        if notes_text:
            abs_tokens = _tokenize_words(abstract_text)
            notes_tokens = _tokenize_words(notes_text)
            window = 16
            notes_sequences = set()
            for i in range(0, max(0, len(notes_tokens) - window + 1)):
                seq = " ".join(notes_tokens[i : i + window])
                notes_sequences.add(seq)
            # Build abstract sequences and test intersection
            for i in range(0, max(0, len(abs_tokens) - window + 1)):
                seq = " ".join(abs_tokens[i : i + window])
                if seq in notes_sequences:
                    originality_ok = False
                    break
        else:
            # If notes missing, cannot verify originality; fail this check strictly
            originality_ok = False
        if length_ok and originality_ok:
            scores["abstract_length_and_originality"] = 1.0

        # Methods: 2-4 sentences, mention CSV and rounding
        methods_text = sections.get("methods", "")
        sents = _split_sentences(methods_text)
        sent_count_ok = 2 <= len(sents) <= 4
        mentions_csv = re.search(r"\b(csv|scene_metrics\.csv)\b", methods_text, re.IGNORECASE) is not None
        mentions_round = re.search(r"\bround\w*\b", methods_text, re.IGNORECASE) is not None
        if sent_count_ok and mentions_csv and mentions_round:
            scores["methods_description_quality"] = 1.0

        # Results bullets
        results_text = sections.get("results", "")
        bullets = _parse_bullets(results_text)
        if len(bullets) >= 4:
            scores["results_bullet_count"] = 1.0

        # Load summary for results validation
        summary_ok = summary_data is not None and scores["summary_values_accuracy"] == 1.0
        summary_rows_map: Dict[str, Dict[str, str]] = {}
        if summary_ok:
            # Map by film name for quick lookup
            for r in summary_rows:
                summary_rows_map[r["film"]] = r

        # Shortest mean shot length correctness
        shortest_found = _find_specific_bullet(bullets, "shortest_asl")
        if len(shortest_found) == 1 and summary_ok:
            _, film_s, val_s = shortest_found[0]
            try:
                val_num = float(val_s)
            except Exception:
                val_num = None
            # Determine film(s) with minimum mean_shot_length_sec
            min_val = None
            min_films = []
            for r in summary_rows:
                try:
                    v = float(r["mean_shot_length_sec"])
                except Exception:
                    continue
                if (min_val is None) or (v < min_val - 1e-9):
                    min_val = v
                    min_films = [r["film"]]
                elif abs(v - min_val) <= 1e-9:
                    min_films.append(r["film"])
            if val_num is not None and min_val is not None:
                # Check film and value alignment (allow ties)
                film_ok = film_s in min_films
                value_ok = abs(val_num - min_val) <= 0.01
                if film_ok and value_ok:
                    scores["results_shortest_mean_shot_length_correct"] = 1.0

        # Highest mean color temperature correctness
        highest_found = _find_specific_bullet(bullets, "highest_color")
        if len(highest_found) == 1 and summary_ok:
            _, film_c, val_c = highest_found[0]
            try:
                val_num_c = int(val_c)
            except Exception:
                val_num_c = None
            max_val = None
            max_films = []
            for r in summary_rows:
                try:
                    v = int(r["mean_color_temp_k"])
                except Exception:
                    continue
                if (max_val is None) or (v > max_val):
                    max_val = v
                    max_films = [r["film"]]
                elif v == max_val:
                    max_films.append(r["film"])
            if val_num_c is not None and max_val is not None:
                film_ok = film_c in max_films
                value_ok = val_num_c == max_val
                if film_ok and value_ok:
                    scores["results_highest_mean_color_temp_correct"] = 1.0

        # Additional quantitative bullets: at least two other bullets with digits and film/context
        if bullets:
            # Exclude matched specific bullets
            specific_lines = set([shortest_found[0][0]]) if len(shortest_found) == 1 else set()
            if len(highest_found) == 1:
                specific_lines.add(highest_found[0][0])
            remaining = [b for b in bullets if b not in specific_lines]
            # Build film name set
            film_names = set([r["film"] for r in summary_rows]) if summary_ok else set()
            quant_count = 0
            for b in remaining:
                has_digit = re.search(r"\d", b) is not None
                mentions_context = any(fn in b for fn in film_names) or re.search(r"\b(interior|exterior|mean|shot|temperature|saturation|brightness|sentiment)\b", b, re.IGNORECASE)
                if has_digit and mentions_context:
                    quant_count += 1
            if quant_count >= 2:
                scores["results_additional_quantitative_bullets"] = 1.0

        # Interpretation: 120–180 words
        interp_text = sections.get("interpretation", "")
        interp_wc = _word_count(interp_text)
        if 120 <= interp_wc <= 180:
            scores["interpretation_length"] = 1.0

    # 4) Email checks
    email_text = _safe_read_text(output_email_txt)
    email_yaml = _safe_load_yaml_simple(input_email_yaml)
    if email_text is not None and email_yaml is not None:
        wc = _word_count(email_text)
        addressed_ok = "Dr. Elaine Porter" in email_text
        if 120 <= wc <= 180 and addressed_ok:
            scores["email_address_and_length"] = 1.0

        # Deadline and request
        deadline_iso = email_yaml.get("deadline_date", "")
        # Build human-readable month name
        deadline_ok = False
        if deadline_iso:
            # Accept ISO date appearance
            if deadline_iso in email_text:
                deadline_ok = True
            else:
                m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", deadline_iso)
                if m:
                    year = m.group(1)
                    month = int(m.group(2))
                    day = int(m.group(3))
                    months = ["January", "February", "March", "April", "May", "June", "July",
                              "August", "September", "October", "November", "December"]
                    month_name = months[month - 1]
                    # Check any sentence that contains month name and year and day
                    sentences = _split_sentences(email_text)
                    for s in sentences:
                        if (re.search(rf"\b{month_name}\b", s, re.IGNORECASE) and
                                re.search(rf"\b{year}\b", s) and
                                re.search(rf"\b0?{day}\b", s)):
                            deadline_ok = True
                            break
        request_ok = re.search(r"\b(sanity check|methodological)\b", email_text, re.IGNORECASE) is not None
        if deadline_ok and request_ok:
            scores["email_deadline_and_request"] = 1.0

        # Headline findings mention and attachment
        attachment_ok = ("outputs/report.md" in email_text) or (re.search(r"\battached report\b", email_text, re.IGNORECASE) is not None)
        # Headline mention: either exact phrases or combo of film+metric
        headline_ok = False
        if re.search(r"Shortest mean shot length:", email_text, re.IGNORECASE) or re.search(r"Highest mean color temperature:", email_text, re.IGNORECASE):
            headline_ok = True
        else:
            # Look for a film name and a metric keyword
            if summary_data is not None:
                film_names = [r["film"] for r in summary_rows]
            else:
                film_names = []
            film_present = any(fn in email_text for fn in film_names)
            metric_present = re.search(r"\b(shot length|color temperature)\b", email_text, re.IGNORECASE) is not None
            if film_present and metric_present:
                headline_ok = True
        if attachment_ok and headline_ok:
            scores["email_headline_and_attachment"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()