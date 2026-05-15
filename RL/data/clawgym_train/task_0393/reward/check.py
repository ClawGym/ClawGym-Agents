import json
import csv
import sys
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Any


def _safe_read_csv_dicts_with_fieldnames(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            fieldnames = reader.fieldnames if reader.fieldnames is not None else []
        return rows, fieldnames
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    res = _safe_read_csv_dicts_with_fieldnames(path)
    if res is None:
        return None
    rows, _ = res
    return rows


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_ncbi_names_dmp(path: Path) -> Optional[Tuple[Dict[int, str], Dict[str, int]]]:
    # Returns (tax_id_to_scientific_name, scientific_name_to_tax_id)
    try:
        tax_id_to_sci: Dict[int, str] = {}
        name_to_tax: Dict[str, int] = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                tax_id_str, name_txt, _unique_name, name_class = parts[0], parts[1], parts[2], parts[3]
                if name_class == "scientific name":
                    try:
                        tax_id = int(tax_id_str)
                    except ValueError:
                        continue
                    tax_id_to_sci[tax_id] = name_txt
                    if name_txt not in name_to_tax:
                        name_to_tax[name_txt] = tax_id
        # Require at least some content for it to be considered parseable
        if len(tax_id_to_sci) == 0 or len(name_to_tax) == 0:
            return None
        return (tax_id_to_sci, name_to_tax)
    except Exception:
        return None


def _parse_ncbi_nodes_dmp(path: Path) -> Optional[Dict[int, Tuple[int, str]]]:
    # Returns mapping: tax_id -> (parent_tax_id, rank)
    try:
        nodes: Dict[int, Tuple[int, str]] = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                tax_id_str, parent_tax_id_str, rank = parts[0], parts[1], parts[2]
                try:
                    tax_id = int(tax_id_str)
                    parent_tax_id = int(parent_tax_id_str)
                except ValueError:
                    continue
                nodes[tax_id] = (parent_tax_id, rank)
        if len(nodes) == 0:
            return None
        return nodes
    except Exception:
        return None


def _find_family_for_tax_id(tax_id: int, nodes: Dict[int, Tuple[int, str]]) -> Optional[int]:
    visited = set()
    current = tax_id
    while current in nodes and current not in visited:
        visited.add(current)
        parent, rank = nodes[current]
        if rank == "family":
            return current
        if current == parent:
            break
        current = parent
    return None


def _compute_expected_mapping(
    species_list: List[str],
    names_taxid_map: Dict[str, int],
    taxid_to_sci: Dict[int, str],
    nodes: Dict[int, Tuple[int, str]],
) -> List[Dict[str, str]]:
    expected = []
    for sp in sorted(set(species_list)):
        if sp in names_taxid_map:
            sp_tax_id = names_taxid_map[sp]
            family_tax_id = _find_family_for_tax_id(sp_tax_id, nodes)
            if family_tax_id is not None and family_tax_id in taxid_to_sci:
                family_name = taxid_to_sci[family_tax_id]
                matched_name = taxid_to_sci.get(sp_tax_id, sp)
                rec = {
                    "species": sp,
                    "tax_id": str(sp_tax_id),
                    "family_tax_id": str(family_tax_id),
                    "family_name": family_name,
                    "matched_name": matched_name,
                    "status": "matched",
                }
            else:
                rec = {
                    "species": sp,
                    "tax_id": str(sp_tax_id),
                    "family_tax_id": "",
                    "family_name": "",
                    "matched_name": taxid_to_sci.get(sp_tax_id, sp),
                    "status": "not_found",
                }
        else:
            rec = {
                "species": sp,
                "tax_id": "",
                "family_tax_id": "",
                "family_name": "",
                "matched_name": "",
                "status": "not_found",
            }
        expected.append(rec)
    return expected


def _normalize_str(s: str) -> str:
    return s.strip()


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _to_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except Exception:
            return None
    return None


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    vals = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    else:
        return float((vals[mid - 1] + vals[mid]) / 2.0)


def _compute_family_summary(
    neuro_rows: List[Dict[str, str]],
    mapping_rows: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    species_to_family: Dict[str, str] = {}
    status_map: Dict[str, str] = {}
    for r in mapping_rows:
        sp = r.get("species", "")
        status = r.get("status", "")
        fam = r.get("family_name", "")
        status_map[sp] = status
        if status == "matched":
            species_to_family[sp] = fam

    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in neuro_rows:
        sp = row.get("species", "").strip()
        region = row.get("brain_region", "").strip()
        if status_map.get(sp) != "matched":
            continue
        family_name = species_to_family.get(sp)
        if family_name is None:
            continue
        key = (family_name, region)
        if key not in groups:
            groups[key] = {
                "family_name": family_name,
                "brain_region": region,
                "species_set": set(),
                "counts": [],
                "n_observations": 0,
            }
        groups[key]["species_set"].add(sp)
        try:
            cnt = float(row.get("neuron_count", ""))
        except Exception:
            continue
        groups[key]["counts"].append(cnt)
        groups[key]["n_observations"] += 1

    summary: List[Dict[str, Any]] = []
    for (_family_name, _region), g in groups.items():
        counts = g["counts"]
        if len(counts) == 0:
            continue
        mean_val = sum(counts) / len(counts)
        median_val = _median(counts)
        rec = {
            "family_name": g["family_name"],
            "brain_region": g["brain_region"],
            "n_species": len(g["species_set"]),
            "n_observations": g["n_observations"],
            "mean_neuron_count": mean_val,
            "median_neuron_count": median_val,
        }
        summary.append(rec)
    summary.sort(key=lambda x: (x["family_name"], x["brain_region"]))
    return summary


def _load_taxonomy_mapping_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    res = _safe_read_csv_dicts_with_fieldnames(path)
    if res is None:
        return None
    rows, fieldnames = res
    required_cols = ["species", "tax_id", "family_tax_id", "family_name", "matched_name", "status"]
    if not all(col in (fieldnames or []) for col in required_cols):
        return None
    norm_rows: List[Dict[str, str]] = []
    for r in rows:
        norm = {k: _normalize_str(v) if isinstance(v, str) else v for k, v in r.items()}
        norm_rows.append(norm)
    return norm_rows


def _compare_mapping(expected: List[Dict[str, str]], actual: List[Dict[str, str]]) -> bool:
    exp_by_sp = {r["species"]: r for r in expected}
    act_by_sp = {r["species"]: r for r in actual}
    if set(exp_by_sp.keys()) != set(act_by_sp.keys()):
        return False
    for sp in exp_by_sp:
        e = exp_by_sp[sp]
        a = act_by_sp[sp]
        if e.get("status") != a.get("status"):
            return False
        if e.get("status") == "matched":
            if e.get("tax_id", "") != a.get("tax_id", ""):
                return False
            if e.get("family_tax_id", "") != a.get("family_tax_id", ""):
                return False
            if e.get("family_name", "") != a.get("family_name", ""):
                return False
            if e.get("matched_name", "") != a.get("matched_name", ""):
                return False
        else:
            fam_name = a.get("family_name", "")
            if fam_name not in ("", None):
                return False
    return True


def _load_family_summary_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    res = _safe_read_csv_dicts_with_fieldnames(path)
    if res is None:
        return None
    rows, fieldnames = res
    required_cols = [
        "family_name",
        "brain_region",
        "n_species",
        "n_observations",
        "mean_neuron_count",
        "median_neuron_count",
    ]
    if not all(col in (fieldnames or []) for col in required_cols):
        return None
    norm_rows: List[Dict[str, Any]] = []
    for r in rows:
        try:
            fam = _normalize_str(r.get("family_name", ""))
            region = _normalize_str(r.get("brain_region", ""))
            n_sp = int(r.get("n_species", ""))
            n_obs = int(r.get("n_observations", ""))
            mean_val = float(r.get("mean_neuron_count", ""))
            median_val = float(r.get("median_neuron_count", ""))
            norm_rows.append(
                {
                    "family_name": fam,
                    "brain_region": region,
                    "n_species": n_sp,
                    "n_observations": n_obs,
                    "mean_neuron_count": mean_val,
                    "median_neuron_count": median_val,
                }
            )
        except Exception:
            return None
    return norm_rows


def _compare_family_summary(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> bool:
    def key(r):
        return (r["family_name"], r["brain_region"])
    exp_map = {key(r): r for r in expected}
    act_map = {key(r): r for r in actual}
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for k in exp_map:
        e = exp_map[k]
        a = act_map[k]
        if e["n_species"] != a["n_species"]:
            return False
        if e["n_observations"] != a["n_observations"]:
            return False
        if not _float_equal(float(e["mean_neuron_count"]), float(a["mean_neuron_count"])):
            return False
        if not _float_equal(float(e["median_neuron_count"]), float(a["median_neuron_count"])):
            return False
    return True


def _compute_key_numbers(
    neuro_rows: List[Dict[str, str]],
    family_summary: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    species_set = set()
    for r in neuro_rows:
        sp = r.get("species", "").strip()
        if sp:
            species_set.add(sp)
    total_species = len(species_set)

    ot_rows = [r for r in family_summary if r["brain_region"] == "optic_tectum"]
    if len(ot_rows) == 0:
        return None
    ot_rows_sorted = sorted(ot_rows, key=lambda x: (-float(x["mean_neuron_count"]), x["family_name"]))
    top = ot_rows_sorted[0]
    top_family_obj = {
        "family_name": top["family_name"],
        "mean_neuron_count": float(top["mean_neuron_count"]),
    }

    means = [float(r["mean_neuron_count"]) for r in ot_rows]
    median_ot = _median(means)

    return {
        "total_species": total_species,
        "top_family_optic_tectum": top_family_obj,
        "median_optic_tectum_across_families": median_ot,
    }


def _validate_key_numbers_json(path: Path, expected: Dict[str, Any]) -> bool:
    data = _safe_load_json(path)
    if data is None:
        return False
    if "total_species" not in data or "top_family_optic_tectum" not in data or "median_optic_tectum_across_families" not in data:
        return False
    try:
        if int(data["total_species"]) != int(expected["total_species"]):
            return False
    except Exception:
        return False
    top_a = data["top_family_optic_tectum"]
    if not isinstance(top_a, dict):
        return False
    if "family_name" not in top_a or "mean_neuron_count" not in top_a:
        return False
    if str(top_a["family_name"]) != str(expected["top_family_optic_tectum"]["family_name"]):
        return False
    a_mean = _to_float(top_a["mean_neuron_count"])
    e_mean = _to_float(expected["top_family_optic_tectum"]["mean_neuron_count"])
    if a_mean is None or e_mean is None or not _float_equal(a_mean, e_mean):
        return False
    a_median = _to_float(data["median_optic_tectum_across_families"])
    e_median = _to_float(expected["median_optic_tectum_across_families"]) if "median_optic_tectum_across_families" in expected else _to_float(expected["median_optic_tectum_across_families"])
    # The expected key is "median_optic_tectum_across_families"
    if a_median is None or e_median is None or not _float_equal(a_median, e_median):
        return False
    return True


def _extract_rewrites_sections(text: str) -> Dict[str, str]:
    markers = ["Rewrite 1", "Rewrite 2", "Rewrite 3"]
    positions = []
    for m in markers:
        idx = text.find(m)
        if idx != -1:
            positions.append((m, idx))
    positions.sort(key=lambda x: x[1])
    sections: Dict[str, str] = {}
    for i, (name, start_idx) in enumerate(positions):
        end_idx = positions[i + 1][1] if i + 1 < len(positions) else len(text)
        section_text = text[start_idx:end_idx].strip()
        sections[name] = section_text
    return sections


def _contains_scientific_notation(text: str) -> bool:
    return ("e" in text) or ("E" in text)


def _find_numeric_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    current = []
    for ch in text:
        if ch.isdigit() or ch in [",", "."]:
            current.append(ch)
        else:
            if current:
                tok = "".join(current)
                if any(c.isdigit() for c in tok):
                    tokens.append(tok)
                current = []
    if current:
        tok = "".join(current)
        if any(c.isdigit() for c in tok):
            tokens.append(tok)
    return tokens


def _numeric_token_matches_value(tokens: List[str], value: float, tol: float = 1e-6) -> bool:
    for tok in tokens:
        normalized = tok.replace(",", "")
        try:
            v = float(normalized)
        except Exception:
            continue
        if _float_equal(v, float(value), tol=tol):
            return True
    return False


def _validate_outreach_rewrites(path: Path, key_numbers: Dict[str, Any]) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    sections = _extract_rewrites_sections(text)
    for i in [1, 2, 3]:
        if f"Rewrite {i}" not in sections:
            return False
    placeholders = ["[TOTAL_SPECIES]", "[TOP_FAMILY]", "[TOP_FAMILY_MEAN_OT]", "[MEDIAN_OT]"]
    for ph in placeholders:
        if ph in text:
            return False
    total_species = key_numbers.get("total_species", None)
    top_family_obj = key_numbers.get("top_family_optic_tectum", {})
    top_family_name = top_family_obj.get("family_name", None)
    top_family_mean = top_family_obj.get("mean_neuron_count", None)
    median_ot = key_numbers.get("median_optic_tectum_across_families", None)
    if total_species is None or top_family_name is None or top_family_mean is None or median_ot is None:
        return False
    for i in [1, 2, 3]:
        sec = sections[f"Rewrite {i}"]
        content = sec.split("\n", 1)[1] if "\n" in sec else ""
        words = [w for w in content.strip().split() if w.strip()]
        if not (70 <= len(words) <= 120):
            return False
        if _contains_scientific_notation(content):
            return False
        if str(top_family_name) not in content:
            return False
        tokens = _find_numeric_tokens(content)
        if not _numeric_token_matches_value(tokens, float(total_species), tol=1e-6):
            return False
        if not _numeric_token_matches_value(tokens, float(top_family_mean), tol=1e-6):
            return False
        if not _numeric_token_matches_value(tokens, float(median_ot), tol=1e-6):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "taxonomy_files_exist": 0.0,
        "names_dmp_parseable": 0.0,
        "nodes_dmp_parseable": 0.0,
        "taxonomy_mapping_csv_correct": 0.0,
        "family_summary_correct": 0.0,
        "key_numbers_correct": 0.0,
        "outreach_rewrites_valid": 0.0,
    }

    names_path = workspace / "external" / "ncbi_taxonomy" / "names.dmp"
    nodes_path = workspace / "external" / "ncbi_taxonomy" / "nodes.dmp"
    neuro_csv_path = workspace / "input" / "neuro_counts.csv"
    mapping_csv_path = workspace / "output" / "taxonomy_mapping.csv"
    family_summary_path = workspace / "output" / "family_summary.csv"
    key_numbers_path = workspace / "output" / "key_numbers.json"
    outreach_rewrites_path = workspace / "output" / "outreach_rewrites.md"

    if names_path.exists() and nodes_path.exists():
        scores["taxonomy_files_exist"] = 1.0

    names_parsed = None
    nodes_parsed = None
    if names_path.exists():
        names_parsed = _parse_ncbi_names_dmp(names_path)
        if names_parsed is not None:
            scores["names_dmp_parseable"] = 1.0
    if nodes_path.exists():
        nodes_parsed = _parse_ncbi_nodes_dmp(nodes_path)
        if nodes_parsed is not None:
            scores["nodes_dmp_parseable"] = 1.0

    neuro_rows = _safe_read_csv_dicts(neuro_csv_path)
    mapping_rows_actual = _load_taxonomy_mapping_csv(mapping_csv_path) if mapping_csv_path.exists() else None
    if (
        neuro_rows is not None
        and names_parsed is not None
        and nodes_parsed is not None
        and mapping_rows_actual is not None
    ):
        taxid_to_sci, name_to_tax = names_parsed
        expected_mapping = _compute_expected_mapping(
            [r.get("species", "").strip() for r in neuro_rows], name_to_tax, taxid_to_sci, nodes_parsed
        )
        if _compare_mapping(expected_mapping, mapping_rows_actual):
            scores["taxonomy_mapping_csv_correct"] = 1.0

    family_summary_actual = _load_family_summary_csv(family_summary_path) if family_summary_path.exists() else None
    if neuro_rows is not None and mapping_rows_actual is not None and family_summary_actual is not None:
        expected_family_summary = _compute_family_summary(neuro_rows, mapping_rows_actual)
        if _compare_family_summary(expected_family_summary, family_summary_actual):
            scores["family_summary_correct"] = 1.0

    if neuro_rows is not None and family_summary_actual is not None:
        expected_key_numbers = _compute_key_numbers(neuro_rows, family_summary_actual)
        if expected_key_numbers is not None and _validate_key_numbers_json(key_numbers_path, expected_key_numbers):
            scores["key_numbers_correct"] = 1.0

    key_numbers_data = _safe_load_json(key_numbers_path) if key_numbers_path.exists() else None
    if key_numbers_data is not None and outreach_rewrites_path.exists():
        if _validate_outreach_rewrites(outreach_rewrites_path, key_numbers_data):
            scores["outreach_rewrites_valid"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()