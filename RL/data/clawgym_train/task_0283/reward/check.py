import json
import sys
import csv
import re
from pathlib import Path
from html.parser import HTMLParser


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_parse_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


class CastHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._in_thead = False
        self._in_tbody = False
        self._in_th = False
        self._in_td = False
        self._current_header = []
        self._current_rows = []
        self._current_row = []
        self._cell_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._current_header = []
            self._current_rows = []
            self._current_row = []
        elif self._in_table and tag == "thead":
            self._in_thead = True
        elif self._in_table and tag == "tbody":
            self._in_tbody = True
        elif self._in_table and self._in_thead and tag == "th":
            self._in_th = True
            self._cell_text = []
        elif self._in_table and self._in_tbody and tag == "td":
            self._in_td = True
            self._cell_text = []
        elif self._in_table and self._in_tbody and tag == "tr":
            self._current_row = []

    def handle_endtag(self, tag):
        if self._in_table and self._in_thead and tag == "th":
            self._in_th = False
            text = "".join(self._cell_text).strip()
            self._current_header.append(text)
            self._cell_text = []
        elif self._in_table and self._in_tbody and tag == "td":
            self._in_td = False
            text = "".join(self._cell_text).strip()
            self._current_row.append(text)
            self._cell_text = []
        elif self._in_table and self._in_tbody and tag == "tr":
            if self._current_row:
                self._current_rows.append(self._current_row)
            self._current_row = []
        elif self._in_table and tag == "thead":
            self._in_thead = False
        elif self._in_table and tag == "tbody":
            self._in_tbody = False
        elif tag == "table":
            self.tables.append({
                "header": self._current_header[:],
                "rows": [r[:] for r in self._current_rows],
            })
            self._in_table = False
            self._in_thead = False
            self._in_tbody = False
            self._in_th = False
            self._in_td = False
            self._current_header = []
            self._current_rows = []
            self._current_row = []
            self._cell_text = []

    def handle_data(self, data):
        if (self._in_th or self._in_td) and self._in_table:
            self._cell_text.append(data)


def parse_cast_html(path: Path):
    text = safe_read_text(path)
    if not text:
        return None
    parser = CastHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    for t in parser.tables:
        header = [h.strip() for h in t.get("header", [])]
        if len(header) >= 2 and header[0] == "Character" and header[1] == "Actor":
            rows = []
            for r in t.get("rows", []):
                if len(r) >= 2:
                    rows.append((r[0].strip(), r[1].strip()))
            return rows
    for t in parser.tables:
        rows = []
        ok = True
        for r in t.get("rows", []):
            if len(r) >= 2:
                rows.append((r[0].strip(), r[1].strip()))
            else:
                ok = False
                break
        if ok and rows:
            return rows
    return None


