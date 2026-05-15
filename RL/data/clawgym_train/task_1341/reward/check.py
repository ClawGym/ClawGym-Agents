import json
import sys
import re
from pathlib import Path
from typing import Optional, List

MIB = 1_048_576

EXPECTED_POS_PATH = "input/logs/pos_front.log"
EXPECTED_KDS_PATH = "input/logs/kitchen_display.log"
TEMPLATE_PATH = "input/config/logrotate_template.conf"
OUTPUT_CONF_PATH = "output/config/logrotate.conf"
OUTPUT_JSON_PATH = "output/reports/log_sizes.json"
POLICY_PATH = "input/docs/IT_Policies.md"


def safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(p: Path) -> Optional[object]:
    try:
        text = p.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def safe_stat_size(p: Path) -> Optional[int]:
    try:
        return p.stat().st_size
    except Exception:
        return None


def compute_rotate_size_bytes(size_a: Optional[int], size_b: Optional[int]) -> Optional[int]:
    if size_a is None or size_b is None:
        return None
    smax = max(size_a, size_b)
    numerator = smax * 12
    denominator = 10 * MIB
    mult = (numerator + denominator - 1) // denominator
    return mult * MIB


def extract_section(text: str, header: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {header}":
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    section_text = "\n".join(lines[start_idx:end_idx]).strip()
    return section_text


def contains_all_keywords(text: str, keywords: List[str]) -> bool:
    lower = text.lower()
    return all(k.lower() in lower for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "log_sizes_json_structure": 0.0,
        "log_sizes_json_values": 0.0,
        "logrotate_conf_exact_replacement": 0.0,
        "it_policies_section_updated": 0.0,
        "it_policies_mentions_files": 0.0,
        "it_policies_rotation_trigger_values": 0.0,
        "it_policies_retention_keep7": 0.0,
        "it_policies_notes_options": 0.0,
        "it_policies_other_sections_unchanged": 0.0,
    }

    # Compute input file sizes
    pos_log_path = workspace / EXPECTED_POS_PATH
    kds_log_path = workspace / EXPECTED_KDS_PATH
    pos_size = safe_stat_size(pos_log_path)
    kds_size = safe_stat_size(kds_log_path)
    rotate_size = compute_rotate_size_bytes(pos_size, kds_size)

    # 1) Validate output/reports/log_sizes.json structure
    json_path = workspace / OUTPUT_JSON_PATH
    data = safe_load_json(json_path)
    structure_ok = False
    if isinstance(data, dict):
        expected_root_keys = {"files", "rotate_size_bytes", "keep_count"}
        if set(data.keys()) == expected_root_keys:
            files = data.get("files")
            if isinstance(files, list) and len(files) == 2:
                file0, file1 = files[0], files[1]
                if isinstance(file0, dict) and isinstance(file1, dict):
                    if set(file0.keys()) == {"path", "size_bytes"} and set(file1.keys()) == {"path", "size_bytes"}:
                        if (
                            isinstance(file0.get("path"), str) and isinstance(file1.get("path"), str)
                            and isinstance(file0.get("size_bytes"), int) and isinstance(file1.get("size_bytes"), int)
                        ):
                            # Check order and paths
                            if file0["path"] == EXPECTED_POS_PATH and file1["path"] == EXPECTED_KDS_PATH:
                                if isinstance(data.get("rotate_size_bytes"), int) and isinstance(data.get("keep_count"), int):
                                    structure_ok = True
    if structure_ok:
        scores["log_sizes_json_structure"] = 1.0

    # 2) Validate JSON values if structure OK and input sizes known
    values_ok = False
    if structure_ok and pos_size is not None and kds_size is not None and rotate_size is not None:
        file0, file1 = data["files"][0], data["files"][1]
        if (
            file0["size_bytes"] == pos_size
            and file1["size_bytes"] == kds_size
            and data["rotate_size_bytes"] == rotate_size
            and data["keep_count"] == 7
        ):
            values_ok = True
    if values_ok:
        scores["log_sizes_json_values"] = 1.0

    # 3) Validate output/config/logrotate.conf matches template replacements exactly
    template_text = safe_read_text(workspace / TEMPLATE_PATH)
    conf_text = safe_read_text(workspace / OUTPUT_CONF_PATH)
    if template_text is not None and conf_text is not None and rotate_size is not None:
        expected_conf = template_text
        expected_conf = expected_conf.replace("LOG_PATH_1", EXPECTED_POS_PATH)
        expected_conf = expected_conf.replace("LOG_PATH_2", EXPECTED_KDS_PATH)
        expected_conf = expected_conf.replace("{{ROTATE_SIZE_BYTES}}", str(rotate_size))
        expected_conf = expected_conf.replace("{{KEEP_COUNT}}", "7")
        if conf_text == expected_conf:
            scores["logrotate_conf_exact_replacement"] = 1.0

    # 4) Validate IT_Policies.md edits
    policy_text = safe_read_text(workspace / POLICY_PATH)
    retention_section = None
    if policy_text is not None:
        retention_section = extract_section(policy_text, "Log Retention Policy")
        if retention_section is not None and "todo" not in retention_section.lower():
            scores["it_policies_section_updated"] = 1.0

        # Mentions both target files
        if retention_section is not None and scores["it_policies_section_updated"] == 1.0:
            if EXPECTED_POS_PATH in retention_section and EXPECTED_KDS_PATH in retention_section:
                scores["it_policies_mentions_files"] = 1.0

        # Rotation trigger values: bytes, MiB with two decimals, mention of size
        if retention_section is not None and rotate_size is not None and scores["it_policies_section_updated"] == 1.0:
            bytes_ok = str(rotate_size) in retention_section
            mibs_str = f"{rotate_size / MIB:.2f}"
            mib_ok = (mibs_str in retention_section) and ("MiB" in retention_section or "mib" in retention_section.lower())
            size_word_ok = "size" in retention_section.lower()
            if bytes_ok and mib_ok and size_word_ok:
                scores["it_policies_rotation_trigger_values"] = 1.0

        # Retention keep 7 literal
        if retention_section is not None and scores["it_policies_section_updated"] == 1.0:
            if re.search(r"\bkeep\s+7\b", retention_section, flags=re.IGNORECASE):
                scores["it_policies_retention_keep7"] = 1.0

        # Notes that options compress, missingok, copytruncate, notifempty are enabled
        if retention_section is not None and scores["it_policies_section_updated"] == 1.0:
            if contains_all_keywords(retention_section, ["compress", "missingok", "copytruncate", "notifempty"]):
                scores["it_policies_notes_options"] = 1.0

        # Other sections unchanged should only score if the Log Retention Policy has been updated
        if scores["it_policies_section_updated"] == 1.0:
            other_ok = True
            if "# IT Policies - Store 17" not in policy_text:
                other_ok = False
            expected_network_header = "## Network"
            expected_network_lines = [
                "- POS terminals and kitchen display units remain on the private VLAN.",
                "- Firmware updates scheduled during off-hours.",
            ]
            if expected_network_header not in policy_text:
                other_ok = False
            for ln in expected_network_lines:
                if ln not in policy_text:
                    other_ok = False
            expected_incident_header = "## Incident Response"
            expected_incident_line = "- Critical incidents are documented in the incident log and reviewed weekly."
            if expected_incident_header not in policy_text or expected_incident_line not in policy_text:
                other_ok = False
            if other_ok:
                scores["it_policies_other_sections_unchanged"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()