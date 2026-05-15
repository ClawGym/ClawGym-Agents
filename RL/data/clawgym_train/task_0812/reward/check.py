import json
import csv
import math
import re
import sys
from pathlib import Path


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        data_rows = rows[1:]
        dict_rows = []
        for r in data_rows:
            if len(r) != len(header):
                return None, []
            dict_rows.append({h: v for h, v in zip(header, r)})
        return header, dict_rows
    except Exception:
        return None, []


def compute_expected_wavelength_and_range(cfg: dict, freq_MHz: float):
    c = 299792458.0
    frequency_Hz = float(freq_MHz) * 1e6
    wavelength_m = c / frequency_Hz
    k = 1.38064852e-23
    snr_threshold_dB = cfg["snr_threshold_dB"]
    SNR_linear = 10.0 ** (snr_threshold_dB / 10.0)
    numerator = (
        cfg["tx_power_W"]
        * (cfg["antenna_gain_linear"] ** 2)
        * (wavelength_m ** 2)
        * cfg["radar_cross_section_m2"]
    )
    denominator = (
        (4.0 * math.pi) ** 3
        * k
        * cfg["noise_temperature_K"]
        * cfg["bandwidth_Hz"]
        * cfg["noise_figure_linear"]
        * cfg["system_losses_linear"]
        * SNR_linear
    )
    R4 = numerator / denominator
    if R4 <= 0:
        max_range_km = 0.0
    else:
        R_m = R4 ** 0.25
        max_range_km = R_m / 1000.0
    return wavelength_m, max_range_km


def parse_marked_sections(text: str, start_marker: str, end_marker: str):
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None, None, None
    before = text[: start_idx]
    inside = text[start_idx + len(start_marker) : end_idx]
    after = text[end_idx + len(end_marker) :]
    return before, inside, after


def check_tokens_in_order(text: str, tokens: list) -> bool:
    last_pos = -1
    for tok in tokens:
        pos = text.find(str(tok), last_pos + 1)
        if pos == -1:
            return False
        last_pos = pos
    return True


