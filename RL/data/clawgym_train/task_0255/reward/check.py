import json
import re
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        data = path.read_text(encoding="utf-8")
        return data
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_log(log_text: str) -> dict:
    # Handle logs that may contain escaped \n literals
    if "\\n" in log_text and "\n" not in log_text:
        log_text = log_text.replace("\\n", "\n")
    lines = [ln.rstrip("\r") for ln in log_text.splitlines()]
    error_lines = [ln for ln in lines if ln.startswith("ERROR:")]
    warning_lines = [ln for ln in lines if ln.startswith("WARNING:")]
    summary_line = None
    for ln in reversed(lines):
        if ln.startswith("SUMMARY:"):
            summary_line = ln
            break

    s_err = None
    s_warn = None
    if summary_line:
        m = re.search(r"SUMMARY:\s*(\d+)\s+errors,\s*(\d+)\s+warnings", summary_line)
        if m:
            s_err = int(m.group(1))
            s_warn = int(m.group(2))
    return {
        "lines": lines,
        "error_lines": error_lines,
        "warning_lines": warning_lines,
        "summary_line": summary_line,
        "summary_errors": s_err,
        "summary_warnings": s_warn,
        "counted_errors": len(error_lines),
        "counted_warnings": len(warning_lines),
    }


def _counts_present(text: str, errors: int, warnings: int) -> bool:
    text_low = text.lower()

    # Find any occurrence of errors and warnings counts
    def find_numbers_for(label: str):
        nums = set()
        # patterns like "errors: 3" or "errors = 3" or "errors 3"
        for m in re.finditer(rf"{label}\s*[:=]?\s*(\d+)", text_low):
            try:
                nums.add(int(m.group(1)))
            except Exception:
                pass
        # patterns like "3 errors"
        for m in re.finditer(rf"(\d+)\s+{label}", text_low):
            try:
                nums.add(int(m.group(1)))
            except Exception:
                pass
        return nums

    errs = find_numbers_for("errors")
    warns = find_numbers_for("warnings")
    return (errors in errs) and (warnings in warns)


