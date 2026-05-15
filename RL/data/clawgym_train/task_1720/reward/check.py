import json
import csv
import sys
import re
import ast
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _parse_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            rows = []
            for r in rdr:
                rows.append(dict(r))
            return rows
    except Exception:
        try:
            with path.open("r") as f:
                rdr = csv.DictReader(f)
                rows = []
                for r in rdr:
                    rows.append(dict(r))
                return rows
        except Exception:
            return None


def _safe_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(s: Any) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def _simple_yaml_load(text: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    result: Dict[str, Any] = {}
    in_weights = False
    in_list = False
    result["weights"] = {}
    result["genres_filter"] = []
    lines = text.splitlines()
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        s = line.strip()
        if s.lower().startswith("weights:"):
            in_weights = True
            in_list = False
            continue
        if s.lower().startswith("top_n:"):
            in_weights = False
            in_list = False
            parts = s.split(":", 1)
            if len(parts) == 2:
                val = parts[1].strip()
                n = _safe_int(val)
                if n is None:
                    return None
                result["top_n"] = n
            continue
        if s.lower().startswith("genres_filter:"):
            in_weights = False
            in_list = True
            result["genres_filter"] = []
            continue
        if in_weights:
            parts = s.split(":", 1)
            if len(parts) != 2:
                return None
            k = parts[0].strip()
            v = parts[1].strip()
            fv = _safe_float(v)
            if fv is None:
                return None
            result["weights"][k] = fv
            continue
        if in_list:
            if s.startswith("- "):
                item = s[2:].strip()
                result["genres_filter"].append(item)
            else:
                in_list = False
            continue
    if "top_n" not in result:
        return None
    if not isinstance(result.get("weights"), dict):
        return None
    if "rating_weight" not in result["weights"] or "plays_weight" not in result["weights"]:
        return None
    if not isinstance(result.get("genres_filter"), list):
        return None
    return result


def _compute_expected_ranking(songs: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    genre_tokens = [str(t).lower() for t in cfg.get("genres_filter", [])]

    def genre_matches(g: str) -> bool:
        g_low = (g or "").lower()
        return any(tok in g_low for tok in genre_tokens)

    filtered = []
    for r in songs:
        genre = r.get("genre", "")
        if genre_matches(genre):
            rating = _safe_float(r.get("rating"))
            plays = _safe_int(r.get("plays"))
            if rating is None or plays is None:
                continue
            r2 = dict(r)
            r2["_rating"] = rating
            r2["_plays"] = plays
            filtered.append(r2)
    if not filtered:
        return []
    max_plays = max(x["_plays"] for x in filtered) if filtered else 1
    if max_plays <= 0:
        max_plays = 1
    rw = float(cfg["weights"]["rating_weight"])
    pw = float(cfg["weights"]["plays_weight"])
    expected = []
    for r in filtered:
        score = rw * (r["_rating"] / 5.0) + pw * (r["_plays"] / max_plays)
        out_row = {
            "id": str(r.get("id", "")),
            "title": str(r.get("title", "")),
            "artist": str(r.get("artist", "")),
            "genre": str(r.get("genre", "")),
            "rating": r["_rating"],
            "plays": r["_plays"],
            "score": score,
        }
        expected.append(out_row)
    expected.sort(key=lambda x: x["score"], reverse=True)
    top_n = int(cfg.get("top_n", len(expected)))
    return expected[: min(top_n, len(expected))]


def _count_loc_and_funcs(path: Path) -> Optional[Dict[str, int]]:
    text = _read_text(path)
    if text is None:
        return None
    loc = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        loc += 1
    try:
        tree = ast.parse(text)
        func_count = sum(isinstance(n, ast.FunctionDef) for n in ast.walk(tree))
    except Exception:
        func_count = 0
    return {"loc": loc, "funcs": func_count}


def _parse_output_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _parse_csv(path)
    if rows is None:
        return None
    parsed = []
    for r in rows:
        new_r = dict(r)
        for key in ["rating", "plays", "score"]:
            if key in new_r:
                val = new_r[key]
                if key == "plays":
                    iv = _safe_int(val)
                    if iv is None:
                        return None
                    new_r[key] = iv
                else:
                    fv = _safe_float(val)
                    if fv is None:
                        return None
                    new_r[key] = fv
        parsed.append(new_r)
    return parsed


def _float_close(a: float, b: float, tol: float = 5e-4) -> bool:
    return abs(a - b) <= tol


def _extract_email_fields(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    to_line = None
    subject_line = None
    body_lines: List[str] = []
    in_body = False
    for line in lines:
        if to_line is None and line.strip().lower().startswith("to:"):
            to_line = line.strip()
            continue
        if subject_line is None and line.strip().lower().startswith("subject:"):
            subject_line = line.strip()
            continue
        if line.strip().lower().startswith("body:"):
            in_body = True
            idx = line.lower().find("body:")
            remainder = line[idx + len("body:"):].strip()
            body_lines.append(remainder)
            continue
        if in_body:
            body_lines.append(line)
    return {
        "to": to_line,
        "subject": subject_line,
        "body": "\n".join(body_lines).strip(),
    }


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    parts = re.split(r"[.!?]+", text)
    count = 0
    for p in parts:
        if re.search(r"[A-Za-z]", p):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "refactored_script_present": 0.0,
        "cli_arguments_declared": 0.0,
        "refactor_uses_with_and_functions": 0.0,
        "output_csv_exists": 0.0,
        "output_columns_order": 0.0,
        "output_row_count_top_n": 0.0,
        "ranking_set_correct": 0.0,
        "ranking_score_correct": 0.0,
        "ranking_sorted_desc": 0.0,
        "status_update_exists": 0.0,
        "status_update_word_limit": 0.0,
        "status_update_sections_present": 0.0,
        "status_update_metrics_numbers_present": 0.0,
        "status_update_top5_matches_output": 0.0,
        "email_exists": 0.0,
        "email_to_field_present": 0.0,
        "email_subject_correct": 0.0,
        "email_thanks_angus_mention": 0.0,
        "email_top_angus_track_mentioned": 0.0,
        "email_body_sentence_count_valid": 0.0,
    }

    original_path = workspace / "src" / "playlist_tool.py"
    refactor_path = workspace / "refactor" / "playlist_tool_refactored.py"
    input_csv_path = workspace / "input" / "songs.csv"
    config_yaml_path = workspace / "input" / "config.yaml"
    output_csv_path = workspace / "outputs" / "top_folk_alt.csv"
    status_md_path = workspace / "outputs" / "status_update.md"
    email_txt_path = workspace / "outputs" / "email_to_blogger.txt"

    songs_rows = _parse_csv(input_csv_path) or []
    cfg_text = _read_text(config_yaml_path)
    cfg = _simple_yaml_load(cfg_text) if cfg_text is not None else None
    expected_rows: List[Dict[str, Any]] = []
    if songs_rows and cfg:
        expected_rows = _compute_expected_ranking(songs_rows, cfg)

    if refactor_path.exists() and refactor_path.is_file():
        scores["refactored_script_present"] = 1.0
        ref_text = _read_text(refactor_path) or ""
        if ("argparse" in ref_text) and ("--input" in ref_text) and ("--config" in ref_text) and ("--out" in ref_text):
            scores["cli_arguments_declared"] = 1.0
        has_with_open = "with open(" in ref_text
        counts = _count_loc_and_funcs(refactor_path) or {"loc": 0, "funcs": 0}
        has_functions = counts.get("funcs", 0) >= 2
        if has_with_open and has_functions:
            scores["refactor_uses_with_and_functions"] = 1.0

    if output_csv_path.exists() and output_csv_path.is_file():
        scores["output_csv_exists"] = 1.0
        try:
            with output_csv_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
        except Exception:
            try:
                with output_csv_path.open("r") as f:
                    header_line = f.readline().strip()
            except Exception:
                header_line = ""
        expected_header = "id,title,artist,genre,rating,plays,score"
        if header_line == expected_header:
            scores["output_columns_order"] = 1.0

        out_rows = _parse_output_csv(output_csv_path)
        if out_rows is not None:
            expected_count = len(expected_rows) if expected_rows else 0
            if expected_count > 0 and len(out_rows) == expected_count:
                scores["output_row_count_top_n"] = 1.0
            elif expected_rows == [] and len(out_rows) == 0:
                scores["output_row_count_top_n"] = 1.0

            if expected_rows and len(out_rows) == len(expected_rows):
                out_ids = [str(r.get("id", "")) for r in out_rows]
                exp_ids = [str(r["id"]) for r in expected_rows]
                if out_ids == exp_ids:
                    scores["ranking_set_correct"] = 1.0
            elif expected_rows == [] and out_rows == []:
                scores["ranking_set_correct"] = 1.0

            if expected_rows and out_rows and len(out_rows) == len(expected_rows):
                all_scores_ok = True
                for o, e in zip(out_rows, expected_rows):
                    o_score = _safe_float(o.get("score"))
                    if o_score is None or not _float_close(o_score, e["score"]):
                        all_scores_ok = False
                        break
                if all_scores_ok:
                    scores["ranking_score_correct"] = 1.0

            if out_rows:
                sorted_ok = True
                for i in range(len(out_rows) - 1):
                    s1 = _safe_float(out_rows[i].get("score"))
                    s2 = _safe_float(out_rows[i + 1].get("score"))
                    if s1 is None or s2 is None:
                        sorted_ok = False
                        break
                    if s1 + 5e-4 < s2:
                        sorted_ok = False
                        break
                if sorted_ok:
                    scores["ranking_sorted_desc"] = 1.0

    if status_md_path.exists() and status_md_path.is_file():
        scores["status_update_exists"] = 1.0
        status_text = _read_text(status_md_path) or ""
        words = re.findall(r"\b\w+\b", status_text)
        if len(words) <= 300:
            scores["status_update_word_limit"] = 1.0
        lower = status_text.lower()
        if ("summary" in lower) and ("changes made" in lower) and ("metrics" in lower) and ("top 5" in lower):
            scores["status_update_sections_present"] = 1.0

        orig_counts = _count_loc_and_funcs(original_path) or {"loc": 0, "funcs": 0}
        ref_counts = _count_loc_and_funcs(refactor_path) or {"loc": 0, "funcs": 0}
        orig_loc_s = str(orig_counts.get("loc", 0))
        ref_loc_s = str(ref_counts.get("loc", 0))
        orig_funcs_s = str(orig_counts.get("funcs", 0))
        ref_funcs_s = str(ref_counts.get("funcs", 0))
        if (orig_loc_s in status_text and ref_loc_s in status_text and
                orig_funcs_s in status_text and ref_funcs_s in status_text):
            scores["status_update_metrics_numbers_present"] = 1.0

        if output_csv_path.exists():
            out_rows_for_top = _parse_output_csv(output_csv_path) or []
            top5 = out_rows_for_top[:5]
            if top5:
                found_all = True
                for r in top5:
                    title = str(r.get("title", ""))
                    artist = str(r.get("artist", ""))
                    pattern_ok = False
                    for line in status_text.splitlines():
                        if title in line and artist in line:
                            pattern_ok = True
                            break
                    if not pattern_ok:
                        found_all = False
                        break
                if found_all:
                    scores["status_update_top5_matches_output"] = 1.0

    if email_txt_path.exists() and email_txt_path.is_file():
        scores["email_exists"] = 1.0
        email_text = _read_text(email_txt_path) or ""
        fields = _extract_email_fields(email_text)
        to_line = fields.get("to") or ""
        if to_line.lower().startswith("to:") and len(to_line.split(":", 1)[1].strip()) > 0:
            scores["email_to_field_present"] = 1.0
        subj_line = fields.get("subject") or ""
        if subj_line.strip() == "Subject: Brief update on my folk/alternative playlist tool":
            scores["email_subject_correct"] = 1.0
        body = fields.get("body") or ""
        lower_body = body.lower()
        if ("thank" in lower_body) and ("angus & julia stone" in lower_body):
            scores["email_thanks_angus_mention"] = 1.0
        n_sent = _count_sentences(body)
        if 3 <= n_sent <= 6:
            scores["email_body_sentence_count_valid"] = 1.0
        top_angus_title: Optional[str] = None
        if output_csv_path.exists():
            out_rows_email = _parse_output_csv(output_csv_path) or []
            angus_rows = [r for r in out_rows_email if str(r.get("artist", "")) == "Angus & Julia Stone"]
            if angus_rows:
                angus_rows_sorted = sorted(angus_rows, key=lambda x: _safe_float(x.get("score")) or -1.0, reverse=True)
                top_angus_title = str(angus_rows_sorted[0].get("title", ""))
        if top_angus_title and (top_angus_title in body):
            scores["email_top_angus_track_mentioned"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()