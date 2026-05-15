import json
import sys
import re
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as ex:
        return None, f"{type(ex).__name__}"


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    text, err = _safe_read_text(path)
    if err or text is None:
        return None, err or "read_error"
    try:
        return json.loads(text), None
    except Exception as ex:
        return None, f"{type(ex).__name__}"


def _norm_path_str(p: str) -> str:
    p = p.replace("\\", "/")
    p = re.sub(r"/\./", "/", p)
    p = re.sub(r"/{2,}", "/", p)
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def _parse_run_log_findings(path: Path) -> Tuple[List[Tuple[str, str, str, str, str, str]], Optional[str]]:
    text, err = _safe_read_text(path)
    if err or text is None:
        return [], err or "read_error"
    findings: List[Tuple[str, str, str, str, str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("WARNING,") or line.startswith("ERROR,"):
            parts = line.split(",", 5)
            if len(parts) != 6:
                return [], "malformed_line"
            sev, code, post_file, image_id, lic, msg = parts
            findings.append((sev.strip(), code.strip(), _norm_path_str(post_file.strip()), image_id.strip(), lic.strip(), msg.strip()))
    return findings, None


def _load_rules(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    rules_path = workspace / "project" / "compliance_rules.json"
    return _safe_load_json(rules_path)


def _load_metadata(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    meta_path = workspace / "project" / "assets" / "metadata.json"
    return _safe_load_json(meta_path)


def _compute_expected_findings(workspace: Path) -> Tuple[Optional[List[Tuple[str, str, str, str, str, str]]], Optional[str]]:
    rules, err_r = _load_rules(workspace)
    metadata, err_m = _load_metadata(workspace)
    if rules is None or metadata is None:
        return None, err_r or err_m or "missing_config"
    allowed = set(rules.get("allowed_licenses", []))
    require_attr = set(rules.get("require_attribution_for", []))
    posts_dir = workspace / "project" / "posts"
    if not posts_dir.exists():
        return None, "missing_posts"
    expected: List[Tuple[str, str, str, str, str, str]] = []
    try:
        for path in posts_dir.rglob("*.md"):
            text, err = _safe_read_text(path)
            if err or text is None:
                continue
            image_ids = re.findall(r"\[image:id=([A-Za-z0-9_\-]+)\]", text)
            has_attribution = bool(re.search(r"^Attribution:\s*.+", text, flags=re.MULTILINE))
            for img_id in image_ids:
                if img_id not in metadata:
                    expected.append((
                        "ERROR",
                        "UNKNOWN_IMAGE_ID",
                        _norm_path_str(str(path)),
                        img_id,
                        "-",
                        "Image id not found in metadata",
                    ))
                    continue
                lic = str(metadata[img_id].get("license", "")).strip()
                if lic not in allowed:
                    expected.append((
                        "WARNING",
                        "DISALLOWED_LICENSE",
                        _norm_path_str(str(path)),
                        img_id,
                        lic,
                        "License not permitted by rules",
                    ))
                if lic in require_attr and not has_attribution:
                    expected.append((
                        "WARNING",
                        "MISSING_ATTRIBUTION",
                        _norm_path_str(str(path)),
                        img_id,
                        lic,
                        "Attribution required for license but none found",
                    ))
    except Exception as ex:
        return None, f"{type(ex).__name__}"
    return expected, None


def _parse_csv_report(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]], Optional[str]]:
    text, err = _safe_read_text(path)
    if err or text is None:
        return None, None, err or "read_error"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return None, None, "empty_csv"
    header = [h.strip() for h in lines[0].split(",")]
    rows: List[List[str]] = []
    for line in lines[1:]:
        parts = line.split(",", 5)
        if len(parts) != 6:
            return header, None, "malformed_row"
        row = [p.strip() for p in parts]
        rows.append(row)
    return header, rows, None


def _rows_from_run_findings(findings: List[Tuple[str, str, str, str, str, str]]) -> List[List[str]]:
    rows: List[List[str]] = []
    for sev, code, post, img_id, lic, msg in findings:
        rows.append([post, img_id, lic, code, sev, msg])
    return rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "run_log_present_and_combined": 0.0,
        "run_log_expected_findings": 0.0,
        "csv_header_correct": 0.0,
        "csv_rows_match_run_output": 0.0,
        "csv_unknown_image_license_dash": 0.0,
        "run_log_matches_expected_findings": 0.0,
        "remediation_rule_basis": 0.0,
        "remediation_fixes_per_file": 0.0,
        "remediation_command_and_exit_code": 0.0,
        "csv_license_unknown_handling": 0.0,
    }

    log_path = workspace / "output" / "logs" / "check_run_1.txt"
    csv_path = workspace / "output" / "report" / "compliance_report.csv"
    md_path = workspace / "output" / "report" / "remediation.md"

    run_findings, run_err = _parse_run_log_findings(log_path)
    if run_err is None:
        has_warning = any(sev == "WARNING" for sev, *_ in run_findings)
        has_error = any(sev == "ERROR" for sev, *_ in run_findings)
        if has_warning and has_error:
            scores["run_log_present_and_combined"] = 1.0

        expected_findings, exp_err = _compute_expected_findings(workspace)
        if expected_findings is not None:
            norm_run = set(run_findings)
            norm_expected = set(expected_findings)
            if len(norm_expected) > 0:
                matched = len(norm_run & norm_expected)
                scores["run_log_expected_findings"] = matched / float(len(norm_expected))
                scores["run_log_matches_expected_findings"] = 1.0 if norm_run == norm_expected else matched / float(len(norm_expected))
            else:
                scores["run_log_expected_findings"] = 1.0 if len(norm_run) == 0 else 0.0
                scores["run_log_matches_expected_findings"] = scores["run_log_expected_findings"]
        else:
            scores["run_log_expected_findings"] = 0.0
            scores["run_log_matches_expected_findings"] = 0.0
    else:
        scores["run_log_present_and_combined"] = 0.0
        scores["run_log_expected_findings"] = 0.0
        scores["run_log_matches_expected_findings"] = 0.0

    header, csv_rows, csv_err = _parse_csv_report(csv_path)
    if csv_err is None and header is not None and csv_rows is not None:
        expected_header = ["post_file", "image_id", "license", "finding_code", "severity", "message"]
        if header == expected_header:
            scores["csv_header_correct"] = 1.0

        run_rows = _rows_from_run_findings(run_findings) if run_err is None else []

        def norm_row(row: List[str]) -> Tuple[str, str, str, str, str, str]:
            return (_norm_path_str(row[0]), row[1], row[2], row[3], row[4], row[5])

        set_csv = set(norm_row(r) for r in csv_rows)
        set_run = set(norm_row(r) for r in run_rows)
        if set_run:
            matched = len(set_csv & set_run)
            scores["csv_rows_match_run_output"] = 1.0 if set_csv == set_run else (matched / float(len(set_run)))
        else:
            scores["csv_rows_match_run_output"] = 1.0 if len(set_csv) == 0 else 0.0

        unknown_rows = [r for r in csv_rows if r[3] == "UNKNOWN_IMAGE_ID"]
        if unknown_rows:
            ok = all(r[2] == "-" for r in unknown_rows)
            val = 1.0 if ok else 0.0
            scores["csv_unknown_image_license_dash"] = val
            scores["csv_license_unknown_handling"] = val
        else:
            if run_err is None and any(code == "UNKNOWN_IMAGE_ID" for _sev, code, *_ in run_findings):
                scores["csv_unknown_image_license_dash"] = 0.0
                scores["csv_license_unknown_handling"] = 0.0
            else:
                scores["csv_unknown_image_license_dash"] = 1.0
                scores["csv_license_unknown_handling"] = 1.0
    else:
        scores["csv_header_correct"] = 0.0
        scores["csv_rows_match_run_output"] = 0.0
        scores["csv_unknown_image_license_dash"] = 0.0
        scores["csv_license_unknown_handling"] = 0.0

    rem_text, rem_err = _safe_read_text(md_path)
    if rem_err is None and rem_text is not None:
        lower_text = rem_text.lower()
        rules, rules_err = _load_rules(workspace)
        tokens_required: List[str] = []
        if rules is not None:
            tokens_required.extend(["allowed_licenses", "require_attribution_for"])
            for lic in rules.get("allowed_licenses", []):
                tokens_required.append(lic)
            for lic in rules.get("require_attribution_for", []):
                tokens_required.append(lic)
            found = 0
            for tok in tokens_required:
                if tok.lower() in lower_text:
                    found += 1
            scores["remediation_rule_basis"] = found / float(len(tokens_required)) if tokens_required else 0.0
        else:
            scores["remediation_rule_basis"] = 0.0

        fixes_ok = 0
        if ("draft_egypt.md" in rem_text and ("require_attribution_for" in rem_text or "missing_attribution" in lower_text or "attribution" in lower_text)):
            fixes_ok += 1
        if ("draft_indus.md" in rem_text and ("allowed_licenses" in rem_text or "disallowed_license" in lower_text or "disallowed" in lower_text or "license not permitted" in lower_text)):
            fixes_ok += 1
        if ("draft_greece.md" in rem_text and ("unknown_image_id" in lower_text or "metadata.json" in lower_text or "assets/metadata.json" in lower_text or "unknown image" in lower_text)):
            fixes_ok += 1
        scores["remediation_fixes_per_file"] = fixes_ok / 3.0

        cmd_score = 0.0
        lines = rem_text.splitlines()
        matched_cmd = None
        for ln in lines:
            if "check_compliance.py" in ln and "--posts" in ln and "--metadata" in ln and "--rules" in ln:
                matched_cmd = ln.strip()
                break
        if matched_cmd:
            has_posts = "--posts project/posts" in matched_cmd
            has_metadata = "--metadata project/assets/metadata.json" in matched_cmd
            has_rules = "--rules project/compliance_rules.json" in matched_cmd
            if has_posts and has_metadata and has_rules:
                cmd_score += 0.5
        exit_code_expected = 2
        exit_code_found: Optional[int] = None
        m = re.search(r'\b(exit\s*code|return\s*code|returned)\s*[:=]?\s*([0-9]+)', rem_text, flags=re.IGNORECASE)
        if m:
            try:
                exit_code_found = int(m.group(2))
            except Exception:
                exit_code_found = None
        if exit_code_found is not None and exit_code_found == exit_code_expected:
            cmd_score += 0.5
        scores["remediation_command_and_exit_code"] = cmd_score
    else:
        scores["remediation_rule_basis"] = 0.0
        scores["remediation_fixes_per_file"] = 0.0
        scores["remediation_command_and_exit_code"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()