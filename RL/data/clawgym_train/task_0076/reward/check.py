import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read_error:{e}"
    try:
        data = json.loads(text)
        return data, None
    except Exception as e:
        return None, f"json_error:{e}"


def _safe_read_csv_dict(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return rows, headers, None
    except Exception as e:
        return None, None, f"csv_read_error:{e}"


def _parse_bool_str(val: str) -> Optional[bool]:
    if val is None:
        return None
    v = val.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    return None


def _extract_entity_from_raw(qid: str, raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        if "entities" in raw and isinstance(raw["entities"], dict):
            ent = raw["entities"].get(qid)
            if isinstance(ent, dict):
                return ent
        if raw.get("id") == qid:
            return raw
    return None


def _get_labels_value(entity: Dict[str, Any], lang: str, key: str = "labels") -> str:
    return entity.get(key, {}).get(lang, {}).get("value", "") if isinstance(entity.get(key, {}), dict) else ""


def _get_aliases(entity: Dict[str, Any], lang: str) -> List[str]:
    aliases = entity.get("aliases", {}).get(lang)
    out: List[str] = []
    if isinstance(aliases, list):
        for a in aliases:
            if isinstance(a, dict):
                val = a.get("value")
                if isinstance(val, str):
                    out.append(val)
    return out


def _extract_time_year(time_str: str) -> Optional[int]:
    if not isinstance(time_str, str):
        return None
    m = re.match(r"^([+-])(\d{1,})-(\d{2})-(\d{2})T", time_str)
    if not m:
        return None
    sign = m.group(1)
    year_raw = m.group(2)
    try:
        year_int = int(year_raw)
    except ValueError:
        return None
    if sign == "-":
        year_int = -year_int
    return year_int


def _get_claim_values(entity: Dict[str, Any], prop: str) -> List[Any]:
    claims = entity.get("claims", {}).get(prop)
    vals: List[Any] = []
    if isinstance(claims, list):
        for cl in claims:
            if not isinstance(cl, dict):
                continue
            mainsnak = cl.get("mainsnak", {})
            if not isinstance(mainsnak, dict):
                continue
            if mainsnak.get("snaktype") != "value":
                continue
            datavalue = mainsnak.get("datavalue", {})
            if not isinstance(datavalue, dict):
                continue
            vals.append(datavalue.get("value"))
    return vals


def _extract_inception_year(entity: Dict[str, Any]) -> Optional[int]:
    vals = _get_claim_values(entity, "P571")
    years: List[int] = []
    for v in vals:
        if isinstance(v, dict):
            t = v.get("time")
            y = _extract_time_year(t)
            if y is not None:
                years.append(y)
    if not years:
        return None
    return min(years)


def _extract_ids_from_claims(entity: Dict[str, Any], prop: str) -> List[str]:
    vals = _get_claim_values(entity, prop)
    ids: List[str] = []
    for v in vals:
        if isinstance(v, dict):
            id_val = v.get("id")
            if isinstance(id_val, str):
                ids.append(id_val)
    return ids


def _extract_image_filename(entity: Dict[str, Any]) -> str:
    vals = _get_claim_values(entity, "P18")
    for v in vals:
        if isinstance(v, str):
            return v
    return ""


def _extract_enwiki_title(entity: Dict[str, Any]) -> str:
    sitelinks = entity.get("sitelinks", {})
    if isinstance(sitelinks, dict):
        enwiki = sitelinks.get("enwiki", {})
        if isinstance(enwiki, dict):
            title = enwiki.get("title")
            if isinstance(title, str):
                return title
    return ""


def _compute_keyword_match(note: str, label_en: str, description_en: str, aliases: List[str], enwiki_title: str) -> bool:
    term = (note or "").strip().lower()
    if term == "":
        return False
    fields = [label_en or "", description_en or "", enwiki_title or ""] + aliases
    term_lower = term.lower()
    for f in fields:
        if term_lower in (f or "").lower():
            return True
    return False


def _extract_summary_fields_from_raw(qid: str, raw: Any, note: str) -> Optional[Dict[str, Any]]:
    ent = _extract_entity_from_raw(qid, raw)
    if ent is None:
        return None
    label_en = _get_labels_value(ent, "en", "labels")
    description_en = _get_labels_value(ent, "en", "descriptions")
    aliases = _get_aliases(ent, "en")
    inception_year_val = _extract_inception_year(ent)
    manufacturer_ids = _extract_ids_from_claims(ent, "P176")
    instance_of_ids = _extract_ids_from_claims(ent, "P31")
    image_filename = _extract_image_filename(ent)
    enwiki_title = _extract_enwiki_title(ent)
    keyword_match = _compute_keyword_match(note, label_en, description_en, aliases, enwiki_title)
    return {
        "qid": qid,
        "label_en": label_en,
        "description_en": description_en,
        "aliases_en_pipe": " | ".join(aliases) if aliases else "",
        "inception_year": str(inception_year_val) if inception_year_val is not None else "",
        "manufacturer_ids_pipe": " | ".join(manufacturer_ids) if manufacturer_ids else "",
        "instance_of_ids_pipe": " | ".join(instance_of_ids) if instance_of_ids else "",
        "image_filename": image_filename,
        "enwiki_title": enwiki_title,
        "keyword_match": keyword_match,
    }


def _state_contains_batch(state_data: Any, batch_id: str) -> bool:
    if isinstance(state_data, list):
        return batch_id in [x for x in state_data if isinstance(x, str)]
    if isinstance(state_data, dict):
        if batch_id in state_data.keys():
            return True
        pb = state_data.get("processed_batches")
        if isinstance(pb, list):
            return batch_id in [x for x in pb if isinstance(x, str)]
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_csv_present": 0.0,
        "summary_contains_required_columns": 0.0,
        "summary_row_count_matches_targets": 0.0,
        "summary_qids_match_targets": 0.0,
        "status_and_error_fields_valid": 0.0,
        "raw_dir_present": 0.0,
        "raw_files_for_ok_rows_present_and_json": 0.0,
        "extracted_fields_match_raw": 0.0,
        "keyword_match_correct": 0.0,
        "state_file_has_batch_id": 0.0,
        "run_log_has_entry_with_correct_counts": 0.0,
    }

    input_path = workspace / "input" / "cii_targets.json"
    input_data, input_err = _safe_load_json(input_path)
    if input_data is None or not isinstance(input_data, dict):
        return scores

    batch_id = input_data.get("batch_id")
    targets = input_data.get("targets")
    if not isinstance(batch_id, str) or not isinstance(targets, list):
        return scores

    target_qids: List[str] = []
    notes_by_qid: Dict[str, str] = {}
    for t in targets:
        if isinstance(t, dict):
            qid = t.get("qid")
            note = t.get("note", "")
            if isinstance(qid, str):
                target_qids.append(qid)
                notes_by_qid[qid] = note if isinstance(note, str) else ""

    outputs_dir = workspace / "outputs" / batch_id
    raw_dir = outputs_dir / "raw"
    summary_csv = outputs_dir / "summary.csv"
    state_file = workspace / "state" / "processed_batches.json"
    log_file = workspace / "logs" / "run.log"

    if raw_dir.exists() and raw_dir.is_dir():
        scores["raw_dir_present"] = 1.0

    rows, headers, csv_err = _safe_read_csv_dict(summary_csv)
    if rows is not None and headers is not None:
        scores["summary_csv_present"] = 1.0
        required_cols = [
            "qid",
            "label_en",
            "description_en",
            "aliases_en_pipe",
            "inception_year",
            "manufacturer_ids_pipe",
            "instance_of_ids_pipe",
            "image_filename",
            "enwiki_title",
            "keyword_match",
            "status",
            "error",
        ]
        if all(col in headers for col in required_cols):
            scores["summary_contains_required_columns"] = 1.0

        if len(rows) == len(target_qids):
            scores["summary_row_count_matches_targets"] = 1.0

        row_qids = [r.get("qid", "") for r in rows]
        if set(row_qids) == set(target_qids) and len(row_qids) == len(target_qids):
            scores["summary_qids_match_targets"] = 1.0

        status_error_ok = True
        for r in rows:
            status = (r.get("status") or "").strip().lower()
            if status not in ("ok", "error"):
                status_error_ok = False
                break
            err_field = r.get("error")
            if status == "ok":
                if err_field is None or len(err_field.strip()) != 0:
                    status_error_ok = False
                    break
            else:
                if err_field is None or len(err_field.strip()) == 0:
                    status_error_ok = False
                    break
        if status_error_ok:
            scores["status_and_error_fields_valid"] = 1.0

        ok_rows = [r for r in rows if (r.get("status") or "").strip().lower() == "ok"]
        ok_raw_presence_valid = True
        fields_match_valid = True
        keyword_match_valid = True
        for r in ok_rows:
            qid = r.get("qid", "").strip()
            note = notes_by_qid.get(qid, "")
            raw_path = raw_dir / f"{qid}.json"
            raw_data, raw_err = _safe_load_json(raw_path)
            if raw_data is None:
                ok_raw_presence_valid = False
                fields_match_valid = False
                keyword_match_valid = False
                continue
            expected = _extract_summary_fields_from_raw(qid, raw_data, note)
            if expected is None:
                ok_raw_presence_valid = False
                fields_match_valid = False
                keyword_match_valid = False
                continue
            comparisons = [
                ("label_en", expected["label_en"], r.get("label_en", "")),
                ("description_en", expected["description_en"], r.get("description_en", "")),
                ("aliases_en_pipe", expected["aliases_en_pipe"], r.get("aliases_en_pipe", "")),
                ("inception_year", expected["inception_year"], r.get("inception_year", "")),
                ("manufacturer_ids_pipe", expected["manufacturer_ids_pipe"], r.get("manufacturer_ids_pipe", "")),
                ("instance_of_ids_pipe", expected["instance_of_ids_pipe"], r.get("instance_of_ids_pipe", "")),
                ("image_filename", expected["image_filename"], r.get("image_filename", "")),
                ("enwiki_title", expected["enwiki_title"], r.get("enwiki_title", "")),
            ]
            for _, exp_val, got_val in comparisons:
                if (exp_val or "") != (got_val or ""):
                    fields_match_valid = False
                    break
            got_kw = r.get("keyword_match", "")
            got_kw_bool = _parse_bool_str(got_kw)
            if got_kw_bool is None or got_kw_bool != expected["keyword_match"]:
                keyword_match_valid = False
        if ok_rows:
            if ok_raw_presence_valid:
                scores["raw_files_for_ok_rows_present_and_json"] = 1.0
            if fields_match_valid:
                scores["extracted_fields_match_raw"] = 1.0
            if keyword_match_valid:
                scores["keyword_match_correct"] = 1.0

        if log_file.exists():
            try:
                log_text = log_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                log_text = ""
            ok_count = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "ok")
            err_count = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "error")
            found_line_matching = False
            for line in log_text.splitlines():
                if batch_id in line:
                    m_ok = re.search(r"ok\s*[:=]\s*(\d+)", line, flags=re.IGNORECASE)
                    m_err = re.search(r"error\s*[:=]\s*(\d+)", line, flags=re.IGNORECASE)
                    if m_ok and m_err:
                        try:
                            ok_val = int(m_ok.group(1))
                            err_val = int(m_err.group(1))
                            if ok_val == ok_count and err_val == err_count:
                                found_line_matching = True
                                break
                        except Exception:
                            continue
            if found_line_matching:
                scores["run_log_has_entry_with_correct_counts"] = 1.0

    state_data, state_err = _safe_load_json(state_file)
    if state_data is not None and _state_contains_batch(state_data, batch_id):
        scores["state_file_has_batch_id"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()