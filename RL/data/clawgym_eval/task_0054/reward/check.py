import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from xml.etree import ElementTree as ET


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_csv_dict(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
        return rows, None
    except Exception as e:
        return None, str(e)


def _parse_gradle_dependencies(text: str) -> List[Tuple[str, str, str]]:
    results: List[Tuple[str, str, str]] = []
    pattern = re.compile(r"^\s*(?:api|implementation|compile|runtimeOnly|compileOnly|testImplementation|androidTestImplementation)\s+['\"]([^'\"\s]+)['\"]", re.MULTILINE)
    for m in pattern.finditer(text):
        coord = m.group(1).strip()
        parts = coord.split(":")
        if len(parts) >= 3:
            group_artifact = ":".join(parts[0:2])
            version = parts[2]
            full = f"{group_artifact}:{version}"
            results.append((group_artifact, version, full))
    return results


def _parse_pubspec_dependencies(text: str) -> List[Tuple[str, str]]:
    lines = text.splitlines()
    deps_started = False
    results: List[Tuple[str, str]] = []
    indent_level: Optional[int] = None
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not deps_started:
            if re.match(r"^\s*dependencies\s*:\s*$", line):
                deps_started = True
                continue
        else:
            if re.match(r"^\S.*:\s*$", line) and not line.strip().startswith("-"):
                break
            if not line.strip() or line.strip().startswith("#"):
                continue
            if indent_level is None:
                m = re.match(r"^(\s+)", line)
                indent_level = len(m.group(1)) if m else 2
            if len(line) - len(line.lstrip(" ")) < (indent_level or 0):
                break
            stripped = line.strip()
            if re.match(r"^[\w\-\_]+:\s*$", stripped):
                continue
            kv = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*([^\s].*)$", stripped)
            if kv:
                name = kv.group(1).strip()
                value = kv.group(2).strip()
                if " #" in value:
                    value = value.split(" #", 1)[0].strip()
                if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
                    value = value[1:-1]
                if value and not value.endswith(":"):
                    results.append((name, value))
    return results


def _parse_manifest(xml_text: str) -> Tuple[Optional[bool], Optional[List[str]]]:
    try:
        root = ET.fromstring(xml_text)
        uses_cleartext = False
        app = root.find("application")
        if app is not None:
            v = app.get("{http://schemas.android.com/apk/res/android}usesCleartextTraffic")
            if v is not None:
                uses_cleartext = (v.lower() == "true")
        perms = []
        for perm in root.findall("uses-permission"):
            name = perm.get("{http://schemas.android.com/apk/res/android}name")
            if name:
                perms.append(name)
        return uses_cleartext, perms
    except Exception:
        return None, None


def _load_permission_risk_map(csv_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    m: Dict[str, Dict[str, str]] = {}
    for row in csv_rows:
        perm = (row.get("permission") or "").strip()
        risk = (row.get("risk_level") or "").strip()
        desc = (row.get("description") or "").strip()
        if perm:
            m[perm] = {"risk_level": risk if risk else "unknown", "description": desc}
    return m


def _compute_expected(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    gradle_path = workspace / "input" / "android" / "app" / "build.gradle"
    manifest_path = workspace / "input" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    pubspec_path = workspace / "input" / "flutter" / "pubspec.yaml"
    advisories_path = workspace / "input" / "security" / "advisories.json"
    perm_csv_path = workspace / "input" / "security" / "permission_risk.csv"

    gradle_text = _read_text(gradle_path)
    manifest_text = _read_text(manifest_path)
    pubspec_text = _read_text(pubspec_path)
    advisories, _ = _load_json(advisories_path)
    perm_rows, _ = _load_csv_dict(perm_csv_path)

    if any(x is None for x in [gradle_text, manifest_text, pubspec_text]) or advisories is None or perm_rows is None:
        return None, "Missing or unreadable input files"

    gradle_deps = _parse_gradle_dependencies(gradle_text)
    pub_deps = _parse_pubspec_dependencies(pubspec_text)
    uses_cleartext, perm_list = _parse_manifest(manifest_text)

    if uses_cleartext is None or perm_list is None:
        return None, "Malformed AndroidManifest.xml"

    perm_map = _load_permission_risk_map(perm_rows)

    expected_dependencies: List[Dict[str, Any]] = []
    gradle_adv: Dict[str, Dict[str, Any]] = advisories.get("gradle", {})
    for group_artifact, version, full in gradle_deps:
        adv_entry = gradle_adv.get(group_artifact)
        vulnerable = False
        advisory_ids: List[str] = []
        min_safe_version = None
        if adv_entry:
            vuln_versions = adv_entry.get("vulnerable_versions") or []
            if version in vuln_versions:
                vulnerable = True
                advisory_ids = list(adv_entry.get("advisory_ids") or [])
                min_safe_version = adv_entry.get("min_safe_version")
        dep = {
            "ecosystem": "gradle",
            "name": full,
            "version": version,
            "vulnerable": vulnerable,
            "advisory_ids": advisory_ids,
            "min_safe_version": min_safe_version if vulnerable else None,
        }
        expected_dependencies.append(dep)

    pub_adv: Dict[str, Dict[str, Any]] = advisories.get("pub", {})
    for name, version in pub_deps:
        adv_entry = pub_adv.get(name)
        vulnerable = False
        advisory_ids: List[str] = []
        min_safe_version = None
        if adv_entry:
            vuln_versions = adv_entry.get("vulnerable_versions") or []
            if version in vuln_versions:
                vulnerable = True
                advisory_ids = list(adv_entry.get("advisory_ids") or [])
                min_safe_version = adv_entry.get("min_safe_version")
        dep = {
            "ecosystem": "pub",
            "name": name,
            "version": version,
            "vulnerable": vulnerable,
            "advisory_ids": advisory_ids,
            "min_safe_version": min_safe_version if vulnerable else None,
        }
        expected_dependencies.append(dep)

    expected_permissions: List[Dict[str, Any]] = []
    for p in perm_list:
        info = perm_map.get(p)
        if info:
            risk_level = info.get("risk_level", "unknown") or "unknown"
            description = info.get("description", "") or ""
        else:
            risk_level = "unknown"
            description = ""
        expected_permissions.append({
            "name": p,
            "risk_level": risk_level,
            "description": description
        })

    total_deps = len(expected_dependencies)
    vulnerable_count = sum(1 for d in expected_dependencies if d.get("vulnerable") is True)
    high_risk_perm_count = sum(1 for perm in expected_permissions if perm.get("risk_level") == "high")
    cleartext_enabled = bool(uses_cleartext)

    expected = {
        "dependencies": expected_dependencies,
        "manifest": {
            "uses_cleartext_traffic": cleartext_enabled,
            "permissions": expected_permissions
        },
        "summary": {
            "total_dependencies": total_deps,
            "vulnerable_dependencies_count": vulnerable_count,
            "high_risk_permissions_count": high_risk_perm_count,
            "cleartext_traffic_enabled": cleartext_enabled
        }
    }
    return expected, None


def _canonicalize_dependencies_list(deps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    canon = []
    for d in deps:
        canon.append({
            "ecosystem": d.get("ecosystem"),
            "name": d.get("name"),
            "version": d.get("version"),
            "vulnerable": d.get("vulnerable"),
            "advisory_ids": list(d.get("advisory_ids") or []),
            "min_safe_version": d.get("min_safe_version", None),
        })
    return sorted(canon, key=lambda x: (str(x.get("ecosystem")), str(x.get("name")), str(x.get("version"))))


def _canonicalize_permissions_list(perms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    canon = []
    for p in perms:
        canon.append({
            "name": p.get("name"),
            "risk_level": p.get("risk_level"),
            "description": p.get("description", "") or ""
        })
    return sorted(canon, key=lambda x: str(x.get("name")))


def _normalize_csv_row(row: Dict[str, str]) -> Dict[str, str]:
    ecosystem = (row.get("ecosystem") or "").strip()
    name = (row.get("name") or "").strip()
    version = (row.get("version") or "").strip()
    msv = (row.get("min_safe_version") or "").strip()
    advis = (row.get("advisory_ids") or "").strip()
    if advis:
        parts = [p.strip() for p in advis.split("|") if p.strip()]
        parts_sorted = sorted(parts)
        advis_norm = "|".join(parts_sorted)
    else:
        advis_norm = ""
    return {
        "ecosystem": ecosystem,
        "name": name,
        "version": version,
        "min_safe_version": msv,
        "advisory_ids": advis_norm
    }


def _expected_vulnerable_rows(expected: dict) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for d in expected.get("dependencies", []):
        if d.get("vulnerable") is True:
            advis_ids = d.get("advisory_ids") or []
            advis_sorted = sorted([str(a) for a in advis_ids])
            rows.append({
                "ecosystem": str(d.get("ecosystem")),
                "name": str(d.get("name")),
                "version": str(d.get("version")),
                "min_safe_version": "" if d.get("min_safe_version") in (None, "") else str(d.get("min_safe_version")),
                "advisory_ids": "|".join(advis_sorted)
            })
    rows_sorted = sorted(rows, key=lambda r: (r["ecosystem"], r["name"], r["version"]))
    return rows_sorted


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "security_audit_json_present": 0.0,
        "security_audit_json_dependencies_correct": 0.0,
        "security_audit_json_manifest_correct": 0.0,
        "security_audit_json_summary_correct": 0.0,
        "vulnerable_csv_present": 0.0,
        "vulnerable_csv_content_correct": 0.0,
        "csv_matches_json_vulnerable_set": 0.0,
    }

    expected, _ = _compute_expected(workspace)
    audit_json_path = workspace / "output" / "security_audit.json"
    vuln_csv_path = workspace / "output" / "vulnerable_dependencies.csv"

    produced_json, _ = _load_json(audit_json_path)
    if produced_json is not None:
        scores["security_audit_json_present"] = 1.0
    else:
        scores["security_audit_json_present"] = 0.0

    if expected is not None and produced_json is not None:
        produced_deps = produced_json.get("dependencies")
        if isinstance(produced_deps, list):
            canon_produced = _canonicalize_dependencies_list(produced_deps)
            canon_expected = _canonicalize_dependencies_list(expected.get("dependencies", []))
            for item in canon_produced:
                item["advisory_ids"] = sorted([str(x) for x in item.get("advisory_ids", [])])
                if item.get("min_safe_version", None) == "":
                    item["min_safe_version"] = ""
            for item in canon_expected:
                item["advisory_ids"] = sorted([str(x) for x in item.get("advisory_ids", [])])
                if not item.get("vulnerable"):
                    item["min_safe_version"] = None
            if canon_produced == canon_expected:
                scores["security_audit_json_dependencies_correct"] = 1.0

        produced_manifest = produced_json.get("manifest")
        if isinstance(produced_manifest, dict):
            uct = produced_manifest.get("uses_cleartext_traffic")
            perms = produced_manifest.get("permissions")
            manifest_ok = True
            if not isinstance(uct, bool):
                manifest_ok = False
            if not isinstance(perms, list):
                manifest_ok = False
            else:
                canon_prod_perms = _canonicalize_permissions_list(perms)
                canon_exp_perms = _canonicalize_permissions_list(expected.get("manifest", {}).get("permissions", []))
                if canon_prod_perms != canon_exp_perms:
                    manifest_ok = False
            if manifest_ok:
                if bool(uct) != bool(expected.get("manifest", {}).get("uses_cleartext_traffic")):
                    manifest_ok = False
            if manifest_ok:
                scores["security_audit_json_manifest_correct"] = 1.0

        produced_summary = produced_json.get("summary")
        if isinstance(produced_summary, dict):
            keys_ok = all(k in produced_summary for k in ["total_dependencies", "vulnerable_dependencies_count", "high_risk_permissions_count", "cleartext_traffic_enabled"])
            if keys_ok:
                try:
                    td = int(produced_summary.get("total_dependencies"))
                    vc = int(produced_summary.get("vulnerable_dependencies_count"))
                    hp = int(produced_summary.get("high_risk_permissions_count"))
                    cte = produced_summary.get("cleartext_traffic_enabled")
                    if not isinstance(cte, bool):
                        raise ValueError("cte not bool")
                except Exception:
                    keys_ok = False
            if keys_ok:
                exp_summary = expected.get("summary", {})
                exp_td = int(exp_summary.get("total_dependencies", -1))
                exp_vc = int(exp_summary.get("vulnerable_dependencies_count", -1))
                exp_hp = int(exp_summary.get("high_risk_permissions_count", -1))
                exp_cte = bool(exp_summary.get("cleartext_traffic_enabled"))
                matches_expected = (td == exp_td and vc == exp_vc and hp == exp_hp and cte == exp_cte)

                internal_ok = False
                if isinstance(produced_json.get("dependencies"), list) and isinstance(produced_json.get("manifest"), dict):
                    prod_deps_list = produced_json.get("dependencies")
                    prod_perm_list = produced_json.get("manifest", {}).get("permissions")
                    prod_manifest_cleartext = produced_json.get("manifest", {}).get("uses_cleartext_traffic")
                    try:
                        internal_td = len(prod_deps_list)
                        internal_vc = sum(1 for d in prod_deps_list if isinstance(d, dict) and d.get("vulnerable") is True)
                        internal_hp = sum(1 for p in (prod_perm_list or []) if isinstance(p, dict) and p.get("risk_level") == "high")
                        internal_cte = bool(prod_manifest_cleartext)
                        if internal_td == td and internal_vc == vc and internal_hp == hp and internal_cte == cte:
                            internal_ok = True
                    except Exception:
                        internal_ok = False
                if matches_expected and internal_ok:
                    scores["security_audit_json_summary_correct"] = 1.0

    if vuln_csv_path.exists():
        try:
            with vuln_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows and rows[0] == ["ecosystem", "name", "version", "min_safe_version", "advisory_ids"]:
                scores["vulnerable_csv_present"] = 1.0
                csv_rows, _ = _load_csv_dict(vuln_csv_path)
                if csv_rows is not None:
                    norm_rows = [_normalize_csv_row(r) for r in csv_rows]
                    if expected is not None:
                        exp_rows = _expected_vulnerable_rows(expected)
                        exp_norm_rows = []
                        for r in exp_rows:
                            exp_norm_rows.append({
                                "ecosystem": r["ecosystem"],
                                "name": r["name"],
                                "version": r["version"],
                                "min_safe_version": r["min_safe_version"],
                                "advisory_ids": r["advisory_ids"],
                            })
                        norm_rows_sorted = sorted(norm_rows, key=lambda r: (r["ecosystem"], r["name"], r["version"]))
                        exp_norm_rows_sorted = sorted(exp_norm_rows, key=lambda r: (r["ecosystem"], r["name"], r["version"]))
                        if norm_rows_sorted == exp_norm_rows_sorted:
                            scores["vulnerable_csv_content_correct"] = 1.0
            else:
                scores["vulnerable_csv_present"] = 0.0
        except Exception:
            scores["vulnerable_csv_present"] = 0.0
    else:
        scores["vulnerable_csv_present"] = 0.0

    if expected is not None and produced_json is not None and (workspace / "output" / "vulnerable_dependencies.csv").exists():
        csv_rows, _ = _load_csv_dict(vuln_csv_path)
        if csv_rows is not None:
            norm_csv = [_normalize_csv_row(r) for r in csv_rows]
            prod_deps = produced_json.get("dependencies")
            if isinstance(prod_deps, list):
                prod_vuln_rows = []
                for d in prod_deps:
                    if isinstance(d, dict) and d.get("vulnerable") is True:
                        ecosystem = str(d.get("ecosystem"))
                        name = str(d.get("name"))
                        version = str(d.get("version"))
                        msv = "" if d.get("min_safe_version") in (None, "") else str(d.get("min_safe_version"))
                        advis = d.get("advisory_ids") or []
                        advis_norm = "|".join(sorted([str(a) for a in advis]))
                        prod_vuln_rows.append({
                            "ecosystem": ecosystem,
                            "name": name,
                            "version": version,
                            "min_safe_version": msv,
                            "advisory_ids": advis_norm
                        })
                norm_csv_sorted = sorted(norm_csv, key=lambda r: (r["ecosystem"], r["name"], r["version"]))
                prod_vuln_sorted = sorted(prod_vuln_rows, key=lambda r: (r["ecosystem"], r["name"], r["version"]))
                if norm_csv_sorted == prod_vuln_sorted:
                    scores["csv_matches_json_vulnerable_set"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()