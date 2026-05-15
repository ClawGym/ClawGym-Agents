import json
import re
import sys
import hashlib
from pathlib import Path
from typing import Optional, Dict, Tuple, List


ORIGINAL_START = "Starting the run now (this will maybe take a long time and it might do a bunch of things)."
ORIGINAL_DOWNLOAD = "About to grab some stuff from the web probably - fingers crossed!"
ORIGINAL_DONE = "All operations completed successfully (I think). Please look somewhere in the output possibly."
ORIGINAL_MESSAGES = {
    "START_MSG": ORIGINAL_START,
    "DOWNLOAD_MSG": ORIGINAL_DOWNLOAD,
    "DONE_MSG": ORIGINAL_DONE,
}

EXPECTED_SUMMARY_KEYS = {
    "source_name",
    "source_organization",
    "rfc_identifier",
    "download_path",
    "download_sha256",
    "line_count",
    "word_count",
    "keyword_counts",
}

KEYWORDS = [
    "MUST",
    "MUST NOT",
    "REQUIRED",
    "SHALL",
    "SHALL NOT",
    "SHOULD",
    "SHOULD NOT",
    "RECOMMENDED",
    "MAY",
    "OPTIONAL",
]

BANNED_PHRASES = ["maybe", "probably", "i think", "fingers crossed"]


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_json_safe(path: Path) -> Optional[dict]:
    try:
        text = _read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _compute_line_and_word_counts(text: str) -> Tuple[int, int]:
    line_count = len(text.split("\n"))
    word_count = len(text.split())
    return line_count, word_count


def _compile_keyword_patterns() -> Dict[str, re.Pattern]:
    patterns = {}
    for k in KEYWORDS:
        pat = re.compile(r"\b" + re.escape(k) + r"\b", flags=re.IGNORECASE)
        patterns[k] = pat
    return patterns


def _compute_keyword_counts(text: str) -> Tuple[Dict[str, int], Dict[str, int]]:
    patterns = _compile_keyword_patterns()
    counts_any: Dict[str, int] = {}
    for k, pat in patterns.items():
        counts_any[k] = len(pat.findall(text))

    counts_excl = dict(counts_any)
    for base, not_key in [("MUST", "MUST NOT"), ("SHALL", "SHALL NOT"), ("SHOULD", "SHOULD NOT")]:
        counts_excl[base] = max(0, counts_any.get(base, 0) - counts_any.get(not_key, 0))
    return counts_any, counts_excl


def _extract_constant_strings_from_main(main_text: str) -> Dict[str, str]:
    constants: Dict[str, str] = {}
    pattern = re.compile(
        r'^\s*(START_MSG|DOWNLOAD_MSG|DONE_MSG)\s*=\s*(?P<quote>["\'])(?P<val>.*?)(?P=quote)\s*$',
        re.MULTILINE,
    )
    for m in pattern.finditer(main_text):
        name = m.group(1)
        val = m.group("val")
        constants[name] = val
    return constants


def _messages_concise_and_clear(msg: str) -> bool:
    if not msg or len(msg) > 120:
        return False
    lower = msg.lower()
    for bad in BANNED_PHRASES:
        if bad in lower:
            return False
    return True


def _has_placeholder_logic(main_text: str) -> bool:
    needles = [
        "placeholder.txt",
        "Replace this placeholder by implementing the download and summary.",
        "placeholder_path",
    ]
    return any(n in main_text for n in needles)


def _contains_official_download_hint(main_text: str) -> bool:
    t = main_text.lower()
    return ("rfc-editor" in t and "rfc8259.txt" in t)


def _uses_third_party_imports(main_text: str) -> bool:
    third_party_patterns = [
        r"^\s*import\s+requests\b",
        r"^\s*from\s+requests\b",
        r"^\s*import\s+urllib3\b",
        r"^\s*from\s+urllib3\b",
        r"^\s*import\s+httpx\b",
        r"^\s*from\s+httpx\b",
        r"^\s*import\s*aiohttp\b",
        r"^\s*from\s+aiohttp\b",
    ]
    for pat in third_party_patterns:
        if re.search(pat, main_text, flags=re.MULTILINE):
            return True
    return False