def _has_bullets(text: str, min_bullets: int = 3, max_bullets: int = 5) -> bool:
    bullets = 0
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets += 1
    return min_bullets <= bullets <= max_bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Input files
    in_renderer_path = workspace / "input" / "config" / "renderer.json"
    in_materials_path = workspace / "input" / "config" / "materials.json"
    in_log_path = workspace / "input" / "logs" / "build_output.txt"

    # Output files
    out_report_path = workspace / "output" / "analysis_report.md"
    out_renderer_fixed_path = workspace / "output" / "renderer.fixed.json"
    out_materials_fixed_path = workspace / "output" / "materials.fixed.json"
    out_message_path = workspace / "output" / "message_to_artist.txt"

    # Load inputs
    renderer_in = _load_json(in_renderer_path)
    materials_in = _load_json(in_materials_path)
    log_text = _read_text(in_log_path)
    parsed_log = _parse_log(log_text) if log_text else {
        "lines": [],
        "error_lines": [],
        "warning_lines": [],
        "summary_line": None,
        "summary_errors": None,
        "summary_warnings": None,
        "counted_errors": 0,
        "counted_warnings": 0,
    }

    # Pre-compute expected values from inputs/logs
    expected_counted_errors = parsed_log["counted_errors"]
    expected_counted_warnings = parsed_log["counted_warnings"]
    expected_summary_errors = parsed_log["summary_errors"]
    expected_summary_warnings = parsed_log["summary_warnings"]
    has_summary = parsed_log["summary_line"] is not None

    # Prepare scores
    scores = {
        "analysis_report_exists": 0.0,
        "report_has_required_sections": 0.0,
        "summary_counts_from_log_correctly_reported": 0.0,
        "summary_line_counts_correctly_reported": 0.0,
        "summary_match_vs_discrepancy_statement": 0.0,
        "report_includes_all_issue_lines_verbatim": 0.0,
        "issues_mention_material_names": 0.0,
        "issues_mention_issue_types_keywords": 0.0,
        "report_includes_proposed_fixes_section": 0.0,
        "config_changes_listed": 0.0,
        "config_changes_mapped_to_log_lines": 0.0,
        "renderer_fixed_exists_and_valid_json": 0.0,
        "renderer_fixed_updates_for_ktx2": 0.0,
        "renderer_added_allow_missing_normal_maps_true": 0.0,
        "renderer_preserved_pipeline_and_tangent_space": 0.0,
        "renderer_no_unrelated_new_fields": 0.0,
        "materials_fixed_exists_and_valid_json": 0.0,
        "materials_albedo_srgb_true_all": 0.0,
        "materials_normal_format_opengl_for_directx_materials": 0.0,
        "materials_preserve_missing_paths_for_glass": 0.0,
        "materials_no_new_fields": 0.0,
        "message_exists": 0.0,
        "message_word_count_limit": 0.0,
        "message_mentions_required_topics": 0.0,
        "message_mentions_both_albedo_paths": 0.0,
        "message_has_3_to_5_bullets": 0.0,
    }

    # Analysis report checks
    report_text = _read_text(out_report_path)
    if out_report_path.exists() and report_text:
        scores["analysis_report_exists"] = 1.0

        # Required sections
        has_summary_sec = "summary" in report_text.lower()
        has_issues_sec = "issues" in report_text.lower()
        has_fixes_sec = "proposed fixes" in report_text.lower()
        if has_summary_sec and has_issues_sec and has_fixes_sec:
            scores["report_has_required_sections"] = 1.0

        # Counts from log present
        if expected_counted_errors is not None and expected_counted_warnings is not None:
            if _counts_present(report_text, expected_counted_errors, expected_counted_warnings):
                scores["summary_counts_from_log_correctly_reported"] = 1.0

        # SUMMARY line counts present (require presence of 'SUMMARY' mention and the counts)
        if has_summary and ("summary" in report_text.lower()):
            if expected_summary_errors is not None and expected_summary_warnings is not None:
                # Presence of summary counts and the word SUMMARY somewhere
                if ("summary" in report_text.lower()) and _counts_present(report_text, expected_summary_errors, expected_summary_warnings):
                    scores["summary_line_counts_correctly_reported"] = 1.0

        # Match vs discrepancy statement
        counts_match = (expected_counted_errors == expected_summary_errors) and (expected_counted_warnings == expected_summary_warnings)
        if counts_match:
            if re.search(r"\bmatch", report_text, flags=re.IGNORECASE):
                scores["summary_match_vs_discrepancy_statement"] = 1.0
        else:
            if re.search(r"discrep", report_text, flags=re.IGNORECASE) or re.search(r"differ", report_text, flags=re.IGNORECASE):
                scores["summary_match_vs_discrepancy_statement"] = 1.0

        # Report includes all issue lines verbatim (all ERROR and WARNING)
        all_lines_present = True
        for ln in parsed_log["error_lines"] + parsed_log["warning_lines"]:
            if ln not in report_text:
                all_lines_present = False
                break
        if all_lines_present and (parsed_log["error_lines"] or parsed_log["warning_lines"]):
            scores["report_includes_all_issue_lines_verbatim"] = 1.0

        # Issues mention material names (Props/Chair and Props/Glass)
        mentions_chair = ("Props/Chair" in report_text) or ("chair_albedo" in report_text)
        mentions_glass = ("Props/Glass" in report_text) or ("glass_albedo" in report_text)
        if mentions_chair and mentions_glass:
            scores["issues_mention_material_names"] = 1.0

        # Issues mention issue type keywords
        keywords_ok = 0
        kw_checks = [
            re.search(r"tangent", report_text, flags=re.IGNORECASE),
            re.search(r"\bsrgb\b", report_text, flags=re.IGNORECASE),
            re.search(r"missing normal", report_text, flags=re.IGNORECASE),
            re.search(r"occlusion", report_text, flags=re.IGNORECASE),
            (re.search(r"yflip", report_text, flags=re.IGNORECASE) or re.search(r"y_flip", report_text, flags=re.IGNORECASE)),
            re.search(r"normalizeNormalMaps", report_text),
        ]
        for k in kw_checks:
            if k:
                keywords_ok += 1
        if keywords_ok >= 4:
            scores["issues_mention_issue_types_keywords"] = 1.0

        # Proposed fixes section present
        if has_fixes_sec:
            scores["report_includes_proposed_fixes_section"] = 1.0

        # Config changes listed: look for "Config changes" and "->" and specific changes
        cfg_changes_present = "config changes" in report_text.lower()
        arrow_present = "->" in report_text
        # Expected explicit change mentions
        change_normal_format = bool(re.search(r"DirectX\s*->\s*OpenGL", report_text))
        change_albedo_srgb = bool(re.search(r"albedoSRGB[^-\n\r]*->\s*true", report_text, flags=re.IGNORECASE)) or bool(re.search(r"albedoSRGB\s*:\s*false\s*->\s*true", report_text, flags=re.IGNORECASE))
        change_yflip = bool(re.search(r"yFlip[^-\n\r]*->\s*false", report_text))
        change_normalize = bool(re.search(r"normalizeNormalMaps[^-\n\r]*->\s*true", report_text))
        mentions_allow_missing = "allowMissingNormalMaps" in report_text

        if cfg_changes_present and arrow_present and change_normal_format and change_albedo_srgb and change_yflip and change_normalize and mentions_allow_missing:
            scores["config_changes_listed"] = 1.0

        # Mapping config changes to relevant log lines (presence of both change text and the exact related log line somewhere)
        mapping_ok = True
        # Map: normal format -> tangent space mismatch ERROR
        ln_tangent = "ERROR: Normal map tangent space mismatch: material 'Props/Chair' normalFormat=DirectX while renderer normalMapTangentSpace=OpenGL. This can invert Y (green) channel."
        if not (change_normal_format and (ln_tangent in report_text)):
            mapping_ok = False
        # Map: albedo sRGB -> albedo warning
        ln_srgb = "WARNING: Albedo texture 'assets/props/chair_albedo.png' loaded without sRGB conversion (albedoSRGB=false). Expected sRGB for color textures."
        if not (change_albedo_srgb and (ln_srgb in report_text)):
            mapping_ok = False
        # Map: yFlip -> y_flip warning
        ln_yflip = "WARNING: basisu: --y_flip is ignored for KTX2; may break normal map orientation. Detected ktx2=true and yFlip=true."
        if not (change_yflip and (ln_yflip in report_text)):
            mapping_ok = False
        # Map: normalizeNormalMaps -> KTX2 requires tangent space orientation error
        ln_normalize = "ERROR: basisu: KTX2 requires normal maps be in tangent space orientation of pipeline. 'normalizeNormalMaps' is false."
        if not (change_normalize and (ln_normalize in report_text)):
            mapping_ok = False
        # Map: allowMissingNormalMaps -> TIP line
        ln_tip = "TIP: To treat missing normals as non-fatal, set renderer.allowMissingNormalMaps=true"
        if not (mentions_allow_missing and (ln_tip in report_text)):
            mapping_ok = False
        if mapping_ok:
            scores["config_changes_mapped_to_log_lines"] = 1.0

    # Renderer fixed JSON checks
    renderer_fixed = _load_json(out_renderer_fixed_path)
    if renderer_fixed is not None and isinstance(renderer_fixed, dict):
        scores["renderer_fixed_exists_and_valid_json"] = 1.0

        # Load original for comparison
        if renderer_in is not None and isinstance(renderer_in, dict):
            rin = renderer_in.get("renderer", {})
            rfix = renderer_fixed.get("renderer", {})
            opt_in = rin.get("optimizeTextures", {})
            opt_fix = rfix.get("optimizeTextures", {})

            # Updates for ktx2: if ktx2 true, yFlip false and normalizeNormalMaps true
            ok_ktx2 = False
            if isinstance(opt_fix, dict) and opt_fix.get("ktx2") is True:
                if opt_fix.get("yFlip") is False and opt_fix.get("normalizeNormalMaps") is True:
                    ok_ktx2 = True
            scores["renderer_fixed_updates_for_ktx2"] = 1.0 if ok_ktx2 else 0.0

            # Added allowMissingNormalMaps true
            allow_missing_ok = rfix.get("allowMissingNormalMaps") is True
            scores["renderer_added_allow_missing_normal_maps_true"] = 1.0 if allow_missing_ok else 0.0

            # Preserved pipeline and tangent space
            preserved = (rfix.get("pipeline") == rin.get("pipeline") == "PBR") and (rfix.get("normalMapTangentSpace") == "OpenGL")
            scores["renderer_preserved_pipeline_and_tangent_space"] = 1.0 if preserved else 0.0

            # No unrelated new fields (renderer block keys equal to original + allowMissingNormalMaps; optimizeTextures keys unchanged)
            orig_r_keys = set(rin.keys())
            fix_r_keys = set(rfix.keys())
            allowed = orig_r_keys | {"allowMissingNormalMaps"}
            no_extra_renderer = fix_r_keys.issubset(allowed) and orig_r_keys.issubset(fix_r_keys)
            # optimizeTextures keys same as original
            orig_opt_keys = set(opt_in.keys()) if isinstance(opt_in, dict) else set()
            fix_opt_keys = set(opt_fix.keys()) if isinstance(opt_fix, dict) else set()
            no_extra_opt = (orig_opt_keys == fix_opt_keys) if orig_opt_keys else (fix_opt_keys == {"compressor", "ktx2", "uastc", "normalizeNormalMaps", "yFlip"})
            scores["renderer_no_unrelated_new_fields"] = 1.0 if (no_extra_renderer and no_extra_opt) else 0.0

    # Materials fixed JSON checks
    materials_fixed = _load_json(out_materials_fixed_path)
    if materials_fixed is not None and isinstance(materials_fixed, dict):
        scores["materials_fixed_exists_and_valid_json"] = 1.0

        if materials_in is not None and isinstance(materials_in, dict):
            min_list = materials_in.get("materials", [])
            mfix_list = materials_fixed.get("materials", [])
            # Map by name
            in_by_name = {m.get("name"): m for m in min_list if isinstance(m, dict)}
            fix_by_name = {m.get("name"): m for m in mfix_list if isinstance(m, dict)}

            # Ensure same materials set
            same_names = set(in_by_name.keys()) == set(fix_by_name.keys()) and len(in_by_name) == len(fix_by_name) == len(min_list) == len(mfix_list)
            # Albedo sRGB true for all
            albedo_ok = True
            normal_format_ok = True
            missing_paths_ok = True
            no_new_fields_ok = True

            if same_names:
                for name, orig in in_by_name.items():
                    fix = fix_by_name.get(name, {})
                    # Albedo sRGB
                    if fix.get("albedoSRGB") is not True:
                        albedo_ok = False
                    # Normal format: if original had DirectX, must be OpenGL in fixed
                    if "normalFormat" in orig and orig.get("normalFormat") == "DirectX":
                        if fix.get("normalFormat") != "OpenGL":
                            normal_format_ok = False
                    # Preserve missing paths for glass (normal "" and occlusion "")
                    if name == "Props/Glass":
                        if fix.get("normal", None) != "":
                            missing_paths_ok = False
                        if fix.get("occlusion", None) != "":
                            missing_paths_ok = False
                    # No new fields per material
                    orig_keys = set(orig.keys())
                    fix_keys = set(fix.keys())
                    # Must be equal sets (no new fields added or removed)
                    if orig_keys != fix_keys:
                        no_new_fields_ok = False
            else:
                albedo_ok = False
                normal_format_ok = False
                missing_paths_ok = False
                no_new_fields_ok = False

            scores["materials_albedo_srgb_true_all"] = 1.0 if albedo_ok else 0.0
            scores["materials_normal_format_opengl_for_directx_materials"] = 1.0 if normal_format_ok else 0.0
            scores["materials_preserve_missing_paths_for_glass"] = 1.0 if missing_paths_ok else 0.0
            scores["materials_no_new_fields"] = 1.0 if no_new_fields_ok else 0.0

    # Message to artist checks
    msg_text = _read_text(out_message_path)
    if out_message_path.exists() and msg_text:
        scores["message_exists"] = 1.0
        words = re.findall(r"\S+", msg_text)
        if len(words) <= 190:
            scores["message_word_count_limit"] = 1.0
        # Mentions required topics: OpenGL tangent space and normals
        mentions_opengl = re.search(r"OpenGL", msg_text) is not None
        mentions_tangent = re.search(r"tangent", msg_text, flags=re.IGNORECASE) is not None
        mentions_normal = re.search(r"normal", msg_text, flags=re.IGNORECASE) is not None
        if mentions_opengl and mentions_tangent and mentions_normal:
            scores["message_mentions_required_topics"] = 1.0
        # Mentions both albedo paths
        has_chair_albedo = "assets/props/chair_albedo.png" in msg_text
        has_glass_albedo = "assets/props/glass_albedo.png" in msg_text
        if has_chair_albedo and has_glass_albedo:
            scores["message_mentions_both_albedo_paths"] = 1.0
        # Bullets
        if _has_bullets(msg_text, 3, 5):
            scores["message_has_3_to_5_bullets"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()