def extract_markdown_section(md_text: str, section_title: str) -> str:
    lines = md_text.splitlines()
    target_idx = None
    for i, line in enumerate(lines):
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", line)
        if m:
            title = m.group(1).strip().lower()
            if title == section_title.strip().lower():
                target_idx = i
                break
    if target_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(target_idx + 1, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s*.+", lines[j]):
            end_idx = j
            break
    return "\n".join(lines[target_idx:end_idx])


def parse_cfg_to_var_mappings(script_text: str) -> dict:
    mapping = {}
    for line in script_text.splitlines():
        m = re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*cfg\[['\"]([^'\"]+)['\"]\]\s*$", line)
        if m:
            var_name = m.group(1)
            cfg_key = m.group(2)
            mapping[cfg_key] = var_name
    return mapping


def round_two_decimals_str(x: float) -> str:
    return f"{x:.2f}"


def freq_to_token(f: float) -> str:
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return str(f)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "csv_exists_and_header": 0.0,
        "csv_row_count_matches_config": 0.0,
        "csv_values_correct": 0.0,
        "lesson_markers_and_outside_unchanged": 0.0,
        "lesson_includes_best_pair": 0.0,
        "lesson_includes_ranked_frequencies": 0.0,
        "lesson_includes_csv_link": 0.0,
        "status_report_exists": 0.0,
        "status_mapping_section_has_3_valid_mappings": 0.0,
        "status_data_summary_header_included": 0.0,
        "status_data_summary_row_count_correct": 0.0,
        "status_data_summary_ranked_order_correct": 0.0,
        "status_data_summary_best_pair_correct": 0.0,
        "status_lesson_update_section_present_and_mentions_markers": 0.0,
    }

    cfg_path = workspace / "config" / "radar_config.json"
    cfg = safe_load_json(cfg_path)
    expected_header = [
        "frequency_MHz",
        "wavelength_m",
        "tx_power_W",
        "antenna_gain_linear",
        "radar_cross_section_m2",
        "noise_temperature_K",
        "bandwidth_Hz",
        "noise_figure_linear",
        "system_losses_linear",
        "snr_threshold_dB",
        "max_range_km",
    ]

    csv_path = workspace / "outputs" / "radar_results.csv"
    header, rows = safe_read_csv(csv_path)

    # CSV existence and header check
    if header is not None and header == expected_header:
        scores["csv_exists_and_header"] = 1.0

    # CSV row count matches configuration
    if cfg is not None and header is not None:
        if isinstance(cfg.get("frequencies_MHz"), list):
            if len(rows) == len(cfg["frequencies_MHz"]):
                scores["csv_row_count_matches_config"] = 1.0

    # CSV values correctness against recomputation
    csv_ok = True
    if cfg is not None and header is not None:
        freq_to_row = {}
        for r in rows:
            try:
                f = float(r["frequency_MHz"])
            except Exception:
                csv_ok = False
                break
            freq_to_row[f] = r
        if csv_ok:
            freqs_cfg = cfg.get("frequencies_MHz", [])
            tol_wavelength = 5e-6
            tol_range = 5e-4
            for f in freqs_cfg:
                f_float = float(f)
                if f_float not in freq_to_row:
                    csv_ok = False
                    break
                r = freq_to_row[f_float]
                try:
                    txp = float(r["tx_power_W"])
                    g = float(r["antenna_gain_linear"])
                    rcs = float(r["radar_cross_section_m2"])
                    T = float(r["noise_temperature_K"])
                    B = float(r["bandwidth_Hz"])
                    nf = float(r["noise_figure_linear"])
                    L = float(r["system_losses_linear"])
                    snr_db = float(r["snr_threshold_dB"])
                except Exception:
                    csv_ok = False
                    break
                if not (
                    math.isclose(txp, float(cfg["tx_power_W"]), rel_tol=0, abs_tol=0)
                    and math.isclose(g, float(cfg["antenna_gain_linear"]), rel_tol=0, abs_tol=0)
                    and math.isclose(rcs, float(cfg["radar_cross_section_m2"]), rel_tol=0, abs_tol=0)
                    and math.isclose(T, float(cfg["noise_temperature_K"]), rel_tol=0, abs_tol=0)
                    and math.isclose(B, float(cfg["bandwidth_Hz"]), rel_tol=0, abs_tol=0)
                    and math.isclose(nf, float(cfg["noise_figure_linear"]), rel_tol=0, abs_tol=0)
                    and math.isclose(L, float(cfg["system_losses_linear"]), rel_tol=0, abs_tol=0)
                    and math.isclose(snr_db, float(cfg["snr_threshold_dB"]), rel_tol=0, abs_tol=0)
                ):
                    csv_ok = False
                    break
                try:
                    wavelength_csv = float(r["wavelength_m"])
                    range_csv = float(r["max_range_km"])
                except Exception:
                    csv_ok = False
                    break
                wl_expected, range_expected = compute_expected_wavelength_and_range(cfg, f_float)
                if not math.isclose(wavelength_csv, wl_expected, rel_tol=0, abs_tol=tol_wavelength):
                    csv_ok = False
                    break
                if not math.isclose(range_csv, range_expected, rel_tol=1e-7, abs_tol=tol_range):
                    csv_ok = False
                    break
        if csv_ok:
            scores["csv_values_correct"] = 1.0

    # Lesson checks
    lesson_path = workspace / "docs" / "module_lesson.md"
    lesson_text = safe_read_text(lesson_path)

    original_lesson_text = (
        "# Module: How Early Radar Engineering Shaped History\n\n"
        "This short lesson uses a simplified radar range equation to illustrate why early long-wavelength systems like Chain Home prioritized detection range at the expense of angular resolution. We run a small calculation locally and use the results to ground a historical discussion about design tradeoffs in the late 1930s and early 1940s.\n\n"
        "## Radar Range vs Frequency (Hands-on)\n"
        "The script in scripts/simulate_radar.py computes maximum detection range as a function of frequency for fixed transmitter power, antenna gain, radar cross-section, and receiver parameters.\n\n"
        "<!-- INJECT_RESULTS_START -->\n"
        "[TODO: Replace this block with a short results summary integrating the latest run of scripts/simulate_radar.py. Include: which frequency achieved the largest max_range_km and its value (rounded to 2 decimals), a ranked list of the configured frequencies from longest to shortest range, and a relative link to outputs/radar_results.csv. Keep these markers in place.]\n"
        "<!-- INJECT_RESULTS_END -->\n\n"
        "### Historical tie-in\n"
        "Lower frequencies (longer wavelengths) generally improve range for a given set of assumptions but reduce angular resolution for a given aperture. This tradeoff shaped early warning network designs.\n"
    )

    start_marker = "<!-- INJECT_RESULTS_START -->"
    end_marker = "<!-- INJECT_RESULTS_END -->"
    best_freq = None
    best_range = None
    ranking_freqs = []
    if header is not None:
        try:
            ranges = []
            for r in rows:
                f = float(r["frequency_MHz"])
                rng = float(r["max_range_km"])
                ranges.append((f, rng))
            ranges.sort(key=lambda x: (-x[1], x[0]))
            ranking_freqs = [f for f, _ in ranges]
            if ranges:
                best_freq = ranges[0][0]
                best_range = ranges[0][1]
        except Exception:
            pass

    if lesson_text:
        before, inside_block, after = parse_marked_sections(lesson_text, start_marker, end_marker)
        obefore, oinside_block, oafter = parse_marked_sections(original_lesson_text, start_marker, end_marker)
        # Only award "outside unchanged" if CSV exists, markers present, outside equals original, and inside has changed from placeholder.
        if (
            header is not None
            and before is not None
            and obefore is not None
            and oinside_block is not None
            and after is not None
            and before == obefore
            and after == oafter
            and inside_block is not None
            and inside_block.strip() != oinside_block.strip()
        ):
            scores["lesson_markers_and_outside_unchanged"] = 1.0

        if inside_block is not None and best_freq is not None and best_range is not None:
            best_freq_str = freq_to_token(best_freq)
            best_val_str = round_two_decimals_str(best_range)
            if best_freq_str in inside_block and best_val_str in inside_block:
                scores["lesson_includes_best_pair"] = 1.0
            rank_tokens = [freq_to_token(f) for f in ranking_freqs]
            if rank_tokens and check_tokens_in_order(inside_block, rank_tokens):
                scores["lesson_includes_ranked_frequencies"] = 1.0
            # Require a markdown link target syntax with parentheses to avoid matching the original placeholder mention.
            if re.search(r"\(outputs/radar_results\.csv\)", inside_block):
                scores["lesson_includes_csv_link"] = 1.0

    # Status report checks
    status_path = workspace / "reports" / "status_update.md"
    status_text = safe_read_text(status_path)
    if status_text:
        scores["status_report_exists"] = 1.0

        mapping_section = extract_markdown_section(status_text, "Config-to-Code Mapping")
        script_text = safe_read_text(workspace / "scripts" / "simulate_radar.py")
        cfg_to_var_map = parse_cfg_to_var_mappings(script_text) if script_text else {}
        valid_map_count = 0
        if mapping_section and cfg_to_var_map:
            for line in mapping_section.splitlines():
                if "->" in line:
                    parts = [p.strip() for p in line.split("->", 1)]
                    if len(parts) == 2:
                        left, right = parts
                        left = left.strip("`")
                        right = right.strip("`")
                        if left in cfg_to_var_map and cfg_to_var_map[left] == right:
                            valid_map_count += 1
        if valid_map_count >= 3:
            scores["status_mapping_section_has_3_valid_mappings"] = 1.0

        data_summary_section = extract_markdown_section(status_text, "Data Summary")
        if data_summary_section and header is not None:
            header_line_exact = ",".join(expected_header)
            if header_line_exact in data_summary_section:
                scores["status_data_summary_header_included"] = 1.0

            n_rows = len(rows)
            m = re.search(r"(\d+)\s+rows?\b", data_summary_section, flags=re.IGNORECASE)
            if m:
                try:
                    reported_rows = int(m.group(1))
                    if reported_rows == n_rows:
                        scores["status_data_summary_row_count_correct"] = 1.0
                except Exception:
                    pass

            rank_tokens = [freq_to_token(f) for f in ranking_freqs]
            if rank_tokens and check_tokens_in_order(data_summary_section, rank_tokens):
                scores["status_data_summary_ranked_order_correct"] = 1.0

            if best_freq is not None and best_range is not None:
                best_freq_str = freq_to_token(best_freq)
                best_val_str = round_two_decimals_str(best_range)
                if best_freq_str in data_summary_section and best_val_str in data_summary_section:
                    scores["status_data_summary_best_pair_correct"] = 1.0

        lesson_update_section = extract_markdown_section(status_text, "Lesson Update")
        if lesson_update_section:
            mentions_markers = ("INJECT_RESULTS_START" in lesson_update_section) and ("INJECT_RESULTS_END" in lesson_update_section)
            has_results_ref = False
            if best_freq is not None and best_range is not None:
                best_freq_str = freq_to_token(best_freq)
                best_val_str = round_two_decimals_str(best_range)
                if best_freq_str in lesson_update_section or best_val_str in lesson_update_section:
                    has_results_ref = True
            if mentions_markers and has_results_ref:
                scores["status_lesson_update_section_present_and_mentions_markers"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()