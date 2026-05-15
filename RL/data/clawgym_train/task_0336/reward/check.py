import ast
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import importlib.util


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _import_module_from_path(name: str, file_path: Path):
    try:
        if not file_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(name, str(file_path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod
    except Exception:
        return None


def _compute_function_metrics(py_path: Path, rel_path_str: str) -> Optional[List[Dict[str, Any]]]:
    """
    Compute per-function metrics for a Python source file:
      - loc: end_lineno - lineno + 1 (span of function definition)
      - max_nesting: approximate max depth of nested If/For/While/Try in the function body
      - params_count: the number of parameters
    Only top-level functions are included to keep interpretation strict and deterministic.
    """
    try:
        source = _safe_read_text(py_path)
        if source is None:
            return None
        tree = ast.parse(source)
    except Exception:
        return None

    control_nodes = (ast.If, ast.For, ast.While, ast.Try)

    def max_depth_in_body(nodes: List[ast.stmt], current: int = 0) -> int:
        max_d = current
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Do not traverse into nested functions/classes for max_nesting of the outer function
                continue
            if isinstance(node, control_nodes):
                children_lists: List[List[ast.stmt]] = []
                if isinstance(node, ast.If):
                    children_lists.append(node.body)
                    children_lists.append(node.orelse)
                elif isinstance(node, (ast.For, ast.While)):
                    children_lists.append(node.body)
                    children_lists.append(node.orelse)
                elif isinstance(node, ast.Try):
                    children_lists.append(node.body)
                    children_lists.append(node.orelse)
                    children_lists.append(node.finalbody)
                    for h in node.handlers:
                        children_lists.append(h.body)
                depth_here = current + 1
                max_d = max(max_d, depth_here)
                for child_body in children_lists:
                    max_d = max(max_d, max_depth_in_body(child_body, depth_here))
            else:
                if isinstance(node, ast.With):
                    max_d = max(max_d, max_depth_in_body(node.body, current))
        return max_d

    def params_count(func_node: ast.AST) -> int:
        if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return 0
        args = func_node.args
        count = 0
        posonly = getattr(args, "posonlyargs", [])
        count += len(posonly)
        count += len(args.args)
        count += len(args.kwonlyargs)
        if args.vararg is not None:
            count += 1
        if args.kwarg is not None:
            count += 1
        return count

    metrics: List[Dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                start = node.lineno
                end = getattr(node, "end_lineno", None)
                if end is None:
                    if node.body:
                        end = getattr(node.body[-1], "end_lineno", getattr(node.body[-1], "lineno", start))
                    else:
                        end = start
                loc = int(end - start + 1)
            except Exception:
                loc = 0

            try:
                md = max_depth_in_body(node.body, 0)
            except Exception:
                md = 0

            pc = params_count(node)

            metrics.append({
                "file": rel_path_str,
                "function": node.name,
                "loc": loc,
                "max_nesting": md,
                "params_count": pc,
            })

    return metrics


def _normalize_metrics_rows(rows: List[Dict[str, Any]]) -> List[Tuple[str, str, int, int, int]]:
    normalized = []
    for r in rows:
        file = r["file"]
        func = r["function"]
        try:
            loc = int(r["loc"])
            max_nesting = int(r["max_nesting"])
            params_count = int(r["params_count"])
        except Exception:
            loc = max_nesting = params_count = -999999
        normalized.append((file, func, loc, max_nesting, params_count))
    normalized.sort(key=lambda x: (x[0], x[1]))
    return normalized


def _compute_issue_ranking(metrics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranking_items: List[Dict[str, Any]] = []
    for m in metrics:
        loc = int(m["loc"])
        nesting = int(m["max_nesting"])
        params = int(m["params_count"])
        score = 0
        triggers = []
        if loc > 35:
            score += 2
            triggers.append("loc>35")
        elif 21 <= loc <= 35:
            score += 1
            triggers.append("21<=loc<=35")
        if nesting >= 4:
            score += 2
            triggers.append("nesting>=4")
        elif nesting == 3:
            score += 1
            triggers.append("nesting==3")
        if params >= 4:
            score += 1
            triggers.append("params>=4")
        if score <= 1:
            severity = "LOW"
        elif 2 <= score <= 3:
            severity = "MEDIUM"
        else:
            severity = "HIGH"
        if severity != "LOW":
            ranking_items.append({
                "file": m["file"],
                "function": m["function"],
                "severity": severity,
                "loc": loc,
                "max_nesting": nesting,
                "params_count": params,
                "triggers": triggers,
                "score": score,
            })
    def severity_rank(s: str) -> int:
        return {"HIGH": 0, "MEDIUM": 1}.get(s, 2)
    ranking_items.sort(key=lambda x: (severity_rank(x["severity"]), -x["loc"], x["file"], x["function"]))
    for i, item in enumerate(ranking_items, start=1):
        item["rank"] = i
    return ranking_items


def _section_text(md: str, section_name: str, following_sections: List[str]) -> str:
    low = md.lower()
    start_idx = low.find(section_name.lower())
    if start_idx == -1:
        return ""
    end_idx = len(md)
    for next_sec in following_sections:
        idx = low.find(next_sec.lower(), start_idx + 1)
        if idx != -1:
            end_idx = min(end_idx, idx)
    return md[start_idx:end_idx]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "refactored_file_exists": 0.0,
        "simulate_behavior_equivalence_runtime": 0.0,
        "equivalence_json_valid_and_matches": 0.0,
        "metrics_csv_correct_values": 0.0,
        "issue_ranking_csv_correct_values": 0.0,
        "metrics_cover_both_files": 0.0,
        "citations_csv_valid": 0.0,
        "meeting_notes_sections": 0.0,
        "meeting_notes_action_items": 0.0,
        "meeting_notes_top3_consistency": 0.0,
        "refactored_simulate_schema_preserved": 0.0,
    }

    src_file = workspace / "src" / "equilibrium.py"
    ref_file = workspace / "refactored" / "equilibrium_refactored.py"
    seeds_path = workspace / "input" / "seeds.json"
    equiv_json_path = workspace / "reports" / "equivalence_check.json"
    metrics_csv_path = workspace / "reports" / "metrics.csv"
    issues_csv_path = workspace / "reports" / "issue_ranking.csv"
    citations_csv_path = workspace / "reports" / "source_citations.csv"
    meeting_notes_path = workspace / "docs" / "meeting_notes.md"

    if ref_file.exists():
        scores["refactored_file_exists"] = 1.0
    else:
        scores["refactored_file_exists"] = 0.0

    seeds_obj = _safe_json_load(seeds_path)
    seeds: List[int] = []
    if isinstance(seeds_obj, list):
        try:
            seeds = [int(x) for x in seeds_obj]
        except Exception:
            seeds = []

    expected_keys = {"seed", "agents", "rounds", "final_coop_rate", "avg_propensity_end", "majority_rounds", "propensity_sd_end"}
    orig_mod = _import_module_from_path("orig_equilibrium", src_file)
    ref_mod = _import_module_from_path("ref_equilibrium", ref_file)

    runtime_results: List[Tuple[int, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]] = []
    schema_ok_count = 0
    if orig_mod is not None and ref_mod is not None and hasattr(orig_mod, "simulate") and hasattr(ref_mod, "simulate") and seeds:
        for sd in seeds:
            try:
                orig_res = orig_mod.simulate(seed=sd)  # type: ignore[attr-defined]
            except Exception:
                orig_res = None
            try:
                ref_res = ref_mod.simulate(seed=sd)  # type: ignore[attr-defined]
            except Exception:
                ref_res = None
            runtime_results.append((sd, orig_res, ref_res))
            if isinstance(ref_res, dict) and set(ref_res.keys()) == expected_keys:
                schema_ok_count += 1
    else:
        runtime_results = []

    if runtime_results:
        matches = 0
        total = 0
        for _, o, r in runtime_results:
            total += 1
            if isinstance(o, dict) and isinstance(r, dict) and o == r:
                matches += 1
        scores["simulate_behavior_equivalence_runtime"] = matches / float(total) if total > 0 else 0.0
        scores["refactored_simulate_schema_preserved"] = 1.0 if schema_ok_count == len(runtime_results) and len(runtime_results) > 0 else (schema_ok_count / float(len(runtime_results)) if len(runtime_results) > 0 else 0.0)
    else:
        scores["simulate_behavior_equivalence_runtime"] = 0.0
        scores["refactored_simulate_schema_preserved"] = 0.0

    eq_json = _safe_json_load(equiv_json_path)
    eq_valid = False
    if isinstance(eq_json, list) and seeds:
        record_by_seed: Dict[int, Dict[str, Any]] = {}
        all_items_ok = True
        try:
            for item in eq_json:
                if not isinstance(item, dict):
                    all_items_ok = False
                    break
                if "seed" not in item or "original" not in item or "refactored" not in item or "match" not in item:
                    all_items_ok = False
                    break
                record_by_seed[int(item["seed"])] = item
            if set(record_by_seed.keys()) != set(seeds):
                all_items_ok = False
            if all_items_ok:
                if runtime_results:
                    for sd, orig_res, ref_res in runtime_results:
                        rec = record_by_seed.get(sd)
                        if rec is None:
                            all_items_ok = False
                            break
                        if not (isinstance(rec.get("original"), dict) and isinstance(rec.get("refactored"), dict)):
                            all_items_ok = False
                            break
                        if orig_res is None or ref_res is None:
                            all_items_ok = False
                            break
                        if rec["original"] != orig_res or rec["refactored"] != ref_res:
                            all_items_ok = False
                            break
                        if rec["match"] is not True:
                            all_items_ok = False
                            break
                        if orig_res != ref_res:
                            all_items_ok = False
                            break
                else:
                    for sd in seeds:
                        rec = record_by_seed.get(sd)
                        if rec is None:
                            all_items_ok = False
                            break
                        if rec.get("match") is not True:
                            all_items_ok = False
                            break
                        if not (isinstance(rec.get("original"), dict) and isinstance(rec.get("refactored"), dict)):
                            all_items_ok = False
                            break
                        if rec["original"] != rec["refactored"]:
                            all_items_ok = False
                            break
            eq_valid = all_items_ok
        except Exception:
            eq_valid = False
    else:
        eq_valid = False
    scores["equivalence_json_valid_and_matches"] = 1.0 if eq_valid else 0.0

    computed_metrics: List[Dict[str, Any]] = []
    metrics_src = None
    metrics_ref = None
    if src_file.exists():
        metrics_src = _compute_function_metrics(src_file, "src/equilibrium.py")
    if ref_file.exists():
        metrics_ref = _compute_function_metrics(ref_file, "refactored/equilibrium_refactored.py")
    if isinstance(metrics_src, list):
        computed_metrics.extend(metrics_src)
    if isinstance(metrics_ref, list):
        computed_metrics.extend(metrics_ref)

    csv_rows = _parse_csv(metrics_csv_path)
    metrics_valid = False
    cover_both = 0.0
    if csv_rows is not None and computed_metrics:
        expected_fields = ["file", "function", "loc", "max_nesting", "params_count"]
        header_ok = True
        try:
            with metrics_csv_path.open("r", encoding="utf-8", newline="") as f:
                first_line = f.readline().strip()
                header_ok = (first_line.replace(" ", "") == ",".join(expected_fields).replace(" ", ""))
        except Exception:
            header_ok = False
        if header_ok:
            norm_expected = _normalize_metrics_rows(computed_metrics)
            norm_found = _normalize_metrics_rows(csv_rows)
            metrics_valid = (norm_expected == norm_found)
    else:
        metrics_valid = False

    scores["metrics_csv_correct_values"] = 1.0 if metrics_valid else 0.0

    if csv_rows is not None and len(csv_rows) > 0:
        files_present = {row.get("file", "") for row in csv_rows}
        has_src = "src/equilibrium.py" in files_present
        has_ref = "refactored/equilibrium_refactored.py" in files_present
        cover_both = 1.0 if (has_src and has_ref) else (0.5 if (has_src or has_ref) else 0.0)
    else:
        cover_both = 0.0
    scores["metrics_cover_both_files"] = cover_both

    issues_rows = _parse_csv(issues_csv_path)
    issues_valid = False
    if issues_rows is not None and computed_metrics:
        expected_issue_fields = ["rank", "file", "function", "severity", "loc", "max_nesting", "params_count", "rationale"]
        header_ok = True
        try:
            with issues_csv_path.open("r", encoding="utf-8", newline="") as f:
                first_line = f.readline().strip()
                header_ok = (first_line.replace(" ", "") == ",".join(expected_issue_fields).replace(" ", ""))
        except Exception:
            header_ok = False
        if header_ok:
            expected_ranking = _compute_issue_ranking(computed_metrics)
            expected_tuples = [(i["rank"], i["file"], i["function"], i["severity"], i["loc"], i["max_nesting"], i["params_count"]) for i in expected_ranking]
            try:
                found_sorted = sorted(issues_rows, key=lambda r: int(r.get("rank", "0")))
            except Exception:
                found_sorted = issues_rows
            found_tuples = []
            rationale_ok = True
            good_len = (len(found_sorted) == len(expected_tuples))
            if good_len:
                for idx, exp in enumerate(expected_tuples):
                    fr = found_sorted[idx]
                    try:
                        t = (
                            int(fr.get("rank", 0)),
                            fr.get("file", ""),
                            fr.get("function", ""),
                            fr.get("severity", ""),
                            int(fr.get("loc", -999999)),
                            int(fr.get("max_nesting", -999999)),
                            int(fr.get("params_count", -999999)),
                        )
                    except Exception:
                        t = (None, "", "", "", None, None, None)
                    found_tuples.append(t)
                    rationale = fr.get("rationale", "")
                    if not isinstance(rationale, str) or len(rationale.strip()) == 0:
                        rationale_ok = False
                    else:
                        loc_v = t[4]
                        nest_v = t[5]
                        params_v = t[6]
                        exp_triggers = []
                        if loc_v > 35 or (21 <= loc_v <= 35):
                            exp_triggers.append("loc")
                        if nest_v >= 4 or nest_v == 3:
                            exp_triggers.append("nest")
                        if params_v >= 4:
                            exp_triggers.append("param")
                        r_low = rationale.lower()
                        for token in exp_triggers:
                            if token not in r_low:
                                rationale_ok = False
                                break
                issues_valid = (found_tuples == expected_tuples) and rationale_ok
            else:
                issues_valid = False
        else:
            issues_valid = False
    else:
        issues_valid = False

    scores["issue_ranking_csv_correct_values"] = 1.0 if issues_valid else 0.0

    citations_rows = _parse_csv(citations_csv_path)
    citations_valid = False
    if citations_rows is not None:
        expected_citations_fields = ["source_title", "publisher_or_host", "author_or_org", "topic", "key_principle", "how_applied_in_refactor", "retrieval_date"]
        header_ok = True
        try:
            with citations_csv_path.open("r", encoding="utf-8", newline="") as f:
                first_line = f.readline().strip()
                header_ok = (first_line.replace(" ", "") == ",".join(expected_citations_fields).replace(" ", ""))
        except Exception:
            header_ok = False

        if header_ok and len(citations_rows) >= 2:
            def has_url(s: str) -> bool:
                return isinstance(s, str) and ("http://" in s.lower() or "https://" in s.lower() or "www." in s.lower() or "://" in s.lower())

            no_urls = True
            dates_ok = True
            pep8_present = False
            scholarly_present = False
            date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            for row in citations_rows:
                for val in row.values():
                    if isinstance(val, str) and has_url(val):
                        no_urls = False
                        break
                rd = row.get("retrieval_date", "")
                if not isinstance(rd, str) or not date_re.match(rd.strip()):
                    dates_ok = False
                title = (row.get("source_title", "") or "").lower()
                publisher = (row.get("publisher_or_host", "") or "").lower()
                author = (row.get("author_or_org", "") or "").lower()
                if ("pep 8" in title) and ("python" in publisher or "python" in author or "python software foundation" in publisher or "python software foundation" in author):
                    pep8_present = True
                recognized_terms = ["stanford encyclopedia", "acm", "ieee", "springer", "elsevier", "oxford", "cambridge", "mit press", "sage", "wiley", "pnas", "nature", "science"]
                if any(term in publisher for term in recognized_terms) or any(term in title for term in recognized_terms):
                    scholarly_present = True
            citations_valid = no_urls and dates_ok and pep8_present and scholarly_present
        else:
            citations_valid = False
    else:
        citations_valid = False
    scores["citations_csv_valid"] = 1.0 if citations_valid else 0.0

    md_text = _safe_read_text(meeting_notes_path) or ""
    required_sections = [
        "Objective",
        "Key findings from code review",
        "Top 3 ranked issues",
        "Decisions",
        "Action items",
        "Sources consulted",
        "Next steps",
    ]
    found_sections = 0
    low_md = md_text.lower()
    for sec in required_sections:
        if sec.lower() in low_md:
            found_sections += 1
    scores["meeting_notes_sections"] = found_sections / float(len(required_sections)) if required_sections else 0.0

    action_items_score = 0.0
    if md_text:
        lines = md_text.splitlines()
        count_items = 0
        for ln in lines:
            if re.match(r"^\s*\d+\.\s", ln):
                if ("owner" in ln.lower()) and ("due" in ln.lower()):
                    count_items += 1
        if count_items >= 2:
            action_items_score = 1.0
        elif count_items == 1:
            action_items_score = 0.5
        else:
            action_items_score = 0.0
    scores["meeting_notes_action_items"] = action_items_score

    top3_score = 0.0
    if md_text and computed_metrics:
        ranking = _compute_issue_ranking(computed_metrics)
        topN = ranking[:3]
        if topN:
            following = [s for s in required_sections if s.lower() != "top 3 ranked issues".lower()]
            section_txt = _section_text(md_text, "Top 3 ranked issues", following)
            hits = 0
            for item in topN:
                file_name = item["file"]
                func_name = item["function"]
                if (file_name in section_txt) and (func_name in section_txt):
                    hits += 1
            top3_score = hits / float(len(topN)) if topN else 0.0
    scores["meeting_notes_top3_consistency"] = top3_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()