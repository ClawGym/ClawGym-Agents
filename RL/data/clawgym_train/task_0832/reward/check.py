import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(_read_text(path) or "")
    except Exception:
        return None


def _safe_parse_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return (reader.fieldnames, rows)
    except Exception:
        return None


def _parse_validation_output(text: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    pattern = re.compile(
        r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(?P<sev>INFO|ERROR|WARNING)\s+(?P<file>[^:\s]+):(?P<line>\d+)\s+(?P<msg>.*)$"
    )
    element_pattern = re.compile(r"<([A-Za-z0-9:_-]+)>")
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        sev = m.group("sev")
        if sev not in {"ERROR", "WARNING"}:
            continue
        msg = m.group("msg")
        elem_match = element_pattern.search(msg)
        element = elem_match.group(1) if elem_match else ""
        entries.append(
            {
                "timestamp": m.group("ts"),
                "severity": sev,
                "file": m.group("file"),
                "line": m.group("line"),
                "element": element,
                "message": msg,
            }
        )
    return entries


def _load_owner_mapping(input_dir: Path) -> Optional[Dict[str, str]]:
    ownership_path = input_dir / "ownership.json"
    data = _load_json(ownership_path)
    if not isinstance(data, dict) or "owners" not in data or not isinstance(data["owners"], dict):
        return None
    return data["owners"]


def _map_owner(file_basename: str, owners: Dict[str, str]) -> str:
    # Owners are keyed relative to input/, e.g., "xml/users.xml"
    # Prefer mapping using "xml/<basename>" then fallback to "<basename>"
    key1 = f"xml/{file_basename}"
    if key1 in owners:
        return owners[key1]
    if file_basename in owners:
        return owners[file_basename]
    return "Unassigned"


def _severity_sort_key(sev: str) -> int:
    order = {"ERROR": 0, "WARNING": 1}
    return order.get(sev, 99)


def _expected_triage_rows(input_dir: Path) -> Optional[List[Dict[str, str]]]:
    # Requires ownership.json and validation_output.txt
    owners = _load_owner_mapping(input_dir)
    validation_text = _read_text(input_dir / "validation_output.txt")
    if owners is None or validation_text is None:
        return None
    parsed = _parse_validation_output(validation_text)
    # Attach owner
    for row in parsed:
        row["owner"] = _map_owner(row["file"], owners)
    # Sort: severity (ERROR before WARNING), then owner (A–Z), then file (A–Z), then line (numeric ascending)
    parsed.sort(
        key=lambda r: (
            _severity_sort_key(r["severity"]),
            r["owner"],
            r["file"],
            int(r["line"]),
        )
    )
    return parsed


def _iter_xml_files(input_xml_dir: Path) -> Optional[List[Path]]:
    try:
        if not input_xml_dir.exists() or not input_xml_dir.is_dir():
            return None
        files = sorted([p for p in input_xml_dir.glob("*.xml") if p.is_file()], key=lambda p: p.name)
        return files
    except Exception:
        return None


def _xml_metrics(xml_path: Path) -> Optional[Dict[str, object]]:
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        element_count = 0
        attribute_count = 0
        unique_elements = set()
        missing_string_keys = 0
        for elem in root.iter():
            element_count += 1
            attribute_count += len(elem.attrib)
            unique_elements.add(elem.tag)
            if elem.tag == "string" and "key" not in elem.attrib:
                missing_string_keys += 1
        metrics = {
            "element_count": int(element_count),
            "attribute_count": int(attribute_count),
            "unique_elements": sorted(unique_elements),
            "missing_string_keys": int(missing_string_keys),
        }
        return metrics
    except Exception:
        return None


def _expected_summary(input_dir: Path) -> Optional[Dict[str, object]]:
    owners = _load_owner_mapping(input_dir)
    if owners is None:
        return None
    xml_dir = input_dir / "xml"
    xml_files = _iter_xml_files(xml_dir)
    if xml_files is None:
        return None

    # Build triage counts expected from validation output (to populate error_count, warning_count per file)
    triage = _expected_triage_rows(input_dir)
    if triage is None:
        # If validation cannot be parsed, we cannot compute expected per-file errors/warnings
        return None

    # Map base filename -> {'errors': n, 'warnings': n}
    counts_by_file: Dict[str, Dict[str, int]] = {}
    for row in triage:
        base = row["file"]  # already basename in logs
        c = counts_by_file.setdefault(base, {"errors": 0, "warnings": 0})
        if row["severity"] == "ERROR":
            c["errors"] += 1
        elif row["severity"] == "WARNING":
            c["warnings"] += 1

    by_file_entries: List[Dict[str, object]] = []
    # Compute per XML file metrics
    for p in xml_files:
        rel_file = f"xml/{p.name}"
        owner = owners.get(rel_file, "Unassigned")
        metrics = _xml_metrics(p)
        if metrics is None:
            return None
        errors = counts_by_file.get(p.name, {}).get("errors", 0)
        warnings = counts_by_file.get(p.name, {}).get("warnings", 0)
        entry = {
            "file": rel_file,
            "owner": owner,
            "element_count": metrics["element_count"],
            "attribute_count": metrics["attribute_count"],
            "unique_elements": metrics["unique_elements"],
            "missing_string_keys": metrics["missing_string_keys"],
            "error_count": errors,
            "warning_count": warnings,
        }
        by_file_entries.append(entry)

    # Aggregates
    totals = {
        "files": len(by_file_entries),
        "elements": sum(int(e["element_count"]) for e in by_file_entries),
        "attributes": sum(int(e["attribute_count"]) for e in by_file_entries),
        "errors": sum(int(e["error_count"]) for e in by_file_entries),
        "warnings": sum(int(e["warning_count"]) for e in by_file_entries),
    }

    by_owner: Dict[str, Dict[str, int]] = {}
    for e in by_file_entries:
        owner = str(e["owner"])
        o = by_owner.setdefault(owner, {
            "total_files": 0,
            "total_elements": 0,
            "total_attributes": 0,
            "total_errors": 0,
            "total_warnings": 0,
        })
        o["total_files"] += 1
        o["total_elements"] += int(e["element_count"])
        o["total_attributes"] += int(e["attribute_count"])
        o["total_errors"] += int(e["error_count"])
        o["total_warnings"] += int(e["warning_count"])

    return {
        "by_file": by_file_entries,
        "totals": totals,
        "by_owner": by_owner,
    }


def _canonicalize_triage_rows(rows: List[Dict[str, str]]) -> List[Tuple[str, str, str, str, str, str, str]]:
    canon = []
    for r in rows:
        canon.append((
            r.get("timestamp", ""),
            r.get("severity", ""),
            r.get("file", ""),
            str(r.get("line", "")),
            r.get("owner", ""),
            r.get("element", ""),
            r.get("message", ""),
        ))
    return canon


def _index_by_file(entries: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    idx: Dict[str, Dict[str, object]] = {}
    for e in entries:
        f = e.get("file")
        if isinstance(f, str):
            idx[f] = e
    return idx


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "triage_csv_exists_and_header": 0.0,
        "triage_csv_content_matches_expected": 0.0,
        "triage_csv_sorted_correctly": 0.0,
        "summary_json_exists_and_shape": 0.0,
        "summary_by_file_metrics_correct": 0.0,
        "summary_totals_correct": 0.0,
        "summary_by_owner_correct": 0.0,
        "summary_consistent_with_triage_csv": 0.0,
    }

    input_dir = workspace / "input"
    out_dir = workspace / "out"

    # Expected computations
    expected_triage = _expected_triage_rows(input_dir)
    expected_summary = _expected_summary(input_dir)

    # Load actual triage.csv
    triage_path = out_dir / "triage.csv"
    triage_header_rows = _safe_parse_csv_dicts(triage_path)

    # Check triage header
    expected_header = ["timestamp", "severity", "file", "line", "owner", "element", "message"]
    if triage_header_rows is not None:
        header, rows = triage_header_rows
        if header == expected_header:
            scores["triage_csv_exists_and_header"] = 1.0

    # triage content checks
    if expected_triage is not None and triage_header_rows is not None and scores["triage_csv_exists_and_header"] == 1.0:
        _, actual_rows = triage_header_rows
        # Compare content ignoring order
        exp_canon = sorted(_canonicalize_triage_rows(expected_triage))
        act_canon = sorted(_canonicalize_triage_rows(actual_rows))
        if exp_canon == act_canon:
            scores["triage_csv_content_matches_expected"] = 1.0

        # Compare exact order (sorting)
        act_ordered = _canonicalize_triage_rows(actual_rows)
        exp_ordered = _canonicalize_triage_rows(expected_triage)
        if act_ordered == exp_ordered:
            scores["triage_csv_sorted_correctly"] = 1.0

    # Load actual summary.json
    summary_path = out_dir / "summary.json"
    summary_json = _load_json(summary_path)

    # summary shape check
    if isinstance(summary_json, dict):
        by_file = summary_json.get("by_file")
        totals = summary_json.get("totals")
        by_owner = summary_json.get("by_owner")
        if isinstance(by_file, list) and isinstance(totals, dict) and isinstance(by_owner, dict):
            # Basic shape OK
            # Also ensure each by_file item is a dict
            if all(isinstance(e, dict) for e in by_file):
                scores["summary_json_exists_and_shape"] = 1.0

    # summary by_file metrics correctness
    if expected_summary is not None and isinstance(summary_json, dict) and scores["summary_json_exists_and_shape"] == 1.0:
        exp_by_file_list: List[Dict[str, object]] = expected_summary["by_file"]  # type: ignore
        act_by_file_list: List[Dict[str, object]] = summary_json.get("by_file", [])  # type: ignore
        exp_idx = _index_by_file(exp_by_file_list)
        act_idx = _index_by_file(act_by_file_list)

        by_file_ok = True
        # Ensure exactly same set of files
        if set(exp_idx.keys()) != set(act_idx.keys()):
            by_file_ok = False
        else:
            for f, exp in exp_idx.items():
                act = act_idx.get(f)
                if not isinstance(act, dict):
                    by_file_ok = False
                    break
                # Required keys and exact values
                required_keys = [
                    "file",
                    "owner",
                    "element_count",
                    "attribute_count",
                    "unique_elements",
                    "missing_string_keys",
                    "error_count",
                    "warning_count",
                ]
                for k in required_keys:
                    if k not in act:
                        by_file_ok = False
                        break
                if not by_file_ok:
                    break
                # Compare values
                if act.get("file") != exp.get("file"):
                    by_file_ok = False
                    break
                if act.get("owner") != exp.get("owner"):
                    by_file_ok = False
                    break
                try:
                    if int(act.get("element_count")) != int(exp.get("element_count")):
                        by_file_ok = False
                        break
                    if int(act.get("attribute_count")) != int(exp.get("attribute_count")):
                        by_file_ok = False
                        break
                    if int(act.get("missing_string_keys")) != int(exp.get("missing_string_keys")):
                        by_file_ok = False
                        break
                    if int(act.get("error_count")) != int(exp.get("error_count")):
                        by_file_ok = False
                        break
                    if int(act.get("warning_count")) != int(exp.get("warning_count")):
                        by_file_ok = False
                        break
                except Exception:
                    by_file_ok = False
                    break
                # unique_elements must be sorted list equality
                act_ue = act.get("unique_elements")
                exp_ue = exp.get("unique_elements")
                if not (isinstance(act_ue, list) and isinstance(exp_ue, list)):
                    by_file_ok = False
                    break
                if act_ue != exp_ue:
                    by_file_ok = False
                    break

        if by_file_ok:
            scores["summary_by_file_metrics_correct"] = 1.0

        # totals check
        act_totals = summary_json.get("totals", {})
        exp_totals = expected_summary["totals"]  # type: ignore
        totals_ok = True
        try:
            for k in ["files", "elements", "attributes", "errors", "warnings"]:
                if int(act_totals.get(k)) != int(exp_totals.get(k)):  # type: ignore
                    totals_ok = False
                    break
        except Exception:
            totals_ok = False
        if totals_ok:
            scores["summary_totals_correct"] = 1.0

        # by_owner check
        act_by_owner = summary_json.get("by_owner", {})
        exp_by_owner = expected_summary["by_owner"]  # type: ignore
        by_owner_ok = True
        if set(act_by_owner.keys()) != set(exp_by_owner.keys()):  # type: ignore
            by_owner_ok = False
        else:
            for owner, expv in exp_by_owner.items():  # type: ignore
                av = act_by_owner.get(owner)
                if not isinstance(av, dict):
                    by_owner_ok = False
                    break
                try:
                    for k in ["total_files", "total_elements", "total_attributes", "total_errors", "total_warnings"]:
                        if int(av.get(k)) != int(expv.get(k)):  # type: ignore
                            by_owner_ok = False
                            break
                except Exception:
                    by_owner_ok = False
                    break
                if not by_owner_ok:
                    break
        if by_owner_ok:
            scores["summary_by_owner_correct"] = 1.0

    # Cross-consistency between triage.csv and summary.json
    # Compute actual counts from triage.csv and compare with summary.json by_file and by_owner
    if triage_header_rows is not None and scores["triage_csv_exists_and_header"] == 1.0 and isinstance(summary_json, dict) and scores["summary_json_exists_and_shape"] == 1.0:
        _, actual_triage_rows = triage_header_rows

        # Build counts by file basename and by owner from triage.csv itself
        triage_counts_by_file: Dict[str, Dict[str, int]] = {}
        triage_counts_by_owner: Dict[str, Dict[str, int]] = {}
        for r in actual_triage_rows:
            sev = r.get("severity", "")
            file_base = r.get("file", "")
            owner = r.get("owner", "Unassigned")
            if sev not in {"ERROR", "WARNING"}:
                continue
            fcounts = triage_counts_by_file.setdefault(file_base, {"errors": 0, "warnings": 0})
            if sev == "ERROR":
                fcounts["errors"] += 1
            else:
                fcounts["warnings"] += 1
            oc = triage_counts_by_owner.setdefault(owner, {"errors": 0, "warnings": 0})
            if sev == "ERROR":
                oc["errors"] += 1
            else:
                oc["warnings"] += 1

        # Compare with summary by_file and by_owner
        by_file_list = summary_json.get("by_file", [])
        by_owner_obj = summary_json.get("by_owner", {})

        consistent = True
        if not isinstance(by_file_list, list) or not isinstance(by_owner_obj, dict):
            consistent = False
        else:
            # Files
            for entry in by_file_list:
                if not isinstance(entry, dict):
                    consistent = False
                    break
                fpath = entry.get("file")
                if not isinstance(fpath, str):
                    consistent = False
                    break
                base = Path(fpath).name
                exp_counts = triage_counts_by_file.get(base, {"errors": 0, "warnings": 0})
                try:
                    if int(entry.get("error_count", -1)) != int(exp_counts["errors"]):
                        consistent = False
                        break
                    if int(entry.get("warning_count", -1)) != int(exp_counts["warnings"]):
                        consistent = False
                        break
                except Exception:
                    consistent = False
                    break
            # Owners
            if consistent:
                for owner, agg in by_owner_obj.items():
                    if not isinstance(agg, dict):
                        consistent = False
                        break
                    tri = triage_counts_by_owner.get(owner, {"errors": 0, "warnings": 0})
                    try:
                        if int(agg.get("total_errors", -1)) != int(tri["errors"]):
                            consistent = False
                            break
                        if int(agg.get("total_warnings", -1)) != int(tri["warnings"]):
                            consistent = False
                            break
                    except Exception:
                        consistent = False
                        break

        if consistent:
            scores["summary_consistent_with_triage_csv"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()