def _code_validates_config_heuristic(main_text: str) -> bool:
    t = main_text
    conds = [
        ("identifier" in t and "RFC 8259" in t),
        ("format" in t and ("'txt'" in t or '"txt"' in t)),
        ("official_source" in t and "IETF RFC Editor" in t),
    ]
    exit_hint = ("sys.exit" in t) or ("SystemExit" in t) or re.search(r"\bexit\s*\(", t) is not None
    return all(conds) and exit_hint


def _parse_messages_rewrite_md(md_text: str) -> List[Tuple[str, str]]:
    lines = md_text.splitlines()
    pairs: List[Tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "Before:" in line:
            before = line.split("Before:", 1)[1].strip()
            j = i + 1
            if not before:
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    before = lines[j].strip()
                    j += 1
            after = None
            while j < len(lines):
                if "After:" in lines[j]:
                    after = lines[j].split("After:", 1)[1].strip()
                    if not after:
                        k = j + 1
                        while k < len(lines) and not lines[k].strip():
                            k += 1
                        if k < len(lines):
                            after = lines[k].strip()
                            j = k + 1
                        else:
                            j += 1
                    else:
                        j += 1
                    break
                j += 1
            if before and after is not None:
                pairs.append((before, after))
            i = j
        else:
            i += 1
    return pairs


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "code_messages_rewritten": 0.0,
        "code_placeholder_logic_removed": 0.0,
        "code_downloads_from_official_source": 0.0,
        "code_validates_config_fields": 0.0,
        "no_third_party_imports": 0.0,
        "raw_rfc_file_exists": 0.0,
        "summary_json_exists": 0.0,
        "summary_fields_exact": 0.0,
        "source_fields_correct": 0.0,
        "download_path_correct": 0.0,
        "summary_sha256_correct": 0.0,
        "summary_line_count_correct": 0.0,
        "summary_word_count_correct": 0.0,
        "keyword_counts_correct": 0.0,
        "messages_rewrite_md_exists": 0.0,
        "messages_rewrite_three_pairs": 0.0,
        "messages_rewrite_matches_code": 0.0,
    }

    main_py = workspace / "project" / "main.py"
    main_text = _read_text_safe(main_py)
    constants: Dict[str, str] = {}

    if main_text is not None:
        constants = _extract_constant_strings_from_main(main_text)
        rewritten_ok = True
        for name, original in ORIGINAL_MESSAGES.items():
            new_val = constants.get(name)
            if not new_val:
                rewritten_ok = False
                break
            if new_val == original:
                rewritten_ok = False
                break
            if not _messages_concise_and_clear(new_val):
                rewritten_ok = False
                break
        scores["code_messages_rewritten"] = 1.0 if rewritten_ok else 0.0

        scores["code_placeholder_logic_removed"] = 0.0 if _has_placeholder_logic(main_text) else 1.0

        scores["code_downloads_from_official_source"] = 1.0 if _contains_official_download_hint(main_text) else 0.0

        scores["code_validates_config_fields"] = 1.0 if _code_validates_config_heuristic(main_text) else 0.0

    output_dir = workspace / "output"
    rfc_path = output_dir / "raw" / "rfc8259.txt"
    summary_path = output_dir / "summary.json"
    messages_md_path = output_dir / "messages_rewrite.md"

    scores["raw_rfc_file_exists"] = 1.0 if rfc_path.exists() and rfc_path.is_file() else 0.0

    summary = _read_json_safe(summary_path)
    scores["summary_json_exists"] = 1.0 if summary is not None else 0.0

    if summary is not None:
        keys_ok = set(summary.keys()) == EXPECTED_SUMMARY_KEYS
        types_ok = True
        if keys_ok:
            types_ok = (
                isinstance(summary.get("source_name"), str)
                and isinstance(summary.get("source_organization"), str)
                and isinstance(summary.get("rfc_identifier"), str)
                and isinstance(summary.get("download_path"), str)
                and isinstance(summary.get("download_sha256"), str)
                and isinstance(summary.get("line_count"), int)
                and isinstance(summary.get("word_count"), int)
                and isinstance(summary.get("keyword_counts"), dict)
            )
            if isinstance(summary.get("keyword_counts"), dict):
                types_ok = types_ok and set(summary["keyword_counts"].keys()) == set(KEYWORDS)
                if types_ok:
                    for v in summary["keyword_counts"].values():
                        if not isinstance(v, int):
                            types_ok = False
                            break
        scores["summary_fields_exact"] = 1.0 if (keys_ok and types_ok) else 0.0

        src_ok = (
            summary.get("source_name") == "RFC 8259"
            and summary.get("source_organization") == "IETF RFC Editor"
            and summary.get("rfc_identifier") == "RFC 8259"
        )
        scores["source_fields_correct"] = 1.0 if src_ok else 0.0

        dl_path_ok = summary.get("download_path") == "output/raw/rfc8259.txt"
        scores["download_path_correct"] = 1.0 if dl_path_ok else 0.0

        rfc_text = _read_text_safe(rfc_path) if rfc_path.exists() else None
        rfc_sha = _sha256_file(rfc_path) if rfc_path.exists() else None

        if rfc_sha is not None:
            sha_ok = isinstance(summary.get("download_sha256"), str) and summary.get("download_sha256", "").lower() == rfc_sha.lower()
            scores["summary_sha256_correct"] = 1.0 if sha_ok else 0.0
        else:
            scores["summary_sha256_correct"] = 0.0

        if rfc_text is not None:
            lc, wc = _compute_line_and_word_counts(rfc_text)
            scores["summary_line_count_correct"] = 1.0 if summary.get("line_count") == lc else 0.0
            scores["summary_word_count_correct"] = 1.0 if summary.get("word_count") == wc else 0.0

            counts_any, counts_excl = _compute_keyword_counts(rfc_text)
            kw = summary.get("keyword_counts") if isinstance(summary.get("keyword_counts"), dict) else None
            kw_ok = False
            if kw is not None:
                kw_ok = (kw == counts_any) or (kw == counts_excl)
            scores["keyword_counts_correct"] = 1.0 if kw_ok else 0.0
        else:
            scores["summary_line_count_correct"] = 0.0
            scores["summary_word_count_correct"] = 0.0
            scores["keyword_counts_correct"] = 0.0

    # Gate third-party import check to avoid rewarding the unmodified scaffold.
    # Only evaluate if deliverables exist (both RFC file and summary present).
    if main_text is not None and scores["raw_rfc_file_exists"] == 1.0 and scores["summary_json_exists"] == 1.0:
        scores["no_third_party_imports"] = 0.0 if _uses_third_party_imports(main_text) else 1.0
    else:
        scores["no_third_party_imports"] = 0.0

    md_text = _read_text_safe(messages_md_path) if messages_md_path.exists() else None
    scores["messages_rewrite_md_exists"] = 1.0 if md_text is not None else 0.0

    if md_text is not None:
        pairs = _parse_messages_rewrite_md(md_text)
        mapping: Dict[str, str] = {}
        for b, a in pairs:
            mapping[b] = a
        have_all = all(orig in mapping for orig in ORIGINAL_MESSAGES.values())
        after_valid = have_all and all(
            _messages_concise_and_clear(mapping[orig]) and mapping[orig] != orig
            for orig in ORIGINAL_MESSAGES.values()
        )
        scores["messages_rewrite_three_pairs"] = 1.0 if (have_all and after_valid) else 0.0

        if constants:
            original_to_constant_name = {v: k for k, v in ORIGINAL_MESSAGES.items()}
            match_all = True
            for orig_msg, after_msg in mapping.items():
                if orig_msg in original_to_constant_name:
                    const_name = original_to_constant_name[orig_msg]
                    code_val = constants.get(const_name)
                    if not code_val or code_val != after_msg:
                        match_all = False
                        break
            scores["messages_rewrite_matches_code"] = 1.0 if (have_all and match_all) else 0.0
        else:
            scores["messages_rewrite_matches_code"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()