def compute_analysis_from_inputs(workspace: Path):
    input_dir = workspace / "input"
    orig_cast_path = input_dir / "original_cast.html"
    reboot_cast_path = input_dir / "reboot_cast.html"
    orig_eps_path = input_dir / "original_episodes.csv"
    reboot_eps_path = input_dir / "reboot_episodes.csv"

    orig_cast = parse_cast_html(orig_cast_path)
    reboot_cast = parse_cast_html(reboot_cast_path)

    orig_eps_rows = safe_parse_csv(orig_eps_path)
    reboot_eps_rows = safe_parse_csv(reboot_eps_path)

    if orig_cast is None or reboot_cast is None or orig_eps_rows is None or reboot_eps_rows is None:
        return None

    def extract_runtime_and_titles(rows):
        runtimes = []
        titles = []
        for r in rows:
            try:
                title = r.get("title", "").strip()
                rt = r.get("runtime_min", "").strip()
                if title == "" or rt == "":
                    return None, None
                titles.append(title)
                runtime_val = float(rt)
                runtimes.append(runtime_val)
            except Exception:
                return None, None
        if len(runtimes) == 0:
            return None, None
        avg = sum(runtimes) / len(runtimes)
        return {"count": len(runtimes), "avg": avg, "titles": titles}, None

    orig_info, _ = extract_runtime_and_titles(orig_eps_rows)
    reboot_info, _ = extract_runtime_and_titles(reboot_eps_rows)
    if orig_info is None or reboot_info is None:
        return None

    orig_characters = [c for c, _ in orig_cast]
    reboot_characters = [c for c, _ in reboot_cast]
    shared_characters = sorted(set(orig_characters).intersection(set(reboot_characters)))
    exclusive_original = sorted(set(orig_characters) - set(reboot_characters))
    exclusive_reboot = sorted(set(reboot_characters) - set(orig_characters))

    orig_map = {c: a for c, a in orig_cast}
    reboot_map = {c: a for c, a in reboot_cast}
    actor_changes = []
    for ch in sorted(set(orig_map.keys()).intersection(set(reboot_map.keys()))):
        if orig_map.get(ch) != reboot_map.get(ch):
            actor_changes.append({"character": ch, "original_actor": orig_map.get(ch, ""), "reboot_actor": reboot_map.get(ch, "")})

    shared_titles = sorted(set(orig_info["titles"]).intersection(set(reboot_info["titles"])))

    result = {
        "original_episode_count": orig_info["count"],
        "reboot_episode_count": reboot_info["count"],
        "original_avg_runtime_min": orig_info["avg"],
        "reboot_avg_runtime_min": reboot_info["avg"],
        "shared_episode_titles": shared_titles,
        "original_characters": orig_characters,
        "reboot_characters": reboot_characters,
        "shared_characters": shared_characters,
        "exclusive_original_characters": exclusive_original,
        "exclusive_reboot_characters": exclusive_reboot,
        "actor_changes": actor_changes,
    }
    return result


def almost_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def ensure_list_of_strings(x):
    if not isinstance(x, list):
        return False
    for v in x:
        if not isinstance(v, str):
            return False
    return True


