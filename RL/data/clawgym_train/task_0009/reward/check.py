import json
import csv
import sys
import re
from html.parser import HTMLParser
from pathlib import Path

# Helper: safe text read
def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

# Helper: safe JSON load
def _safe_load_json(path: Path):
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None

# Helper: safe CSV read (returns list of dicts and header)
def _safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                return reader.fieldnames, rows
        except Exception:
            return None, None

class CommentHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_comment_div = False
        self.current_attrs = {}
        self.current_text = []
        self.records = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "div":
            attrs_dict = dict(attrs)
            if attrs_dict.get("class") == "comment":
                self.in_comment_div = True
                self.current_attrs = {
                    "data-id": attrs_dict.get("data-id"),
                    "data-team": attrs_dict.get("data-team"),
                    "data-language": attrs_dict.get("data-language"),
                }
                self.current_text = []

    def handle_endtag(self, tag):
        if tag.lower() == "div" and self.in_comment_div:
            text = "".join(self.current_text).strip()
            rec = {
                "id": self.current_attrs.get("data-id"),
                "team": self.current_attrs.get("data-team"),
                "language": self.current_attrs.get("data-language"),
                "text": text,
            }
            # Only add if id and team present
            if rec["id"] is not None and rec["team"] is not None and rec["language"] is not None:
                self.records.append(rec)
            self.in_comment_div = False
            self.current_attrs = {}
            self.current_text = []

    def handle_data(self, data):
        if self.in_comment_div:
            self.current_text.append(data)

def _parse_comments_html(path: Path):
    txt = _safe_read_text(path)
    if txt is None:
        return None
    parser = CommentHTMLParser()
    try:
        parser.feed(txt)
    except Exception:
        return None
    # Build dict by id
    recs = {}
    for rec in parser.records:
        if rec["id"] not in recs:
            recs[rec["id"]] = rec
    return recs

def _compute_keywords(text: str, keywords: list):
    found = set()
    if text is None:
        return found
    low = text.lower()
    for kw in keywords:
        if kw in low:
            found.add(kw)
    return found

def _split_semicolon_list(s: str):
    if s is None:
        return []
    parts = [p.strip() for p in s.split(";")]
    parts = [p for p in parts if p != ""]
    return parts

