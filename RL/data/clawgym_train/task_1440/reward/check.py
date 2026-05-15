import json
import sys
import re
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List, Set
import zipfile


def _read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json_safe(p: Path) -> Optional[Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_sha256(p: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _file_size(p: Path) -> Optional[int]:
    try:
        return p.stat().st_size
    except Exception:
        return None


def _normalize_quotes(s: str) -> str:
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_simple_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    """
    Purpose-built YAML parser for provided config structure.
    Supports:
      - top-level scalar keys: app_name, app_version, copyright_holder, copyright_year
      - assets: list of dicts with keys 'path' (string) and 'include_in_package' (bool)
    Returns dict or None on failure.
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    config: Dict[str, Any] = {}
    assets: List[Dict[str, Any]] = []
    in_assets = False
    current_asset: Optional[Dict[str, Any]] = None

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_assets = False
            current_asset = None
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key == "assets":
                    in_assets = True
                    continue
                val = _normalize_quotes(val)
                if val.lower() == "true":
                    config[key] = True
                elif val.lower() == "false":
                    config[key] = False
                else:
                    config[key] = val
            continue

        if in_assets:
            if line.lstrip().startswith("-"):
                current_asset = {}
                assets.append(current_asset)
                after_dash = line.split("-", 1)[1].strip()
                if after_dash:
                    if ":" in after_dash and current_asset is not None:
                        k, v = after_dash.split(":", 1)
                        k = k.strip()
                        v = _normalize_quotes(v.strip())
                        if v.lower() == "true":
                            current_asset[k] = True
                        elif v.lower() == "false":
                            current_asset[k] = False
                        else:
                            current_asset[k] = v
                continue
            if current_asset is not None and ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = _normalize_quotes(v.strip())
                if v.lower() == "true":
                    current_asset[k] = True
                elif v.lower() == "false":
                    current_asset[k] = False
                else:
                    current_asset[k] = v
            continue

    config["assets"] = assets
    required_keys = {"app_name", "app_version", "copyright_holder", "copyright_year", "assets"}
    if not required_keys.issubset(config.keys()):
        return None
    for a in assets:
        if "path" not in a or "include_in_package" not in a:
            return None
        if not isinstance(a["path"], str):
            return None
        if not isinstance(a["include_in_package"], bool):
            if isinstance(a["include_in_package"], str):
                low = a["include_in_package"].lower()
                if low == "true":
                    a["include_in_package"] = True
                elif low == "false":
                    a["include_in_package"] = False
                else:
                    return None
            else:
                return None
    return config


def _extract_licenses_from_md(path: Path) -> Optional[List[str]]:
    """
    Extract SPDX license identifiers from markdown file lines of the form 'License: <ID>'.
    Returns unique IDs preserving first-seen order.
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    ids: List[str] = []
    seen: Set[str] = set()
    for m in re.finditer(r"License:\s*([A-Za-z0-9\.\-\+]+)", text):
        lic = m.group(1).strip()
        if lic and lic not in seen:
            ids.append(lic)
            seen.add(lic)
    return ids


def _load_spdx_ids(spdx_json_path: Path) -> Optional[Set[str]]:
    data = _read_json_safe(spdx_json_path)
    if data is None:
        return None
    licenses = data.get("licenses")
    if not isinstance(licenses, list):
        return None
    ids: Set[str] = set()
    for item in licenses:
        if isinstance(item, dict):
            lid = item.get("licenseId")
            if isinstance(lid, str):
                ids.add(lid)
    return ids


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def _read_zip_member_bytes(zip_path: Path, member_name: str) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open(member_name, "r") as f:
                return f.read()
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_present": 0.0,
        "external_spdx_valid": 0.0,
        "external_osi_valid": 0.0,
        "notice_generated": 0.0,
        "license_report_correct": 0.0,
        "manifest_correct": 0.0,
        "package_zip_contents": 0.0,
    }

    # Check script presence
    script_py = workspace / "scripts" / "build_release.py"
    script_sh = workspace / "scripts" / "build_release.sh"
    if script_py.is_file() or script_sh.is_file():
        scores["script_present"] = 1.0

    # Paths
    config_path = workspace / "release" / "config.yaml"
    allowed_path = workspace / "policy" / "allowed_licenses.json"
    third_party_md = workspace / "LICENSES" / "THIRD_PARTY_LICENSES.md"
    template_notice = workspace / "NOTICE" / "COPYRIGHT_NOTICE_TEMPLATE.md"

    external_spdx = workspace / "external" / "spdx" / "licenses.json"
    external_osi = workspace / "external" / "osi" / "open-source-definition.html"

    build_dir = workspace / "build" / "release"
    notice_output = build_dir / "NOTICE.md"
    report_path = build_dir / "license_validation_report.json"
    manifest_path = build_dir / "manifest.json"
    package_zip_path = build_dir / "package.zip"

    # Load inputs
    config = _parse_simple_yaml_config(config_path) if config_path.exists() else None
    licenses_used = _extract_licenses_from_md(third_party_md) if third_party_md.exists() else None
    allowed = _read_json_safe(allowed_path) if allowed_path.exists() else None
    allowed_ids: Optional[Set[str]] = None
    if isinstance(allowed, dict) and isinstance(allowed.get("allowed_spdx_ids"), list):
        allowed_ids = set([x for x in allowed.get("allowed_spdx_ids") if isinstance(x, str)])

    spdx_ids = _load_spdx_ids(external_spdx) if external_spdx.exists() else None

    # Check external SPDX validity: file exists, parse OK, and includes the used license IDs
    if spdx_ids is not None and licenses_used is not None:
        if all(lic in spdx_ids for lic in licenses_used):
            scores["external_spdx_valid"] = 1.0

    # Check external OSI validity: file exists and contains key phrases
    osi_text = _read_text_safe(external_osi) if external_osi.exists() else None
    if osi_text is not None:
        text_low = osi_text.lower()
        if ("open source definition" in text_low) and ("open source initiative" in text_low):
            scores["external_osi_valid"] = 1.0

    # NOTICE generation check
    if config is not None and template_notice.exists() and notice_output.exists():
        tmpl_text = _read_text_safe(template_notice)
        notice_text = _read_text_safe(notice_output)
        if tmpl_text is not None and notice_text is not None:
            expected_notice = tmpl_text
            expected_notice = expected_notice.replace("{{APP_NAME}}", str(config.get("app_name", "")))
            expected_notice = expected_notice.replace("{{APP_VERSION}}", str(config.get("app_version", "")))
            expected_notice = expected_notice.replace("{{HOLDER}}", str(config.get("copyright_holder", "")))
            expected_notice = expected_notice.replace("{{YEAR}}", str(config.get("copyright_year", "")))
            if _normalize_newlines(expected_notice) == _normalize_newlines(notice_text):
                scores["notice_generated"] = 1.0

    # License validation report correctness
    report = _read_json_safe(report_path) if report_path.exists() else None
    if (report is not None and isinstance(report, dict) and
            licenses_used is not None and allowed_ids is not None and spdx_ids is not None):
        lic_list = report.get("licenses_used")
        all_in_allowed = report.get("all_in_allowed")
        all_in_spdx = report.get("all_in_spdx")
        per_license = report.get("per_license")

        ok = True
        if not isinstance(lic_list, list) or not all(isinstance(x, str) for x in lic_list):
            ok = False
        if not isinstance(all_in_allowed, bool) or not isinstance(all_in_spdx, bool):
            ok = False
        if not isinstance(per_license, list):
            ok = False

        if ok:
            if set(lic_list) != set(licenses_used):
                ok = False

        if ok:
            per_map: Dict[str, Dict[str, Any]] = {}
            for item in per_license:
                if not isinstance(item, dict):
                    ok = False
                    break
                i = item.get("id")
                allowed_flag = item.get("allowed")
                in_spdx_flag = item.get("in_spdx")
                if not isinstance(i, str) or not isinstance(allowed_flag, bool) or not isinstance(in_spdx_flag, bool):
                    ok = False
                    break
                per_map[i] = {"allowed": allowed_flag, "in_spdx": in_spdx_flag}
            if ok:
                if set(per_map.keys()) != set(licenses_used):
                    ok = False
                else:
                    for i in licenses_used:
                        expected_allowed = i in allowed_ids
                        expected_in_spdx = i in spdx_ids
                        if per_map[i]["allowed"] != expected_allowed or per_map[i]["in_spdx"] != expected_in_spdx:
                            ok = False
                            break
                    if ok:
                        expected_all_allowed = all(i in allowed_ids for i in licenses_used)
                        expected_all_in_spdx = all(i in spdx_ids for i in licenses_used)
                        if all_in_allowed != expected_all_allowed or all_in_spdx != expected_all_in_spdx:
                            ok = False
        if ok:
            scores["license_report_correct"] = 1.0

    # Manifest correctness
    manifest = _read_json_safe(manifest_path) if manifest_path.exists() else None
    if (manifest is not None and isinstance(manifest, dict) and config is not None and
            licenses_used is not None and allowed_ids is not None and spdx_ids is not None):
        ok = True
        if manifest.get("app_name") != config.get("app_name"):
            ok = False
        if manifest.get("app_version") != config.get("app_version"):
            ok = False
        assets_cfg = [a for a in config.get("assets", []) if a.get("include_in_package") is True]
        assets_list = manifest.get("assets")
        if not isinstance(assets_list, list):
            ok = False
        else:
            expected_paths = [a["path"] for a in assets_cfg]
            manifest_paths = []
            for item in assets_list:
                if not isinstance(item, dict):
                    ok = False
                    break
                if "path" not in item or "size" not in item or "sha256" not in item:
                    ok = False
                    break
                pth = item["path"]
                if not isinstance(pth, str) or not isinstance(item["size"], int) or not isinstance(item["sha256"], str):
                    ok = False
                    break
                manifest_paths.append(pth)
                asset_file = workspace / pth
                actual_size = _file_size(asset_file)
                actual_sha = _compute_sha256(asset_file) if actual_size is not None else None
                if actual_size is None or actual_sha is None:
                    ok = False
                    break
                if item["size"] != actual_size or item["sha256"].lower() != actual_sha.lower():
                    ok = False
                    break
            if ok:
                if set(manifest_paths) != set(expected_paths):
                    ok = False

        summary = manifest.get("license_validation_summary")
        if not isinstance(summary, dict):
            ok = False
        else:
            expected_all_allowed = all(i in allowed_ids for i in licenses_used)
            expected_all_in_spdx = all(i in spdx_ids for i in licenses_used)
            expected_licenses_used_set = set(licenses_used)
            su_lics = summary.get("licenses_used")
            su_all_allowed = summary.get("all_in_allowed")
            su_all_in_spdx = summary.get("all_in_spdx")
            if (not isinstance(su_lics, list) or
                not isinstance(su_all_allowed, bool) or
                not isinstance(su_all_in_spdx, bool)):
                ok = False
            else:
                if set(su_lics) != expected_licenses_used_set:
                    ok = False
                if su_all_allowed != expected_all_allowed or su_all_in_spdx != expected_all_in_spdx:
                    ok = False
            if ok and report is not None and isinstance(report, dict):
                r_lics = report.get("licenses_used")
                r_all_allowed = report.get("all_in_allowed")
                r_all_in_spdx = report.get("all_in_spdx")
                if (isinstance(r_lics, list) and isinstance(r_all_allowed, bool) and isinstance(r_all_in_spdx, bool)):
                    if set(r_lics) != set(su_lics) or r_all_allowed != su_all_allowed or r_all_in_spdx != su_all_in_spdx:
                        ok = False

        if ok:
            scores["manifest_correct"] = 1.0

    # Package zip contents
    if package_zip_path.exists():
        try:
            if zipfile.is_zipfile(package_zip_path):
                with zipfile.ZipFile(package_zip_path, "r") as zf:
                    names = set(zf.namelist())
                    ok = True
                    if config is None:
                        ok = False
                    else:
                        expected_assets = [a["path"] for a in config.get("assets", []) if a.get("include_in_package") is True]
                        for ap in expected_assets:
                            if ap not in names:
                                ok = False
                                break
                    # Require exact paths inside the zip as specified
                    if "build/release/manifest.json" not in names:
                        ok = False
                    if "build/release/NOTICE.md" not in names:
                        ok = False
                    # docs folder files must exist and match external sources exactly
                    docs_spdx = "docs/licenses.json"
                    docs_osi = "docs/open-source-definition.html"
                    if docs_spdx not in names or docs_osi not in names:
                        ok = False
                    else:
                        if (workspace / "external" / "spdx" / "licenses.json").exists():
                            zip_spdx_bytes = _read_zip_member_bytes(package_zip_path, docs_spdx)
                            try:
                                ext_spdx_bytes = (workspace / "external" / "spdx" / "licenses.json").read_bytes()
                            except Exception:
                                ext_spdx_bytes = None
                            if zip_spdx_bytes is None or ext_spdx_bytes is None or zip_spdx_bytes != ext_spdx_bytes:
                                ok = False
                        else:
                            ok = False
                        if (workspace / "external" / "osi" / "open-source-definition.html").exists():
                            zip_osi_bytes = _read_zip_member_bytes(package_zip_path, docs_osi)
                            try:
                                ext_osi_bytes = (workspace / "external" / "osi" / "open-source-definition.html").read_bytes()
                            except Exception:
                                ext_osi_bytes = None
                            if zip_osi_bytes is None or ext_osi_bytes is None or zip_osi_bytes != ext_osi_bytes:
                                ok = False
                        else:
                            ok = False
                    if ok:
                        scores["package_zip_contents"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()