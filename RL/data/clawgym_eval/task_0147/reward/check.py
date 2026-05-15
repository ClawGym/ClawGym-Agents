import csv
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


class VerbClassTableParser(HTMLParser):
    def __init__(self, target_id: str):
        super().__init__()
        self.target_id = target_id
        self.in_table = False
        self.in_td = False
        self.current_row: List[str] = []
        self.current_cell: List[str] = []
        self.rows: List[List[str]] = []
        self._table_depth = 0  # handle nested tables if any

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        if tag.lower() == "table":
            attrs_dict = dict(attrs)
            if not self.in_table and attrs_dict.get("id") == self.target_id:
                self.in_table = True
                self._table_depth = 1
            elif self.in_table:
                # nested table inside target table
                self._table_depth += 1
        if self.in_table and tag.lower() == "tr":
            self.current_row = []
        if self.in_table and tag.lower() == "td":
            self.in_td = True
            self.current_cell = []

    def handle_endtag(self, tag: str):
        if self.in_table and tag.lower() == "td":
            self.in_td = False
            cell_text = "".join(self.current_cell).strip()
            self.current_row.append(cell_text)
            self.current_cell = []
        if self.in_table and tag.lower() == "tr":
            # only collect body rows (should have 3 columns)
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        if tag.lower() == "table" and self.in_table:
            self._table_depth -= 1
            if self._table_depth <= 0:
                self.in_table = False

    def handle_data(self, data: str):
        if self.in_table and self.in_td:
            self.current_cell.append(data)


def _read_all_corpus_tsvs(corpus_dir: Path) -> Tuple[bool, List[Dict[str, str]]]:
    rows: List[Dict[str, str]] = []
    if not corpus_dir.exists() or not corpus_dir.is_dir():
        return False, rows
    tsv_files = sorted([p for p in corpus_dir.glob("*.tsv") if p.is_file()])
    if not tsv_files:
        return False, rows
    expected_fields = ["sentence_id", "verb_lemma", "frame", "genre"]
    for path in tsv_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                if reader.fieldnames is None:
                    return False, []
                # Require exact fields in any order? The input spec provides exact columns.
                # We'll ensure the required columns are present.
                for field in expected_fields:
                    if field not in reader.fieldnames:
                        return False, []
                for rec in reader:
                    # ensure required fields exist
                    if not all(k in rec for k in expected_fields):
                        return False, []
                    rows.append({
                        "sentence_id": rec["sentence_id"],
                        "verb_lemma": rec["verb_lemma"],
                        "frame": rec["frame"],
                        "genre": rec["genre"],
                    })
        except Exception:
            return False, []
    return True, rows


def _parse_mapping_html(html_path: Path) -> Tuple[bool, Dict[str, Dict[str, Any]]]:
    if not html_path.exists() or not html_path.is_file():
        return False, {}
    try:
        content = html_path.read_text(encoding="utf-8", errors="ignore")
        parser = VerbClassTableParser(target_id="verb-classes")
        parser.feed(content)
        # Expect rows with 3 columns: lemma, alternation_class, ditransitive_possible
        mapping: Dict[str, Dict[str, Any]] = {}
        for row in parser.rows:
            # Filter header rows by checking cells length and header names not numeric; We'll rely on tbody
            if len(row) != 3:
                # Keep only rows with exactly 3 cells
                continue
            lemma, alternation_class, ditransitive_possible = row
            lemma = lemma.strip()
            alternation_class = alternation_class.strip()
            dtr = ditransitive_possible.strip().lower()
            if lemma:
                mapping[lemma] = {
                    "alternation_class": alternation_class,
                    "ditransitive_possible": True if dtr == "yes" else False if dtr == "no" else None,
                }
        if not mapping:
            return False, {}
        return True, mapping
    except Exception:
        return False, {}


def _round3(x: float) -> float:
    return round(x + 0.0, 3)


