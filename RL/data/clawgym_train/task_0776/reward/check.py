import sys
import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if (len(v) >= 2) and ((v[0] == v[-1]) and (v[0] in ("'", '"'))):
        return v[1:-1]
    lv = v.lower()
    if lv == "true":
        return True
    if lv == "false":
        return False
    try:
        if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
            return int(v)
    except Exception:
        pass
    try:
        return float(v)
    except Exception:
        pass
    return v


def _parse_flow_list(value: str) -> Optional[List[str]]:
    s = value.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    inner = s[1:-1].strip()
    if inner == "":
        return []
    parts = []
    current = ""
    in_quote = False
    quote_char = ""
    for ch in inner:
        if in_quote:
            current += ch
            if ch == quote_char:
                in_quote = False
        else:
            if ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                current += ch
            elif ch == ",":
                token = current.strip()
                if (len(token) >= 2) and ((token[0] == token[-1]) and token[0] in ("'", '"')):
                    token = token[1:-1]
                parts.append(token)
                current = ""
            else:
                current += ch
    if current.strip() != "":
        token = current.strip()
        if (len(token) >= 2) and ((token[0] == token[-1]) and token[0] in ("'", '"')):
            token = token[1:-1]
        parts.append(token)
    return [p.strip() for p in parts]


def _parse_simple_yaml(text: str) -> Optional[Dict[str, Any]]:
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw in lines:
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = raw.strip()
        if ":" not in content:
            return None
        key, _, rest = content.partition(":")
        key = key.strip()
        value = rest.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if value == "":
            new_map: Dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent, new_map))
        else:
            flow_list = _parse_flow_list(value)
            if flow_list is not None:
                current[key] = flow_list
            else:
                current[key] = _parse_scalar(value)
    return root


