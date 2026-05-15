import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


ALLOWED_CATEGORIES = {"bonfires", "fireworks", "decorations", "waste"}
ALLOWED_STATUS = {"allowed", "prohibited", "conditional"}
EXPECTED_HEADER = ["source_file", "category", "item", "status", "conditions", "fine_brl", "notes"]
STATE_SOURCE = "guidelines_state.html"
MUNICIPAL_SOURCE = "ordinance_municipal.html"


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Verify header strictly
            if reader.fieldnames is None:
                return None
            header = [h.strip() for h in reader.fieldnames]
            if header != EXPECTED_HEADER:
                return None
            rows = []
            for row in reader:
                # Ensure all expected keys exist
                if any(k not in row for k in EXPECTED_HEADER):
                    return None
                # Coerce to strings
                clean = {k: (row.get(k, "") if row.get(k, "") is not None else "") for k in EXPECTED_HEADER}
                rows.append(clean)
            return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        for obj in data:
            if not isinstance(obj, dict):
                return None
            for key in EXPECTED_HEADER:
                if key not in obj:
                    return None
        return data
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _normalize_fine_value(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        # render as integer string if whole number
        if float(val).is_integer():
            return str(int(val))
        return str(float(val))
    s = str(val).strip()
    if s == "":
        return ""
    # Try to parse numeric from string (allow commas and currency)
    s2 = re.sub(r"[^\d\.,-]", "", s)
    s2 = s2.replace(",", ".")
    try:
        num = float(s2)
        if num.is_integer():
            return str(int(num))
        return str(num)
    except Exception:
        # Not numeric, treat as empty to be safe in normalization
        return ""


def _row_signature_from_csv(row: Dict[str, str]) -> tuple:
    return (
        row["source_file"].strip(),
        _normalize_text(row["category"]),
        _normalize_text(row["item"]),
        _normalize_text(row["status"]),
        _normalize_text(row["conditions"]),
        _normalize_fine_value(row["fine_brl"]),
        _normalize_text(row["notes"]),
    )


def _row_signature_from_json(obj: Dict[str, Any]) -> tuple:
    return (
        str(obj["source_file"]).strip(),
        _normalize_text(str(obj["category"])),
        _normalize_text(str(obj["item"])),
        _normalize_text(str(obj["status"])),
        _normalize_text(str(obj["conditions"])),
        _normalize_fine_value(obj["fine_brl"]),
        _normalize_text(str(obj["notes"])),
    )


def _run_parse_script(workspace: Path) -> bool:
    script = workspace / "scripts" / "parse_rules.py"
    if not script.exists():
        return False
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            text=True,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _validate_rules_values(rows: List[Dict[str, str]]) -> bool:
    for row in rows:
        # source_file must be exact basenames
        src = row["source_file"].strip()
        if src not in {STATE_SOURCE, MUNICIPAL_SOURCE}:
            return False
        # category
        if row["category"] not in ALLOWED_CATEGORIES:
            return False
        # status
        if row["status"] not in ALLOWED_STATUS:
            return False
        # fine must be numeric or empty
        fine = row["fine_brl"]
        if fine.strip() != "":
            norm = _normalize_fine_value(fine)
            if norm == "":
                return False
    return True


def _rows_by_source_and_category(rows: List[Dict[str, str]], source: str, category: str) -> List[Dict[str, str]]:
    out = []
    for r in rows:
        if r["source_file"].strip() != source:
            continue
        if r["category"] != category:
            continue
        out.append(r)
    return out


def _contains_tokens(text: str, tokens: List[str]) -> bool:
    t = _normalize_text(text)
    return all(tok in t for tok in tokens)


def _any_field_contains_tokens(row: Dict[str, str], tokens: List[str]) -> bool:
    fields = [row.get("item", ""), row.get("conditions", ""), row.get("notes", "")]
    joined = " ".join(_normalize_text(f) for f in fields)
    return all(tok in joined for tok in tokens)


def _find_rule(rows: List[Dict[str, str]], source: str, category: str, status: Optional[str], tokens_all: List[str]) -> bool:
    for r in rows:
        if r["source_file"].strip() != source:
            continue
        if r["category"] != category:
            continue
        if status is not None and r["status"] != status:
            continue
        if _any_field_contains_tokens(r, tokens_all):
            return True
    return False


def _extract_bullet_lines(text: str) -> List[str]:
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*[-*•]\s+", line):
            lines.append(line.strip())
    return lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists": 0.0,
        "script_runs": 0.0,
        "rules_csv_schema": 0.0,
        "rules_json_schema": 0.0,
        "rules_csv_json_consistency": 0.0,
        "rules_values_normalized": 0.0,
        "rules_include_both_sources": 0.0,
        "fireworks_prohibited_both_sources": 0.0,
        "bonfires_conditional_auth_area_both_sources": 0.0,
        "decorations_plastic_confetti_glitter_prohibited_both_sources": 0.0,
        "waste_separate_bins_both_sources": 0.0,
        "fireworks_state_fine_500": 0.0,
        "waste_municipal_cleaning_fine_200": 0.0,
        "message_exists_and_length": 0.0,
        "message_bullets_three_and_required_points": 0.0,
        "message_tone_warm_respectful": 0.0,
    }

    # Check script existence
    script = workspace / "scripts" / "parse_rules.py"
    if script.exists() and script.is_file():
        scores["script_exists"] = 1.0

    # Try running the script to (re)generate outputs
    ran = _run_parse_script(workspace)
    if ran:
        scores["script_runs"] = 1.0

    # Load outputs
    output_csv = workspace / "output" / "rules.csv"
    output_json = workspace / "output" / "rules.json"
    rows_csv = _load_csv(output_csv) if output_csv.exists() else None
    rows_json = _load_json(output_json) if output_json.exists() else None

    if rows_csv is not None:
        scores["rules_csv_schema"] = 1.0
    if rows_json is not None:
        scores["rules_json_schema"] = 1.0

    # Consistency between CSV and JSON
    if rows_csv is not None and rows_json is not None:
        sig_csv = [_row_signature_from_csv(r) for r in rows_csv]
        sig_json = [_row_signature_from_json(o) for o in rows_json]
        if len(sig_csv) == len(sig_json) and set(sig_csv) == set(sig_json):
            scores["rules_csv_json_consistency"] = 1.0

    # Values normalized
    if rows_csv is not None and _validate_rules_values(rows_csv):
        scores["rules_values_normalized"] = 1.0

    # Ensure both sources are represented
    if rows_csv is not None:
        sources_present = {r["source_file"].strip() for r in rows_csv}
        if {STATE_SOURCE, MUNICIPAL_SOURCE}.issubset(sources_present):
            scores["rules_include_both_sources"] = 1.0

        # Fireworks prohibited in both sources
        fw_state = _find_rule(rows_csv, STATE_SOURCE, "fireworks", "prohibited", ["fogo"])
        fw_muni = _find_rule(rows_csv, MUNICIPAL_SOURCE, "fireworks", "prohibited", ["fogo"])
        if fw_state and fw_muni:
            scores["fireworks_prohibited_both_sources"] = 1.0

        # Bonfires conditional with authorization and designated area in both sources
        bf_state = _find_rule(rows_csv, STATE_SOURCE, "bonfires", "conditional", ["autoriza", "designa"])
        bf_muni = _find_rule(rows_csv, MUNICIPAL_SOURCE, "bonfires", "conditional", ["autoriza", "designa"])
        if bf_state and bf_muni:
            scores["bonfires_conditional_auth_area_both_sources"] = 1.0

        # Decorations: plastic confetti or glitter prohibited in both sources
        dec_state = _find_rule(rows_csv, STATE_SOURCE, "decorations", "prohibited", ["plast", "confete"]) or _find_rule(rows_csv, STATE_SOURCE, "decorations", "prohibited", ["plast", "glitter"])
        dec_muni = _find_rule(rows_csv, MUNICIPAL_SOURCE, "decorations", "prohibited", ["plast", "confete"]) or _find_rule(rows_csv, MUNICIPAL_SOURCE, "decorations", "prohibited", ["plast", "glitter"])
        if dec_state and dec_muni:
            scores["decorations_plastic_confetti_glitter_prohibited_both_sources"] = 1.0

        # Waste: separate bins in both sources (status not prohibited)
        ws_state_candidates = _rows_by_source_and_category(rows_csv, STATE_SOURCE, "waste")
        ws_muni_candidates = _rows_by_source_and_category(rows_csv, MUNICIPAL_SOURCE, "waste")

        def has_separate_bins(rows: List[Dict[str, str]]) -> bool:
            for r in rows:
                if r["status"] == "prohibited":
                    continue
                if _any_field_contains_tokens(r, ["separad"]) and (_any_field_contains_tokens(r, ["recicl"]) or _any_field_contains_tokens(r, ["orgânic"]) or _any_field_contains_tokens(r, ["organ"])):
                    return True
            return False

        if has_separate_bins(ws_state_candidates) and has_separate_bins(ws_muni_candidates):
            scores["waste_separate_bins_both_sources"] = 1.0

        # Fireworks state fine 500
        found_500 = False
        for r in rows_csv:
            if r["source_file"].strip() == STATE_SOURCE and r["category"] == "fireworks":
                fine = _normalize_fine_value(r["fine_brl"])
                if fine == "500":
                    found_500 = True
                    break
        if found_500:
            scores["fireworks_state_fine_500"] = 1.0

        # Waste municipal cleaning fine 200 (look for 'limp' token and fine 200)
        found_200 = False
        for r in rows_csv:
            if r["source_file"].strip() == MUNICIPAL_SOURCE and r["category"] == "waste":
                if _any_field_contains_tokens(r, ["limp"]):
                    fine = _normalize_fine_value(r["fine_brl"])
                    if fine == "200":
                        found_200 = True
                        break
        if found_200:
            scores["waste_municipal_cleaning_fine_200"] = 1.0

    # Message checks
    message_path = workspace / "output" / "message_pt.txt"
    msg = _read_text(message_path)
    if msg is not None:
        msg_len_ok = len(msg) <= 800
        bullets = _extract_bullet_lines(msg)
        if msg_len_ok:
            scores["message_exists_and_length"] = 1.0

        # Check three bullet points and required content
        required_ok = False
        if len(bullets) >= 3:
            # Normalize bullets
            nb = [_normalize_text(b) for b in bullets]

            def find_in_bullets(tokens: List[str]) -> bool:
                for b in nb:
                    if all(tok in b for tok in tokens):
                        return True
                return False

            # (a) fireworks prohibited
            cond_a = find_in_bullets(["fogo", "proibid"])
            # (b) bonfire only with authorization and designated area
            cond_b = find_in_bullets(["fogueira", "autoriza"]) and find_in_bullets(["fogueira", "área"]) or find_in_bullets(["fogueira", "designa"])
            # (c) avoid plastic confetti/glitter suggesting paper
            cond_c = (find_in_bullets(["confete", "plast"]) or find_in_bullets(["glitter", "plast"])) and ("papel" in " ".join(nb))
            if cond_a and cond_b and cond_c:
                required_ok = True
        if required_ok:
            scores["message_bullets_three_and_required_points"] = 1.0

        # Tone: warm/respectful heuristic
        msg_norm = _normalize_text(msg)
        warm_tokens = 0
        for tok in ["oi", "olá", "vizinhan", "vamos", "por favor", "obrigado", "obrigada"]:
            if tok in msg_norm:
                warm_tokens += 1
        if warm_tokens >= 2:
            scores["message_tone_warm_respectful"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()