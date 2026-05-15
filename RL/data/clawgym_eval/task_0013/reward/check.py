import json
import csv
import hashlib
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, Dict, Any, List


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _load_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def _read_csv_assets(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    if not path.exists():
        return None, "missing"
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required = ["asset_name", "width_px", "height_px", "color_hex", "roughness", "metallic"]
            if reader.fieldnames is None or any(h not in reader.fieldnames for h in required):
                return None, "missing_columns"
            rows = []
            for row in reader:
                try:
                    asset_name = row["asset_name"].strip()
                    width_px = int(row["width_px"])
                    height_px = int(row["height_px"])
                    color_hex = row["color_hex"].strip()
                except Exception:
                    return None, "bad_row"
                rows.append(
                    {
                        "asset_name": asset_name,
                        "width_px": width_px,
                        "height_px": height_px,
                        "color_hex": color_hex,
                        "roughness": row.get("roughness"),
                        "metallic": row.get("metallic"),
                    }
                )
            return rows, None
    except Exception as e:
        return None, str(e)


def _compute_sha256(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest(), None
    except Exception as e:
        return None, str(e)


def _png_dimensions(path: Path) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
    try:
        with path.open("rb") as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return None, "not_png"
            length_bytes = f.read(4)
            if len(length_bytes) != 4:
                return None, "short_length"
            length = int.from_bytes(length_bytes, "big")
            chunk_type = f.read(4)
            if chunk_type != b"IHDR":
                return None, "no_ihdr"
            if length != 13:
                return None, "ihdr_length"
            data = f.read(13)
            if len(data) != 13:
                return None, "short_ihdr"
            width = int.from_bytes(data[0:4], "big")
            height = int.from_bytes(data[4:8], "big")
            return (width, height), None
    except Exception as e:
        return None, str(e)


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if s.endswith("Z"):
        test = s[:-1] + "+00:00"
    else:
        test = s
    try:
        datetime.fromisoformat(test)
        return True
    except Exception:
        pass
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(?:\.\d+)?"
        r"(?:(?:Z)|(?:[+\-]\d{2}:\d{2}))?$"
    )
    return bool(pattern.match(s))


def _parse_hex_color(hex_str: str) -> Optional[Tuple[int, int, int]]:
    if not isinstance(hex_str, str):
        return None
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", hex_str.strip())
    if not m:
        return None
    hexval = m.group(1)
    r = int(hexval[0:2], 16)
    g = int(hexval[2:4], 16)
    b = int(hexval[4:6], 16)
    return (r, g, b)


def _normalize_rel_path_str(p: str) -> str:
    parts = Path(p).parts
    parts = tuple(part for part in parts if part != ".")
    return "/".join(parts)


def _get_validation_report_map(data: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    if isinstance(data, dict):
        mapping = {}
        for k, v in data.items():
            if isinstance(v, dict):
                mapping[k] = v
            else:
                return None
        return mapping
    if isinstance(data, list):
        mapping = {}
        for item in data:
            if not isinstance(item, dict):
                return None
            name = item.get("asset_name")
            if not isinstance(name, str):
                return None
            mapping[name] = item
        return mapping
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "design_doc_sections": 0.0,
        "design_doc_content": 0.0,
        "requirements_versions": 0.0,
        "script_path_and_cli": 0.0,
        "previews_generated": 0.0,
        "png_dimensions_match_csv": 0.0,
        "manifest_structure_and_fields": 0.0,
        "manifest_assets_sorted_and_paths_relative": 0.0,
        "manifest_hashes_match_files": 0.0,
        "validation_report_structure": 0.0,
        "validation_report_consistency": 0.0,
        "run_log_present_and_lines": 0.0,
        "email_bilingual_and_content": 0.0,
    }

    csv_path = workspace / "input" / "assets.csv"
    assets_rows, assets_err = _read_csv_assets(csv_path)
    expected_assets: List[Dict[str, Any]] = assets_rows or []
    expected_names = [r["asset_name"] for r in expected_assets]

    design_path = workspace / "docs" / "pipeline_design.md"
    design_text, design_err = _read_text_safe(design_path)
    if design_text is not None:
        lines = [ln.strip() for ln in design_text.splitlines()]
        has_title = any(ln.strip() == "# Environment Asset Prep PoC" for ln in lines)
        needed_sections = [
            "1. Goals",
            "2. Folder Structure",
            "3. Data Flow",
            "4. Dependencies",
            "5. Reproducibility",
            "6. Verification",
        ]
        has_sections = all(any(ln.startswith(sec) for ln in lines) for sec in needed_sections)
        if has_title and has_sections:
            scores["design_doc_sections"] = 1.0

        lower_text = design_text.lower()
        has_dirs = all(x in design_text for x in ["input/", "scripts/", "docs/", "out/"])
        has_keywords = all(
            kw in lower_text
            for kw in ["csv", "manifest", "preview", "validat", "size", "color"]
        )
        if has_dirs and has_keywords:
            scores["design_doc_content"] = 1.0

    req_path = workspace / "requirements.txt"
    req_text, req_err = _read_text_safe(req_path)
    if req_text is not None:
        entries = []
        for ln in req_text.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            entries.append(s)
        expected_set = {"Pillow>=10,<11", "numpy>=1.26,<2"}
        if set(entries) == expected_set and len(entries) == 2:
            scores["requirements_versions"] = 1.0

    script_path = workspace / "scripts" / "generate_assets.py"
    script_text, script_err = _read_text_safe(script_path)
    if script_text is not None:
        if ("--input" in script_text) and ("--out" in script_text):
            scores["script_path_and_cli"] = 1.0

    previews_ok_count = 0
    for name in expected_names:
        p = workspace / "out" / "previews" / f"{name}.png"
        if p.exists():
            previews_ok_count += 1
    if expected_names:
        scores["previews_generated"] = previews_ok_count / float(len(expected_names))

    dims_ok_count = 0
    for row in expected_assets:
        name = row["asset_name"]
        expected_w = row["width_px"]
        expected_h = row["height_px"]
        p = workspace / "out" / "previews" / f"{name}.png"
        dims, err = _png_dimensions(p) if p.exists() else (None, "missing")
        if dims is not None and dims[0] == expected_w and dims[1] == expected_h:
            dims_ok_count += 1
    if expected_assets:
        scores["png_dimensions_match_csv"] = dims_ok_count / float(len(expected_assets))

    manifest_path = workspace / "out" / "manifest.json"
    manifest_data, manifest_err = _load_json_safe(manifest_path)
    manifest_valid = False
    manifest_assets_list: List[Dict[str, Any]] = []
    manifest_asset_map: Dict[str, Dict[str, Any]] = {}
    if isinstance(manifest_data, dict):
        top_ok = (
            manifest_data.get("project") == "env_asset_preview_poc"
            and isinstance(manifest_data.get("assets"), list)
            and _is_iso8601(manifest_data.get("generated_at", ""))
        )
        if top_ok:
            assets_list = manifest_data.get("assets", [])
            per_asset_ok = True
            manifest_assets_list = assets_list
            for item in assets_list:
                if not isinstance(item, dict):
                    per_asset_ok = False
                    break
                required_keys = [
                    "asset_name",
                    "preview_path",
                    "width_px",
                    "height_px",
                    "color_hex",
                    "avg_color_hex",
                    "sha256",
                ]
                if any(k not in item for k in required_keys):
                    per_asset_ok = False
                    break
                if not isinstance(item["asset_name"], str):
                    per_asset_ok = False
                    break
                if not isinstance(item["preview_path"], str):
                    per_asset_ok = False
                    break
                if not isinstance(item["width_px"], int) or not isinstance(item["height_px"], int):
                    per_asset_ok = False
                    break
                if not isinstance(item["color_hex"], str) or not isinstance(item["avg_color_hex"], str):
                    per_asset_ok = False
                    break
                sha = item["sha256"]
                if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha or "") is not None):
                    per_asset_ok = False
                    break
                if _parse_hex_color(item["avg_color_hex"]) is None:
                    per_asset_ok = False
                    break
                manifest_asset_map[item["asset_name"]] = item
            if per_asset_ok and len(manifest_asset_map) == len(expected_assets):
                per_fields_ok = True
                for row in expected_assets:
                    name = row["asset_name"]
                    mi = manifest_asset_map.get(name)
                    if mi is None:
                        per_fields_ok = False
                        break
                    if mi["width_px"] != row["width_px"] or mi["height_px"] != row["height_px"]:
                        per_fields_ok = False
                        break
                    if mi["color_hex"] != row["color_hex"]:
                        per_fields_ok = False
                        break
                    pp = mi["preview_path"]
                    rel_ok = not Path(pp).is_absolute()
                    normalized = _normalize_rel_path_str(pp)
                    expected_rel = f"out/previews/{name}.png"
                    if not (rel_ok and normalized.endswith(expected_rel)):
                        per_fields_ok = False
                        break
                manifest_valid = per_fields_ok
            else:
                manifest_valid = False
        else:
            manifest_valid = False
    if manifest_valid:
        scores["manifest_structure_and_fields"] = 1.0

    if manifest_valid and manifest_assets_list:
        names_in_order = [a.get("asset_name") for a in manifest_assets_list]
        sorted_names = sorted(names_in_order)
        order_ok = names_in_order == sorted_names
        paths_relative_ok = all(
            not Path(a["preview_path"]).is_absolute()
            for a in manifest_assets_list
            if isinstance(a, dict) and "preview_path" in a
        )
        if order_ok and paths_relative_ok:
            scores["manifest_assets_sorted_and_paths_relative"] = 1.0

    hashes_ok_count = 0
    hashes_total = 0
    if manifest_valid:
        for name, item in manifest_asset_map.items():
            pp = item["preview_path"]
            file_path = workspace / Path(pp)
            hashes_total += 1
            digest, err = _compute_sha256(file_path)
            if digest is not None and digest.lower() == item["sha256"].lower():
                hashes_ok_count += 1
        if hashes_total > 0:
            scores["manifest_hashes_match_files"] = hashes_ok_count / float(hashes_total)

    vr_path = workspace / "out" / "validation_report.json"
    vr_data, vr_err = _load_json_safe(vr_path)
    vr_map: Optional[Dict[str, Dict[str, Any]]] = None
    if vr_data is not None:
        vr_map = _get_validation_report_map(vr_data)
    vr_structure_ok = False
    if vr_map is not None and expected_names:
        vr_structure_ok = True
        for name in expected_names:
            ent = vr_map.get(name)
            if ent is None:
                vr_structure_ok = False
                break
            if not isinstance(ent.get("size_match"), bool) or not isinstance(ent.get("color_match"), bool):
                vr_structure_ok = False
                break
    if vr_structure_ok:
        scores["validation_report_structure"] = 1.0

    vr_consistency_ok_count = 0
    vr_consistency_total = 0
    if vr_structure_ok and manifest_valid:
        for row in expected_assets:
            name = row["asset_name"]
            target_rgb = _parse_hex_color(row["color_hex"]) or (0, 0, 0)
            ent = vr_map.get(name)  # type: ignore
            mi = manifest_asset_map.get(name)
            file_path = workspace / "out" / "previews" / f"{name}.png"
            dims, err = _png_dimensions(file_path)
            expected_size_match = dims is not None and dims[0] == row["width_px"] and dims[1] == row["height_px"]
            avg_rgb = _parse_hex_color(mi["avg_color_hex"]) if mi else None
            if avg_rgb is not None:
                color_diff_ok = all(abs(avg_rgb[i] - target_rgb[i]) <= 5 for i in range(3))
            else:
                color_diff_ok = False
            expected_color_match = color_diff_ok
            vr_consistency_total += 2
            if isinstance(ent.get("size_match"), bool) and ent.get("size_match") == expected_size_match:
                vr_consistency_ok_count += 1
            if isinstance(ent.get("color_match"), bool) and ent.get("color_match") == expected_color_match:
                vr_consistency_ok_count += 1
        if vr_consistency_total > 0:
            scores["validation_report_consistency"] = vr_consistency_ok_count / float(vr_consistency_total)

    run_log_path = workspace / "out" / "run.log"
    run_log_text, run_log_err = _read_text_safe(run_log_path)
    if run_log_text is not None:
        lines = [ln for ln in run_log_text.splitlines() if ln.strip()]
        low = run_log_text.lower()
        mentions = sum(1 for kw in ["csv", "manifest", "validation", "preview", "sha256"] if kw in low)
        if len(lines) >= 3 and mentions >= 2:
            scores["run_log_present_and_lines"] = 1.0

    email_path = workspace / "out" / "email_to_producer_en_fr.txt"
    email_text, email_err = _read_text_safe(email_path)
    if email_text is not None:
        lines = email_text.splitlines()
        subject_present = any(re.match(r"^\s*(Subject|Sujet)\s*:", ln, flags=re.IGNORECASE) for ln in lines)
        bullets_present = any(re.match(r"^\s*[-*]\s+", ln) for ln in lines)
        deliverables_required = [
            "docs/pipeline_design.md",
            "scripts/generate_assets.py",
            "out/manifest.json",
            "out/validation_report.json",
        ]
        deliverables_ok = all(d in email_text for d in deliverables_required)
        pillow_ver = re.search(r"Pillow[^0-9]{0,10}([0-9]+\.[0-9]+(?:\.[0-9]+)?)", email_text, flags=re.IGNORECASE)
        numpy_ver = re.search(r"numpy[^0-9]{0,10}([0-9]+\.[0-9]+(?:\.[0-9]+)?)", email_text, flags=re.IGNORECASE)
        deps_ok = pillow_ver is not None and numpy_ver is not None
        lower_email = email_text.lower()
        en_tokens = ["subject", "hello", "status", "summary", "regards", "producer", "deliverables", "dependencies"]
        fr_tokens = ["sujet", "bonjour", "statut", "résumé", "livrables", "dépendances", "cordialement", "producteur"]
        en_present = any(tok in lower_email for tok in en_tokens)
        fr_present = any(tok in lower_email for tok in fr_tokens)
        sub_checks = [subject_present, bullets_present, deliverables_ok, deps_ok, en_present, fr_present]
        if sub_checks:
            scores["email_bilingual_and_content"] = sum(1.0 for b in sub_checks if b) / float(len(sub_checks))

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()