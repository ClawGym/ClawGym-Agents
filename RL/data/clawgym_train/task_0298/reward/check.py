import json
import sys
import hashlib
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict


def compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def file_size(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
        if header is None:
            return None, None
        rows: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8", newline="") as f2:
            dict_reader = csv.DictReader(f2)
            for row in dict_reader:
                rows.append(row)
        return header, rows
    except Exception:
        return None, None


def is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        # Accept 'Z' suffix by converting to +00:00
        if s.endswith("Z"):
            datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def is_hex_str(s: str, min_len: int = 1, max_len: int = 4) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if len(s) < min_len or len(s) > max_len:
        return False
    for ch in s:
        if ch not in "0123456789abcdefABCDEF":
            return False
    return True


def _tool_consistency(tool_json: dict, raw_exists: bool, err_exists: bool) -> float:
    # Validate types
    if not isinstance(tool_json, dict):
        return 0.0
    available = tool_json.get("available", None)
    exit_code = tool_json.get("exit_code", None)
    stderr_excerpt = tool_json.get("stderr_excerpt", None)

    if not isinstance(available, bool):
        return 0.0
    if not (isinstance(exit_code, int) or exit_code is None):
        return 0.0
    if not isinstance(stderr_excerpt, str):
        return 0.0

    # Success case: raw exists -> available True, exit_code 0, stderr_excerpt "".
    if raw_exists:
        if available is True and exit_code == 0 and stderr_excerpt == "":
            return 1.0
        else:
            return 0.0

    # Error case: no raw, error exists -> either tool missing or failed
    if (not raw_exists) and err_exists:
        # If tool was executed and failed
        if available is True:
            if isinstance(exit_code, int) and exit_code != 0 and isinstance(stderr_excerpt, str) and len(stderr_excerpt) >= 0:
                return 1.0 if len(stderr_excerpt) > 0 else 0.0
            else:
                return 0.0
        # If tool not available (missing)
        if available is False:
            # exit_code may be None or int; stderr should be non-empty
            if (exit_code is None or isinstance(exit_code, int)) and isinstance(stderr_excerpt, str) and len(stderr_excerpt) > 0:
                return 1.0
            else:
                return 0.0

    # Neither artifact present -> inconsistent
    return 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    out_dir = workspace / "out"
    tmp_dir = workspace / "tmp"

    scores = {
        "pci_ids_download_record_match": 0.0,
        "usb_ids_download_record_match": 0.0,
        "lspci_artifacts_present": 0.0,
        "lsusb_artifacts_present": 0.0,
        "tools_lspci_consistency": 0.0,
        "tools_lsusb_consistency": 0.0,
        "devices_csv_structure": 0.0,
        "devices_csv_source_values": 0.0,
        "counts_pci_match": 0.0,
        "counts_usb_match": 0.0,
        "resolved_names_count_match": 0.0,
        "generated_at_is_iso8601": 0.0,
        "id_fields_hex_format": 0.0,
    }

    # Paths for deliverables
    pci_ids_path = tmp_dir / "pci.ids"
    usb_ids_path = tmp_dir / "usb.ids"
    lspci_raw = out_dir / "lspci_raw.txt"
    lspci_err = out_dir / "lspci_error.txt"
    lsusb_raw = out_dir / "lsusb_raw.txt"
    lsusb_err = out_dir / "lsusb_error.txt"
    devices_csv = out_dir / "devices.csv"
    report_json_path = out_dir / "hardware_inventory.json"

    # Load JSON report
    report = load_json_file(report_json_path)

    # Check generated_at
    if isinstance(report, dict):
        generated_at = report.get("generated_at")
        if isinstance(generated_at, str) and is_iso8601(generated_at):
            scores["generated_at_is_iso8601"] = 1.0

    # Downloads checks
    downloads = report.get("downloads") if isinstance(report, dict) else None

    # PCI
    pci_sha = compute_sha256(pci_ids_path) if pci_ids_path.exists() else None
    pci_bytes = file_size(pci_ids_path) if pci_ids_path.exists() else None
    if pci_sha is not None and pci_bytes is not None and isinstance(downloads, dict):
        pci_download = downloads.get("pci_ids")
        if isinstance(pci_download, dict):
            src_ok = pci_download.get("source") == "pciutils pci.ids"
            sha_ok = pci_download.get("sha256") == pci_sha
            bytes_ok = pci_download.get("bytes") == pci_bytes
            if src_ok and sha_ok and bytes_ok:
                scores["pci_ids_download_record_match"] = 1.0

    # USB
    usb_sha = compute_sha256(usb_ids_path) if usb_ids_path.exists() else None
    usb_bytes = file_size(usb_ids_path) if usb_ids_path.exists() else None
    if usb_sha is not None and usb_bytes is not None and isinstance(downloads, dict):
        usb_download = downloads.get("usb_ids")
        if isinstance(usb_download, dict):
            src_ok = usb_download.get("source") == "linux-usb usb.ids"
            sha_ok = usb_download.get("sha256") == usb_sha
            bytes_ok = usb_download.get("bytes") == usb_bytes
            if src_ok and sha_ok and bytes_ok:
                scores["usb_ids_download_record_match"] = 1.0

    # Artifacts presence
    if lspci_raw.exists() or lspci_err.exists():
        scores["lspci_artifacts_present"] = 1.0
    if lsusb_raw.exists() or lsusb_err.exists():
        scores["lsusb_artifacts_present"] = 1.0

    # Tools consistency
    tools = report.get("tools") if isinstance(report, dict) else None
    if isinstance(tools, dict):
        lspci_tool = tools.get("lspci")
        if isinstance(lspci_tool, dict):
            scores["tools_lspci_consistency"] = _tool_consistency(
                lspci_tool, lspci_raw.exists(), lspci_err.exists()
            )
        lsusb_tool = tools.get("lsusb")
        if isinstance(lsusb_tool, dict):
            scores["tools_lsusb_consistency"] = _tool_consistency(
                lsusb_tool, lsusb_raw.exists(), lsusb_err.exists()
            )

    # CSV structure and source values
    expected_header = [
        "source",
        "bus",
        "slot_or_device",
        "class_or_type",
        "vendor_id",
        "device_id_or_product_id",
        "vendor_name",
        "device_name_or_product_name",
    ]
    header, rows = (None, None)
    if devices_csv.exists():
        header, rows = read_csv_header_and_rows(devices_csv)
        if header == expected_header and isinstance(rows, list):
            scores["devices_csv_structure"] = 1.0
            # Source values check
            valid_sources = {"lspci", "lsusb"}
            ok = True
            for r in rows:
                src = (r.get("source") or "").strip()
                if src not in valid_sources:
                    ok = False
                    break
            if ok:
                scores["devices_csv_source_values"] = 1.0

            # ID fields hex format (require non-empty hex-like IDs for present rows)
            id_ok = True
            for r in rows:
                vid = (r.get("vendor_id") or "").strip()
                pid = (r.get("device_id_or_product_id") or "").strip()
                if vid == "" or pid == "":
                    id_ok = False
                    break
                if (not is_hex_str(vid, 1, 4)) or (not is_hex_str(pid, 1, 4)):
                    id_ok = False
                    break
            if rows == []:
                id_ok = True
            if id_ok:
                scores["id_fields_hex_format"] = 1.0

    # Counts consistency
    counts = report.get("counts") if isinstance(report, dict) else None
    if isinstance(counts, dict) and isinstance(rows, list):
        pci_count_json = counts.get("pci_devices")
        usb_count_json = counts.get("usb_devices")
        resolved_names_json = counts.get("resolved_names")
        # Type check
        if isinstance(pci_count_json, int):
            pci_count_csv = sum(1 for r in rows if (r.get("source") or "").strip() == "lspci")
            if pci_count_json == pci_count_csv:
                scores["counts_pci_match"] = 1.0
        if isinstance(usb_count_json, int):
            usb_count_csv = sum(1 for r in rows if (r.get("source") or "").strip() == "lsusb")
            if usb_count_json == usb_count_csv:
                scores["counts_usb_match"] = 1.0
        # Resolved names: count rows where both vendor_name and device/product name are non-empty
        if isinstance(resolved_names_json, int):
            both_nonempty = 0
            at_least_one = 0
            for r in rows:
                vname = (r.get("vendor_name") or "").strip()
                dname = (r.get("device_name_or_product_name") or "").strip()
                if vname or dname:
                    at_least_one += 1
                if vname and dname:
                    both_nonempty += 1
            if resolved_names_json == both_nonempty:
                scores["resolved_names_count_match"] = 1.0
            elif resolved_names_json == at_least_one:
                scores["resolved_names_count_match"] = 0.5

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()