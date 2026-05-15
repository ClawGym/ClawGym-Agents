import json
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_line_commented(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("//") or stripped == ""


def _strip_inline_comment(line: str) -> str:
    idx = line.find("//")
    if idx != -1:
        return line[:idx]
    return line


def _parse_apt_periodic(text: str) -> Dict[str, List[str]]:
    directives: Dict[str, List[str]] = {}
    for raw_line in text.splitlines():
        if _is_line_commented(raw_line):
            continue
        line = _strip_inline_comment(raw_line).strip()
        if not line:
            continue
        m = re.match(r'^\s*APT::Periodic::([A-Za-z\-]+)\s+"([^"]+)"\s*;\s*$', line)
        if m:
            name = m.group(1)
            value = m.group(2)
            directives.setdefault(name, []).append(value)
    return directives


def _parse_unattended_blocks(text: str) -> Dict[str, Any]:
    """
    Parse 50unattended-upgrades for:
    - allowed_origins: list of active strings
    - package_blacklist: list of active package names
    - directives: mapping directive name -> list of values from active lines
    """
    lines = text.splitlines()
    allowed_origins: List[str] = []
    package_blacklist: List[str] = []

    def find_block_items(start_idx: int) -> Tuple[List[str], int]:
        items: List[str] = []
        i = start_idx
        opened = False
        while i < len(lines):
            raw = lines[i]
            if not _is_line_commented(raw):
                content = _strip_inline_comment(raw)
                if "{" in content:
                    opened = True
                    i += 1
                    break
            i += 1
        if not opened:
            return items, i
        while i < len(lines):
            raw = lines[i]
            content = _strip_inline_comment(raw).strip()
            if "};" in content:
                i += 1
                break
            if not _is_line_commented(raw):
                m = re.match(r'^\s*"([^"]+)"\s*;\s*$', content)
                if m:
                    items.append(m.group(1))
            i += 1
        return items, i

    i = 0
    while i < len(lines):
        raw = lines[i]
        if not _is_line_commented(raw):
            line = _strip_inline_comment(raw).strip()
            if re.search(r'^\s*Unattended-Upgrade::Allowed-Origins\s*\{', line):
                items, i = find_block_items(i)
                allowed_origins.extend(items)
                continue
            elif re.search(r'^\s*Unattended-Upgrade::Package-Blacklist\s*\{', line):
                items, i = find_block_items(i)
                package_blacklist.extend(items)
                continue
        i += 1

    # Parse single-line directives
    dir_values: Dict[str, List[str]] = {}
    for raw_line in lines:
        if _is_line_commented(raw_line):
            continue
        line = _strip_inline_comment(raw_line).strip()
        if not line:
            continue
        m = re.match(r'^\s*Unattended-Upgrade::([A-Za-z\-]+)\s+"([^"]+)"\s*;\s*$', line)
        if m:
            name = m.group(1)
            value = m.group(2)
            dir_values.setdefault(name, []).append(value)

    return {
        "allowed_origins": allowed_origins,
        "package_blacklist": package_blacklist,
        "directives": dir_values,
    }


def _derive_settings_from_configs(cfg20_text: Optional[str], cfg50_text: Optional[str]) -> Optional[Dict[str, Any]]:
    if cfg20_text is None or cfg50_text is None:
        return None
    periodic = _parse_apt_periodic(cfg20_text)
    update_package_lists = None
    download_upgradeable_packages = None
    unattended_upgrade = None
    autoclean_interval_days = None

    if "Update-Package-Lists" in periodic and len(periodic["Update-Package-Lists"]) == 1:
        update_package_lists = periodic["Update-Package-Lists"][0]
    if "Download-Upgradeable-Packages" in periodic and len(periodic["Download-Upgradeable-Packages"]) == 1:
        download_upgradeable_packages = periodic["Download-Upgradeable-Packages"][0]
    if "Unattended-Upgrade" in periodic and len(periodic["Unattended-Upgrade"]) == 1:
        unattended_upgrade = periodic["Unattended-Upgrade"][0]
    if "AutocleanInterval" in periodic and len(periodic["AutocleanInterval"]) == 1:
        try:
            autoclean_interval_days = int(periodic["AutocleanInterval"][0])
        except Exception:
            autoclean_interval_days = None

    un = _parse_unattended_blocks(cfg50_text)
    allowed_origins = un.get("allowed_origins", [])
    pkg_blacklist = un.get("package_blacklist", [])
    dirs = un.get("directives", {})
    remove_unused = None
    auto_reboot = None
    auto_reboot_time = None
    if "Remove-Unused-Dependencies" in dirs and len(dirs["Remove-Unused-Dependencies"]) == 1:
        val = dirs["Remove-Unused-Dependencies"][0].strip().lower()
        if val in ("true", "false"):
            remove_unused = (val == "true")
    if "Automatic-Reboot" in dirs and len(dirs["Automatic-Reboot"]) == 1:
        val = dirs["Automatic-Reboot"][0].strip().lower()
        if val in ("true", "false"):
            auto_reboot = (val == "true")
    if "Automatic-Reboot-Time" in dirs and len(dirs["Automatic-Reboot-Time"]) == 1:
        auto_reboot_time = dirs["Automatic-Reboot-Time"][0]

    return {
        "update_package_lists": update_package_lists,
        "download_upgradeable_packages": download_upgradeable_packages,
        "unattended_upgrade": unattended_upgrade,
        "autoclean_interval_days": autoclean_interval_days,
        "allowed_origins": allowed_origins,
        "package_blacklist": pkg_blacklist,
        "remove_unused_dependencies": remove_unused,
        "automatic_reboot": auto_reboot,
        "automatic_reboot_time": auto_reboot_time,
    }


def _expected_snapshot_values() -> Dict[str, Any]:
    return {
        "update_package_lists": "1",
        "download_upgradeable_packages": "1",
        "unattended_upgrade": "1",
        "autoclean_interval_days": 7,
        "allowed_origins": ['${distro_id}:${distro_codename}-security'],
        "package_blacklist": ['postgresql', 'mysql-server'],
        "remove_unused_dependencies": True,
        "automatic_reboot": True,
        "automatic_reboot_time": "03:30",
    }


def _parse_doc_summary(md: Optional[str]) -> Dict[str, Any]:
    result = {
        "has_summary": False,
        "has_rationale": False,
        "auto_updates_enabled": None,
        "allowed_origins_security_only": None,
        "package_blacklist": None,
        "remove_unused_dependencies": None,
        "automatic_reboot": None,
        "automatic_reboot_time": None,
        "autoclean_interval_days": None,
    }
    if md is None:
        return result

    lower_md = md.lower()
    if "summary" in lower_md:
        result["has_summary"] = True
    if ("rationale" in lower_md) or ("risk" in lower_md and "security" in lower_md):
        result["has_rationale"] = True

    lines = [l.strip() for l in md.splitlines() if l.strip()]
    for line in lines:
        l = line.lower()
        if "auto updates enabled:" in l:
            if "yes" in l:
                result["auto_updates_enabled"] = True
            elif "no" in l:
                result["auto_updates_enabled"] = False
        if "allowed origins:" in l:
            if "security only" in l:
                result["allowed_origins_security_only"] = True
            else:
                result["allowed_origins_security_only"] = False
        if "package blacklist:" in l:
            names: List[str] = []
            m = re.search(r'\[(.*?)\]', line)
            if m:
                inner = m.group(1)
                parts = [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]
                names = [p for p in parts if p]
            else:
                if "postgresql" in l:
                    names.append("postgresql")
                if "mysql-server" in l:
                    names.append("mysql-server")
            result["package_blacklist"] = names
        if "remove unused dependencies:" in l:
            if "true" in l:
                result["remove_unused_dependencies"] = True
            elif "false" in l:
                result["remove_unused_dependencies"] = False
        if "automatic reboot:" in l:
            if "true" in l:
                result["automatic_reboot"] = True
            elif "false" in l:
                result["automatic_reboot"] = False
            tm = re.search(r'(\d{2}:\d{2})', line)
            if tm:
                result["automatic_reboot_time"] = tm.group(1)
        if "autoclean interval:" in l:
            mnum = re.search(r'(\d+)', line)
            if mnum:
                try:
                    result["autoclean_interval_days"] = int(mnum.group(1))
                except Exception:
                    pass

    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "auto_cfg_complete_and_values_correct": 0.0,
        "auto_cfg_one_active_instance_each": 0.0,
        "allowed_origins_security_only": 0.0,
        "package_blacklist_exact": 0.0,
        "remove_unused_dependencies_true": 0.0,
        "automatic_reboot_true": 0.0,
        "automatic_reboot_time_0330": 0.0,
        "doc_has_summary_section": 0.0,
        "doc_has_rationale": 0.0,
        "doc_summary_complete_values": 0.0,
        "docs_summary_consistent_with_configs": 0.0,
        "snapshot_structure_correct": 0.0,
        "snapshot_matches_expected_values": 0.0,
        "snapshot_consistent_with_configs": 0.0,
    }

    cfg20_path = workspace / "configs" / "20auto-upgrades"
    cfg50_path = workspace / "configs" / "50unattended-upgrades"
    doc_path = workspace / "docs" / "update_policy.md"
    snapshot_path = workspace / "output" / "update_policy_snapshot.json"

    cfg20_text = _read_text(cfg20_path)
    cfg50_text = _read_text(cfg50_path)
    doc_text = _read_text(doc_path)
    snapshot_json = _load_json(snapshot_path)

    # 20auto-upgrades checks: require all four directives present once with exact values for awarding
    if cfg20_text is not None:
        periodic = _parse_apt_periodic(cfg20_text)
        required_values = {
            "Update-Package-Lists": "1",
            "Download-Upgradeable-Packages": "1",
            "Unattended-Upgrade": "1",
            "AutocleanInterval": "7",
        }
        # presence and exactly one active occurrence for each directive
        one_active_each = True
        values_correct = True
        for key, expected_val in required_values.items():
            vals = periodic.get(key, [])
            if len(vals) != 1:
                one_active_each = False
                values_correct = False
                break
            if vals[0] != expected_val:
                values_correct = False
        if one_active_each:
            scores["auto_cfg_one_active_instance_each"] = 1.0
        if one_active_each and values_correct:
            scores["auto_cfg_complete_and_values_correct"] = 1.0

    # 50unattended-upgrades checks
    if cfg50_text is not None:
        un = _parse_unattended_blocks(cfg50_text)
        allowed_origins = un.get("allowed_origins", [])
        pkg_blacklist = un.get("package_blacklist", [])
        directives = un.get("directives", {})

        sec_str = '${distro_id}:${distro_codename}-security'
        if allowed_origins == [sec_str]:
            scores["allowed_origins_security_only"] = 1.0

        expected_pkgs = ["postgresql", "mysql-server"]
        if sorted([p.lower() for p in pkg_blacklist]) == sorted(expected_pkgs):
            scores["package_blacklist_exact"] = 1.0

        rud_vals = directives.get("Remove-Unused-Dependencies", [])
        if len(rud_vals) == 1 and rud_vals[0].strip().lower() == "true":
            scores["remove_unused_dependencies_true"] = 1.0

        ar_vals = directives.get("Automatic-Reboot", [])
        if len(ar_vals) == 1 and ar_vals[0].strip().lower() == "true":
            scores["automatic_reboot_true"] = 1.0

        art_vals = directives.get("Automatic-Reboot-Time", [])
        if len(art_vals) == 1 and art_vals[0].strip() == "03:30":
            scores["automatic_reboot_time_0330"] = 1.0

    # Docs checks
    doc_info = _parse_doc_summary(doc_text)
    if doc_info["has_summary"]:
        scores["doc_has_summary_section"] = 1.0
    if doc_info["has_rationale"]:
        scores["doc_has_rationale"] = 1.0

    # Require all six summary items to match exactly to award
    pkg_list = doc_info["package_blacklist"] if doc_info["package_blacklist"] is not None else []
    summary_complete = (
        doc_info["has_summary"] is True and
        doc_info["auto_updates_enabled"] is True and
        doc_info["allowed_origins_security_only"] is True and
        set([p.lower() for p in pkg_list]) == {"postgresql", "mysql-server"} and
        len(pkg_list) == 2 and
        doc_info["remove_unused_dependencies"] is True and
        doc_info["automatic_reboot"] is True and
        doc_info["automatic_reboot_time"] == "03:30" and
        doc_info["autoclean_interval_days"] == 7
    )
    if summary_complete:
        scores["doc_summary_complete_values"] = 1.0

    # Docs consistency with configs
    cfg_values = _derive_settings_from_configs(cfg20_text, cfg50_text)
    consistent = True
    if cfg_values is None:
        consistent = False
    else:
        # Auto updates enabled -> Unattended-Upgrade == "1"
        if doc_info["auto_updates_enabled"] is not True or cfg_values["unattended_upgrade"] != "1":
            consistent = False
        # Allowed origins: exactly security only
        if doc_info["allowed_origins_security_only"] is not True:
            consistent = False
        else:
            if not (isinstance(cfg_values.get("allowed_origins"), list) and
                    cfg_values["allowed_origins"] == ['${distro_id}:${distro_codename}-security']):
                consistent = False
        # Package blacklist
        if not (isinstance(doc_info["package_blacklist"], list) and
                set([p.lower() for p in (doc_info["package_blacklist"] or [])]) == {"postgresql", "mysql-server"} and
                set([p.lower() for p in (cfg_values.get("package_blacklist") or [])]) == {"postgresql", "mysql-server"} and
                len(cfg_values.get("package_blacklist") or []) == 2):
            consistent = False
        # Remove unused deps
        if not (doc_info["remove_unused_dependencies"] is True and cfg_values.get("remove_unused_dependencies") is True):
            consistent = False
        # Automatic reboot/time
        if not (doc_info["automatic_reboot"] is True and
                doc_info["automatic_reboot_time"] == "03:30" and
                cfg_values.get("automatic_reboot") is True and
                cfg_values.get("automatic_reboot_time") == "03:30"):
            consistent = False
        # Autoclean interval
        if not (doc_info["autoclean_interval_days"] == 7 and cfg_values.get("autoclean_interval_days") == 7):
            consistent = False

    if consistent:
        scores["docs_summary_consistent_with_configs"] = 1.0

    # Snapshot checks
    expected_keys = {
        "update_package_lists",
        "download_upgradeable_packages",
        "unattended_upgrade",
        "autoclean_interval_days",
        "allowed_origins",
        "package_blacklist",
        "remove_unused_dependencies",
        "automatic_reboot",
        "automatic_reboot_time",
    }
    structure_ok = False
    matches_expected_values = False
    consistent_with_configs = False

    if isinstance(snapshot_json, dict) and set(snapshot_json.keys()) == expected_keys:
        types_ok = True
        types_ok = types_ok and isinstance(snapshot_json.get("update_package_lists"), str)
        types_ok = types_ok and isinstance(snapshot_json.get("download_upgradeable_packages"), str)
        types_ok = types_ok and isinstance(snapshot_json.get("unattended_upgrade"), str)
        types_ok = types_ok and isinstance(snapshot_json.get("autoclean_interval_days"), int)
        types_ok = types_ok and isinstance(snapshot_json.get("allowed_origins"), list) and all(isinstance(x, str) for x in snapshot_json.get("allowed_origins"))
        types_ok = types_ok and isinstance(snapshot_json.get("package_blacklist"), list) and all(isinstance(x, str) for x in snapshot_json.get("package_blacklist"))
        types_ok = types_ok and isinstance(snapshot_json.get("remove_unused_dependencies"), bool)
        types_ok = types_ok and isinstance(snapshot_json.get("automatic_reboot"), bool)
        types_ok = types_ok and isinstance(snapshot_json.get("automatic_reboot_time"), str)
        structure_ok = types_ok

    if structure_ok:
        scores["snapshot_structure_correct"] = 1.0
        exp = _expected_snapshot_values()
        try:
            lists_ok = (
                sorted(snapshot_json["allowed_origins"]) == sorted(exp["allowed_origins"]) and
                sorted([p.lower() for p in snapshot_json["package_blacklist"]]) == sorted([p.lower() for p in exp["package_blacklist"]])
            )
            scalars_ok = (
                snapshot_json["update_package_lists"] == exp["update_package_lists"] and
                snapshot_json["download_upgradeable_packages"] == exp["download_upgradeable_packages"] and
                snapshot_json["unattended_upgrade"] == exp["unattended_upgrade"] and
                snapshot_json["autoclean_interval_days"] == exp["autoclean_interval_days"] and
                snapshot_json["remove_unused_dependencies"] == exp["remove_unused_dependencies"] and
                snapshot_json["automatic_reboot"] == exp["automatic_reboot"] and
                snapshot_json["automatic_reboot_time"] == exp["automatic_reboot_time"]
            )
            if lists_ok and scalars_ok:
                matches_expected_values = True
        except Exception:
            matches_expected_values = False

        if matches_expected_values:
            scores["snapshot_matches_expected_values"] = 1.0

        if cfg_values is not None:
            try:
                ok = True
                ok = ok and snapshot_json["update_package_lists"] == (cfg_values["update_package_lists"] or "")
                ok = ok and snapshot_json["download_upgradeable_packages"] == (cfg_values["download_upgradeable_packages"] or "")
                ok = ok and snapshot_json["unattended_upgrade"] == (cfg_values["unattended_upgrade"] or "")
                ok = ok and snapshot_json["autoclean_interval_days"] == (cfg_values["autoclean_interval_days"] if cfg_values["autoclean_interval_days"] is not None else -1)
                cfg_allowed = cfg_values["allowed_origins"] if cfg_values["allowed_origins"] is not None else []
                ok = ok and sorted(snapshot_json["allowed_origins"]) == sorted(cfg_allowed)
                cfg_bl = cfg_values["package_blacklist"] if cfg_values["package_blacklist"] is not None else []
                ok = ok and sorted([p.lower() for p in snapshot_json["package_blacklist"]]) == sorted([p.lower() for p in cfg_bl])
                ok = ok and snapshot_json["remove_unused_dependencies"] == (cfg_values["remove_unused_dependencies"] if cfg_values["remove_unused_dependencies"] is not None else False)
                ok = ok and snapshot_json["automatic_reboot"] == (cfg_values["automatic_reboot"] if cfg_values["automatic_reboot"] is not None else False)
                ok = ok and snapshot_json["automatic_reboot_time"] == (cfg_values["automatic_reboot_time"] or "")
                if ok:
                    consistent_with_configs = True
            except Exception:
                consistent_with_configs = False

        if consistent_with_configs:
            scores["snapshot_consistent_with_configs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()