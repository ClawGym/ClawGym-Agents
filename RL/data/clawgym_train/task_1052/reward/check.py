import json
import csv
import sys
import re
import ast
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _parse_config_py(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        wanted = {"PROJECT_NAME", "DATA_VERSION", "FIGURES_DIR", "HIGHLIGHTS_TOP_N"}
        vals: Dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in wanted:
                        try:
                            vals[target.id] = ast.literal_eval(node.value)
                        except Exception:
                            # Fallback for simple constants
                            if isinstance(node.value, ast.Constant):
                                vals[target.id] = node.value.value
        # Basic type normalization
        if "HIGHLIGHTS_TOP_N" in vals:
            try:
                vals["HIGHLIGHTS_TOP_N"] = int(vals["HIGHLIGHTS_TOP_N"])
            except Exception:
                pass
        return vals
    except Exception:
        return None


def _parse_visual_manifest_yaml(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Minimal YAML parser for the expected structure:
    figures:
      - id: F001
        file: path
        source_publication_id: P...
        license: ...
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    in_figures = False
    items: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def _parse_key_val(s: str) -> Optional[Tuple[str, str]]:
        if ":" not in s:
            return None
        key, val = s.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes if present
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        return key, val

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("figures:"):
            in_figures = True
            continue
        if not in_figures:
            continue
        if stripped.startswith("-"):
            # Start of a new item
            # Could be "- id: F001" or just "-"
            after_dash = stripped[1:].strip()
            current = {}
            items.append(current)
            if after_dash:
                kv = _parse_key_val(after_dash)
                if kv and current is not None:
                    k, v = kv
                    current[k] = v
            continue
        # Subsequent key: value lines within an item
        if current is not None:
            kv2 = _parse_key_val(stripped)
            if kv2:
                k2, v2 = kv2
                current[k2] = v2

    return items


def _parse_press_highlights_ids(path: Path) -> Optional[List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    ids: List[str] = []
    pattern = re.compile(r"^\s*-\s+.*\((P\d+)\)\s*$")
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            ids.append(m.group(1))
    return ids


def _compute_top_publications(pub_rows: List[Dict[str, str]], top_n: int) -> List[Tuple[str, str, float]]:
    parsed: List[Tuple[str, str, float]] = []
    for r in pub_rows:
        try:
            pid = r["id"].strip()
            title = r["title"].strip()
            score = float(r["impact_score"])
            parsed.append((pid, title, score))
        except Exception:
            # If any row invalid, fail the whole parse by returning empty
            return []
    # Sort: by impact_score desc, break ties by id asc
    parsed.sort(key=lambda x: (-x[2], x[0]))
    return parsed[:max(0, top_n)]


def _scan_figures_dir(workspace: Path, figures_dir: str) -> List[str]:
    dir_path = workspace / figures_dir
    files: List[str] = []
    try:
        if dir_path.exists() and dir_path.is_dir():
            for p in sorted(dir_path.iterdir()):
                if p.is_file():
                    files.append(str(p.relative_to(workspace).as_posix()))
    except Exception:
        return []
    return files


def _normalize_list(obj: Any) -> List[Any]:
    if isinstance(obj, list):
        return obj
    return []


def _contains_any_bullet(text: str) -> bool:
    for line in text.splitlines():
        if line.strip().startswith("- "):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_fields_present": 0.0,
        "report_project_and_versions_correct": 0.0,
        "report_figures_validation_correct": 0.0,
        "report_top_n_ids_correct": 0.0,
        "report_press_highlights_claims_correct": 0.0,
        "report_press_highlights_discrepancies_correct": 0.0,
        "top_publications_csv_correct": 0.0,
        "output_dirs_present": 0.0,
        "email_exists_and_nonempty": 0.0,
        "email_version_status_mentioned": 0.0,
        "email_figures_issues_mentioned": 0.0,
        "email_press_discrepancies_mentioned": 0.0,
        "email_polite_tone_and_next_steps": 0.0,
    }

    # Load config
    config_path = workspace / "input" / "code" / "config.py"
    config = _parse_config_py(config_path)
    if not config:
        return scores

    project_name = config.get("PROJECT_NAME")
    data_version_config = config.get("DATA_VERSION")
    figures_dir = config.get("FIGURES_DIR")
    top_n = config.get("HIGHLIGHTS_TOP_N")

    if project_name is None or data_version_config is None or figures_dir is None or top_n is None:
        return scores

    # Load dataset metadata
    metadata_path = workspace / "input" / "dataset_metadata.json"
    metadata_json = _safe_load_json(metadata_path) or {}
    data_version_metadata = metadata_json.get("version")

    # Load publications
    pubs_path = workspace / "input" / "publications.csv"
    pubs_rows = _safe_load_csv(pubs_path)
    if pubs_rows is None:
        pubs_rows = []

    # Compute expected top-N
    expected_top = _compute_top_publications(pubs_rows, top_n)
    expected_top_ids = [pid for pid, title, score in expected_top]

    # Load manifest
    manifest_path = workspace / "input" / "visual_manifest.yaml"
    manifest_entries = _parse_visual_manifest_yaml(manifest_path)
    if manifest_entries is None:
        manifest_entries = []

    # Compute expected figures checks
    present_files = set(_scan_figures_dir(workspace, figures_dir))
    manifest_files = set()
    missing_figures: List[str] = []
    figures_without_license: List[str] = []
    figures_with_invalid_pub: List[Dict[str, str]] = []

    pub_ids_set = set([r.get("id", "").strip() for r in pubs_rows if "id" in r])

    for entry in manifest_entries:
        fid = entry.get("id", "")
        fpath = entry.get("file", "")
        spid = entry.get("source_publication_id", "")
        lic = entry.get("license", None)
        if fpath:
            manifest_files.add(fpath)
            f_abs = workspace / fpath
            if not f_abs.exists():
                missing_figures.append(fpath)
        # license check: blank or missing
        if lic is None or str(lic).strip() == "":
            if fid:
                figures_without_license.append(fid)
        # invalid publication check
        if spid and spid not in pub_ids_set:
            figures_with_invalid_pub.append({"figure_id": fid, "source_publication_id": spid})

    orphan_figures = sorted(list(present_files - manifest_files))
    missing_figures_sorted = sorted(missing_figures)
    figures_without_license_sorted = sorted(figures_without_license)
    invalid_pub_sorted = sorted(figures_with_invalid_pub, key=lambda d: (d.get("figure_id", ""), d.get("source_publication_id", "")))

    figures_manifest_count = len(manifest_entries)
    figures_dir_count = len(present_files)

    # Parse press highlights
    press_md_path = workspace / "input" / "press_highlights.md"
    claimed_ids = _parse_press_highlights_ids(press_md_path) or []
    claimed_id_set = set(claimed_ids)
    expected_top_id_set = set(expected_top_ids)
    expected_missing_from_claims = sorted(list(expected_top_id_set - claimed_id_set))
    expected_extra_in_claims = sorted(list(claimed_id_set - expected_top_id_set))

    # Load outputs
    report_path = workspace / "outputs" / "verification" / "report.json"
    report_json = _safe_load_json(report_path)

    # Check report fields present
    required_report_keys = {
        "project_name",
        "data_version_config",
        "data_version_metadata",
        "dataset_version_match",
        "figures_dir",
        "figures_manifest_count",
        "figures_dir_count",
        "missing_figures",
        "orphan_figures",
        "figures_without_license",
        "figures_with_invalid_publication",
        "top_n_ids",
        "press_highlights_claimed_ids",
        "press_highlights_discrepancies",
        "generated_at",
    }
    if isinstance(report_json, dict) and required_report_keys.issubset(set(report_json.keys())):
        scores["report_fields_present"] = 1.0

        # Check project and versions correctness
        try:
            version_match_expected = (data_version_config == data_version_metadata)
            version_match_report = bool(report_json.get("dataset_version_match"))
            cond = (
                report_json.get("project_name") == project_name
                and report_json.get("data_version_config") == data_version_config
                and report_json.get("data_version_metadata") == data_version_metadata
                and report_json.get("figures_dir") == figures_dir
                and version_match_report == version_match_expected
            )
            scores["report_project_and_versions_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["report_project_and_versions_correct"] = 0.0

        # Figures validation correctness
        try:
            rep_missing = sorted(_normalize_list(report_json.get("missing_figures")))
            rep_orphan = sorted(_normalize_list(report_json.get("orphan_figures")))
            rep_wo_license = sorted(_normalize_list(report_json.get("figures_without_license")))
            rep_invalid = report_json.get("figures_with_invalid_publication")
            if not isinstance(rep_invalid, list):
                rep_invalid = []
            rep_invalid_sorted = sorted(
                [
                    {"figure_id": str(d.get("figure_id", "")), "source_publication_id": str(d.get("source_publication_id", ""))}
                    for d in rep_invalid
                ],
                key=lambda d: (d.get("figure_id", ""), d.get("source_publication_id", "")),
            )
            counts_ok = (
                isinstance(report_json.get("figures_manifest_count"), int)
                and isinstance(report_json.get("figures_dir_count"), int)
                and report_json.get("figures_manifest_count") == figures_manifest_count
                and report_json.get("figures_dir_count") == figures_dir_count
            )
            cond_fig = (
                rep_missing == missing_figures_sorted
                and rep_orphan == orphan_figures
                and rep_wo_license == figures_without_license_sorted
                and rep_invalid_sorted == invalid_pub_sorted
                and counts_ok
            )
            scores["report_figures_validation_correct"] = 1.0 if cond_fig else 0.0
        except Exception:
            scores["report_figures_validation_correct"] = 0.0

        # Top N IDs correctness in report
        try:
            rep_top_ids = report_json.get("top_n_ids")
            if isinstance(rep_top_ids, list):
                rep_top_ids_list = [str(x) for x in rep_top_ids]
            else:
                rep_top_ids_list = []
            scores["report_top_n_ids_correct"] = 1.0 if rep_top_ids_list == expected_top_ids else 0.0
        except Exception:
            scores["report_top_n_ids_correct"] = 0.0

        # Press highlights claimed IDs correctness in report
        try:
            rep_claimed_ids = report_json.get("press_highlights_claimed_ids")
            rep_claimed_set = set([str(x) for x in rep_claimed_ids]) if isinstance(rep_claimed_ids, list) else set()
            cond_claims = (rep_claimed_set == claimed_id_set)
            scores["report_press_highlights_claims_correct"] = 1.0 if cond_claims else 0.0
        except Exception:
            scores["report_press_highlights_claims_correct"] = 0.0

        # Press highlights discrepancies correctness in report
        try:
            rep_disc = report_json.get("press_highlights_discrepancies")
            if isinstance(rep_disc, dict):
                rep_missing_from_claims = sorted([str(x) for x in rep_disc.get("missing_from_claims", [])])
                rep_extra_in_claims = sorted([str(x) for x in rep_disc.get("extra_in_claims", [])])
                cond_disc = (
                    rep_missing_from_claims == expected_missing_from_claims
                    and rep_extra_in_claims == expected_extra_in_claims
                )
                scores["report_press_highlights_discrepancies_correct"] = 1.0 if cond_disc else 0.0
            else:
                scores["report_press_highlights_discrepancies_correct"] = 0.0
        except Exception:
            scores["report_press_highlights_discrepancies_correct"] = 0.0

    else:
        # report_fields_present already 0.0
        pass

    # Check top_publications.csv correctness
    top_csv_path = workspace / "outputs" / "verification" / "top_publications.csv"
    out_rows = _safe_load_csv(top_csv_path)
    if out_rows is not None and isinstance(out_rows, list):
        # Validate columns and content
        try:
            # Header check: id,title,impact_score in that exact order
            with top_csv_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
            expected_header = "id,title,impact_score"
            header_ok = header_line == expected_header

            # Row count equals top_n
            count_ok = (len(out_rows) == len(expected_top))

            # Content check in order
            content_ok = True
            for idx, row in enumerate(out_rows):
                exp_id, exp_title, exp_score = expected_top[idx]
                rid = row.get("id", "").strip()
                rtitle = row.get("title", "").strip()
                try:
                    rscore = float(row.get("impact_score", ""))
                except Exception:
                    content_ok = False
                    break
                if rid != exp_id or rtitle != exp_title or abs(rscore - exp_score) > 1e-9:
                    content_ok = False
                    break

            if header_ok and count_ok and content_ok:
                scores["top_publications_csv_correct"] = 1.0
            else:
                scores["top_publications_csv_correct"] = 0.0
        except Exception:
            scores["top_publications_csv_correct"] = 0.0
    else:
        scores["top_publications_csv_correct"] = 0.0

    # Output dirs present
    ver_dir = workspace / "outputs" / "verification"
    comm_dir = workspace / "outputs" / "communication"
    try:
        if ver_dir.exists() and ver_dir.is_dir() and comm_dir.exists() and comm_dir.is_dir():
            scores["output_dirs_present"] = 1.0
    except Exception:
        scores["output_dirs_present"] = 0.0

    # Email checks
    email_path = workspace / "outputs" / "communication" / "draft_email.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None and email_text.strip():
        scores["email_exists_and_nonempty"] = 1.0

        # Version status mentioned
        dv_match = (data_version_config == data_version_metadata)
        lower = email_text.lower()
        has_bullets = _contains_any_bullet(email_text)
        version_status_ok = False
        if dv_match:
            # Accept if "match"/"matches" present OR both version strings present and not explicitly stating mismatch
            if "mismatch" in lower or "do not match" in lower:
                version_status_ok = False
            elif ("match" in lower or "matches" in lower) or (
                str(data_version_config) in email_text and str(data_version_metadata) in email_text and "version" in lower
            ):
                version_status_ok = True
        else:
            # Accept if indicates mismatch/difference
            if "mismatch" in lower or "do not match" in lower or "different" in lower:
                version_status_ok = True
        scores["email_version_status_mentioned"] = 1.0 if version_status_ok else 0.0

        # Figures issues mentioned (list missing, orphans, licenses, invalid pub refs)
        figs_issues_ok = True
        # Must reference each concrete item if any
        for miss in missing_figures_sorted:
            if miss not in email_text:
                figs_issues_ok = False
                break
        if figs_issues_ok:
            for orphan in orphan_figures:
                if orphan not in email_text:
                    figs_issues_ok = False
                    break
        if figs_issues_ok:
            for fid in figures_without_license_sorted:
                if fid not in email_text:
                    figs_issues_ok = False
                    break
        if figs_issues_ok:
            for inv in invalid_pub_sorted:
                # Require figure id mentioned; optionally source_publication_id as well
                fid = inv.get("figure_id", "")
                spid = inv.get("source_publication_id", "")
                if fid and fid not in email_text:
                    figs_issues_ok = False
                    break
                if spid and spid not in email_text:
                    figs_issues_ok = False
                    break
        # Also require at least one bullet line in the email
        figs_issues_ok = figs_issues_ok and has_bullets
        scores["email_figures_issues_mentioned"] = 1.0 if figs_issues_ok else 0.0

        # Press discrepancies mentioned
        press_disc_ok = True
        for mid in expected_missing_from_claims:
            if mid not in email_text:
                press_disc_ok = False
                break
        if press_disc_ok:
            for xid in expected_extra_in_claims:
                if xid not in email_text:
                    press_disc_ok = False
                    break
        press_disc_ok = press_disc_ok and has_bullets
        scores["email_press_discrepancies_mentioned"] = 1.0 if press_disc_ok else 0.0

        # Polite tone and next steps
        polite = ("please" in lower) or ("thank you" in lower) or ("thanks" in lower) or ("kind regards" in lower)
        next_steps = ("next steps" in lower) or ("we will" in lower) or ("let's" in lower) or ("action" in lower) or ("update" in lower) or ("fix" in lower) or ("proceed" in lower)
        scores["email_polite_tone_and_next_steps"] = 1.0 if (polite and next_steps) else 0.0

    else:
        # email_exists_and_nonempty remains 0.0
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()