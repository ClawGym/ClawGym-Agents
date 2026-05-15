import json
import re
import sys
from pathlib import Path


INITIAL_TIMEOUT_MS = 500
INITIAL_MAX_RETRIES = 5
INITIAL_THRESHOLD_MS = 1200

MEASURED_RE = re.compile(
    r"MEASURED\s+elapsed_ms=([0-9]+(?:\.[0-9]+)?)\s+threshold=([0-9]+)\s+timeout_ms=([0-9]+)\s+retries=([0-9]+)"
)


def _safe_read_text(path: Path) -> str:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_measured_line(text: str) -> str:
    if not text:
        return None
    lines = [ln.strip() for ln in text.splitlines() if "MEASURED" in ln]
    return lines[-1] if lines else None


def _parse_measured(line: str):
    if not line:
        return None
    m = MEASURED_RE.search(line)
    if not m:
        return None
    try:
        elapsed = float(m.group(1))
        threshold = int(m.group(2))
        timeout_ms = int(m.group(3))
        retries = int(m.group(4))
        return {
            "elapsed_ms": elapsed,
            "threshold": threshold,
            "timeout_ms": timeout_ms,
            "retries": retries,
        }
    except Exception:
        return None


def _has_failure_markers(text: str) -> bool:
    if not text:
        return False
    markers = ["FAIL", "FAILED", "Traceback", "AssertionError"]
    return any(tok in text for tok in markers)


def _has_ok_marker(text: str) -> bool:
    if not text:
        return False
    return "OK" in text


