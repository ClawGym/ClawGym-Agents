import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _load_json_safe(path: Path) -> Optional[Any]:
    txt = _read_text_safe(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def _parse_csproj(path: Path) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return None
    # Handle potential XML namespaces by stripping them
    def strip_ns(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    # Extract TargetFramework
    target_framework = None
    for prop_group in root.findall(".//"):
        if strip_ns(prop_group.tag) == "PropertyGroup":
            for child in prop_group:
                if strip_ns(child.tag) == "TargetFramework":
                    if child.text:
                        target_framework = child.text.strip()
                        break
            if target_framework:
                break

    if not target_framework:
        return None

    # Extract PackageReference (Include, Version attributes)
    packages: List[Dict[str, str]] = []
    for item_group in root.findall(".//"):
        if strip_ns(item_group.tag) == "ItemGroup":
            for child in item_group:
                if strip_ns(child.tag) == "PackageReference":
                    name = child.attrib.get("Include")
                    version = child.attrib.get("Version")
                    if name is not None and version is not None:
                        packages.append({"name": name, "version": version})

    # Sort packages for deterministic comparison
    packages.sort(key=lambda x: (x["name"].lower(), x["version"]))
    return target_framework, packages


def _normalize_path_str(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _path_matches(value: str, expected_rel: str) -> bool:
    v = _normalize_path_str(value.strip())
    exp = _normalize_path_str(expected_rel)
    return v.endswith(exp)


def _compute_expected_from_workspace(workspace: Path) -> Dict[str, Any]:
    # Expected projects
    app_csproj = workspace / "src" / "App" / "App.csproj"
    lib_csproj = workspace / "src" / "Lib" / "Lib.csproj"

    expected: Dict[str, Any] = {
        "projects": {},
        "frameworks": set(),
        "packages_by_project": {},
        "conflicts": set(),
        "issues": {"errors": {}, "warnings": {}},
        "paths": {
            "app_rel": "src/App/App.csproj",
            "lib_rel": "src/Lib/Lib.csproj",
        },
    }

    # Parse csproj files
    app_parsed = _parse_csproj(app_csproj) if app_csproj.exists() else None
    lib_parsed = _parse_csproj(lib_csproj) if lib_csproj.exists() else None

    if app_parsed:
        tfm, pkgs = app_parsed
        expected["projects"]["app"] = {"path": expected["paths"]["app_rel"], "targetFramework": tfm, "packages": pkgs}
        expected["frameworks"].add(tfm)
        expected["packages_by_project"][expected["paths"]["app_rel"]] = {p["name"]: p["version"] for p in pkgs}

    if lib_parsed:
        tfm, pkgs = lib_parsed
        expected["projects"]["lib"] = {"path": expected["paths"]["lib_rel"], "targetFramework": tfm, "packages": pkgs}
        expected["frameworks"].add(tfm)
        expected["packages_by_project"][expected["paths"]["lib_rel"]] = {p["name"]: p["version"] for p in pkgs}

    # Compute conflicts across projects
    if expected["packages_by_project"]:
        # Collect package versions per project
        all_projects = list(expected["packages_by_project"].keys())
        pkg_to_versions: Dict[str, Dict[str, str]] = {}
        for proj_path, pkgmap in expected["packages_by_project"].items():
            for pkg, ver in pkgmap.items():
                pkg_to_versions.setdefault(pkg, {})
                pkg_to_versions[pkg][proj_path] = ver
        for pkg, versions in pkg_to_versions.items():
            if len(versions) > 1:
                # Check if versions differ
                versions_set = set(versions.values())
                if len(versions_set) > 1:
                    expected["conflicts"].add(pkg)

    # Parse issues from input/build_log.txt
    build_log_path = workspace / "input" / "build_log.txt"
    log_text = _read_text_safe(build_log_path)
    if log_text:
        # Count only lines that start with "error CODE" or "warning CODE" (case-insensitive)
        # Sample message is the first occurrence line for that code.
        for raw_line in log_text.splitlines():
            line = raw_line.rstrip("\r\n")
            m = re.match(r"(?i)^(error|warning)\s+([A-Za-z0-9]+)\b", line)
            if m:
                sev = m.group(1).lower()  # 'error' or 'warning'
                code = m.group(2)
                grp = "errors" if sev == "error" else "warnings"
                if code not in expected["issues"][grp]:
                    expected["issues"][grp][code] = {"count": 1, "sampleMessage": line.strip()}
                else:
                    expected["issues"][grp][code]["count"] += 1

    return expected


def _extract_projects_by_path(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Return mapping from normalized path endings ('src/App/App.csproj', etc.) to project dict in report.
    """
    by_path: Dict[str, Dict[str, Any]] = {}
    projects = report.get("projects")
    if not isinstance(projects, list):
        return by_path
    for proj in projects:
        if not isinstance(proj, dict):
            continue
        path_val = proj.get("path")
        if isinstance(path_val, str):
            norm = _normalize_path_str(path_val)
            by_path[norm] = proj
    return by_path


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "dependency_report_exists": 0.0,
        "dependency_report_projects_paths": 0.0,
        "dependency_report_projects_target_frameworks": 0.0,
        "dependency_report_projects_packages": 0.0,
        "dependency_report_frameworks": 0.0,
        "dependency_report_conflicts": 0.0,
        "dependency_report_issues": 0.0,
        "docs_target_frameworks_section": 0.0,
        "docs_known_issues_section": 0.0,
        "docs_restore_conflict_note": 0.0,
    }

    expected = _compute_expected_from_workspace(workspace)

    # Paths
    report_path = workspace / "output" / "dependency-report.json"
    docs_path = workspace / "docs" / "CONTRIBUTING.md"

    # 1) Check dependency report
    report = _load_json_safe(report_path)
    if isinstance(report, dict):
        scores["dependency_report_exists"] = 1.0
    else:
        # If report missing or malformed, dependent checks remain 0.0
        report = None

    if report is not None:
        # Validate presence of top-level keys
        has_projects = isinstance(report.get("projects"), list)
        has_conflicts = isinstance(report.get("conflicts"), list)
        has_frameworks = isinstance(report.get("frameworks"), list)
        issues = report.get("issues")
        has_issues = isinstance(issues, dict) and isinstance(issues.get("errors"), list) and isinstance(issues.get("warnings"), list)

        # Projects paths
        if has_projects:
            # Expect exactly the two provided projects and no more
            by_path = _extract_projects_by_path(report)
            expected_paths = {_normalize_path_str(expected["paths"]["app_rel"]), _normalize_path_str(expected["paths"]["lib_rel"])}
            present_paths = set()
            for p in by_path.keys():
                # match if path endswith expected
                for exp in expected_paths:
                    if p.endswith(exp):
                        present_paths.add(exp)
            if present_paths == expected_paths and len(report["projects"]) == 2:
                scores["dependency_report_projects_paths"] = 1.0

            # Projects target frameworks
            tfm_ok = True
            # Build mapping from expected rel path to expected tfm
            exp_tfm_map = {}
            if "app" in expected["projects"]:
                exp_tfm_map[_normalize_path_str(expected["paths"]["app_rel"])] = expected["projects"]["app"]["targetFramework"]
            if "lib" in expected["projects"]:
                exp_tfm_map[_normalize_path_str(expected["paths"]["lib_rel"])] = expected["projects"]["lib"]["targetFramework"]

            for exp_rel, exp_tfm in exp_tfm_map.items():
                found_match = False
                for norm_path, proj in by_path.items():
                    if norm_path.endswith(exp_rel):
                        found_match = True
                        if proj.get("targetFramework") != exp_tfm:
                            tfm_ok = False
                        break
                if not found_match:
                    tfm_ok = False
            if tfm_ok and len(exp_tfm_map) == 2:
                scores["dependency_report_projects_target_frameworks"] = 1.0

            # Projects packages
            pkgs_ok = True
            for exp_rel, exp_tfm in exp_tfm_map.items():
                # find corresponding project
                proj = None
                for norm_path, p in by_path.items():
                    if norm_path.endswith(exp_rel):
                        proj = p
                        break
                if proj is None:
                    pkgs_ok = False
                    continue
                pkgs = proj.get("packages")
                if not isinstance(pkgs, list):
                    pkgs_ok = False
                    continue
                # Compare set of (name, version)
                try:
                    pkgs_set = {(d["name"], d["version"]) for d in pkgs if isinstance(d, dict)}
                except Exception:
                    pkgs_ok = False
                    continue

                exp_pkgs_list = expected["projects"]["app" if "App" in exp_rel else "lib"]["packages"]
                exp_pkgs_set = {(d["name"], d["version"]) for d in exp_pkgs_list}
                if pkgs_set != exp_pkgs_set:
                    pkgs_ok = False
            if pkgs_ok and len(exp_tfm_map) == 2:
                scores["dependency_report_projects_packages"] = 1.0

        # Frameworks
        if has_frameworks:
            exp_frameworks = set(expected["frameworks"])
            try:
                rep_frameworks = set(report.get("frameworks", []))
                if rep_frameworks == exp_frameworks:
                    scores["dependency_report_frameworks"] = 1.0
            except Exception:
                pass

        # Conflicts
        if has_conflicts and has_projects:
            # Build expected conflicts from csproj: packages with differing versions across projects
            if "app" in expected["projects"] and "lib" in expected["projects"]:
                # Determine names used in report for these projects, via their path entries
                by_path = _extract_projects_by_path(report)
                app_name = None
                lib_name = None
                for norm_path, proj in by_path.items():
                    if norm_path.endswith(_normalize_path_str(expected["paths"]["app_rel"])):
                        app_name = proj.get("name")
                    if norm_path.endswith(_normalize_path_str(expected["paths"]["lib_rel"])):
                        lib_name = proj.get("name")

                # Build expected conflict versions mapping keyed by these names
                app_pkgs = {p["name"]: p["version"] for p in expected["projects"]["app"]["packages"]}
                lib_pkgs = {p["name"]: p["version"] for p in expected["projects"]["lib"]["packages"]}
                expected_conflict_pkgs = set()
                for pkg in set(app_pkgs.keys()) & set(lib_pkgs.keys()):
                    if app_pkgs[pkg] != lib_pkgs[pkg]:
                        expected_conflict_pkgs.add(pkg)

                rep_conflicts = report.get("conflicts", [])
                # Check that reported conflict packages exactly match expected
                try:
                    rep_conflict_pkgs = {d["package"] for d in rep_conflicts if isinstance(d, dict) and "package" in d}
                except Exception:
                    rep_conflict_pkgs = set()

                conflicts_ok = rep_conflict_pkgs == expected_conflict_pkgs and app_name and lib_name

                # Also check versionsByProject mapping entries
                if conflicts_ok:
                    for d in rep_conflicts:
                        if not isinstance(d, dict):
                            conflicts_ok = False
                            break
                        pkg = d.get("package")
                        vbp = d.get("versionsByProject")
                        if pkg not in expected_conflict_pkgs or not isinstance(vbp, dict):
                            conflicts_ok = False
                            break
                        # versionsByProject must have two entries with names matching the projects and correct versions
                        if app_name not in vbp or lib_name not in vbp:
                            conflicts_ok = False
                            break
                        if vbp[app_name] != app_pkgs.get(pkg) or vbp[lib_name] != lib_pkgs.get(pkg):
                            conflicts_ok = False
                            break
                if conflicts_ok:
                    scores["dependency_report_conflicts"] = 1.0

        # Issues
        if has_issues:
            # Compute expected issues from build_log.txt using the same rules
            exp_errors = expected["issues"]["errors"]  # dict code -> {count, sampleMessage}
            exp_warnings = expected["issues"]["warnings"]

            def list_to_map(lst: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
                out: Dict[str, Dict[str, Any]] = {}
                for d in lst:
                    if not isinstance(d, dict):
                        continue
                    code = d.get("code")
                    count = d.get("count")
                    sample = d.get("sampleMessage")
                    if isinstance(code, str) and isinstance(count, int) and isinstance(sample, str):
                        out[code] = {"count": count, "sampleMessage": sample}
                return out

            rep_errors = list_to_map(report["issues"]["errors"])
            rep_warnings = list_to_map(report["issues"]["warnings"])

            issues_ok = True
            # Exact equality on keys and values
            if set(rep_errors.keys()) != set(exp_errors.keys()):
                issues_ok = False
            else:
                for code, info in exp_errors.items():
                    if code not in rep_errors:
                        issues_ok = False
                        break
                    if rep_errors[code]["count"] != info["count"] or rep_errors[code]["sampleMessage"] != info["sampleMessage"]:
                        issues_ok = False
                        break
            if set(rep_warnings.keys()) != set(exp_warnings.keys()):
                issues_ok = False
            else:
                for code, info in exp_warnings.items():
                    if code not in rep_warnings:
                        issues_ok = False
                        break
                    if rep_warnings[code]["count"] != info["count"] or rep_warnings[code]["sampleMessage"] != info["sampleMessage"]:
                        issues_ok = False
                        break

            if issues_ok:
                scores["dependency_report_issues"] = 1.0

    # 2) Check docs/CONTRIBUTING.md updates
    docs_text = _read_text_safe(docs_path)
    if docs_text is not None:
        lines = docs_text.splitlines()
        # a) Target Frameworks section checks
        # - Ensure no single "Target Framework:" line remains
        singular_present = any(re.search(r"^\s*-\s*Target Framework\s*:", ln, flags=re.IGNORECASE) for ln in lines)
        # - Ensure "Target Frameworks" section present
        tfm_section_present = any(re.search(r"Target Frameworks", ln, flags=re.IGNORECASE) for ln in lines)
        # - Ensure entries for App and Lib with correct target frameworks
        exp_app_tfm = expected["projects"].get("app", {}).get("targetFramework")
        exp_lib_tfm = expected["projects"].get("lib", {}).get("targetFramework")

        def contains_entry(project_label: str, tfm: Optional[str]) -> bool:
            if not tfm:
                return False
            pattern = re.compile(rf"{re.escape(project_label)}\s*:\s*{re.escape(tfm)}", flags=re.IGNORECASE)
            return any(pattern.search(ln) for ln in lines)

        app_entry_ok = contains_entry("App", exp_app_tfm)
        lib_entry_ok = contains_entry("Lib", exp_lib_tfm)

        if (not singular_present) and tfm_section_present and app_entry_ok and lib_entry_ok:
            scores["docs_target_frameworks_section"] = 1.0

        # b) Known issues section replaced with bullet list of error/warning codes with counts
        # Find "Known issues" line index
        ki_indices = [i for i, ln in enumerate(lines) if ln.strip().lower() == "known issues"]
        ki_ok = False
        if ki_indices:
            idx = ki_indices[0]
            # Collect following bullet lines until next non-bullet section header or EOF
            bullets: List[str] = []
            for j in range(idx + 1, len(lines)):
                ln = lines[j]
                if ln.strip() == "":
                    # Could be separation; continue scanning as some markdown sections might have blank lines
                    continue
                if re.match(r"^\s*-\s+", ln):
                    bullets.append(ln.strip())
                else:
                    # Stop at first non-bullet, non-empty line
                    # Assuming next section starts
                    break

            # Parse bullets into (severity, code, count)
            bullet_entries: Dict[Tuple[str, str], int] = {}
            parse_ok = True
            for b in bullets:
                m = re.match(r"^\s*-\s*(error|warning)\s+([A-Za-z0-9]+)\s*\((\d+)\)", b, flags=re.IGNORECASE)
                if not m:
                    # If any bullet doesn't match the required pattern, fail
                    parse_ok = False
                    break
                sev = m.group(1).lower()
                code = m.group(2)
                count = int(m.group(3))
                bullet_entries[(sev, code)] = count

            # Compute expected entries from build log
            exp_entries: Dict[Tuple[str, str], int] = {}
            for code, info in expected["issues"]["errors"].items():
                exp_entries[("error", code)] = int(info["count"])
            for code, info in expected["issues"]["warnings"].items():
                exp_entries[("warning", code)] = int(info["count"])

            if parse_ok and bullet_entries == exp_entries and bullets:
                ki_ok = True

        if ki_ok:
            scores["docs_known_issues_section"] = 1.0

        # c) Restore note about conflicts
        # Find the Restore command line
        restore_indices = [i for i, ln in enumerate(lines) if re.match(r"^\s*-\s*Restore\s*:", ln, flags=re.IGNORECASE)]
        restore_note_ok = False
        if restore_indices:
            r_idx = restore_indices[0]
            # Inspect the next few lines under Restore for a conflict note if conflicts exist
            # We will look up to the next bullet item or up to 5 lines
            window_lines: List[str] = []
            for j in range(r_idx + 1, min(len(lines), r_idx + 6)):
                if re.match(r"^\s*-\s+", lines[j]):
                    break
                window_lines.append(lines[j])

            conflicts_expected = set(expected["conflicts"])
            note_text = " ".join(window_lines).lower()
            if conflicts_expected:
                # Must mention 'conflict' and name all affected packages
                if "conflict" in note_text:
                    all_present = True
                    for pkg in conflicts_expected:
                        if not any(pkg in wl for wl in window_lines):
                            all_present = False
                            break
                    if all_present:
                        restore_note_ok = True
            else:
                # No conflicts expected; a note stating none is acceptable
                if any(re.search(r"no\s+conflicts|none", wl, flags=re.IGNORECASE) for wl in window_lines):
                    restore_note_ok = True

        if restore_note_ok:
            scores["docs_restore_conflict_note"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) > 1:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()