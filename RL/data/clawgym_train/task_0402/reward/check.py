import json
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List
import math
import re


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_2d_points(path: Path) -> Optional[List[Tuple[float, float]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    if not lines:
        return None
    # Skip header
    data_lines = lines[1:]
    pts: List[Tuple[float, float]] = []
    try:
        for ln in data_lines:
            if not ln.strip():
                continue
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) < 2:
                return None
            x = float(parts[0])
            y = float(parts[1])
            pts.append((x, y))
    except Exception:
        return None
    if not pts:
        return None
    return pts


def _covariance_2d(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float]]:
    # Return (a, b, d) for symmetric matrix [[a, b], [b, d]]
    n = len(points)
    if n < 2:
        return None
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    mx = sx / n
    my = sy / n
    sxx = 0.0
    syy = 0.0
    sxy = 0.0
    for (x, y) in points:
        dx = x - mx
        dy = y - my
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy
    denom = (n - 1)
    if denom <= 0:
        return None
    a = sxx / denom
    d = syy / denom
    b = sxy / denom
    return (a, b, d)


def _top_eigenvector_2x2(a: float, b: float, d: float) -> Optional[Tuple[float, float]]:
    # For symmetric matrix [[a, b], [b, d]]
    # Compute eigenvalues
    trace = a + d
    det = a * d - b * b
    disc = (trace * trace) / 4.0 - det
    if disc < 0:
        # numerical issues shouldn't happen for exact arithmetic, clamp
        disc = 0.0
    sqrt_disc = math.sqrt(disc)
    lam1 = trace / 2.0 + sqrt_disc  # largest eigenvalue
    # Compute eigenvector for lam1
    # Solve (A - lam1 I)v = 0; we can pick v = [b, lam1 - a] if not both zero
    vx = b
    vy = lam1 - a
    if abs(vx) < 1e-12 and abs(vy) < 1e-12:
        # Try alternative form v = [lam1 - d, b]
        vx = lam1 - d
        vy = b
    if abs(vx) < 1e-24 and abs(vy) < 1e-24:
        # Degenerate: pick axis of larger variance
        if a >= d:
            vx, vy = 1.0, 0.0
        else:
            vx, vy = 0.0, 1.0
    norm = math.sqrt(vx * vx + vy * vy)
    if norm == 0.0:
        return None
    return (vx / norm, vy / norm)


def _abs_cosine_similarity(w: Tuple[float, float], v: Tuple[float, float]) -> float:
    wx, wy = w
    vx, vy = v
    num = abs(wx * vx + wy * vy)
    nw = math.sqrt(wx * wx + wy * wy)
    nv = math.sqrt(vx * vx + vy * vy)
    if nw == 0.0 or nv == 0.0:
        return 0.0
    return num / (nw * nv)