def _is_mostly_ascii_letters(s: str):
    if not s:
        return False
    letters = re.findall(r"[A-Za-z]", s)
    return len(letters) >= 1

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Keywords per specification
    english_keywords = [
        "sponsor",
        "naming rights",
        "betting",
        "ticket prices",
        "TV deal",
        "paywall",
        "owner",
        "corporate",
        "brand",
        "stadium rebrand",
        "merch prices",
    ]
    spanish_keywords = [
        "patrocinador",
        "derechos de nombre",
        "apuestas",
        "precios de entradas",
        "acuerdo de TV",
        "muro de pago",
        "propietario",
        "corporativo",
        "marca",
        "rebrand del estadio",
        "precios de mercancía",
    ]
    all_keywords = [kw.lower() for kw in english_keywords + spanish_keywords]

    # Load inputs
    html_path = workspace / "input" / "fan_comments.html"
    sponsors_path = workspace / "input" / "sponsors.csv"
    teams_path = workspace / "input" / "teams.json"

    comments = _parse_comments_html(html_path) if html_path.exists() else None
    sponsors_header, sponsors_rows = _safe_read_csv(sponsors_path) if sponsors_path.exists() else (None, None)
    teams_json = _safe_load_json(teams_path) if teams_path.exists() else None

    sponsors_map = {}
    if sponsors_rows is not None:
        for r in sponsors_rows:
            team = (r.get("team") or "").strip()
            sponsor = (r.get("sponsor") or "").strip()
            if team:
                sponsors_map[team] = sponsor

    target_teams = []
    if teams_json and isinstance(teams_json, dict) and isinstance(teams_json.get("target_teams"), list):
        target_teams = teams_json.get("target_teams")

    # Load outputs
    quotes_csv_path = workspace / "output" / "quotes_ranked.csv"
    top5_md_path = workspace / "output" / "top5_excerpts.md"
    quotes_header, quotes_rows = _safe_read_csv(quotes_csv_path) if quotes_csv_path.exists() else (None, None)

    scores = {
        "quotes_ranked_exists_and_header": 0.0,
        "quotes_ranked_ids_expected": 0.0,
        "quotes_ranked_team_sponsor_crosscheck": 0.0,
        "quotes_ranked_language_and_original_text": 0.0,
        "relevance_and_keywords_correct": 0.0,
        "english_translation_identity": 0.0,
        "non_english_translation_nonempty": 0.0,
        "quotes_ranked_sorting": 0.0,
        "top5_structure": 0.0,
        "top5_matches_csv": 0.0,
        "top5_resonates_keyword_reference": 0.0,
    }

    required_header = [
        "id",
        "team",
        "sponsor",
        "original_language",
        "original_quote",
        "translated_quote",
        "relevance_score",
        "keywords_found",
    ]

    # Check quotes_ranked header
    if quotes_rows is not None and quotes_header is not None:
        if quotes_header == required_header:
            scores["quotes_ranked_exists_and_header"] = 1.0

    # If we have inputs and quotes rows, compute expected IDs and verify completeness
    expected_ids = set()
    if comments is not None and target_teams:
        for cid, rec in comments.items():
            if rec["team"] in target_teams:
                orig_kw = _compute_keywords(rec["text"], all_keywords)
                if len(orig_kw) > 0:
                    expected_ids.add(cid)

    if quotes_rows is not None and comments is not None and target_teams:
        output_ids = { (r.get("id") or "").strip() for r in quotes_rows }
        # Ensure expected equals actual
        if output_ids == expected_ids and len(expected_ids) > 0:
            scores["quotes_ranked_ids_expected"] = 1.0
        elif expected_ids == set() and output_ids == set():
            # If no expected (edge case), consider pass
            scores["quotes_ranked_ids_expected"] = 1.0
        else:
            scores["quotes_ranked_ids_expected"] = 0.0

    # Team and sponsor cross-check per row
    if quotes_rows is not None and comments is not None and target_teams and sponsors_map:
        total = len(quotes_rows)
        if total > 0:
            passed = 0
            for r in quotes_rows:
                cid = (r.get("id") or "").strip()
                team = (r.get("team") or "").strip()
                sponsor = (r.get("sponsor") or "").strip()
                rec = comments.get(cid)
                if rec is None:
                    continue
                cond_team = (team == rec["team"]) and (team in target_teams)
                cond_sponsor = sponsors_map.get(team, None) == sponsor
                if cond_team and cond_sponsor:
                    passed += 1
            scores["quotes_ranked_team_sponsor_crosscheck"] = passed / total

    # Language and original text per row
    if quotes_rows is not None and comments is not None:
        total = len(quotes_rows)
        if total > 0:
            passed = 0
            for r in quotes_rows:
                cid = (r.get("id") or "").strip()
                orig_lang = (r.get("original_language") or "").strip()
                orig_quote = (r.get("original_quote") or "").strip()
                rec = comments.get(cid)
                if rec is None:
                    continue
                if orig_lang == (rec["language"] or "") and orig_quote == (rec["text"] or ""):
                    passed += 1
            scores["quotes_ranked_language_and_original_text"] = passed / total

    # Relevance and keywords correctness
    if quotes_rows is not None and comments is not None:
        total = len(quotes_rows)
        if total > 0:
            passed = 0
            for r in quotes_rows:
                cid = (r.get("id") or "").strip()
                rec = comments.get(cid)
                if rec is None:
                    continue
                orig_text = rec["text"] or ""
                translated = (r.get("translated_quote") or "")
                found_list = _split_semicolon_list(r.get("keywords_found") or "")
                # Normalize to lowercase
                found_set = {kw.lower() for kw in found_list}
                # All found keywords must be from allowed set
                if not found_set.issubset(set(all_keywords)):
                    continue
                # Compute matched keywords in either original or translated
                matched = _compute_keywords(orig_text, all_keywords) | _compute_keywords(translated, all_keywords)
                # We expect keywords_found to equal matched unique keywords
                if found_set != matched:
                    continue
                # relevance_score must equal count of unique keywords
                try:
                    rs = int(str(r.get("relevance_score") or "0"))
                except Exception:
                    continue
                if rs != len(matched):
                    continue
                passed += 1
            scores["relevance_and_keywords_correct"] = passed / total

    # Translation behavior checks
    if quotes_rows is not None and comments is not None:
        en_rows = 0
        en_pass = 0
        non_en_rows = 0
        non_en_pass = 0
        for r in quotes_rows:
            cid = (r.get("id") or "").strip()
            rec = comments.get(cid)
            if rec is None:
                continue
            orig_lang = rec["language"] or ""
            orig_quote = rec["text"] or ""
            translated = (r.get("translated_quote") or "")
            if orig_lang == "en":
                en_rows += 1
                if translated == orig_quote:
                    en_pass += 1
            else:
                non_en_rows += 1
                # Must be non-empty, not identical, and plausibly English (contains ASCII letters)
                if translated and translated != orig_quote and _is_mostly_ascii_letters(translated):
                    non_en_pass += 1
        scores["english_translation_identity"] = 1.0 if en_rows == 0 else (en_pass / en_rows if en_rows > 0 else 0.0)
        scores["non_english_translation_nonempty"] = 1.0 if non_en_rows == 0 else (non_en_pass / non_en_rows if non_en_rows > 0 else 0.0)

    # Sorting rule check
    if quotes_rows is not None:
        try:
            # Build list with parsed relevance and translated len
            rows_with_keys = []
            for r in quotes_rows:
                rs = int(str(r.get("relevance_score") or "0"))
                tquote = (r.get("translated_quote") or "")
                rows_with_keys.append((r, rs, len(tquote)))
            # Compute expected order by rules
            sorted_rows = sorted(rows_with_keys, key=lambda x: (-x[1], -x[2]))
            expected_ids = [x[0].get("id") for x in sorted_rows]
            actual_ids = [r.get("id") for r in quotes_rows]
            scores["quotes_ranked_sorting"] = 1.0 if expected_ids == actual_ids else 0.0
        except Exception:
            scores["quotes_ranked_sorting"] = 0.0

    # Parse top5_excerpts.md
    top_blocks = []
    if top5_md_path.exists():
        txt = _safe_read_text(top5_md_path)
        if txt is None:
            txt = ""
        # Normalize line endings
        lines = txt.splitlines()
        # Split into blocks separated by blank lines
        block = []
        for line in lines:
            if line.strip() == "":
                if block:
                    top_blocks.append(block)
                    block = []
            else:
                block.append(line.rstrip("\n"))
        if block:
            top_blocks.append(block)

        # Structure check: exactly 5 blocks, each with exactly 3 lines and correct prefixes
        structure_ok = True
        if len(top_blocks) != 5:
            structure_ok = False
        else:
            for b in top_blocks:
                if len(b) != 3:
                    structure_ok = False
                    break
                if not b[0].startswith("Team — Sponsor: "):
                    structure_ok = False
                    break
                if not b[1].startswith("Quote: "):
                    structure_ok = False
                    break
                if not b[2].startswith("Why it resonates: "):
                    structure_ok = False
                    break
        scores["top5_structure"] = 1.0 if structure_ok else 0.0

        # Compare with first 5 rows of CSV
        if quotes_rows is not None and scores["top5_structure"] == 1.0:
            first5 = quotes_rows[:5]
            if len(first5) == 5:
                match_ok = True
                for i in range(5):
                    b = top_blocks[i]
                    # Parse first line: "Team — Sponsor: <team> — <sponsor>"
                    first_line = b[0][len("Team — Sponsor: "):]
                    # Split by " — "
                    if " — " not in first_line:
                        match_ok = False
                        break
                    parts = first_line.split(" — ")
                    if len(parts) != 2:
                        match_ok = False
                        break
                    team_b = parts[0].strip()
                    sponsor_b = parts[1].strip()
                    quote_b = b[1][len("Quote: "):]
                    if (team_b != (first5[i].get("team") or "").strip() or
                        sponsor_b != (first5[i].get("sponsor") or "").strip() or
                        quote_b != (first5[i].get("translated_quote") or "")):
                        match_ok = False
                        break
                scores["top5_matches_csv"] = 1.0 if match_ok else 0.0
            else:
                scores["top5_matches_csv"] = 0.0

        # Resonance line contains at least one matched keyword
        if quotes_rows is not None and scores["top5_structure"] == 1.0 and len(quotes_rows) >= 5:
            # Build bilingual mapping index
            eng_to_idx = {english_keywords[i].lower(): i for i in range(len(english_keywords))}
            spa_to_idx = {spanish_keywords[i].lower(): i for i in range(len(spanish_keywords))}
            idx_to_bilingual = {i: (english_keywords[i].lower(), spanish_keywords[i].lower()) for i in range(len(english_keywords))}
            passed = 0
            total = 5
            for i in range(5):
                b = top_blocks[i]
                why_text = b[2][len("Why it resonates: "):].lower()
                # Gather keywords for this row from csv
                kf = _split_semicolon_list(quotes_rows[i].get("keywords_found") or "")
                # Build set of bilingual variants for keywords_found
                variants = set()
                for k in kf:
                    kl = k.lower()
                    if kl in eng_to_idx:
                        idx = eng_to_idx[kl]
                        variants.update(idx_to_bilingual[idx])
                    elif kl in spa_to_idx:
                        idx = spa_to_idx[kl]
                        variants.update(idx_to_bilingual[idx])
                    else:
                        # If keyword not recognized, just include as-is
                        variants.add(kl)
                found_any = any((var in why_text) for var in variants)
                if found_any:
                    passed += 1
            scores["top5_resonates_keyword_reference"] = passed / total if total > 0 else 0.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()