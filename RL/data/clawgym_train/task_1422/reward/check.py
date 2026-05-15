import os
import sys
import json
import csv
import base64
import hashlib
from urllib.parse import unquote

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_csv_with_header(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = [row for row in reader]
        return header, rows, None
    except Exception as e:
        return None, None, str(e)

def is_lower_hex(s):
    return all(c in "0123456789abcdef" for c in s)

def add_b64_padding(s):
    # Return string padded to length multiple of 4
    rem = len(s) % 4
    if rem == 0:
        return s
    return s + ("=" * (4 - rem))

def parse_simple_yaml_ints(text):
    # Very small YAML subset parser: lines "key: value"
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # remove possible quotes
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        try:
            ival = int(val)
        except ValueError:
            return None
        data[key] = ival
    # require exactly the three keys
    return data

def compute_digests(plaintext):
    b = plaintext.encode("utf-8")
    return {
        "md5": hashlib.md5(b).hexdigest(),
        "sha1": hashlib.sha1(b).hexdigest(),
        "sha256": hashlib.sha256(b).hexdigest(),
        "sha512": hashlib.sha512(b).hexdigest(),
    }

def last_json_output(payload):
    print(json.dumps(payload, ensure_ascii=False))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "decoded_json_exists": False,
        "decoded_json_valid": False,
        "decoded_schema_valid": False,
        "decoded_ids_complete": False,
        "decoded_matches_expected": False,

        "validation_csv_exists": False,
        "validation_header_correct": False,
        "validation_rows_complete": False,
        "validation_consistent_with_decoded": False,

        "digests_csv_exists": False,
        "digests_header_correct": False,
        "digests_values_correct": False,

        "reencoded_json_exists": False,
        "reencoded_json_valid": False,
        "reencoded_values_correct": False,

        "manifest_yaml_exists": False,
        "manifest_keys_valid": False,
        "manifest_counts_match": False,

        "notes_md_exists": False,
        "notes_word_count_ok": False,
        "notes_keywords_present": False,
        "notes_mentions_auto_ids": False,
    }

    # Load inputs for reference
    encodings_path = os.path.join(input_dir, "encodings.json")
    expected_path = os.path.join(input_dir, "expected_plaintexts.json")
    encodings, enc_err = load_json(encodings_path)
    expected_map, exp_err = load_json(expected_path)
    if encodings is None:
        # If input is missing, we cannot award positives anyway; still compute baseline 0
        total_ids = set()
        auto_ids = set()
    else:
        try:
            total_ids = {int(item["id"]) for item in encodings}
            auto_ids = {int(item["id"]) for item in encodings if str(item.get("encoding", "")).lower() == "auto"}
        except Exception:
            total_ids = set()
            auto_ids = set()
    # decoded.json checks
    decoded_path = os.path.join(output_dir, "decoded.json")
    if os.path.isfile(decoded_path):
        checks["decoded_json_exists"] = True
        decoded, dec_err = load_json(decoded_path)
        if decoded is not None and isinstance(decoded, list):
            checks["decoded_json_valid"] = True
            # schema validation
            schema_ok = True
            ids = []
            for el in decoded:
                if not isinstance(el, dict):
                    schema_ok = False
                    break
                if "id" not in el or "plaintext" not in el:
                    schema_ok = False
                    break
                if not isinstance(el["id"], int):
                    schema_ok = False
                    break
                if not isinstance(el["plaintext"], str):
                    schema_ok = False
                    break
                ids.append(el["id"])
            if schema_ok:
                checks["decoded_schema_valid"] = True
                # ids coverage
                if encodings is not None:
                    # exactly one entry per id
                    id_set = set(ids)
                    if id_set == total_ids and len(ids) == len(total_ids):
                        checks["decoded_ids_complete"] = True
                # matches expected
                if expected_map is not None and checks["decoded_ids_complete"]:
                    all_match = True
                    for el in decoded:
                        _id = el["id"]
                        actual = el["plaintext"]
                        exp = expected_map.get(str(_id))
                        if exp is None:
                            all_match = False
                            break
                        if actual != exp:
                            all_match = False
                    if all_match:
                        checks["decoded_matches_expected"] = True
        # else invalid json; leave flags false

    # validation.csv checks
    validation_path = os.path.join(output_dir, "validation.csv")
    decoded_for_consistency = None
    if os.path.isfile(validation_path):
        checks["validation_csv_exists"] = True
        header, rows, val_err = parse_csv_with_header(validation_path)
        if header is not None and header == ["id", "expected", "actual", "match"]:
            checks["validation_header_correct"] = True
            # rows completeness: one row per id
            try:
                row_ids = [int(r["id"]) for r in rows]
                if set(row_ids) == total_ids and len(row_ids) == len(total_ids):
                    checks["validation_rows_complete"] = True
            except Exception:
                pass

            # consistency: match accuracy and consistency with decoded.json
            # Load decoded.json content if available
            if checks["decoded_json_valid"]:
                decoded_for_consistency = {}
                decoded, _ = load_json(decoded_path)
                for el in decoded:
                    decoded_for_consistency[el["id"]] = el["plaintext"]

            consistent = True
            if expected_map is None:
                consistent = False
            else:
                for r in rows:
                    try:
                        rid = int(r["id"])
                        expected = expected_map.get(str(rid))
                        actual = r["actual"]
                        match_val = str(r["match"]).strip().lower()
                        # ensure boolean truth
                        should_match = (expected == actual)
                        if match_val not in ("true", "false"):
                            consistent = False
                            break
                        if (match_val == "true") != should_match:
                            consistent = False
                            break
                        # check 'expected' column equals expected_map
                        if r["expected"] != (expected if expected is not None else ""):
                            # If expected is None (missing id), still inconsistent
                            consistent = False
                            break
                        # if decoded.json available, ensure actual equals decoded plaintext
                        if decoded_for_consistency is not None:
                            if rid not in decoded_for_consistency or decoded_for_consistency[rid] != actual:
                                consistent = False
                                break
                    except Exception:
                        consistent = False
                        break
            if consistent:
                checks["validation_consistent_with_decoded"] = True

    # digests.csv checks
    digests_path = os.path.join(output_dir, "digests.csv")
    if os.path.isfile(digests_path):
        checks["digests_csv_exists"] = True
        header, rows, dig_err = parse_csv_with_header(digests_path)
        if header is not None and header == ["id", "md5", "sha1", "sha256", "sha512"]:
            checks["digests_header_correct"] = True
            # verify per-id digest correctness against decoded.json
            all_ok = True
            # Need decoded.json
            if not checks["decoded_schema_valid"]:
                all_ok = False
            else:
                decoded, _ = load_json(decoded_path)
                plain_map = {el["id"]: el["plaintext"] for el in decoded}
                # rows per id
                try:
                    row_ids = [int(r["id"]) for r in rows]
                except Exception:
                    all_ok = False
                    row_ids = []
                if set(row_ids) != set(plain_map.keys()) or len(row_ids) != len(plain_map):
                    all_ok = False
                else:
                    for r in rows:
                        try:
                            rid = int(r["id"])
                            pt = plain_map[rid]
                            dg = compute_digests(pt)
                            # hex lower-case check and equality
                            for k in ["md5", "sha1", "sha256", "sha512"]:
                                val = r[k]
                                if not isinstance(val, str) or not is_lower_hex(val):
                                    all_ok = False
                                    break
                                if val != dg[k]:
                                    all_ok = False
                                    break
                            if not all_ok:
                                break
                        except Exception:
                            all_ok = False
                            break
            if all_ok:
                checks["digests_values_correct"] = True

    # reencoded.json checks
    reenc_path = os.path.join(output_dir, "reencoded.json")
    if os.path.isfile(reenc_path):
        checks["reencoded_json_exists"] = True
        reenc, re_err = load_json(reenc_path)
        if reenc is not None and isinstance(reenc, list):
            checks["reencoded_json_valid"] = True
            # verify values decode back to plaintext and format constraints
            values_ok = True
            # Need decoded.json map
            if not checks["decoded_schema_valid"]:
                values_ok = False
            else:
                decoded, _ = load_json(decoded_path)
                plain_map = {el["id"]: el["plaintext"] for el in decoded}
                # ensure one per id
                try:
                    ids = [int(el.get("id")) for el in reenc]
                except Exception:
                    ids = []
                if set(ids) != set(plain_map.keys()) or len(ids) != len(plain_map):
                    values_ok = False
                else:
                    for el in reenc:
                        try:
                            rid = int(el["id"])
                            b64u = el["base64url"]
                            hx = el["hex"]
                            urlenc = el["url"]
                            a85 = el["ascii85"]
                            pt = plain_map[rid]

                            # base64url: no '=', no '+' '/', url-safe
                            if any(ch in b64u for ch in "+/="):
                                values_ok = False
                                break
                            # Decode base64url with padding added
                            try:
                                decoded_bytes = base64.urlsafe_b64decode(add_b64_padding(b64u))
                                if decoded_bytes.decode("utf-8") != pt:
                                    values_ok = False
                                    break
                            except Exception:
                                values_ok = False
                                break

                            # hex: lowercase and decodes
                            if not is_lower_hex(hx):
                                values_ok = False
                                break
                            try:
                                if bytes.fromhex(hx).decode("utf-8") != pt:
                                    values_ok = False
                                    break
                            except Exception:
                                values_ok = False
                                break

                            # url: no '+', no spaces; decode equals pt
                            if "+" in urlenc or " " in urlenc:
                                values_ok = False
                                break
                            try:
                                if unquote(urlenc) != pt:
                                    values_ok = False
                                    break
                            except Exception:
                                values_ok = False
                                break

                            # ascii85: no <~ ~> delimiters, decode equals pt
                            if "<~" in a85 or "~>" in a85:
                                values_ok = False
                                break
                            try:
                                dec_bytes = base64.a85decode(a85)
                                if dec_bytes.decode("utf-8") != pt:
                                    values_ok = False
                                    break
                            except Exception:
                                values_ok = False
                                break
                        except Exception:
                            values_ok = False
                            break
            if values_ok:
                checks["reencoded_values_correct"] = True

    # manifest.yaml checks (simple YAML)
    manifest_path = os.path.join(output_dir, "manifest.yaml")
    if os.path.isfile(manifest_path):
        checks["manifest_yaml_exists"] = True
        text, man_err = read_text(manifest_path)
        if text is not None:
            data = parse_simple_yaml_ints(text)
            if isinstance(data, dict) and set(data.keys()) == {"total_messages", "auto_detected_count", "mismatches_count"}:
                checks["manifest_keys_valid"] = True
                # counts match
                counts_ok = True
                # total_messages equals length of encodings.json
                if encodings is None:
                    counts_ok = False
                else:
                    if data.get("total_messages") != len(encodings):
                        counts_ok = False
                # auto_detected_count equals count where encoding == "auto"
                if counts_ok:
                    if data.get("auto_detected_count") != len(auto_ids):
                        counts_ok = False
                # mismatches_count equals count of match == false in validation.csv
                if counts_ok:
                    if not checks["validation_csv_exists"]:
                        counts_ok = False
                    else:
                        _, rows, _ = parse_csv_with_header(validation_path)
                        mismatches = 0
                        for r in rows:
                            if str(r["match"]).strip().lower() == "false":
                                mismatches += 1
                        if data.get("mismatches_count") != mismatches:
                            counts_ok = False
                if counts_ok:
                    checks["manifest_counts_match"] = True

    # notes.md checks (heuristic)
    notes_path = os.path.join(output_dir, "notes.md")
    if os.path.isfile(notes_path):
        checks["notes_md_exists"] = True
        text, n_err = read_text(notes_path)
        if text is not None:
            # word count
            words = [w for w in text.split() if w.strip()]
            if len(words) >= 200:
                checks["notes_word_count_ok"] = True
            # keywords presence
            kw_ok = all(k in text for k in ["base64url", "base32", "padding", "ROT13"])
            if kw_ok:
                checks["notes_keywords_present"] = True
            # mention ids for auto-detected rows
            ids_ok = True
            for aid in sorted(list(auto_ids)):
                if str(aid) not in text:
                    ids_ok = False
                    break
            if auto_ids and ids_ok:
                checks["notes_mentions_auto_ids"] = True
            elif not auto_ids:
                # If there are no auto items, require presence is vacuously true? To avoid vacuous pass, keep it False unless there are auto_ids.
                checks["notes_mentions_auto_ids"] = False

    # Calculate reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Enforce no-op baseline: if output dir missing or empty, reward must be 0.0
    if not os.path.isdir(output_dir) or len([name for name in os.listdir(output_dir) if not name.startswith(".")]) == 0:
        reward = 0.0
        # leave checks as-is (mostly False)

    # Print result JSON (single line, reward first)
    result = {"reward": float(reward)}
    result.update(checks)
    last_json_output(result)

if __name__ == "__main__":
    main()