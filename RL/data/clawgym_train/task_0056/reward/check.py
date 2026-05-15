import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


def load_json_safe(path: Path):
    try:
        return json.loads(read_text_safe(path))
    except Exception:
        return None


def read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


class SpecsTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_specs_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.rows = []
        self.current_cell_data = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("id") == "specs":
            self.in_specs_table = True
        elif self.in_specs_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_tr and tag == "td":
            self.in_td = True
            self.current_cell_data = []

    def handle_endtag(self, tag):
        if tag == "table" and self.in_specs_table:
            self.in_specs_table = False
        elif tag == "tbody" and self.in_tbody:
            self.in_tbody = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif tag == "td" and self.in_td:
            self.in_td = False
            data = "".join(self.current_cell_data).strip()
            self.current_row.append(data)
            self.current_cell_data = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell_data.append(data)


def parse_press_specs_html(path: Path):
    html = read_text_safe(path)
    if not html:
        return None
    parser = SpecsTableParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    specs = {}
    for row in parser.rows:
        if len(row) < 6:
            continue
        model = row[0].strip()
        try:
            year = int(row[1].strip())
        except Exception:
            continue
        try:
            hp = float(row[2].strip())
            tq = float(row[3].strip())
            zero60 = float(row[4].strip())
            msrp = float(row[5].strip())
        except Exception:
            continue
        specs[(model, year)] = {
            "horsepower_hp": hp,
            "torque_lbft": tq,
            "zero_to_sixty_s": zero60,
            "msrp_usd": msrp,
        }
    return specs


def extract_unique_model_years_from_log(log_rows):
    pairs = set()
    for r in log_rows:
        m = (r.get("model") or "").strip()
        mobj = re.match(r"^\s*(\d{4})\s+(.*\S)\s*$", m)
        if mobj:
            year = int(mobj.group(1))
            model_name = mobj.group(2).strip()
            pairs.add((model_name, year))
    return pairs


def sentence_count(text: str) -> int:
    endings = re.findall(r"[\.!?](?:\s|$)", text)
    return len(endings)


def get_section_bounds(text: str, label_names):
    lines = text.splitlines()
    found = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        lowered = stripped.lower().rstrip(":")
        for name in label_names:
            if lowered == name.lower().rstrip(":"):
                found[name] = i
    ordered = sorted(found.items(), key=lambda x: x[1])
    bounds = {}
    for idx, (name, start_line) in enumerate(ordered):
        end_line = len(lines)
        if idx + 1 < len(ordered):
            end_line = ordered[idx + 1][1]
        section_text = "\n".join(lines[start_line + 1:end_line]).strip()
        bounds[name] = section_text
    return bounds


def parse_bullet_kv_lines(section_text: str):
    result = {}
    for line in section_text.splitlines():
        l = line.strip()
        if not l:
            continue
        if l.startswith(("-", "*", "•")):
            content = l[1:].strip()
        else:
            content = l
        if ":" in content:
            k, v = content.split(":", 1)
            result[k.strip().lower()] = v.strip()
    return result


def parse_percentage_value(val_str: str):
    if val_str is None:
        return None
    s = val_str.strip()
    s = s.replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def count_words(text: str) -> int:
    words = re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE)
    return len(words)


def extract_quoted_texts(text: str):
    quotes = []
    for m in re.finditer(r"“([^”]+)”", text):
        quotes.append(m.group(0))
    for m in re.finditer(r"\"([^\"]+)\"", text):
        quotes.append(m.group(0))
    for m in re.finditer(r"'([^']+)'", text):
        quotes.append(m.group(0))
    return quotes