def _safe_load_csv(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    if not path.exists() or not path.is_file():
        return False, [], []
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
        return True, headers, rows
    except Exception:
        return False, [], []


def _compute_expected(corpus_rows: List[Dict[str, str]], mapping: Dict[str, Dict[str, Any]]) -> Tuple[
    List[Tuple[str, str, str, int, int, float]],
    List[Tuple[str, int, int, float]],
    List[str]
]:
    # Determine mapped and unmapped
    lemmas_in_corpus = set()
    for r in corpus_rows:
        lemmas_in_corpus.add(r["verb_lemma"])
    unmapped = sorted([l for l in lemmas_in_corpus if l not in mapping])

    # Filter to mapped tokens
    mapped_tokens = [r for r in corpus_rows if r["verb_lemma"] in mapping]

    # Counts per verb and frame
    by_verb_counts: Dict[str, Dict[str, int]] = {}
    totals_per_verb: Dict[str, int] = {}
    for r in mapped_tokens:
        v = r["verb_lemma"]
        f = r["frame"]
        by_verb_counts.setdefault(v, {})
        by_verb_counts[v][f] = by_verb_counts[v].get(f, 0) + 1
        totals_per_verb[v] = totals_per_verb.get(v, 0) + 1

    # Build by_verb_frame expected rows
    by_verb_frame_rows: List[Tuple[str, str, str, int, int, float]] = []
    for verb, frame_counts in by_verb_counts.items():
        total = totals_per_verb[verb]
        alt_class = mapping[verb]["alternation_class"]
        for frame, cnt in frame_counts.items():
            prop = _round3(cnt / total if total > 0 else 0.0)
            by_verb_frame_rows.append((verb, alt_class, frame, cnt, total, prop))

    # Build by_class_summary expected rows
    # Aggregate total tokens and DITRANS tokens per class, and distinct verbs per class
    class_totals: Dict[str, int] = {}
    class_ditrans: Dict[str, int] = {}
    class_verbs: Dict[str, set] = {}
    for r in mapped_tokens:
        verb = r["verb_lemma"]
        frame = r["frame"]
        alt_class = mapping[verb]["alternation_class"]
        class_totals[alt_class] = class_totals.get(alt_class, 0) + 1
        if frame == "DITRANS":
            class_ditrans[alt_class] = class_ditrans.get(alt_class, 0) + 1
        class_verbs.setdefault(alt_class, set()).add(verb)

    by_class_summary_rows: List[Tuple[str, int, int, float]] = []
    for alt_class, total_tokens in class_totals.items():
        ditrans_tokens = class_ditrans.get(alt_class, 0)
        distinct_verbs = len(class_verbs.get(alt_class, set()))
        share = _round3(ditrans_tokens / total_tokens if total_tokens > 0 else 0.0)
        by_class_summary_rows.append((alt_class, total_tokens, distinct_verbs, share))

    return by_verb_frame_rows, by_class_summary_rows, unmapped


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value.strip())
    except Exception:
        return None