def _run_pytest(workspace: Path, timeout_sec: float = 30.0) -> Tuple[Optional[int], str]:
    try:
        proc = subprocess.run(
            ["pytest", "-q"],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_sec,
        )
        return proc.returncode, proc.stdout or ""
    except FileNotFoundError:
        # pytest not installed
        return None, ""
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        return -1, out
    except Exception:
        return -1, ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pytest_tests_passed": 0.0,
        "pytest_output_saved": 0.0,
        "pytest_output_indicates_pass": 0.0,
        "validation_report_quality": 0.0,
        "learned_weights_file_valid": 0.0,
        "learned_weights_consistent": 0.0,
        "learned_weights_alignment_high": 0.0,
        "meeting_notes_contains_values_and_keywords": 0.0,
        "meeting_notes_action_items_count": 0.0,
    }

    # 1) Run pytest to verify tests pass (if environment allows)
    rc, pytest_out = _run_pytest(workspace)
    if rc == 0:
        scores["pytest_tests_passed"] = 1.0
    else:
        scores["pytest_tests_passed"] = 0.0

    # 2) Check saved pytest output
    test_output_path = workspace / "outputs" / "test_output.txt"
    text = _read_text(test_output_path)
    if text is not None and len(text.strip()) > 0:
        scores["pytest_output_saved"] = 1.0
        low = text.lower()
        # look for "passed" to indicate passing tests saved
        if "passed" in low:
            scores["pytest_output_indicates_pass"] = 1.0

    # 3) Validation report quality: existence + mentions tests and Oja and pass/fail language
    report_path = workspace / "outputs" / "validation_report.md"
    report = _read_text(report_path)
    if report is not None and len(report.strip()) > 0:
        low = report.lower()
        mentions_tests = ("test" in low) or ("pytest" in low)
        mentions_oja = ("oja" in low) or ("hebb" in low) or ("learning rule" in low)
        mentions_pass_fail = ("pass" in low) or ("fail" in low) or ("error" in low)
        if mentions_tests and mentions_oja and mentions_pass_fail:
            scores["validation_report_quality"] = 1.0

    # 4) Learned weights file checks
    lw_path = workspace / "outputs" / "learned_weights.json"
    lw = _load_json(lw_path)
    weights_tuple: Optional[Tuple[float, float]] = None
    if isinstance(lw, dict):
        weights = lw.get("weights", None)
        norm = lw.get("norm", None)
        corr_pc1 = lw.get("corr_pc1", None)
        epochs = lw.get("epochs", None)
        lr = lw.get("lr", None)
        valid = True
        # Validate fields existence and types
        if not (isinstance(weights, list) and len(weights) == 2):
            valid = False
        else:
            try:
                w0 = float(weights[0])
                w1 = float(weights[1])
                weights_tuple = (w0, w1)
            except Exception:
                valid = False
        if not (isinstance(norm, (int, float))):
            valid = False
        if not (isinstance(corr_pc1, (int, float))):
            valid = False
        if not isinstance(epochs, int):
            valid = False
        if not isinstance(lr, (int, float)):
            valid = False
        # If fields valid, perform norm check (unit norm within tolerance)
        if valid and weights_tuple is not None:
            nw = math.sqrt(weights_tuple[0] ** 2 + weights_tuple[1] ** 2)
            # Check reported norm matches computed norm closely
            if norm is None or abs(float(norm) - nw) > 1e-4:
                valid = False
            # Basic unit norm
            if abs(nw - 1.0) > 1e-3:
                valid = False
        if valid:
            scores["learned_weights_file_valid"] = 1.0

    # 5) Learned weights consistency with dataset and high alignment
    data_path = workspace / "input" / "sensory_signals.csv"
    points = _load_csv_2d_points(data_path)
    if points is not None and weights_tuple is not None:
        cov = _covariance_2d(points)
        if cov is not None:
            a, b, d = cov
            vec = _top_eigenvector_2x2(a, b, d)
            if vec is not None:
                cos = _abs_cosine_similarity(weights_tuple, vec)
                # recorded corr_pc1 must match recomputed within tolerance
                recorded = None
                if isinstance(lw, dict) and isinstance(lw.get("corr_pc1", None), (int, float)):
                    recorded = float(lw["corr_pc1"])
                if recorded is not None and abs(recorded - cos) <= 1e-3:
                    scores["learned_weights_consistent"] = 1.0
                # High alignment threshold as in tests
                if cos > 0.999:
                    scores["learned_weights_alignment_high"] = 1.0

    # 6) Meeting notes checks
    notes_path = workspace / "outputs" / "meeting_notes.md"
    notes = _read_text(notes_path)
    if notes is not None and len(notes.strip()) > 0 and weights_tuple is not None and isinstance(lw, dict):
        nlow = notes.lower()
        # Numeric formatting presence
        w0s = f"{weights_tuple[0]:.4f}"
        w1s = f"{weights_tuple[1]:.4f}"
        corr = lw.get("corr_pc1", None)
        corr_s_ok = False
        if isinstance(corr, (int, float)):
            corr_s = f"{float(corr):.4f}"
            corr_s_ok = corr_s in notes
        numbers_ok = (w0s in notes) and (w1s in notes) and corr_s_ok

        # Keywords for biological plausibility and limitations
        keywords_present = 0
        for kw in ["online", "local", "locality", "normalization", "normalized"]:
            if kw in nlow:
                keywords_present += 1
        has_spiking_or_stdp = ("spiking" in nlow) or ("stdp" in nlow)
        if numbers_ok and (keywords_present >= 1) and has_spiking_or_stdp:
            scores["meeting_notes_contains_values_and_keywords"] = 1.0

        # Action items count: 3–5 bullet points
        bullet_lines = [ln for ln in notes.splitlines() if ln.strip().startswith(("- ", "* "))]
        if 3 <= len(bullet_lines) <= 5:
            scores["meeting_notes_action_items_count"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()