def _extract_section(md_text: str, heading: str) -> str:
    if not md_text:
        return None
    lines = md_text.splitlines()
    start_idx = None
    heading_lower = heading.strip().lower().rstrip(":")
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith(heading_lower + ":"):
            start_idx = i
            break
    if start_idx is None:
        return None
    content_lines = []
    for j in range(start_idx + 1, len(lines)):
        ln = lines[j]
        if ln.strip().endswith(":") and len(ln.strip()) <= 50:
            break
        content_lines.append(ln)
    section = "\n".join(content_lines).strip()
    return section if section else None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "before_output_present": 0.0,
        "before_output_measured_and_failed": 0.0,
        "before_output_values_match_initial": 0.0,
        "before_elapsed_exceeded_threshold": 0.0,
        "after_output_present": 0.0,
        "after_output_measured_and_ok": 0.0,
        "after_elapsed_within_threshold": 0.0,
        "config_threshold_unchanged": 0.0,
        "config_adjusted_within_budget": 0.0,
        "config_changed_from_initial": 0.0,
        "after_measured_matches_config": 0.0,
        "incident_sections_present": 0.0,
        "incident_context_quality": 0.0,
        "incident_root_cause_quality": 0.0,
        "incident_remediation_matches_config": 0.0,
        "incident_evidence_includes_measured_lines": 0.0,
    }

    # Paths
    before_report_path = workspace / "reports" / "before_fix_test_output.txt"
    after_report_path = workspace / "reports" / "after_fix_test_output.txt"
    incident_md_path = workspace / "reports" / "incident_review.md"
    config_path = workspace / "config" / "config.json"

    before_text = _safe_read_text(before_report_path)
    after_text = _safe_read_text(after_report_path)

    if before_text is not None and before_text.strip():
        scores["before_output_present"] = 1.0
    if after_text is not None and after_text.strip():
        scores["after_output_present"] = 1.0

    # Parse MEASURED lines
    before_measured_line = _find_measured_line(before_text or "")
    after_measured_line = _find_measured_line(after_text or "")
    before_measured = _parse_measured(before_measured_line) if before_measured_line else None
    after_measured = _parse_measured(after_measured_line) if after_measured_line else None

    # Before run: should fail and show MEASURED line
    if before_measured is not None and _has_failure_markers(before_text or "") and not _has_ok_marker(before_text or ""):
        scores["before_output_measured_and_failed"] = 1.0

    # Verify before values match initial config (timeout=500, retries=5, threshold=1200)
    if before_measured is not None:
        if (
            before_measured.get("timeout_ms") == INITIAL_TIMEOUT_MS
            and before_measured.get("retries") == INITIAL_MAX_RETRIES
            and before_measured.get("threshold") == INITIAL_THRESHOLD_MS
        ):
            scores["before_output_values_match_initial"] = 1.0
        # and elapsed exceeded threshold
        try:
            if float(before_measured.get("elapsed_ms", -1.0)) > float(before_measured.get("threshold", 0.0)):
                scores["before_elapsed_exceeded_threshold"] = 1.0
        except Exception:
            pass

    # After run: should pass (OK) and show MEASURED line
    if after_measured is not None and _has_ok_marker(after_text or "") and not _has_failure_markers(after_text or ""):
        scores["after_output_measured_and_ok"] = 1.0
        try:
            if float(after_measured.get("elapsed_ms", 1e9)) <= float(after_measured.get("threshold", 0.0)):
                scores["after_elapsed_within_threshold"] = 1.0
        except Exception:
            pass

    # Config checks
    cfg = _safe_load_json(config_path)
    tmo = None
    retries = None
    threshold = None
    if isinstance(cfg, dict):
        try:
            tmo = int(cfg.get("timeouts", {}).get("dependency_timeout_ms"))
        except Exception:
            tmo = None
        try:
            retries = int(cfg.get("timeouts", {}).get("max_retries"))
        except Exception:
            retries = None
        try:
            threshold = int(cfg.get("reliability", {}).get("fail_fast_threshold_ms"))
        except Exception:
            threshold = None

    # adjusted within budget: tmo * retries <= threshold
    if isinstance(tmo, int) and isinstance(retries, int) and isinstance(threshold, int) and tmo >= 0 and retries >= 0:
        if tmo * retries <= threshold:
            scores["config_adjusted_within_budget"] = 1.0

    # changed from initial in at least one of the tuneable values
    if isinstance(tmo, int) and isinstance(retries, int):
        if (tmo != INITIAL_TIMEOUT_MS) or (retries != INITIAL_MAX_RETRIES):
            scores["config_changed_from_initial"] = 1.0

    # After measured values match current config
    if after_measured is not None and isinstance(tmo, int) and isinstance(retries, int):
        if after_measured.get("timeout_ms") == tmo and after_measured.get("retries") == retries:
            scores["after_measured_matches_config"] = 1.0

    # Only award "threshold unchanged" once the after run exists and passed, to avoid crediting baseline setup
    if (
        after_measured is not None
        and _has_ok_marker(after_text or "")
        and not _has_failure_markers(after_text or "")
        and isinstance(threshold, int)
        and threshold == INITIAL_THRESHOLD_MS
    ):
        scores["config_threshold_unchanged"] = 1.0

    # Incident review checks
    incident_text = _safe_read_text(incident_md_path)
    if incident_text is not None and incident_text.strip():
        context_sec = _extract_section(incident_text, "Context")
        root_cause_sec = _extract_section(incident_text, "Root cause")
        remediation_sec = _extract_section(incident_text, "Remediation")
        evidence_sec = _extract_section(incident_text, "Evidence")
        if all([context_sec, root_cause_sec, remediation_sec, evidence_sec]):
            scores["incident_sections_present"] = 1.0

        # Context quality: mention partner outage and cart-sync/cart sync
        if context_sec:
            ctx_lower = context_sec.lower()
            if ("partner" in ctx_lower) and ("outage" in ctx_lower) and ("cart-sync" in ctx_lower or "cart sync" in ctx_lower):
                scores["incident_context_quality"] = 1.0

        # Root cause quality: must include initial keys+values and cite file+function
        if root_cause_sec:
            rc = root_cause_sec
            has_keys_vals = (
                "timeouts.dependency_timeout_ms" in rc
                and str(INITIAL_TIMEOUT_MS) in rc
                and "timeouts.max_retries" in rc
                and str(INITIAL_MAX_RETRIES) in rc
                and "reliability.fail_fast_threshold_ms" in rc
                and str(INITIAL_THRESHOLD_MS) in rc
            )
            cites_code = ("app/service.py" in rc) and ("sync_with_partner" in rc)
            if has_keys_vals and cites_code:
                scores["incident_root_cause_quality"] = 1.0

        # Remediation: include exact new values from config (current tmo and retries)
        if remediation_sec and isinstance(tmo, int) and isinstance(retries, int):
            rem = remediation_sec
            has_new = (
                "timeouts.dependency_timeout_ms" in rem
                and str(tmo) in rem
                and "timeouts.max_retries" in rem
                and str(retries) in rem
            )
            if has_new:
                scores["incident_remediation_matches_config"] = 1.0

        # Evidence: include exact measured lines from both runs
        if evidence_sec:
            ev = evidence_sec
            before_ok_ev = before_measured_line is not None and before_measured_line in ev
            after_ok_ev = after_measured_line is not None and after_measured_line in ev
            if before_ok_ev and after_ok_ev:
                scores["incident_evidence_includes_measured_lines"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()