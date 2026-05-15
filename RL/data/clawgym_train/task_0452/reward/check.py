import csv
import json
import hashlib
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_bool(s: Any) -> Optional[bool]:
    if isinstance(s, bool):
        return s
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in {"true", "t", "1", "yes", "y"}:
        return True
    if s in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _to_int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _to_float(s: Any) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _run_mock_checker(python_exe: str, script: Path, item_id: str, claim: str, notes: str) -> Tuple[Optional[float], Optional[str], int]:
    try:
        cmd = [python_exe, str(script), "--id", str(item_id), "--claim", str(claim), "--notes", str(notes)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        rc = proc.returncode
        if rc == 0:
            # Expect: CONSISTENCY <id> <score>
            m = re.search(r"CONSISTENCY\s+(\S+)\s+([0-9]*\.?[0-9]+)", (proc.stdout or "").strip())
            if m:
                try:
                    score = float(m.group(2))
                    return score, None, rc
                except Exception:
                    return None, "parse_error", rc
            else:
                return None, "parse_error", rc
        else:
            err = (proc.stderr or "").strip()
            if not err and proc.stdout:
                err = proc.stdout.strip()
            return None, err, rc
    except Exception as e:
        return None, str(e), -1


def _normalize_formula(s: str) -> str:
    return re.sub(r"\s+", "", s.lower()) if s is not None else ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "cli_script_present_and_uses_subprocess": 0.0,
        "ranked_csv_present_and_columns": 0.0,
        "ranked_csv_ranking_and_rows_match": 0.0,
        "ranked_csv_scores_and_fields_correct": 0.0,
        "top5_txt_correct": 0.0,
        "report_json_counts_and_hash_correct": 0.0,
        "report_json_formula_and_filters_documented": 0.0,
        "architecture_md_content_quality": 0.0,
    }

    input_csv = workspace / "input" / "artifacts.csv"
    mock_checker = workspace / "input" / "scripts" / "mock_claim_check.py"

    # Gate: read dataset
    dataset = _safe_read_csv(input_csv)
    if not dataset:
        # Evaluate CLI script presence and behavior (subprocess invocation)
        cli_py = workspace / "output" / "bin" / "rank_artifacts.py"
        cli_sh = workspace / "output" / "bin" / "rank_artifacts.sh"
        cli_score = 0.0
        if cli_py.exists():
            text = _safe_read_text(cli_py) or ""
            if "subprocess" in text and "mock_claim_check.py" in text and "--id" in text and "--claim" in text and "--notes" in text:
                cli_score = 1.0
        elif cli_sh.exists():
            text = _safe_read_text(cli_sh) or ""
            if ("python" in text or "python3" in text) and "mock_claim_check.py" in text and "--id" in text and "--claim" in text and "--notes" in text:
                cli_score = 1.0
        scores["cli_script_present_and_uses_subprocess"] = cli_score

        # Architecture check even if others missing
        architecture = workspace / "output" / "architecture.md"
        arch_text = _safe_read_text(architecture) or ""
        if arch_text:
            norm = arch_text.lower()
            conditions = [
                ("stdout" in norm),
                ("stderr" in norm),
                ("missing documents" in norm),
                ("forgery" in norm),
                ("filter" in norm),
                ("rank" in norm),
                ("command" in norm or "cli" in norm),
                ("python" in norm),
            ]
            if all(conditions) and len(arch_text) >= 200:
                scores["architecture_md_content_quality"] = 1.0
        return scores

    # Prepare expected values by evaluating the mock checker
    python_exe = sys.executable or "python"
    evaluated: Dict[int, Dict[str, Any]] = {}
    error_counts = {"forgery": 0, "missing_documents": 0, "other": 0}
    for row in dataset:
        try:
            item_id = _to_int(row.get("id"))
            if item_id is None:
                continue
            name = row.get("name", "")
            prov = _to_int(row.get("provenance_score"))
            cond = _to_int(row.get("condition_score"))
            age_index = _to_int(row.get("age_index"))
            verified = _parse_bool(row.get("verified_authentic"))
            claim = row.get("authenticity_claim", "") or ""
            controversy = _to_int(row.get("controversy_mentions"))
            value_usd = _to_int(row.get("appraised_value_usd"))
            notes = row.get("notes", "") or ""
            if None in (prov, cond, age_index, verified, controversy, value_usd):
                # Skip malformed row
                continue
            # Run mock checker
            score, err_msg, rc = _run_mock_checker(python_exe, mock_checker, str(item_id), claim, notes)
            cat = None
            if score is None:
                msg_l = (err_msg or "").lower()
                if "forgery" in msg_l:
                    cat = "forgery"
                elif "missing documents" in msg_l:
                    cat = "missing_documents"
                else:
                    cat = "other"
                error_counts[cat] = error_counts.get(cat, 0) + 1
            # Compute derived values
            value_factor = min(100, math.floor(value_usd / 10000))
            base = 0.5 * prov + 0.2 * cond + 0.2 * (age_index * 10) + 0.1 * value_factor
            final_score = None
            if score is not None:
                final_score = max(0.0, base * score - 5 * controversy)
            evaluated[item_id] = {
                "id": item_id,
                "name": name,
                "provenance_score": prov,
                "condition_score": cond,
                "age_index": age_index,
                "verified_authentic": verified,
                "authenticity_claim": claim,
                "controversy_mentions": controversy,
                "appraised_value_usd": value_usd,
                "notes": notes,
                "claim_consistency": score,
                "error_category": cat,
                "base": base,
                "final_score": final_score,
            }
        except Exception:
            continue

    # Determine expected filtered and ranked items
    expected_items: List[Dict[str, Any]] = []
    for item in evaluated.values():
        cc = item["claim_consistency"]
        if cc is None:
            continue  # not evaluated -> excluded
        # filtering
        if (item["verified_authentic"] is False) and (cc < 0.5):
            continue
        fs = item["final_score"]
        if fs is None:
            continue
        if fs < 30:
            continue
        expected_items.append(item)
    # sort by final_score desc, then id to stabilize
    expected_items.sort(key=lambda x: (-x["final_score"], x["id"]))
    # assign ranks
    for idx, item in enumerate(expected_items, start=1):
        item["rank"] = idx

    expected_ids_order = [item["id"] for item in expected_items]

    # Check CLI script presence and use of subprocess + checker invocation
    cli_py = workspace / "output" / "bin" / "rank_artifacts.py"
    cli_sh = workspace / "output" / "bin" / "rank_artifacts.sh"
    cli_score = 0.0
    if cli_py.exists():
        text = _safe_read_text(cli_py) or ""
        if "subprocess" in text and "mock_claim_check.py" in text and "--id" in text and "--claim" in text and "--notes" in text:
            cli_score = 1.0
    elif cli_sh.exists():
        text = _safe_read_text(cli_sh) or ""
        if ("python" in text or "python3" in text) and "mock_claim_check.py" in text and "--id" in text and "--claim" in text and "--notes" in text:
            cli_score = 1.0
    scores["cli_script_present_and_uses_subprocess"] = cli_score

    # ranked.csv checks
    ranked_csv_path = workspace / "output" / "ranked.csv"
    ranked_rows = _safe_read_csv(ranked_csv_path)
    if ranked_rows is not None:
        # Columns check
        required_cols = ["rank", "id", "name", "final_score", "provenance_score", "claim_consistency", "verified_authentic", "controversy_mentions"]
        got_cols = []
        try:
            with ranked_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                got_cols = list(reader.fieldnames or [])
        except Exception:
            got_cols = []
        if got_cols == required_cols:
            scores["ranked_csv_present_and_columns"] = 1.0
        else:
            scores["ranked_csv_present_and_columns"] = 0.0

        # Ranking and rows match check
        rows_ids = []
        order_ok = True
        ranks_ok = True
        content_ok_count = 0
        total_expected = len(expected_items)
        if len(ranked_rows) == total_expected:
            for i, r in enumerate(ranked_rows):
                rid = _to_int(r.get("id"))
                rrank = _to_int(r.get("rank"))
                rows_ids.append(rid if rid is not None else -1)
                if rrank != (i + 1):
                    ranks_ok = False
            if rows_ids == expected_ids_order:
                order_ok = True
            else:
                order_ok = False
            if order_ok and ranks_ok:
                scores["ranked_csv_ranking_and_rows_match"] = 1.0
            else:
                scores["ranked_csv_ranking_and_rows_match"] = 0.0

            # Detailed values check
            expected_by_id = {it["id"]: it for it in expected_items}
            for r in ranked_rows:
                rid = _to_int(r.get("id"))
                if rid is None or rid not in expected_by_id:
                    continue
                exp = expected_by_id[rid]
                name_ok = (r.get("name", "") == exp["name"])
                prov_ok = (_to_int(r.get("provenance_score")) == exp["provenance_score"])
                contr_ok = (_to_int(r.get("controversy_mentions")) == exp["controversy_mentions"])
                r_verified = _parse_bool(r.get("verified_authentic"))
                ver_ok = (r_verified == exp["verified_authentic"])
                r_cc = _to_float(r.get("claim_consistency"))
                cc_ok = (r_cc is not None and exp["claim_consistency"] is not None and abs(r_cc - exp["claim_consistency"]) <= 1e-2)
                r_fs = _to_float(r.get("final_score"))
                fs_ok = (r_fs is not None and exp["final_score"] is not None and abs(r_fs - exp["final_score"]) <= 1e-2)
                if all([name_ok, prov_ok, contr_ok, ver_ok, cc_ok, fs_ok]):
                    content_ok_count += 1
            if total_expected > 0 and content_ok_count == total_expected:
                scores["ranked_csv_scores_and_fields_correct"] = 1.0
            else:
                scores["ranked_csv_scores_and_fields_correct"] = 0.0
        else:
            scores["ranked_csv_ranking_and_rows_match"] = 0.0
            scores["ranked_csv_scores_and_fields_correct"] = 0.0
    else:
        scores["ranked_csv_present_and_columns"] = 0.0
        scores["ranked_csv_ranking_and_rows_match"] = 0.0
        scores["ranked_csv_scores_and_fields_correct"] = 0.0

    # top5.txt checks
    top5_path = workspace / "output" / "top5.txt"
    try:
        top5_text = top5_path.read_text(encoding="utf-8")
        lines = [ln for ln in top5_text.splitlines() if ln.strip() != ""]
        expected_top_n = min(5, len(expected_items))
        if len(lines) == expected_top_n and expected_top_n > 0:
            ok = True
            ranked_lookup: Dict[int, Dict[str, Any]] = {}
            if ranked_rows:
                for r in ranked_rows:
                    rid = _to_int(r.get("id"))
                    if rid is not None:
                        ranked_lookup[rid] = r
            for idx, line in enumerate(lines, start=1):
                m = re.match(r"^\s*(\d+)\.\s+(\d+)\s*-\s*(.*?)\s*-\s*([0-9]+(?:\.[0-9]+)?)\s*$", line)
                if not m:
                    ok = False
                    break
                rank_num = int(m.group(1))
                lid = int(m.group(2))
                lname = m.group(3)
                lscore = float(m.group(4))
                if rank_num != idx:
                    ok = False
                    break
                exp_item = expected_items[idx - 1]
                if lid != exp_item["id"]:
                    ok = False
                    break
                if lname != exp_item["name"]:
                    ok = False
                    break
                if abs(lscore - exp_item["final_score"]) > 1e-2:
                    ok = False
                    break
                if lid in ranked_lookup:
                    rr = ranked_lookup[lid]
                    rr_name = rr.get("name", "")
                    rr_fs = _to_float(rr.get("final_score"))
                    if rr_name != lname or (rr_fs is None or abs(rr_fs - lscore) > 1e-6):
                        ok = False
                        break
            scores["top5_txt_correct"] = 1.0 if ok else 0.0
        else:
            scores["top5_txt_correct"] = 0.0
    except Exception:
        scores["top5_txt_correct"] = 0.0

    # report.json checks
    report_path = workspace / "output" / "report.json"
    report = _safe_load_json(report_path)
    if report is not None:
        dataset_total = len(dataset)
        evaluated_rows = sum(1 for v in evaluated.values() if v.get("claim_consistency") is not None)
        errors_total = sum(error_counts.values())
        ok_counts = True
        if report.get("dataset_rows_total") != dataset_total:
            ok_counts = False
        if report.get("evaluated_rows") != evaluated_rows:
            ok_counts = False
        if report.get("errors_captured_count") != errors_total:
            ok_counts = False
        es = report.get("error_summary")
        if not isinstance(es, dict):
            ok_counts = False
        else:
            f_cnt = es.get("forgery", 0)
            m_cnt = es.get("missing_documents", 0)
            o_cnt = es.get("other", 0)
            if f_cnt != error_counts["forgery"] or m_cnt != error_counts["missing_documents"] or o_cnt != error_counts["other"]:
                ok_counts = False
        expected_sha = _sha256_file(input_csv)
        if (report.get("input_csv_sha256") or "").lower() != (expected_sha or "").lower():
            ok_counts = False
        scores["report_json_counts_and_hash_correct"] = 1.0 if ok_counts else 0.0

        formula_str = str(report.get("scoring_formula") or "")
        filt_str = str(report.get("filter_criteria") or "")
        nf = _normalize_formula(formula_str)
        f_ok = all([
            "value_factor=min(100,floor(appraised_value_usd/10000))" in nf,
            "base=0.5*provenance_score+0.2*condition_score+0.2*(age_index*10)+0.1*value_factor" in nf,
            "final_score=max(0,base*claim_consistency-5*controversy_mentions)" in nf,
        ])
        fs = filt_str.lower()
        filt_ok = ("verified_authentic" in fs and "claim_consistency" in fs and ("< 0.5" in fs or "<0.5" in fs)) and ("final_score" in fs and ("< 30" in fs or "<30" in fs))
        scores["report_json_formula_and_filters_documented"] = 1.0 if (f_ok and filt_ok) else 0.0
    else:
        scores["report_json_counts_and_hash_correct"] = 0.0
        scores["report_json_formula_and_filters_documented"] = 0.0

    # architecture.md checks
    architecture = workspace / "output" / "architecture.md"
    arch_text = _safe_read_text(architecture) or ""
    if arch_text:
        norm = arch_text.lower()
        conditions = [
            ("stdout" in norm),
            ("stderr" in norm),
            ("missing documents" in norm),
            ("forgery" in norm),
            ("filter" in norm),
            ("rank" in norm),
            ("command" in norm or "cli" in norm),
            ("python" in norm),
        ]
        if all(conditions) and len(arch_text) >= 200:
            scores["architecture_md_content_quality"] = 1.0
        else:
            scores["architecture_md_content_quality"] = 0.0
    else:
        scores["architecture_md_content_quality"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()