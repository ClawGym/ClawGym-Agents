import json
import sys
import re
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        headers = set(h.strip().lower() for h in (reader.fieldnames or []))
        required = {"path", "mode", "owner"}
        if not required.issubset(headers):
            return None
        return rows
    except Exception:
        return None


def _is_iso8601(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _scan_directory_secrets(input_root: Path) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    if not input_root.exists():
        return found
    for p in input_root.rglob("*"):
        if p.is_file():
            name = p.name
            t: Optional[str] = None
            if name == ".env":
                t = "env"
            elif name.endswith(".key"):
                t = "key"
            elif name.endswith(".pem"):
                t = "pem"
            if t:
                rel = p.as_posix()
                found.append((rel, t))
    seen = set()
    out: List[Tuple[str, str]] = []
    for path, t in sorted(found):
        if path not in seen:
            out.append((path, t))
            seen.add(path)
    return out


def _summarize_totals(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for f in findings:
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
    return counts


def _parse_summary_counts(text: str) -> Optional[Dict[str, int]]:
    if not text:
        return None
    counts: Dict[str, int] = {}
    for sev in ["High", "Medium", "Low"]:
        pattern = re.compile(rf"{sev}\s*[:\-]?\s*(\d+)", flags=re.IGNORECASE)
        m = pattern.search(text)
        if m:
            try:
                counts[sev] = int(m.group(1))
            except Exception:
                return None
        else:
            return None
    return counts


def _extract_top3_section_lines(text: str) -> List[str]:
    lines = text.splitlines()
    idx = -1
    for i, line in enumerate(lines):
        if "top 3" in line.lower():
            idx = i
            break
    if idx == -1:
        return []
    collected: List[str] = []
    for j in range(idx + 1, len(lines)):
        line = lines[j].strip()
        if not line:
            if collected:
                break
            else:
                continue
        if any(h in line.lower() for h in ["next steps", "overview", "risk posture", "conclusion", "summary"]):
            break
        collected.append(line)
        if len(collected) >= 6:
            break
    return collected


def _path_exists_relative(workspace: Path, rel_path: str) -> bool:
    p = (workspace / rel_path)
    try:
        return p.exists()
    except Exception:
        return False


def _normalize_rel_path(base: Path, p: Path) -> str:
    try:
        return p.relative_to(base).as_posix()
    except Exception:
        return p.as_posix()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_json_loadable": 0.0,
        "scope_matches_spec": 0.0,
        "generated_at_iso8601": 0.0,
        "findings_count_and_areas": 0.0,
        "findings_evidence_paths_valid": 0.0,
        "totals_match_findings": 0.0,
        "directory_secrets_complete": 0.0,
        "permissions_analysis_from_csv": 0.0,
        "excerpts_do_not_leak_secrets": 0.0,
        "summary_exists_and_sections": 0.0,
        "summary_severity_counts_match": 0.0,
        "summary_top3_refer_to_findings": 0.0,
        "summary_within_300_words": 0.0,
    }

    report_path = workspace / "output" / "findings" / "report.json"
    summary_path = workspace / "output" / "findings" / "summary.md"

    report = _load_json(report_path)
    if report is None:
        return scores
    scores["report_json_loadable"] = 1.0

    expected_scope = [
        "input/app/src/app.py",
        "input/app/config/settings.yaml",
        "input/app/docker/Dockerfile",
        "input/infra/nginx.conf",
        "input/ops/file_inventory.csv",
        "input/** (directory scan)",
    ]
    scope = report.get("scope")
    if isinstance(scope, list) and scope == expected_scope:
        scores["scope_matches_spec"] = 1.0

    gen = report.get("generated_at")
    if isinstance(gen, str) and _is_iso8601(gen):
        scores["generated_at_iso8601"] = 1.0

    findings = report.get("findings")
    allowed_areas = {
        "app_code",
        "app_config",
        "container",
        "web_server",
        "file_permissions",
        "secrets_in_repo",
    }
    allowed_sev = {"High", "Medium", "Low"}
    areas_present = set()
    evidence_paths_valid = True
    findings_ok = False
    if isinstance(findings, list) and len(findings) >= 6:
        for f in findings:
            if not isinstance(f, dict):
                evidence_paths_valid = False
                break
            if not f.get("id") or not isinstance(f.get("id"), str):
                evidence_paths_valid = False
                break
            area = f.get("area")
            title = f.get("title")
            sev = f.get("severity")
            evidence = f.get("evidence")
            rationale = f.get("rationale")
            remediation = f.get("remediation")
            if area in allowed_areas:
                areas_present.add(area)
            else:
                evidence_paths_valid = False
                break
            if not title or not isinstance(title, str):
                evidence_paths_valid = False
                break
            if sev not in allowed_sev:
                evidence_paths_valid = False
                break
            if not rationale or not isinstance(rationale, str):
                evidence_paths_valid = False
                break
            if not remediation or not isinstance(remediation, str):
                evidence_paths_valid = False
                break
            if not isinstance(evidence, dict):
                evidence_paths_valid = False
                break
            file_path = evidence.get("file_path")
            lines_or_keys = evidence.get("lines_or_keys")
            excerpt = evidence.get("excerpt")
            if not isinstance(file_path, str) or not file_path.startswith("input/"):
                evidence_paths_valid = False
                break
            if not _path_exists_relative(workspace, file_path):
                evidence_paths_valid = False
                break
            if not isinstance(lines_or_keys, list) or len(lines_or_keys) == 0:
                evidence_paths_valid = False
                break
            if not isinstance(excerpt, str):
                evidence_paths_valid = False
                break
        required_areas = {
            "app_code",
            "app_config",
            "container",
            "web_server",
            "file_permissions",
            "secrets_in_repo",
        }
        if required_areas.issubset(areas_present):
            findings_ok = True

    if findings_ok:
        scores["findings_count_and_areas"] = 1.0

    if evidence_paths_valid and findings_ok:
        scores["findings_evidence_paths_valid"] = 1.0

    totals = report.get("totals")
    if isinstance(totals, dict):
        computed = _summarize_totals(findings if isinstance(findings, list) else [])
        try:
            t_high = int(totals.get("High", -1))
            t_med = int(totals.get("Medium", -1))
            t_low = int(totals.get("Low", -1))
            if t_high == computed["High"] and t_med == computed["Medium"] and t_low == computed["Low"]:
                scores["totals_match_findings"] = 1.0
        except Exception:
            pass

    directory_secrets = report.get("directory_secrets")
    input_root = (workspace / "input")
    scanned = _scan_directory_secrets(input_root)
    expected_secrets = [(p if p.startswith("input/") else _normalize_rel_path(workspace, Path(p)), t) for p, t in scanned]

    if isinstance(directory_secrets, list):
        got = set()
        valid_structure = True
        for item in directory_secrets:
            if not isinstance(item, dict):
                valid_structure = False
                break
            pth = item.get("path")
            typ = item.get("type")
            if not isinstance(pth, str) or typ not in {"env", "key", "pem"}:
                valid_structure = False
                break
            got.add((pth, typ))
        if valid_structure:
            if expected_secrets:
                included_all = all(es in got for es in expected_secrets)
                if included_all and len(got) >= len(expected_secrets):
                    scores["directory_secrets_complete"] = 1.0
            else:
                if len(directory_secrets) == 0:
                    scores["directory_secrets_complete"] = 1.0

    permissions_analysis = report.get("permissions_analysis")
    csv_rows = _load_csv_rows(workspace / "input" / "ops" / "file_inventory.csv")
    csv_paths_to_mode_owner: Dict[str, Tuple[str, str]] = {}
    if csv_rows is not None:
        for r in csv_rows:
            p = (r.get("path") or "").strip()
            mode = (r.get("mode") or "").strip()
            owner = (r.get("owner") or "").strip()
            if p:
                csv_paths_to_mode_owner[p] = (mode, owner)

    perm_ok = False
    if isinstance(permissions_analysis, list) and len(permissions_analysis) > 0 and csv_rows is not None:
        valid_entries = 0
        risky_csv_paths = set()
        for p, (mode, owner) in csv_paths_to_mode_owner.items():
            sensitive = (".env" in p) or (p.endswith("settings.yaml")) or (p.endswith(".key"))
            g = o = None
            if len(mode) == 3 and mode.isdigit():
                try:
                    g = int(mode[1])
                    o = int(mode[2])
                except Exception:
                    g = o = None
            permissive = False
            if g is not None and o is not None:
                if (g & 0b010) or (o & 0b010):
                    permissive = True
                if sensitive and (o & 0b100):
                    permissive = True
            if sensitive or permissive:
                risky_csv_paths.add(p)

        for item in permissions_analysis:
            if not isinstance(item, dict):
                continue
            path_val = item.get("path")
            mode_val = item.get("mode")
            owner_val = item.get("owner")
            risk_val = item.get("risk")
            reason = item.get("reason")
            rec = item.get("recommendation")
            if (
                isinstance(path_val, str) and isinstance(mode_val, str) and isinstance(owner_val, str)
                and risk_val in {"High", "Medium", "Low"} and isinstance(reason, str) and isinstance(rec, str)
            ):
                csv_tuple = csv_paths_to_mode_owner.get(path_val)
                if csv_tuple and csv_tuple[0] == mode_val and csv_tuple[1] == owner_val:
                    valid_entries += 1

        if valid_entries >= 1:
            has_risky = False
            for item in permissions_analysis:
                path_val = item.get("path") if isinstance(item, dict) else None
                if isinstance(path_val, str) and path_val in risky_csv_paths:
                    has_risky = True
                    break
            if has_risky:
                perm_ok = True

    if perm_ok:
        scores["permissions_analysis_from_csv"] = 1.0

    secrets_to_avoid: List[str] = []
    env_text = _read_text(workspace / "input" / "app" / ".env")
    if env_text:
        for line in env_text.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                val = v.strip()
                if val:
                    secrets_to_avoid.append(val)
    settings_text = _read_text(workspace / "input" / "app" / "config" / "settings.yaml")
    if settings_text:
        for m in re.finditer(r'[:=]\s*"(.*?)"', settings_text):
            secrets_to_avoid.append(m.group(1))
        for m in re.finditer(r'[:=]\s*([^\s#]+://[^\s#]+)', settings_text):
            secrets_to_avoid.append(m.group(1))
    key_text = _read_text(workspace / "input" / "credentials" / "dev.key")
    if key_text:
        if "-----BEGIN PRIVATE KEY-----" in key_text:
            secrets_to_avoid.append("-----BEGIN PRIVATE KEY-----")
        for line in key_text.splitlines():
            s = line.strip()
            if s and len(s) > 10:
                secrets_to_avoid.append(s[:16])
                break

    excerpt_leak_free = True
    if isinstance(findings, list):
        for f in findings:
            evidence = f.get("evidence") if isinstance(f, dict) else None
            excerpt = evidence.get("excerpt") if isinstance(evidence, dict) else None
            if isinstance(excerpt, str) and excerpt:
                for secret in secrets_to_avoid:
                    if secret and secret in excerpt:
                        excerpt_leak_free = False
                        break
            if not excerpt_leak_free:
                break
    if excerpt_leak_free and findings_ok:
        scores["excerpts_do_not_leak_secrets"] = 1.0

    summary_text = _read_text(summary_path)
    if isinstance(summary_text, str):
        has_overview = "overview" in summary_text.lower()
        has_risk_posture = "risk posture" in summary_text.lower()
        has_top3 = "top 3" in summary_text.lower()
        has_next_steps = "next steps" in summary_text.lower()
        if has_overview and has_risk_posture and has_top3 and has_next_steps:
            scores["summary_exists_and_sections"] = 1.0

        word_count = len(re.findall(r"\b\w+\b", summary_text))
        if word_count <= 300:
            scores["summary_within_300_words"] = 1.0

        parsed_counts = _parse_summary_counts(summary_text)
        if parsed_counts and isinstance(totals, dict):
            try:
                if (
                    int(totals.get("High", -1)) == parsed_counts["High"]
                    and int(totals.get("Medium", -1)) == parsed_counts["Medium"]
                    and int(totals.get("Low", -1)) == parsed_counts["Low"]
                ):
                    scores["summary_severity_counts_match"] = 1.0
            except Exception:
                pass

        top3_lines = _extract_top3_section_lines(summary_text)
        evidence_paths = []
        if isinstance(findings, list):
            for f in findings:
                ev = f.get("evidence") if isinstance(f, dict) else None
                fp = ev.get("file_path") if isinstance(ev, dict) else None
                if isinstance(fp, str):
                    evidence_paths.append(fp)
        refs = 0
        for line in top3_lines:
            for fp in evidence_paths:
                if fp in line or Path(fp).name in line:
                    refs += 1
                    break
        if refs >= 3:
            scores["summary_top3_refer_to_findings"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()