def extract_numbers(text: str):
    tokens = re.findall(r"\d+(?:/\d+|\.\d+)?", text)
    return set(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "model_specs_exists": 0.0,
        "model_specs_header": 0.0,
        "model_specs_row_count": 0.0,
        "model_specs_values_match": 0.0,
        "weekly_summary_exists": 0.0,
        "week_overview_sentence_count": 0.0,
        "shoot_metrics_computed_correct": 0.0,
        "hero_shots_coverage": 0.0,
        "summary_model_specs_section_values": 0.0,
        "pitch_rewrite_exists": 0.0,
        "pitch_rewrite_word_count_range": 0.0,
        "pitch_rewrite_subject_and_cta": 0.0,
        "pitch_rewrite_format_no_bullets_no_exclaim": 0.0,
        "feature_edited_exists": 0.0,
        "feature_edit_headings_preserved": 0.0,
        "feature_edit_numbers_preserved": 0.0,
        "feature_edit_quotes_preserved": 0.0,
        "feature_edit_reduction_15_30": 0.0,
        "feature_edit_metrics_json_valid": 0.0,
    }

    shoot_log_path = workspace / "input" / "shoot_log.csv"
    press_specs_path = workspace / "input" / "press_specs.html"
    feature_draft_path = workspace / "input" / "feature_draft.md"

    model_specs_out = workspace / "output" / "model_specs.csv"
    weekly_summary_out = workspace / "output" / "weekly_shoot_summary.md"
    pitch_rewrite_out = workspace / "output" / "pitch_email_rewrite.txt"
    feature_edited_out = workspace / "output" / "feature_draft_edited.md"
    feature_metrics_out = workspace / "output" / "feature_edit_metrics.json"

    log_header, log_rows = read_csv_dicts(shoot_log_path)
    press_specs = parse_press_specs_html(press_specs_path)

    unique_pairs = set()
    if log_rows is not None:
        unique_pairs = extract_unique_model_years_from_log(log_rows)

    expected_specs = {}
    if press_specs is not None and unique_pairs:
        for pair in unique_pairs:
            if pair in press_specs:
                expected_specs[pair] = press_specs[pair]

    if model_specs_out.exists():
        scores["model_specs_exists"] = 1.0
        header, rows = read_csv_dicts(model_specs_out)
        expected_header = ["model", "year", "horsepower_hp", "torque_lbft", "zero_to_sixty_s", "msrp_usd"]
        if header == expected_header:
            scores["model_specs_header"] = 1.0
        if rows is not None and log_rows is not None and press_specs is not None:
            parsed_rows = {}
            numeric_ok = True
            for r in rows:
                model = (r.get("model") or "").strip()
                year_str = (r.get("year") or "").strip()
                try:
                    year = int(year_str)
                except Exception:
                    numeric_ok = False
                    continue
                try:
                    hp = float((r.get("horsepower_hp") or "").strip())
                    tq = float((r.get("torque_lbft") or "").strip())
                    zero60 = float((r.get("zero_to_sixty_s") or "").strip())
                    msrp = float((r.get("msrp_usd") or "").strip())
                except Exception:
                    numeric_ok = False
                    continue
                parsed_rows[(model, year)] = {
                    "horsepower_hp": hp,
                    "torque_lbft": tq,
                    "zero_to_sixty_s": zero60,
                    "msrp_usd": msrp,
                }
            if numeric_ok:
                if len(parsed_rows) == len(unique_pairs) and set(parsed_rows.keys()) == unique_pairs:
                    scores["model_specs_row_count"] = 1.0
                values_match = True
                if expected_specs and parsed_rows:
                    for k, v in expected_specs.items():
                        if k not in parsed_rows:
                            values_match = False
                            break
                        out_v = parsed_rows[k]
                        for key in ["horsepower_hp", "torque_lbft", "zero_to_sixty_s", "msrp_usd"]:
                            ev = float(v[key])
                            ov = float(out_v[key])
                            if abs(ev - ov) > 1e-6:
                                values_match = False
                                break
                        if not values_match:
                            break
                else:
                    values_match = False
                scores["model_specs_values_match"] = 1.0 if values_match else 0.0
            else:
                scores["model_specs_row_count"] = 0.0
                scores["model_specs_values_match"] = 0.0
        else:
            scores["model_specs_row_count"] = 0.0
            scores["model_specs_values_match"] = 0.0
    else:
        scores["model_specs_exists"] = 0.0

    if weekly_summary_out.exists():
        scores["weekly_summary_exists"] = 1.0
        weekly_text = read_text_safe(weekly_summary_out)
        section_labels = ["Week Overview:", "Shoot Metrics", "Hero shots:", "Model specs:"]
        sections = get_section_bounds(weekly_text, section_labels)

        week_overview_txt = sections.get("Week Overview:", "")
        sc = sentence_count(week_overview_txt)
        if 2 <= sc <= 3:
            scores["week_overview_sentence_count"] = 1.0

        if log_rows is not None:
            metrics_txt = sections.get("Shoot Metrics", "")
            metrics_map = parse_bullet_kv_lines(metrics_txt)
            total_shoots = len(log_rows)
            unique_models = len(set([(r.get("model") or "").strip() for r in log_rows]))
            locations_covered = len(set([(r.get("location") or "").strip() for r in log_rows]))
            keepers = sum(1 for r in log_rows if (r.get("keeper") or "").strip().lower() == "yes")
            keeper_rate = round(keepers / total_shoots * 100.0, 1) if total_shoots > 0 else 0.0
            loc_counts = {}
            for r in log_rows:
                loc = (r.get("location") or "").strip()
                if not loc:
                    continue
                loc_counts[loc] = loc_counts.get(loc, 0) + 1
            top_location = None
            if loc_counts:
                max_count = max(loc_counts.values())
                candidates = sorted([loc for loc, cnt in loc_counts.items() if cnt == max_count])
                top_location = candidates[0] if candidates else None

            try:
                ok = True
                ts_str = metrics_map.get("total_shoots")
                ok = ok and (ts_str is not None and ts_str.isdigit() and int(ts_str) == total_shoots)
                um_str = metrics_map.get("unique_models")
                ok = ok and (um_str is not None and um_str.isdigit() and int(um_str) == unique_models)
                lc_str = metrics_map.get("locations_covered")
                ok = ok and (lc_str is not None and lc_str.isdigit() and int(lc_str) == locations_covered)
                kp_str = metrics_map.get("keepers")
                ok = ok and (kp_str is not None and kp_str.isdigit() and int(kp_str) == keepers)
                kr_str = metrics_map.get("keeper_rate")
                kr_val = parse_percentage_value(kr_str) if kr_str is not None else None
                ok = ok and (kr_val is not None and abs(kr_val - keeper_rate) < 0.05)
                tl_str = metrics_map.get("top_location_by_shots")
                ok = ok and (tl_str is not None and top_location is not None and tl_str.strip() == top_location)
                scores["shoot_metrics_computed_correct"] = 1.0 if ok else 0.0
            except Exception:
                scores["shoot_metrics_computed_correct"] = 0.0
        else:
            scores["shoot_metrics_computed_correct"] = 0.0

        if log_rows is not None:
            hero_txt = sections.get("Hero shots:", "")
            hero_lines = hero_txt.splitlines()

            def has_line_with_all(details):
                for line in hero_lines:
                    if all(d in line for d in details):
                        return True
                return False

            all_present = True
            for r in log_rows:
                if (r.get("keeper") or "").strip().lower() != "yes":
                    continue
                filev = (r.get("file") or "").strip()
                modelv = (r.get("model") or "").strip()
                locv = (r.get("location") or "").strip()
                lightv = (r.get("lighting") or "").strip()
                if not has_line_with_all([filev, modelv, locv, lightv]):
                    all_present = False
                    break
            scores["hero_shots_coverage"] = 1.0 if all_present else 0.0
        else:
            scores["hero_shots_coverage"] = 0.0

        specs_txt = sections.get("Model specs:", "")
        if specs_txt and expected_specs:
            lines = [ln.strip() for ln in specs_txt.splitlines() if ln.strip()]

            def has_row_line(pair, vals):
                model_name, year = pair
                year_str = str(year)
                hp_str = str(int(vals["horsepower_hp"])) if float(vals["horsepower_hp"]).is_integer() else str(vals["horsepower_hp"])
                tq_str = str(int(vals["torque_lbft"])) if float(vals["torque_lbft"]).is_integer() else str(vals["torque_lbft"])
                zero60_str = str(vals["zero_to_sixty_s"])
                msrp_str = str(int(vals["msrp_usd"])) if float(vals["msrp_usd"]).is_integer() else str(vals["msrp_usd"])
                for line in lines:
                    if (model_name in line and year_str in line and
                        hp_str in line and tq_str in line and
                        zero60_str in line and msrp_str in line):
                        return True
                return False

            ok = True
            for k, v in expected_specs.items():
                if not has_row_line(k, v):
                    ok = False
                    break
            scores["summary_model_specs_section_values"] = 1.0 if ok else 0.0
        else:
            scores["summary_model_specs_section_values"] = 0.0
    else:
        scores["weekly_summary_exists"] = 0.0

    if pitch_rewrite_out.exists():
        scores["pitch_rewrite_exists"] = 1.0
        txt = read_text_safe(pitch_rewrite_out)
        lines = txt.splitlines()
        lines = [l.rstrip() for l in lines]
        wc = count_words(txt)
        if 120 <= wc <= 150:
            scores["pitch_rewrite_word_count_range"] = 1.0
        first_nonempty_idx = None
        for i, l in enumerate(lines):
            if l.strip():
                first_nonempty_idx = i
                break
        subject_ok = False
        if first_nonempty_idx is not None:
            subject_ok = lines[first_nonempty_idx].lstrip().startswith("Subject:")
        last_nonempty_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                last_nonempty_idx = i
                break
        cta_ok = False
        if last_nonempty_idx is not None:
            cta_ok = lines[last_nonempty_idx].lstrip().startswith("Would you like")
        if subject_ok and cta_ok:
            scores["pitch_rewrite_subject_and_cta"] = 1.0

        fmt_ok = True
        if "!" in txt:
            fmt_ok = False
        if any(l.strip().startswith(("-", "*", "•")) for l in lines):
            fmt_ok = False
        body_lines = []
        if first_nonempty_idx is not None:
            body_lines = lines[first_nonempty_idx + 1:]
        paragraphs = []
        current = []
        for l in body_lines:
            if l.strip() == "":
                if current:
                    paragraphs.append("\n".join(current).strip())
                    current = []
            else:
                current.append(l)
        if current:
            paragraphs.append("\n".join(current).strip())
        if len(paragraphs) != 1:
            fmt_ok = False
        if fmt_ok:
            scores["pitch_rewrite_format_no_bullets_no_exclaim"] = 1.0
    else:
        scores["pitch_rewrite_exists"] = 0.0

    if feature_edited_out.exists():
        scores["feature_edited_exists"] = 1.0
        original_text = read_text_safe(feature_draft_path) if feature_draft_path.exists() else ""
        edited_text = read_text_safe(feature_edited_out)

        def extract_headings(text):
            return [ln.rstrip() for ln in text.splitlines() if ln.lstrip().startswith("#")]
        if original_text and edited_text:
            orig_headings = extract_headings(original_text)
            edit_headings = extract_headings(edited_text)
            headings_ok = orig_headings == edit_headings
            scores["feature_edit_headings_preserved"] = 1.0 if headings_ok else 0.0
        else:
            scores["feature_edit_headings_preserved"] = 0.0

        if original_text and edited_text:
            orig_nums = extract_numbers(original_text)
            nums_ok = True
            for num in orig_nums:
                if num not in edited_text:
                    nums_ok = False
                    break
            scores["feature_edit_numbers_preserved"] = 1.0 if nums_ok else 0.0
        else:
            scores["feature_edit_numbers_preserved"] = 0.0

        if original_text and edited_text:
            orig_quotes = extract_quoted_texts(original_text)
            quotes_ok = True
            for q in orig_quotes:
                if q not in edited_text:
                    quotes_ok = False
                    break
            scores["feature_edit_quotes_preserved"] = 1.0 if quotes_ok else 0.0
        else:
            scores["feature_edit_quotes_preserved"] = 0.0

        if original_text and edited_text:
            owc = count_words(original_text)
            rwc = count_words(edited_text)
            reduction_percent = (1 - (rwc / owc)) * 100 if owc > 0 else 0.0
            if 15.0 - 1e-6 <= reduction_percent <= 30.0 + 1e-6:
                scores["feature_edit_reduction_15_30"] = 1.0
            else:
                scores["feature_edit_reduction_15_30"] = 0.0
        else:
            scores["feature_edit_reduction_15_30"] = 0.0

        if feature_metrics_out.exists() and original_text and edited_text:
            data = load_json_safe(feature_metrics_out)
            if isinstance(data, dict):
                owc_exp = count_words(original_text)
                rwc_exp = count_words(edited_text)
                red_exp = round((1 - (rwc_exp / owc_exp)) * 100, 1) if owc_exp > 0 else 0.0
                try:
                    if (int(data.get("original_word_count", -1)) == owc_exp and
                        int(data.get("revised_word_count", -1)) == rwc_exp and
                        abs(float(data.get("reduction_percent", -9999)) - red_exp) < 0.05):
                        scores["feature_edit_metrics_json_valid"] = 1.0
                except Exception:
                    scores["feature_edit_metrics_json_valid"] = 0.0
        else:
            scores["feature_edit_metrics_json_valid"] = 0.0
    else:
        scores["feature_edited_exists"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()