def _parse_int(value: str) -> Optional[int]:
    try:
        # Allow floats formatted as integers; but require strict integer
        if isinstance(value, str):
            v = value.strip()
        else:
            v = str(value)
        if v.lower().startswith("+"):
            v = v[1:]
        if "." in v:
            # explicitly reject floats
            return None
        return int(v)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "by_verb_frame_file_exists": 0.0,
        "by_verb_frame_header_valid": 0.0,
        "by_verb_frame_content_correct": 0.0,
        "by_class_summary_file_exists": 0.0,
        "by_class_summary_header_valid": 0.0,
        "by_class_summary_content_correct": 0.0,
        "unmapped_verbs_file_exists": 0.0,
        "unmapped_verbs_content_correct": 0.0,
    }

    # Compute expected from inputs
    corpus_ok, corpus_rows = _read_all_corpus_tsvs(workspace / "input" / "corpus")
    mapping_ok, mapping = _parse_mapping_html(workspace / "input" / "resources" / "verb_classes.html")

    expected_by_verb_frame: List[Tuple[str, str, str, int, int, float]] = []
    expected_by_class_summary: List[Tuple[str, int, int, float]] = []
    expected_unmapped: List[str] = []

    if corpus_ok and mapping_ok:
        expected_by_verb_frame, expected_by_class_summary, expected_unmapped = _compute_expected(corpus_rows, mapping)

    # Paths to outputs
    by_verb_frame_path = workspace / "output" / "by_verb_frame.csv"
    by_class_summary_path = workspace / "output" / "by_class_summary.csv"
    unmapped_verbs_path = workspace / "output" / "unmapped_verbs.txt"

    # Check by_verb_frame.csv
    bvf_ok, bvf_headers, bvf_rows = _safe_load_csv(by_verb_frame_path)
    if bvf_ok:
        scores["by_verb_frame_file_exists"] = 1.0
        expected_headers = ["verb_lemma", "alternation_class", "frame", "token_count", "total_tokens_for_verb", "token_proportion"]
        if bvf_headers == expected_headers:
            scores["by_verb_frame_header_valid"] = 1.0
            # Content check only if we have expected
            if corpus_ok and mapping_ok:
                # Build observed set
                observed: List[Tuple[str, str, str, int, int, float]] = []
                valid = True
                for row in bvf_rows:
                    try:
                        verb_lemma = row["verb_lemma"].strip()
                        alt_class = row["alternation_class"].strip()
                        frame = row["frame"].strip()
                        token_count = _parse_int(row["token_count"])
                        total_tokens = _parse_int(row["total_tokens_for_verb"])
                        prop = _parse_float(row["token_proportion"])
                        if verb_lemma == "" or alt_class == "" or frame == "":
                            valid = False
                            break
                        if token_count is None or total_tokens is None or prop is None:
                            valid = False
                            break
                        # Check internal proportion consistency
                        expected_prop = _round3(token_count / total_tokens if total_tokens > 0 else 0.0)
                        if _round3(prop) != expected_prop:
                            valid = False
                            break
                        observed.append((verb_lemma, alt_class, frame, token_count, total_tokens, expected_prop))
                    except Exception:
                        valid = False
                        break
                if valid:
                    # Compare sets exactly
                    if set(observed) == set(expected_by_verb_frame):
                        scores["by_verb_frame_content_correct"] = 1.0
        else:
            # header invalid
            scores["by_verb_frame_header_valid"] = 0.0

    # Check by_class_summary.csv
    bcs_ok, bcs_headers, bcs_rows = _safe_load_csv(by_class_summary_path)
    if bcs_ok:
        scores["by_class_summary_file_exists"] = 1.0
        expected_headers = ["alternation_class", "total_tokens", "distinct_verbs", "ditransitive_token_share"]
        if bcs_headers == expected_headers:
            scores["by_class_summary_header_valid"] = 1.0
            if corpus_ok and mapping_ok:
                valid = True
                observed: List[Tuple[str, int, int, float]] = []
                for row in bcs_rows:
                    try:
                        alt_class = row["alternation_class"].strip()
                        total_tokens = _parse_int(row["total_tokens"])
                        distinct_verbs = _parse_int(row["distinct_verbs"])
                        share = _parse_float(row["ditransitive_token_share"])
                        if alt_class == "" or total_tokens is None or distinct_verbs is None or share is None:
                            valid = False
                            break
                        # Share should be rounded to 3 decimals; don't recompute here since we don't have details per row.
                        share_r = _round3(share)
                        observed.append((alt_class, total_tokens, distinct_verbs, share_r))
                    except Exception:
                        valid = False
                        break
                if valid:
                    if set(observed) == set(expected_by_class_summary):
                        scores["by_class_summary_content_correct"] = 1.0
        else:
            scores["by_class_summary_header_valid"] = 0.0

    # Check unmapped_verbs.txt
    if unmapped_verbs_path.exists() and unmapped_verbs_path.is_file():
        scores["unmapped_verbs_file_exists"] = 1.0
        try:
            content = unmapped_verbs_path.read_text(encoding="utf-8")
            lines = [ln.strip() for ln in content.splitlines() if ln.strip() != ""]
            # Ensure sorted and unique
            if lines == sorted(set(lines)):
                if corpus_ok and mapping_ok:
                    if lines == expected_unmapped:
                        scores["unmapped_verbs_content_correct"] = 1.0
                else:
                    # If we cannot compute expected, we cannot verify content; leave at 0.0
                    pass
            else:
                # either not sorted or duplicates present
                pass
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()