import json
import csv
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        if isinstance(s, str):
            ss = s.strip()
            ss = ss.replace(",", "")
            return float(ss)
        return None
    except Exception:
        return None


def _simple_yaml_load(text: str) -> Dict[str, Any]:
    def parse_value(val: str) -> Any:
        val = val.strip()
        if val == "":
            return {}
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            return val[1:-1]
        try:
            if "." in val:
                return float(val)
            else:
                return int(val)
        except Exception:
            return val

    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        while stack and indent < stack[-1][0]:
            stack.pop()
        current = stack[-1][1] if stack else root

        if ":" in line.strip():
            key_part, val_part = line.strip().split(":", 1)
            key = key_part.strip()
            if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
                key = key[1:-1]
            val = val_part.strip()
            if val == "":
                new_map: Dict[str, Any] = {}
                current[key] = new_map
                stack.append((indent + 2, new_map))
            else:
                current[key] = parse_value(val)
        else:
            continue
    return root


def _load_yaml_file(p: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(p)
    if text is None:
        return None
    try:
        return _simple_yaml_load(text)
    except Exception:
        return None


def _parse_resolution(res: str) -> Optional[Tuple[int, int]]:
    try:
        parts = res.lower().split("x")
        if len(parts) != 2:
            return None
        w = int(parts[0].strip())
        h = int(parts[1].strip())
        return (w, h)
    except Exception:
        return None


def _float_close(a: float, b: float, rel_tol: float = 1e-3, abs_tol: float = 1e-2) -> bool:
    if abs(a - b) <= abs_tol:
        return True
    if b != 0 and abs((a - b) / b) <= rel_tol:
        return True
    return False


def _normalize_yes(val: str) -> str:
    v = (val or "").strip().lower()
    if v in {"yes", "y", "true", "1"}:
        return "yes"
    if v in {"no", "n", "false", "0"}:
        return "no"
    return v


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "signal_breakdown_file_present": 0.0,
        "signal_breakdown_columns_valid": 0.0,
        "calculated_mbps_values_correct": 0.0,
        "encoder_selections_correct": 0.0,
        "notes_requirements_met": 0.0,
        "aggregate_bandwidth_file_present": 0.0,
        "aggregate_rows_and_values_correct": 0.0,
        "capacity_flag_correct": 0.0,
        "enc_probe_results_logged": 0.0,
        "recommendations_file_present": 0.0,
        "recommendations_contains_bandwidth_summary": 0.0,
        "recommendations_contains_encoder_summary": 0.0,
        "recommendations_contains_bullets_with_guidance": 0.0,
    }

    input_csv_path = workspace / "input" / "signal_plan.csv"
    input_yaml_path = workspace / "input" / "constraints.yaml"
    signals = _read_csv_dicts(input_csv_path)
    constraints = _load_yaml_file(input_yaml_path)

    if signals is None or constraints is None:
        signal_breakdown_path = workspace / "out" / "capacity" / "signal_breakdown.csv"
        if signal_breakdown_path.exists():
            scores["signal_breakdown_file_present"] = 1.0
        aggregate_path = workspace / "out" / "capacity" / "aggregate_bandwidth.csv"
        if aggregate_path.exists():
            scores["aggregate_bandwidth_file_present"] = 1.0
        rec_path = workspace / "out" / "reports" / "recommendations.md"
        if rec_path.exists():
            scores["recommendations_file_present"] = 1.0
        enc_log_path = workspace / "out" / "logs" / "enc_probe_results.txt"
        if enc_log_path.exists():
            txt = _read_text(enc_log_path) or ""
            if any(k in txt for k in ["h264_nvenc", "hevc_nvenc", "prores_ks"]):
                scores["enc_probe_results_logged"] = 0.5
            else:
                scores["enc_probe_results_logged"] = 0.0
        return scores

    tprofiles = constraints.get("transport_profiles", {})
    ndi_prof = tprofiles.get("NDI", {})
    rtmp_prof = tprofiles.get("RTMP", {})
    ip_net = constraints.get("ip_network", {})
    capacity_mbps = float(ip_net.get("capacity_mbps", 0))
    safety_margin_pct = float(ip_net.get("safety_margin_pct", 0))

    enc_tool = workspace / "tools" / "enc_probe.py"
    probe_expected: Dict[str, Dict[str, Any]] = {}
    encoders = ["h264_nvenc", "hevc_nvenc", "prores_ks"]
    for enc in encoders:
        probe_expected[enc] = {"stdout": "", "stderr": "", "code": None}
        try:
            cp = subprocess.run(
                [sys.executable, str(enc_tool), "--query", enc],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            probe_expected[enc]["stdout"] = cp.stdout
            probe_expected[enc]["stderr"] = cp.stderr
            probe_expected[enc]["code"] = cp.returncode
        except Exception:
            if enc == "h264_nvenc":
                probe_expected[enc]["stdout"] = "ENCODER: h264_nvenc OK max_streams=4 max_bitrate_mbps=200\n"
                probe_expected[enc]["stderr"] = ""
                probe_expected[enc]["code"] = 0
            elif enc == "hevc_nvenc":
                probe_expected[enc]["stdout"] = ""
                probe_expected[enc]["stderr"] = "ERROR: encoder hevc_nvenc not found\n"
                probe_expected[enc]["code"] = 3
            elif enc == "prores_ks":
                probe_expected[enc]["stdout"] = "ENCODER: prores_ks OK_SW_ONLY max_streams=2 max_bitrate_mbps=800\n"
                probe_expected[enc]["stderr"] = ""
                probe_expected[enc]["code"] = 0

    hevc_available = (probe_expected["hevc_nvenc"]["code"] == 0) and (probe_expected["hevc_nvenc"]["stderr"] == "")
    prores_software_only = ("OK_SW_ONLY" in (probe_expected["prores_ks"]["stdout"] or "")) and (probe_expected["prores_ks"]["code"] == 0)

    expected_rows: Dict[str, Dict[str, Any]] = {}
    for row in signals:
        source = row.get("Source", "").strip()
        res_str = row.get("Resolution", "").strip()
        fr_str = row.get("FrameRate", "").strip()
        transport = row.get("Transport", "").strip()
        bit_depth = row.get("BitDepth", "").strip()
        chroma = row.get("Chroma", "").strip()
        count_str = row.get("Count", "").strip()
        rec_pref = (row.get("RecordingCodecPreference", "") or "").strip()
        live_pref = (row.get("LiveEncodingPreference", "") or "").strip()

        w_h = _parse_resolution(res_str)
        fr = _parse_float(fr_str) or 0.0
        count = int(_parse_float(count_str) or 0)

        calc_per_mbps = 0.0
        calc_total_mbps = 0.0

        notes_expect: List[str] = []

        if transport.upper() == "NDI":
            try:
                comp_ratio = float(ndi_prof.get("compression_ratio", 1))
                overhead_pct = float(ndi_prof.get("overhead_pct", 0))
                bpp_map = ndi_prof.get("bpp_map", {})
                key = f"{bit_depth}bit_{chroma.replace(':', '')}"
                bpp_val = float(bpp_map.get(key, 0))
                if w_h is not None and bpp_val > 0 and fr > 0 and comp_ratio > 0:
                    w, h = w_h
                    calc_per_mbps = (w * h * fr * bpp_val) / 1_000_000.0 / comp_ratio * (1.0 + overhead_pct / 100.0)
                else:
                    calc_per_mbps = 0.0
            except Exception:
                calc_per_mbps = 0.0
            calc_total_mbps = calc_per_mbps * count
        elif transport.upper() == "RTMP":
            table = rtmp_prof.get("bitrate_table_mbps", {})
            key = f"{res_str}@{int(fr)}"
            val = _parse_float(table.get(key, 0))
            calc_per_mbps = float(val or 0.0)
            calc_total_mbps = calc_per_mbps * count
        elif transport.upper() == "SDI":
            calc_per_mbps = 0.0
            calc_total_mbps = 0.0
        else:
            calc_per_mbps = 0.0
            calc_total_mbps = 0.0

        live_sel = live_pref
        if live_pref.upper() == "HEVC" and not hevc_available:
            live_sel = "H264"
            notes_expect.append("fallback")
        rec_sel = rec_pref
        if rec_pref.lower() == "prores" and prores_software_only:
            notes_expect.append("software")

        expected_rows[source] = {
            "Source": source,
            "Transport": transport,
            "Resolution": res_str,
            "FrameRate": int(fr) if fr else 0,
            "Count": count,
            "Calculated_Mbps_per_stream": calc_per_mbps,
            "Calculated_Mbps_total": calc_total_mbps,
            "LiveEncodingSelected": live_sel,
            "RecordingCodecSelected": rec_sel,
            "Notes_expect": notes_expect,
        }

    signal_breakdown_path = workspace / "out" / "capacity" / "signal_breakdown.csv"
    if signal_breakdown_path.exists():
        scores["signal_breakdown_file_present"] = 1.0
        out_rows = _read_csv_dicts(signal_breakdown_path)
        if out_rows is not None:
            required_cols = [
                "Source",
                "Transport",
                "Resolution",
                "FrameRate",
                "Count",
                "Calculated_Mbps_per_stream",
                "Calculated_Mbps_total",
                "LiveEncodingSelected",
                "RecordingCodecSelected",
                "Notes",
            ]
            header_ok = bool(out_rows) and all(c in out_rows[0].keys() for c in required_cols)
            scores["signal_breakdown_columns_valid"] = 1.0 if header_ok else 0.0

            out_by_source: Dict[str, Dict[str, str]] = {}
            for r in out_rows:
                out_by_source[r.get("Source", "").strip()] = r

            calc_ok = True
            enc_ok = True
            notes_ok = True
            for src, exp in expected_rows.items():
                r = out_by_source.get(src)
                if r is None:
                    calc_ok = False
                    enc_ok = False
                    notes_ok = False
                    continue
                per_val = _parse_float(r.get("Calculated_Mbps_per_stream", ""))
                total_val = _parse_float(r.get("Calculated_Mbps_total", ""))
                if per_val is None or total_val is None:
                    calc_ok = False
                else:
                    if not _float_close(per_val, exp["Calculated_Mbps_per_stream"]):
                        calc_ok = False
                    if not _float_close(total_val, exp["Calculated_Mbps_total"]):
                        calc_ok = False
                if (r.get("LiveEncodingSelected", "").strip().upper() or "") != (exp["LiveEncodingSelected"].upper() if exp["LiveEncodingSelected"] else ""):
                    enc_ok = False
                if (r.get("RecordingCodecSelected", "").strip() or "") != (exp["RecordingCodecSelected"] or ""):
                    enc_ok = False
                notes_str = (r.get("Notes", "") or "").lower()
                for sub in exp["Notes_expect"]:
                    if sub.lower() not in notes_str:
                        notes_ok = False
            scores["calculated_mbps_values_correct"] = 1.0 if calc_ok else 0.0
            scores["encoder_selections_correct"] = 1.0 if enc_ok else 0.0
            scores["notes_requirements_met"] = 1.0 if notes_ok else 0.0
        else:
            scores["signal_breakdown_columns_valid"] = 0.0
            scores["calculated_mbps_values_correct"] = 0.0
            scores["encoder_selections_correct"] = 0.0
            scores["notes_requirements_met"] = 0.0
    else:
        scores["signal_breakdown_file_present"] = 0.0

    aggregate_path = workspace / "out" / "capacity" / "aggregate_bandwidth.csv"
    if aggregate_path.exists():
        scores["aggregate_bandwidth_file_present"] = 1.0
        agg_rows = _read_csv_dicts(aggregate_path)
        agg_ok = False
        cap_flag_ok = False
        if agg_rows is not None and len(agg_rows) > 0:
            exp_ndi_streams = 0
            exp_ndi_mbps = 0.0
            exp_rtmp_streams = 0
            exp_rtmp_mbps = 0.0
            for _, exp in expected_rows.items():
                transport = str(exp["Transport"]).upper()
                if transport == "NDI":
                    exp_ndi_streams += int(exp["Count"])
                    exp_ndi_mbps += float(exp["Calculated_Mbps_total"])
                elif transport == "RTMP":
                    exp_rtmp_streams += int(exp["Count"])
                    exp_rtmp_mbps += float(exp["Calculated_Mbps_total"])
            exp_total_streams = exp_ndi_streams + exp_rtmp_streams
            exp_total_mbps = exp_ndi_mbps + exp_rtmp_mbps

            by_transport = {}
            for r in agg_rows:
                key = (r.get("Transport", "") or "").strip().upper()
                by_transport[key] = r

            ndi_r = by_transport.get("NDI")
            rtmp_r = by_transport.get("RTMP")
            total_r = by_transport.get("TOTAL_IP")

            have_all = ndi_r is not None and rtmp_r is not None and total_r is not None

            vals_ok = False
            if have_all:
                ndi_streams = _parse_float(ndi_r.get("Total_Streams", ""))
                ndi_mbps = _parse_float(ndi_r.get("Aggregate_Mbps", ""))
                rtmp_streams = _parse_float(rtmp_r.get("Total_Streams", ""))
                rtmp_mbps = _parse_float(rtmp_r.get("Aggregate_Mbps", ""))
                total_streams = _parse_float(total_r.get("Total_Streams", ""))
                total_mbps = _parse_float(total_r.get("Aggregate_Mbps", ""))
                if None not in (ndi_streams, ndi_mbps, rtmp_streams, rtmp_mbps, total_streams, total_mbps):
                    vals_ok = (
                        int(ndi_streams) == exp_ndi_streams
                        and _float_close(ndi_mbps, exp_ndi_mbps)
                        and int(rtmp_streams) == exp_rtmp_streams
                        and _float_close(rtmp_mbps, exp_rtmp_mbps)
                        and int(total_streams) == exp_total_streams
                        and _float_close(total_mbps, exp_total_mbps)
                    )
                allowed_flag = (total_r.get("AllowedUnderCapacityWithSafetyMargin") or "").strip()
                threshold = capacity_mbps * (1.0 - safety_margin_pct / 100.0)
                should_be_yes = exp_total_mbps <= threshold
                if allowed_flag:
                    normalized = _normalize_yes(allowed_flag)
                    cap_flag_ok = (normalized == ("yes" if should_be_yes else "no"))
                else:
                    cap_flag_ok = False
            agg_ok = have_all and vals_ok
        scores["aggregate_rows_and_values_correct"] = 1.0 if agg_ok else 0.0
        scores["capacity_flag_correct"] = 1.0 if cap_flag_ok else 0.0
    else:
        scores["aggregate_bandwidth_file_present"] = 0.0

    enc_log_path = workspace / "out" / "logs" / "enc_probe_results.txt"
    if enc_log_path.exists():
        txt = _read_text(enc_log_path) or ""
        has_h264 = "h264_nvenc" in txt and "ENCODER: h264_nvenc OK" in txt
        has_hevc = "hevc_nvenc" in txt and "ERROR: encoder hevc_nvenc not found" in txt
        has_prores = "prores_ks" in txt and "ENCODER: prores_ks OK_SW_ONLY" in txt
        has_exit_label = ("exit" in txt.lower()) or ("returncode" in txt.lower()) or ("code" in txt.lower())
        if has_h264 and has_hevc and has_prores and has_exit_label:
            scores["enc_probe_results_logged"] = 1.0
        else:
            partial = 0.0
            partial += 0.25 if has_h264 else 0.0
            partial += 0.25 if has_hevc else 0.0
            partial += 0.25 if has_prores else 0.0
            partial += 0.25 if has_exit_label else 0.0
            scores["enc_probe_results_logged"] = partial
    else:
        scores["enc_probe_results_logged"] = 0.0

    rec_path = workspace / "out" / "reports" / "recommendations.md"
    if rec_path.exists():
        scores["recommendations_file_present"] = 1.0
        md = _read_text(rec_path) or ""
        md_low = md.lower()

        total_ip_mbps = 0.0
        for _, exp in expected_rows.items():
            if str(exp["Transport"]).upper() in {"NDI", "RTMP"}:
                total_ip_mbps += float(exp["Calculated_Mbps_total"])
        threshold_val = capacity_mbps * (1.0 - safety_margin_pct / 100.0)

        def contains_number_approx(text: str, value: float) -> bool:
            candidates = {
                f"{value:.0f}",
                f"{value:.1f}",
                f"{value:.2f}",
                f"{value:.3f}",
            }
            return any(c in text for c in candidates)

        has_capacity = str(int(capacity_mbps)) in md
        has_safety = (f"{int(safety_margin_pct)}%" in md) or (str(int(safety_margin_pct)) in md)
        has_total_mbps = contains_number_approx(md, total_ip_mbps)
        has_threshold = contains_number_approx(md, threshold_val)
        if (has_capacity and has_safety and has_total_mbps) or (has_threshold and has_total_mbps):
            scores["recommendations_contains_bandwidth_summary"] = 1.0
        else:
            scores["recommendations_contains_bandwidth_summary"] = 0.0

        enc_ok_mentions = True
        enc_ok_mentions = enc_ok_mentions and (("hevc" in md_low) and (("unavailable" in md_low) or ("not available" in md_low) or ("not found" in md_low)))
        enc_ok_mentions = enc_ok_mentions and (("h264" in md_low) and ("available" in md_low))
        enc_ok_mentions = enc_ok_mentions and (("prores" in md_low) and (("software" in md_low) or ("sw-only" in md_low) or ("software-only" in md_low)))
        scores["recommendations_contains_encoder_summary"] = 1.0 if enc_ok_mentions else 0.0

        lines = [ln.strip() for ln in md.splitlines()]
        bullets = [ln for ln in lines if ln.startswith("- ") or ln.startswith("* ")]
        has_bullets = len(bullets) > 0
        mentions_guidance = any(("fallback" in ln.lower()) or ("software" in ln.lower()) or ("headroom" in ln.lower()) for ln in bullets)
        scores["recommendations_contains_bullets_with_guidance"] = 1.0 if (has_bullets and mentions_guidance) else 0.0
    else:
        scores["recommendations_file_present"] = 0.0
        scores["recommendations_contains_bandwidth_summary"] = 0.0
        scores["recommendations_contains_encoder_summary"] = 0.0
        scores["recommendations_contains_bullets_with_guidance"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()