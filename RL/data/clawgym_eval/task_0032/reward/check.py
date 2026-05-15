import json
import hashlib
import sys
import subprocess
from pathlib import Path
from typing import Tuple, Optional, Dict, List, Any


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = path.read_text(encoding="utf-8")
        return data, None
    except Exception as e:
        return None, str(e)


def _read_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def _compute_sha256_hex(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest(), None
    except Exception as e:
        return None, str(e)


def _run_subprocess(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return -1, "", str(e)


def _relative_posix(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except Exception:
        rel = path
    return rel.as_posix()


def _collect_expected_inventory(workspace: Path) -> Dict[str, Tuple[str, int]]:
    expected: Dict[str, Tuple[str, int]] = {}
    # Collect .py files under crypto_lib
    crypto_dir = workspace / "crypto_lib"
    if crypto_dir.exists():
        for p in sorted(crypto_dir.rglob("*.py")):
            sha, _ = _compute_sha256_hex(p)
            if sha is None:
                continue
            size = p.stat().st_size
            expected[_relative_posix(p, workspace)] = (sha, int(size))
    # Add config/security.json
    cfg = workspace / "config" / "security.json"
    if cfg.exists():
        sha, _ = _compute_sha256_hex(cfg)
        if sha is not None:
            expected[_relative_posix(cfg, workspace)] = (sha, int(cfg.stat().st_size))
    return expected


def _parse_inventory_file(inv_path: Path, workspace: Path) -> Tuple[Optional[Dict[str, Tuple[str, int]]], Optional[str]]:
    text, err = _read_text_safe(inv_path)
    if text is None:
        return None, err or "failed to read inventory"
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    parsed: Dict[str, Tuple[str, int]] = {}
    for i, ln in enumerate(lines, 1):
        parts = ln.split("\t")
        if len(parts) != 3:
            return None, f"line {i} does not have 3 tab-separated fields"
        rel_path, sha, size_str = parts
        # Basic validations
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha.lower()):
            return None, f"line {i} sha256 invalid"
        try:
            size = int(size_str)
            if size < 0:
                return None, f"line {i} size negative"
        except Exception:
            return None, f"line {i} size not integer"
        # Ensure file exists
        file_path = workspace / rel_path
        if not file_path.exists():
            return None, f"line {i} references non-existent file {rel_path}"
        parsed[rel_path] = (sha.lower(), size)
    return parsed, None


def _import_crypto_and_list(workspace: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        import importlib

        mod = importlib.import_module("crypto_lib")
        mod = importlib.reload(mod)
        if not hasattr(mod, "list_algorithms"):
            return None, "crypto_lib has no list_algorithms"
        algos = mod.list_algorithms()
        if not isinstance(algos, list) or not all(isinstance(a, str) for a in algos):
            return None, "list_algorithms did not return a list of strings"
        return algos, None
    except Exception as e:
        return None, str(e)


def _scan_disallowed_tokens(workspace: Path, tokens: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    crypto_dir = workspace / "crypto_lib"
    if not crypto_dir.exists():
        return results
    for file in sorted(crypto_dir.rglob("*")):
        if not file.is_file():
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines, 1):
            for token in tokens:
                start = 0
                # If token is empty, skip to avoid infinite loop
                if token == "":
                    continue
                while True:
                    pos = line.find(token, start)
                    if pos == -1:
                        break
                    results.append(
                        {
                            "file": _relative_posix(file, workspace),
                            "line": idx,
                            "match": token,
                        }
                    )
                    start = pos + len(token)
    return results


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "audit_script_runs": 0.0,
        "dir_inventory_correct": 0.0,
        "test_results_verbatim": 0.0,
        "compliance_report_structure": 0.0,
        "policy_fields_match_config": 0.0,
        "algorithms_declared_runtime_match": 0.0,
        "disallowed_scan_correct": 0.0,
        "compliance_logic_correct": 0.0,
    }

    # 1) Run audit script if present
    script_path = workspace / "scripts" / "audit_crypto.py"
    if script_path.exists():
        rc, out, err = _run_subprocess([sys.executable, str(script_path)], cwd=workspace)
        if rc == 0:
            scores["audit_script_runs"] = 1.0
        else:
            scores["audit_script_runs"] = 0.0
    else:
        scores["audit_script_runs"] = 0.0

    # Expected inventory
    expected_inventory = _collect_expected_inventory(workspace)

    # 2) Validate inventory file
    inv_path = workspace / "output" / "dir_inventory.txt"
    parsed_inv, inv_err = _parse_inventory_file(inv_path, workspace) if inv_path.exists() else (None, "missing")
    if parsed_inv is not None:
        # Check exact set equality
        expected_keys = set(expected_inventory.keys())
        parsed_keys = set(parsed_inv.keys())
        if parsed_keys == expected_keys:
            # Check sha and size match
            match_all = True
            for k in expected_keys:
                exp_sha, exp_size = expected_inventory[k]
                got_sha, got_size = parsed_inv[k]
                if exp_sha.lower() != got_sha.lower() or int(exp_size) != int(got_size):
                    match_all = False
                    break
            if match_all:
                scores["dir_inventory_correct"] = 1.0

    # 3) Validate test results are verbatim to validation command stdout
    test_out_path = workspace / "output" / "test_results.json"
    expected_stdout = None
    if (workspace / "tests" / "run_validation.py").exists():
        rc2, stdout2, stderr2 = _run_subprocess([sys.executable, "tests/run_validation.py"], cwd=workspace)
        if rc2 == 0:
            expected_stdout = stdout2
    actual_text, _ = _read_text_safe(test_out_path) if test_out_path.exists() else (None, "missing")
    if expected_stdout is not None and actual_text is not None:
        # Exact verbatim comparison (no normalization)
        if expected_stdout == actual_text:
            scores["test_results_verbatim"] = 1.0

    # 4) Compliance report structure and content
    report_path = workspace / "output" / "compliance_report.json"
    report_obj, _ = _read_json_safe(report_path) if report_path.exists() else (None, "missing")
    cfg_path = workspace / "config" / "security.json"
    cfg_obj, _ = _read_json_safe(cfg_path) if cfg_path.exists() else (None, "missing")
    # Structure check
    if isinstance(report_obj, dict):
        required_fields = [
            "fips_mode",
            "allowed_algorithms",
            "denylist",
            "algorithms_declared",
            "disallowed_references",
            "compliance",
            "reasons",
        ]
        has_all = all(k in report_obj for k in required_fields)
        types_ok = (
            isinstance(report_obj.get("fips_mode"), bool)
            and isinstance(report_obj.get("allowed_algorithms"), list)
            and all(isinstance(x, str) for x in report_obj.get("allowed_algorithms", []))
            and isinstance(report_obj.get("denylist"), list)
            and all(isinstance(x, str) for x in report_obj.get("denylist", []))
            and isinstance(report_obj.get("algorithms_declared"), list)
            and all(isinstance(x, str) for x in report_obj.get("algorithms_declared", []))
            and isinstance(report_obj.get("disallowed_references"), list)
            and all(
                isinstance(x, dict)
                and "file" in x
                and "line" in x
                and "match" in x
                and isinstance(x.get("file"), str)
                and isinstance(x.get("line"), int)
                and isinstance(x.get("match"), str)
                for x in report_obj.get("disallowed_references", [])
            )
            and report_obj.get("compliance") in {"pass", "fail"}
            and isinstance(report_obj.get("reasons"), list)
            and all(isinstance(x, str) for x in report_obj.get("reasons", []))
        )
        reasons_ok = True
        if report_obj.get("compliance") == "fail":
            reasons_ok = len(report_obj.get("reasons", [])) >= 1
        if has_all and types_ok and reasons_ok:
            scores["compliance_report_structure"] = 1.0

    # Policy fields should match config
    if isinstance(report_obj, dict) and isinstance(cfg_obj, dict):
        cfg_fips = cfg_obj.get("fips_mode")
        cfg_allowed = cfg_obj.get("allowed_algorithms", [])
        cfg_deny = cfg_obj.get("denylist", [])
        if (
            report_obj.get("fips_mode") == cfg_fips
            and report_obj.get("allowed_algorithms") == cfg_allowed
            and report_obj.get("denylist") == cfg_deny
        ):
            scores["policy_fields_match_config"] = 1.0

    # Algorithms declared should match runtime import
    runtime_algos, _ = _import_crypto_and_list(workspace)
    if isinstance(report_obj, dict) and runtime_algos is not None:
        if report_obj.get("algorithms_declared") == runtime_algos:
            scores["algorithms_declared_runtime_match"] = 1.0

    # Disallowed scan expected correctness
    if isinstance(report_obj, dict) and isinstance(cfg_obj, dict):
        deny_tokens = list(cfg_obj.get("denylist", []))
        allowed = set(cfg_obj.get("allowed_algorithms", []))
        runtime_algos2, _ = _import_crypto_and_list(workspace)
        non_allowed_names = set()
        if runtime_algos2 is not None:
            non_allowed_names = set(a for a in runtime_algos2 if a not in allowed)
        tokens_to_search = sorted(set(deny_tokens) | non_allowed_names)
        expected_refs = _scan_disallowed_tokens(workspace, tokens_to_search)

        def _to_counts(refs: List[Dict[str, Any]]) -> Dict[Tuple[str, int, str], int]:
            d: Dict[Tuple[str, int, str], int] = {}
            for r in refs:
                key = (r.get("file"), int(r.get("line")), r.get("match"))
                d[key] = d.get(key, 0) + 1
            return d

        reported_refs = report_obj.get("disallowed_references", []) if isinstance(report_obj, dict) else []
        # Validate that all reported matches are valid (file under crypto_lib, line contains the match)
        valid_reported = True
        for r in reported_refs:
            if not isinstance(r, dict):
                valid_reported = False
                break
            f = r.get("file")
            l = r.get("line")
            m = r.get("match")
            if not (isinstance(f, str) and isinstance(l, int) and isinstance(m, str)):
                valid_reported = False
                break
            fpath = workspace / f
            if not fpath.exists():
                valid_reported = False
                break
            rel = _relative_posix(fpath, workspace)
            if not rel.startswith("crypto_lib/"):
                valid_reported = False
                break
            content, err = _read_text_safe(fpath)
            if content is None:
                valid_reported = False
                break
            lines = content.splitlines()
            if l <= 0 or l > len(lines):
                valid_reported = False
                break
            if lines[l - 1].find(m) == -1:
                valid_reported = False
                break
            if m not in tokens_to_search:
                valid_reported = False
                break
        if valid_reported:
            exp_counts = _to_counts(expected_refs)
            rep_counts = _to_counts(reported_refs)
            if exp_counts == rep_counts:
                scores["disallowed_scan_correct"] = 1.0

    # Compliance logic correctness
    if isinstance(report_obj, dict) and isinstance(cfg_obj, dict):
        fips_mode = bool(cfg_obj.get("fips_mode", False))
        allowed_algos = list(cfg_obj.get("allowed_algorithms", []))
        algos_declared = report_obj.get("algorithms_declared", [])
        disallowed_refs = report_obj.get("disallowed_references", [])
        if fips_mode:
            subset_ok = set(algos_declared).issubset(set(allowed_algos))
            disallowed_empty = len(disallowed_refs) == 0
            expected_compliance = "pass" if (subset_ok and disallowed_empty) else "fail"
        else:
            expected_compliance = "pass" if len(disallowed_refs) == 0 else "fail"
        if report_obj.get("compliance") == expected_compliance:
            scores["compliance_logic_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()