def _extract_front_matter_and_body(md_text: str) -> Optional[Tuple[Dict[str, Any], str]]:
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = None
    for i in range(start_idx + 1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None
    fm_text = "\n".join(lines[start_idx + 1 : end_idx])
    body_text = "\n".join(lines[end_idx + 1 :])
    fm_lines = fm_text.splitlines()
    fm: Dict[str, Any] = {}
    for raw in fm_lines:
        if not raw.strip():
            continue
        if ":" not in raw:
            return None
        key, _, rest = raw.partition(":")
        key = key.strip()
        value = rest.strip()
        flow = _parse_flow_list(value)
        if flow is not None:
            fm[key] = flow
        else:
            fm[key] = _parse_scalar(value)
    return fm, body_text


def _load_drafts(drafts_dir: Path) -> Optional[List[Dict[str, Any]]]:
    if not drafts_dir.exists() or not drafts_dir.is_dir():
        return []
    drafts: List[Dict[str, Any]] = []
    for path in sorted(drafts_dir.glob("*.md")):
        text = _read_text(path)
        if text is None:
            return None
        parsed = _extract_front_matter_and_body(text)
        if parsed is None:
            return None
        fm, body = parsed
        title = str(fm.get("title", "")).strip()
        feel = str(fm.get("feel", "")).strip()
        instruments_raw = fm.get("instruments", [])
        if isinstance(instruments_raw, list):
            instruments = [str(x).strip() for x in instruments_raw]
        else:
            if isinstance(instruments_raw, str):
                fl = _parse_flow_list(instruments_raw)
                instruments = [str(x).strip() for x in (fl or [])]
            else:
                instruments = []
        drafts.append(
            {
                "filename": path.name,
                "title": title,
                "feel": feel,
                "instruments": instruments,
                "lyrics": body,
            }
        )
    return drafts


def _normalize_text(s: str) -> str:
    return s.lower()


def _detect_feature_for_draft(draft: Dict[str, Any], feature_def: Dict[str, Any]) -> bool:
    fields = feature_def.get("fields", [])
    patterns = feature_def.get("patterns", [])
    all_of = bool(feature_def.get("all_of", False))
    matched_patterns = set()
    for patt in patterns:
        lp = _normalize_text(str(patt))
        found = False
        for field in fields:
            f = str(field).strip().lower()
            if f == "lyrics":
                body = _normalize_text(draft.get("lyrics", ""))
                if lp in body:
                    found = True
                    break
            elif f == "feel":
                feel = _normalize_text(draft.get("feel", ""))
                if lp in feel:
                    found = True
                    break
            elif f == "instruments":
                items = [x.lower() for x in draft.get("instruments", [])]
                if lp in items:
                    found = True
                    break
            else:
                continue
        if found:
            matched_patterns.add(lp)
    if all_of:
        return all(_normalize_text(str(p)) in matched_patterns for p in patterns)
    else:
        return len(matched_patterns) > 0


def _compute_expected(drafts: List[Dict[str, Any]], features_def: Dict[str, Any], feature_order: List[str]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, float]]:
    rows: Dict[str, Dict[str, Any]] = {}
    totals: Dict[str, int] = {f: 0 for f in feature_order}
    total_drafts = len(drafts)

    for d in drafts:
        row = {
            "filename": d["filename"],
            "title": d.get("title", ""),
        }
        for feat in feature_order:
            fdef = features_def.get(feat, {})
            matched = _detect_feature_for_draft(d, fdef)
            val = 1 if matched else 0
            row[feat] = val
            totals[feat] += val
        rows[d["filename"]] = row

    weights: Dict[str, float] = {}
    for feat in feature_order:
        if total_drafts == 0:
            w = 0.0
        else:
            w = round(totals[feat] / total_drafts, 2)
        weights[feat] = float(w)
    return rows, weights


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "feature_scan_csv_header_correct": 0.0,
        "feature_scan_csv_rows_correct": 0.0,
        "feature_weights_json_schema_valid": 0.0,
        "feature_weights_values_correct": 0.0,
        "config_enabled_flag_true": 0.0,
        "config_feature_weights_updated": 0.0,
        "config_other_fields_unchanged": 0.0,
    }

    features_path = workspace / "input" / "reference" / "the_band_features.json"
    drafts_dir = workspace / "input" / "drafts"
    csv_path = workspace / "output" / "the_band_feature_scan.csv"
    weights_json_path = workspace / "output" / "the_band_feature_weights.json"
    config_path = workspace / "config" / "songgen.yaml"

    features_def = _load_json(features_path)
    drafts = _load_drafts(drafts_dir)

    feature_order = [
        "call_and_response",
        "piano_organ_combo",
        "roots_rock_shuffle",
        "storytelling_verses",
    ]

    expected_rows: Optional[Dict[str, Dict[str, Any]]] = None
    expected_weights: Optional[Dict[str, float]] = None
    total_drafts: Optional[int] = None

    if features_def is not None and drafts is not None:
        total_drafts = len(drafts)
        expected_rows, expected_weights = _compute_expected(drafts, features_def, feature_order)

    header_expected = ["filename", "title"] + feature_order
    if csv_path.exists():
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == header_expected:
                    scores["feature_scan_csv_header_correct"] = 1.0
                rows_list = []
                if header is not None:
                    for row in reader:
                        if any(cell.strip() for cell in row):
                            rows_list.append(row)
                if expected_rows is not None and header == header_expected:
                    produced: Dict[str, Dict[str, Any]] = {}
                    for row in rows_list:
                        if len(row) != len(header_expected):
                            produced = {}
                            break
                        fname = row[0]
                        produced[fname] = {
                            "filename": row[0],
                            "title": row[1],
                            feature_order[0]: row[2],
                            feature_order[1]: row[3],
                            feature_order[2]: row[4],
                            feature_order[3]: row[5],
                        }
                    if produced and set(produced.keys()) == set(expected_rows.keys()):
                        ok = True
                        for fname, exp in expected_rows.items():
                            prod = produced.get(fname)
                            if prod is None:
                                ok = False
                                break
                            if prod["title"] != exp["title"]:
                                ok = False
                                break
                            for feat in feature_order:
                                pv = prod[feat]
                                if pv not in ("0", "1"):
                                    try:
                                        pv_num = int(str(pv))
                                        pv_str = str(pv_num)
                                    except Exception:
                                        ok = False
                                        break
                                    if pv_str not in ("0", "1"):
                                        ok = False
                                        break
                                    pv = pv_str
                                ev = str(int(exp[feat]))
                                if pv != ev:
                                    ok = False
                                    break
                            if not ok:
                                break
                        if ok:
                            scores["feature_scan_csv_rows_correct"] = 1.0
                    else:
                        if expected_rows is not None and len(expected_rows) == 0 and len(rows_list) == 0:
                            scores["feature_scan_csv_rows_correct"] = 1.0
        except Exception:
            pass

    weights_data = _load_json(weights_json_path) if weights_json_path.exists() else None
    if weights_data is not None and isinstance(weights_data, dict):
        schema_ok = True
        if "total_drafts" not in weights_data or "feature_weights" not in weights_data:
            schema_ok = False
        if schema_ok:
            if not isinstance(weights_data["total_drafts"], int):
                schema_ok = False
            if not isinstance(weights_data["feature_weights"], dict):
                schema_ok = False
            else:
                fw = weights_data["feature_weights"]
                if set(fw.keys()) != set(feature_order):
                    schema_ok = False
                else:
                    for k in feature_order:
                        v = fw.get(k)
                        if not isinstance(v, (int, float)):
                            schema_ok = False
                            break
        if schema_ok:
            scores["feature_weights_json_schema_valid"] = 1.0

        if expected_weights is not None and total_drafts is not None and schema_ok:
            values_ok = True
            if weights_data.get("total_drafts") != total_drafts:
                values_ok = False
            fw = weights_data.get("feature_weights", {})
            for k in feature_order:
                try:
                    if float(fw.get(k)) != float(expected_weights.get(k)):
                        values_ok = False
                        break
                except Exception:
                    values_ok = False
                    break
            if values_ok:
                scores["feature_weights_values_correct"] = 1.0

    config_text = _read_text(config_path) if config_path.exists() else None
    cfg = _parse_simple_yaml(config_text) if config_text is not None else None
    enabled_ok = False
    fw_ok = False
    if cfg is not None and isinstance(cfg, dict):
        influences = cfg.get("influences")
        the_band = None
        if isinstance(influences, dict):
            the_band = influences.get("the_band")
        if isinstance(the_band, dict):
            enabled_ok = bool(the_band.get("enabled") is True)
        if enabled_ok:
            scores["config_enabled_flag_true"] = 1.0
        if isinstance(the_band, dict) and isinstance(the_band.get("feature_weights"), dict) and expected_weights is not None:
            fw_map = the_band.get("feature_weights")
            if set(fw_map.keys()) == set(feature_order):
                match_all = True
                for k in feature_order:
                    v = fw_map.get(k)
                    if not isinstance(v, (int, float)):
                        try:
                            v = float(str(v))
                        except Exception:
                            match_all = False
                            break
                    if float(v) != float(expected_weights[k]):
                        match_all = False
                        break
                if match_all:
                    fw_ok = True
        if fw_ok:
            scores["config_feature_weights_updated"] = 1.0

        # Only assess "other fields unchanged" if the config updates are correct
        if enabled_ok and fw_ok:
            other_ok = True
            if cfg.get("project") != "SongLab":
                other_ok = False
            if cfg.get("version") != "1.2":
                other_ok = False
            general = None
            if isinstance(influences, dict):
                general = influences.get("general")
            if not isinstance(general, dict):
                other_ok = False
            else:
                if general.get("groove_bias") != 0.5:
                    other_ok = False
                if general.get("lyric_density") != 0.6:
                    other_ok = False
            if isinstance(the_band, dict):
                allowed_keys = {"enabled", "feature_weights"}
                if set(the_band.keys()) != allowed_keys:
                    other_ok = False
            else:
                other_ok = False
            if other_ok:
                scores["config_other_fields_unchanged"] = 1.0

    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()