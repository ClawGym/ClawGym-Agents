import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


INITIAL_KEYWORDS = ["safety", "risk", "ethics", "trial", "containment", "off-target", "regulatory"]
INITIAL_CASE_SENSITIVE = False


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:
        return None, f"error: {e}"


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read(), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:
        return None, f"error: {e}"


def _token_word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _extract_tagged_quote_ids(text: str) -> List[str]:
    return [f"Q{m}" for m in re.findall(r"\[Q(\d+)\]", text)]


def _normalize_heading(line: str) -> str:
    s = line.strip()
    s = s.lstrip("#").strip()
    return s


def _set_casefold(lst: List[str]) -> Set[str]:
    return set(str(x).casefold() for x in lst)


def _items_by_id(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(it.get("id")): it for it in items if isinstance(it, dict) and "id" in it}


def _run_extractor_with_config(workspace: Path, in_dir: Path, config_path: Path, out_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    script = workspace / "tools" / "extract_sentences.py"
    if not script.is_file() or not in_dir.is_dir() or not config_path.is_file():
        return None, "prereq_missing"
    try:
        cmd = [sys.executable, str(script), "--in_dir", str(in_dir), "--config", str(config_path), "--out", str(out_path)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            return None, f"returncode_{res.returncode}"
        obj, err = _load_json(out_path)
        if obj is None:
            return None, err or "load_failed"
        return obj, None
    except Exception as e:
        return None, f"exception: {e}"


def _rerun_current_extractor(workspace: Path, out_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    in_dir = workspace / "input"
    config = workspace / "config" / "keywords.json"
    return _run_extractor_with_config(workspace, in_dir, config, out_path)


def _rerun_initial_extractor(workspace: Path, out_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    in_dir = workspace / "input"
    # Create a temporary initial config file
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump({"keywords": INITIAL_KEYWORDS, "case_sensitive": INITIAL_CASE_SENSITIVE}, tf, ensure_ascii=False, indent=2)
            temp_cfg_path = Path(tf.name)
    except Exception as e:
        return None, f"temp_config_error: {e}"
    try:
        obj, err = _run_extractor_with_config(workspace, in_dir, temp_cfg_path, out_path)
    finally:
        try:
            temp_cfg_path.unlink(missing_ok=True)  # type: ignore
        except Exception:
            pass
    return obj, err


def _tuple_key(it: Dict[str, Any]) -> Tuple[str, int, str]:
    return (str(it.get("file")), int(it.get("line_no")), str(it.get("sentence")))


def _validate_citations_structure(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if "used_quotes" not in obj or "keywords_used" not in obj:
        return False
    if not isinstance(obj["used_quotes"], list) or not isinstance(obj["keywords_used"], list):
        return False
    for uq in obj["used_quotes"]:
        if not isinstance(uq, dict):
            return False
        if not all(k in uq for k in ("id", "source_file", "line_no", "sentence", "matched_keywords")):
            return False
        if not isinstance(uq.get("id"), str):
            return False
        if not isinstance(uq.get("source_file"), str):
            return False
        if not isinstance(uq.get("line_no"), int):
            return False
        if not isinstance(uq.get("sentence"), str):
            return False
        if not isinstance(uq.get("matched_keywords"), list):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "config_contains_all_original_keywords": 0.0,
        "config_added_at_least_two_new_keywords": 0.0,
        "quotes_keywords_match_config": 0.0,
        "quotes_json_matches_rerun": 0.0,
        "rebuttal_word_count_600_800": 0.0,
        "rebuttal_uses_min_three_tagged_quotes": 0.0,
        "rebuttal_quotes_verbatim_from_workspace": 0.0,
        "rebuttal_includes_quote_not_in_initial_keywords_extraction": 0.0,
        "claims_challenged_section_at_end_with_bullets": 0.0,
        "citations_json_structure_valid": 0.0,
        "citations_used_quotes_align_with_rebuttal_and_workspace": 0.0,
        "citations_keywords_used_match_config": 0.0,
    }

    # Load current config (used internally; no direct score for mere presence)
    config_path = workspace / "config" / "keywords.json"
    config_obj, _ = _load_json(config_path)
    config_keywords: List[str] = []
    if isinstance(config_obj, dict) and isinstance(config_obj.get("keywords"), list):
        config_keywords = [str(k) for k in config_obj["keywords"]]
        conf_set = _set_casefold(config_keywords)
        initial_set = _set_casefold(INITIAL_KEYWORDS)
        added = conf_set - initial_set
        kept_all = initial_set.issubset(conf_set)
        added_two = len(added) >= 2
        if added_two:
            scores["config_added_at_least_two_new_keywords"] = 1.0
            if kept_all:
                scores["config_contains_all_original_keywords"] = 1.0

    # Load workspace quotes (must be produced by running extractor)
    workspace_quotes_path = workspace / "workspace" / "quotes.json"
    ws_quotes_obj, _ = _load_json(workspace_quotes_path)
    ws_items: List[Dict[str, Any]] = []
    ws_items_by_id: Dict[str, Dict[str, Any]] = {}
    if isinstance(ws_quotes_obj, dict) and isinstance(ws_quotes_obj.get("items"), list):
        ws_items = ws_quotes_obj["items"]
        ws_items_by_id = _items_by_id(ws_items)
        if config_keywords:
            ws_keywords = ws_quotes_obj.get("keywords", [])
            if isinstance(ws_keywords, list) and _set_casefold(ws_keywords) == _set_casefold(config_keywords):
                scores["quotes_keywords_match_config"] = 1.0

    # Rerun extractor with current config and compare with workspace/quotes.json for reproducibility
    rerun_ok = False
    with tempfile.TemporaryDirectory() as td:
        rerun_out_path = Path(td) / "quotes_rerun.json"
        rerun_obj, _ = _rerun_current_extractor(workspace, rerun_out_path)
        if isinstance(rerun_obj, dict) and isinstance(rerun_obj.get("items"), list) and ws_items:
            rerun_items = rerun_obj["items"]

            def norm_item(it: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    "id": str(it.get("id")),
                    "file": str(it.get("file")),
                    "line_no": int(it.get("line_no")),
                    "sentence": str(it.get("sentence")),
                    "matched_keywords": sorted(list(set(str(x) for x in it.get("matched_keywords", [])))),
                }

            if len(ws_items) == len(rerun_items):
                all_match = True
                for a, b in zip(ws_items, rerun_items):
                    na = norm_item(a)
                    nb = norm_item(b)
                    if na["id"] != nb["id"] or na["file"] != nb["file"] or na["line_no"] != nb["line_no"] or na["sentence"] != nb["sentence"]:
                        all_match = False
                        break
                    if set(x.casefold() for x in na["matched_keywords"]) != set(x.casefold() for x in nb["matched_keywords"]):
                        all_match = False
                        break
                if all_match:
                    rerun_ok = True
    if rerun_ok:
        scores["quotes_json_matches_rerun"] = 1.0

    # Load rebuttal
    rebuttal_path = workspace / "output" / "rebuttal.md"
    rebuttal_text, _ = _read_text(rebuttal_path)
    used_ids_set: Set[str] = set()
    if rebuttal_text is not None:
        wc = _token_word_count(rebuttal_text)
        if 600 <= wc <= 800:
            scores["rebuttal_word_count_600_800"] = 1.0
        used_ids = _extract_tagged_quote_ids(rebuttal_text)
        used_ids_set = set(used_ids)
        if len(used_ids_set) >= 3:
            scores["rebuttal_uses_min_three_tagged_quotes"] = 1.0
        # Quotes must be verbatim from workspace/quotes.json
        verbatim_ok = True
        if used_ids_set and ws_items_by_id:
            for qid in used_ids_set:
                it = ws_items_by_id.get(qid)
                if not it:
                    verbatim_ok = False
                    break
                sentence = str(it.get("sentence", ""))
                if not sentence or sentence not in rebuttal_text:
                    verbatim_ok = False
                    break
        else:
            verbatim_ok = False
        if verbatim_ok:
            scores["rebuttal_quotes_verbatim_from_workspace"] = 1.0

        # Claims Challenged section at end with bullets and valid line refs
        lines = rebuttal_text.splitlines()
        last_heading_idx = -1
        for idx, line in enumerate(lines):
            if _normalize_heading(line) == "Claims Challenged":
                last_heading_idx = idx
        claims_ok = False
        if last_heading_idx != -1:
            bullets: List[str] = []
            trailing_ok = True
            for line in lines[last_heading_idx + 1:]:
                if not line.strip():
                    continue
                if line.lstrip().startswith("- ") or line.lstrip().startswith("* "):
                    bullets.append(line)
                else:
                    trailing_ok = False
                    break
            if trailing_ok and len(bullets) >= 2:
                ja_path = workspace / "input" / "journalist_article.md"
                ja_text, _ = _read_text(ja_path)
                if ja_text is not None:
                    ja_lines = ja_text.splitlines()
                    max_ln = len(ja_lines)
                    pattern = re.compile(r"\(journalist_article\.md line (\d+)\)")
                    refs_valid = True
                    for b in bullets:
                        m = pattern.search(b)
                        if not m:
                            refs_valid = False
                            break
                        n = int(m.group(1))
                        if not (1 <= n <= max_ln):
                            refs_valid = False
                            break
                        if not ja_lines[n - 1].strip():
                            refs_valid = False
                            break
                    if refs_valid:
                        claims_ok = True
        if claims_ok:
            scores["claims_challenged_section_at_end_with_bullets"] = 1.0

    # Verify that at least one used quote would not have been extracted with the initial keywords
    # This requires: workspace quotes present, rerun current success or not strictly required,
    # and ability to run initial extractor. We compare by (file, line_no, sentence).
    new_only_ok = False
    if used_ids_set and ws_items_by_id:
        # Build set of (file, line_no, sentence) from initial extraction
        with tempfile.TemporaryDirectory() as td2:
            base_out_path = Path(td2) / "quotes_base.json"
            base_obj, _ = _rerun_initial_extractor(workspace, base_out_path)
            if isinstance(base_obj, dict) and isinstance(base_obj.get("items"), list):
                base_items = base_obj["items"]
                base_tuple_set = set(_tuple_key(it) for it in base_items)
                for qid in used_ids_set:
                    it = ws_items_by_id.get(qid)
                    if not it:
                        continue
                    tup = _tuple_key(it)
                    if tup not in base_tuple_set:
                        new_only_ok = True
                        break
    if new_only_ok:
        scores["rebuttal_includes_quote_not_in_initial_keywords_extraction"] = 1.0

    # Load and validate citations.json
    citations_path = workspace / "output" / "citations.json"
    citations_obj, _ = _load_json(citations_path)
    if citations_obj is not None and _validate_citations_structure(citations_obj):
        scores["citations_json_structure_valid"] = 1.0
        # Alignment: used IDs in text must equal used_quotes IDs in citations, and metadata must match workspace quotes
        alignment_ok = False
        if ws_items_by_id and rebuttal_text is not None:
            used_ids_in_text = set(_extract_tagged_quote_ids(rebuttal_text))
            cit_used_ids = set()
            meta_match = True
            for uq in citations_obj["used_quotes"]:
                qid = str(uq.get("id"))
                cit_used_ids.add(qid)
                it = ws_items_by_id.get(qid)
                if not it:
                    meta_match = False
                    break
                if str(uq.get("source_file")) != str(it.get("file")):
                    meta_match = False
                    break
                if int(uq.get("line_no")) != int(it.get("line_no")):
                    meta_match = False
                    break
                if str(uq.get("sentence")) != str(it.get("sentence")):
                    meta_match = False
                    break
                mk1 = set(str(x).casefold() for x in uq.get("matched_keywords", []))
                mk2 = set(str(x).casefold() for x in it.get("matched_keywords", []))
                if mk1 != mk2:
                    meta_match = False
                    break
            if used_ids_in_text and meta_match and cit_used_ids == used_ids_in_text:
                alignment_ok = True
        if alignment_ok:
            scores["citations_used_quotes_align_with_rebuttal_and_workspace"] = 1.0
        # Keywords_used should match final config keywords
        if isinstance(citations_obj.get("keywords_used"), list) and config_keywords:
            if _set_casefold(citations_obj["keywords_used"]) == _set_casefold(config_keywords):
                scores["citations_keywords_used_match_config"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()