def load_review_bullets(review_text: str, header_title: str = "## What the reboot changes"):
    lines = review_text.splitlines()
    bullets = []
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header_title:
            start_idx = i
            break
    if start_idx is None:
        return []
    for j in range(start_idx + 1, len(lines)):
        line = lines[j].rstrip("\n")
        if line.strip() == "":
            continue
        if line.strip().startswith("- "):
            bullets.append(line.strip())
        else:
            if line.strip().startswith("#"):
                break
            if bullets:
                break
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "analysis_json_schema_valid": 0.0,
        "episode_counts_correct": 0.0,
        "average_runtimes_correct": 0.0,
        "shared_episode_titles_correct": 0.0,
        "original_reboot_characters_correct_sets": 0.0,
        "shared_and_exclusive_characters_correct": 0.0,
        "actor_changes_correct": 0.0,
        "review_placeholders_resolved": 0.0,
        "review_pacing_cites_avgs": 0.0,
        "review_character_continuity_mentions_shared_and_actor_swaps": 0.0,
        "review_bullet_list_data_backed": 0.0,
        "review_final_data_check_matches": 0.0,
        "entrypoint_script_present": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"
    scripts_dir = workspace / "scripts"
    analysis_path = output_dir / "analysis.json"
    review_path = output_dir / "review.md"
    compare_script_path = scripts_dir / "compare.sh"

    expected = compute_analysis_from_inputs(workspace)

    analysis = safe_load_json(analysis_path)
    required_keys = [
        "original_episode_count",
        "reboot_episode_count",
        "original_avg_runtime_min",
        "reboot_avg_runtime_min",
        "shared_episode_titles",
        "original_characters",
        "reboot_characters",
        "shared_characters",
        "exclusive_original_characters",
        "exclusive_reboot_characters",
        "actor_changes",
    ]
    schema_ok = False
    if isinstance(analysis, dict):
        key_ok = all(k in analysis for k in required_keys)
        types_ok = True
        if key_ok:
            for k in ["original_episode_count", "reboot_episode_count", "original_avg_runtime_min", "reboot_avg_runtime_min"]:
                v = analysis.get(k, None)
                if not isinstance(v, (int, float)):
                    types_ok = False
                    break
            for k in ["shared_episode_titles", "original_characters", "reboot_characters", "shared_characters", "exclusive_original_characters", "exclusive_reboot_characters"]:
                v = analysis.get(k, None)
                if not ensure_list_of_strings(v):
                    types_ok = False
                    break
            ac = analysis.get("actor_changes", None)
            if not isinstance(ac, list):
                types_ok = False
            else:
                for item in ac:
                    if not (isinstance(item, dict) and all(isinstance(item.get(x, None), str) for x in ["character", "original_actor", "reboot_actor"])):
                        types_ok = False
                        break
        schema_ok = key_ok and types_ok
    if schema_ok:
        scores["analysis_json_schema_valid"] = 1.0

    if expected is not None and isinstance(analysis, dict):
        ep_counts_ok = (
            expected["original_episode_count"] == analysis.get("original_episode_count") and
            expected["reboot_episode_count"] == analysis.get("reboot_episode_count")
        )
        scores["episode_counts_correct"] = 1.0 if ep_counts_ok else 0.0

        avg_ok = (
            almost_equal(expected["original_avg_runtime_min"], analysis.get("original_avg_runtime_min")) and
            almost_equal(expected["reboot_avg_runtime_min"], analysis.get("reboot_avg_runtime_min"))
        )
        scores["average_runtimes_correct"] = 1.0 if avg_ok else 0.0

        shared_titles_ok = set(expected["shared_episode_titles"]) == set(analysis.get("shared_episode_titles", []))
        scores["shared_episode_titles_correct"] = 1.0 if shared_titles_ok else 0.0

        orig_chars_ok = set(expected["original_characters"]) == set(analysis.get("original_characters", []))
        reboot_chars_ok = set(expected["reboot_characters"]) == set(analysis.get("reboot_characters", []))
        scores["original_reboot_characters_correct_sets"] = 1.0 if (orig_chars_ok and reboot_chars_ok) else 0.0

        shared_chars_ok = set(expected["shared_characters"]) == set(analysis.get("shared_characters", []))
        excl_orig_ok = set(expected["exclusive_original_characters"]) == set(analysis.get("exclusive_original_characters", []))
        excl_reboot_ok = set(expected["exclusive_reboot_characters"]) == set(analysis.get("exclusive_reboot_characters", []))
        scores["shared_and_exclusive_characters_correct"] = 1.0 if (shared_chars_ok and excl_orig_ok and excl_reboot_ok) else 0.0

        def normalize_changes(lst):
            s = set()
            for item in lst:
                try:
                    s.add((item["character"], item["original_actor"], item["reboot_actor"]))
                except Exception:
                    return None
            return s

        expected_ac = normalize_changes(expected["actor_changes"])
        analysis_ac = normalize_changes(analysis.get("actor_changes", [])) if isinstance(analysis.get("actor_changes", None), list) else None
        ac_ok = (expected_ac is not None) and (analysis_ac is not None) and (expected_ac == analysis_ac)
        scores["actor_changes_correct"] = 1.0 if ac_ok else 0.0

    review_text = safe_read_text(review_path)
    if review_text:
        placeholders = ["[VERIFY-PACING]", "[VERIFY-CHARACTERS]", "[VERIFY-COUNT]", "[FILL]"]
        if not any(p in review_text for p in placeholders):
            scores["review_placeholders_resolved"] = 1.0

        if isinstance(analysis, dict):
            a_orig = analysis.get("original_avg_runtime_min")
            a_reb = analysis.get("reboot_avg_runtime_min")
            if isinstance(a_orig, (int, float)) and isinstance(a_reb, (int, float)):
                lines = review_text.splitlines()
                last_non_empty = None
                for idx in range(len(lines) - 1, -1):
                    if lines[idx].strip() != "":
                        last_non_empty = idx
                        break
                content_to_search = "\n".join(lines[:last_non_empty]) if last_non_empty is not None else review_text

                def number_patterns(val):
                    s = str(val)
                    pats = {re.escape(s)}
                    try:
                        f = float(val)
                        if abs(f - int(f)) < 1e-9:
                            pats.add(r"\b" + str(int(f)) + r"\b")
                    except Exception:
                        pass
                    return pats

                pats_orig = number_patterns(a_orig)
                pats_reb = number_patterns(a_reb)

                found_orig = any(re.search(p, content_to_search) for p in pats_orig)
                found_reb = any(re.search(p, content_to_search) for p in pats_reb)

                if found_orig and found_reb:
                    scores["review_pacing_cites_avgs"] = 1.0

        if isinstance(analysis, dict) and expected is not None:
            shared_count = len(expected["shared_characters"])
            has_shared_num = bool(re.search(r"\b" + re.escape(str(shared_count)) + r"\b", review_text))
            actor_changes = analysis.get("actor_changes", [])
            swaps_mentioned = 0
            for item in actor_changes:
                oa = item.get("original_actor", "")
                ra = item.get("reboot_actor", "")
                ch = item.get("character", "")
                both_actors_in_text = (oa and oa in review_text) and (ra and ra in review_text)
                cooccur_line = False
                for ln in review_text.splitlines():
                    if ch and ch in ln and ((oa and oa in ln) or (ra and ra in ln)):
                        cooccur_line = True
                        break
                if both_actors_in_text or cooccur_line:
                    swaps_mentioned += 1
            if has_shared_num and swaps_mentioned >= 2:
                scores["review_character_continuity_mentions_shared_and_actor_swaps"] = 1.0

        bullets = load_review_bullets(review_text, "## What the reboot changes")
        bullets_ok = False
        if bullets and len(bullets) >= 3 and all("[FILL]" not in b for b in bullets):
            known_tokens = set()
            data_source = expected if expected is not None else analysis if isinstance(analysis, dict) else None
            if data_source:
                for nm in data_source.get("original_characters", []):
                    known_tokens.add(nm)
                for nm in data_source.get("reboot_characters", []):
                    known_tokens.add(nm)
                for nm in data_source.get("shared_episode_titles", []):
                    known_tokens.add(nm)
                for item in data_source.get("actor_changes", []):
                    if isinstance(item, dict):
                        for k in ["character", "original_actor", "reboot_actor"]:
                            val = item.get(k, "")
                            if isinstance(val, str) and val:
                                known_tokens.add(val)
                for nm in data_source.get("exclusive_reboot_characters", []):
                    known_tokens.add(nm)
            if data_source:
                each_bullet_ok = True
                for b in bullets:
                    contains_token = any(tok in b for tok in known_tokens)
                    if not contains_token:
                        each_bullet_ok = False
                        break
                bullets_ok = each_bullet_ok
        scores["review_bullet_list_data_backed"] = 1.0 if bullets_ok else 0.0

        if isinstance(analysis, dict):
            X = analysis.get("original_episode_count")
            Y = analysis.get("reboot_episode_count")
            A = analysis.get("original_avg_runtime_min")
            B = analysis.get("reboot_avg_runtime_min")
            if all(isinstance(v, (int, float)) for v in [X, Y, A, B]):
                expected_line = f"Data check: original episodes={X}, reboot episodes={Y}; avg runtime: original={A} min, reboot={B} min."
                lines = [ln.rstrip("\n") for ln in review_text.splitlines()]
                last_line = ""
                for idx in range(len(lines) - 1, -1, -1):
                    if lines[idx].strip() != "":
                        last_line = lines[idx].strip()
                        break
                if last_line == expected_line:
                    scores["review_final_data_check_matches"] = 1.0

    script_text = safe_read_text(compare_script_path)
    if script_text:
        has_shebang = script_text.lstrip().startswith("#!") or "sh" in compare_script_path.suffix
        refers_input = "input/" in script_text
        refers_output = "output/" in script_text
        no_network = ("http://" not in script_text and "https://" not in script_text and "curl " not in script_text and "wget " not in script_text)
        if has_shebang and refers_input and refers_output and no_network:
            scores["entrypoint_script_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()