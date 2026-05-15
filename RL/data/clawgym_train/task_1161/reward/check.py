import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


class TutorialHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_h1 = False
        self.in_p_era = False
        self.in_h2 = False
        self.current_h2_text = ""
        self.current_section = None  # materials, steps, cautions
        self.in_li = False
        self.current_li = ""
        self.technique_name = ""
        self.era_text = ""
        self.sections: Dict[str, List[str]] = {"materials": [], "steps": [], "cautions": []}

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "h1":
            self.in_h1 = True
        elif tag.lower() == "p":
            attrdict = dict(attrs)
            if "class" in attrdict and attrdict["class"] == "era":
                self.in_p_era = True
        elif tag.lower() == "h2":
            self.in_h2 = True
            self.current_h2_text = ""
        elif tag.lower() == "li":
            self.in_li = True
            self.current_li = ""

    def handle_data(self, data):
        if self.in_h1:
            self.technique_name += data.strip()
        elif self.in_p_era:
            self.era_text += data.strip()
        elif self.in_h2:
            self.current_h2_text += data.strip()
        elif self.in_li:
            self.current_li += data

    def handle_endtag(self, tag):
        if tag.lower() == "h1":
            self.in_h1 = False
        elif tag.lower() == "p":
            self.in_p_era = False
        elif tag.lower() == "h2":
            self.in_h2 = False
            h = self.current_h2_text.strip().lower()
            if h == "materials":
                self.current_section = "materials"
            elif h == "steps":
                self.current_section = "steps"
            elif h == "cautions":
                self.current_section = "cautions"
            else:
                self.current_section = None
            self.current_h2_text = ""
        elif tag.lower() == "li":
            self.in_li = False
            item = self.current_li.strip()
            if self.current_section in self.sections and item:
                item = re.sub(r"\s+", " ", item).strip()
                self.sections[self.current_section].append(item)
            self.current_li = ""


def parse_1930s_html(path: Path) -> Optional[Dict]:
    html = safe_read_text(path)
    if html is None:
        return None
    parser = TutorialHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    technique_name = parser.technique_name.strip()
    era = parser.era_text.strip()
    if era.lower().startswith("era:"):
        era = era.split(":", 1)[1].strip()
    if not technique_name or not era:
        return None
    return {
        "era": era,
        "technique_name": technique_name,
        "materials": parser.sections.get("materials", []),
        "steps": parser.sections.get("steps", []),
        "cautions": parser.sections.get("cautions", []),
    }


def parse_victorian_markdown(path: Path) -> Optional[Dict]:
    text = safe_read_text(path)
    if text is None:
        return None
    lines = [l.rstrip("\n") for l in text.splitlines()]
    title = None
    era = None
    materials: List[str] = []
    steps: List[str] = []
    cautions: List[str] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
        elif line.lower().startswith("era:"):
            era = line.split(":", 1)[1].strip()
        i += 1

    if title is None or era is None:
        return None

    def collect_bullets(start_index: int) -> Tuple[List[str], int]:
        items: List[str] = []
        idx = start_index
        while idx < n:
            l = lines[idx].strip()
            if not l:
                break
            if l.startswith("- "):
                items.append(l[2:].strip())
                idx += 1
                continue
            if l.endswith(":") and l[:-1].isalpha():
                break
            break
        return items, idx

    def collect_numbered(start_index: int) -> Tuple[List[str], int]:
        items: List[str] = []
        idx = start_index
        while idx < n:
            l = lines[idx].strip()
            if not l:
                break
            m = re.match(r"^\s*\d+\)\s*(.+)$", l)
            if m:
                items.append(m.group(1).strip())
                idx += 1
                continue
            m2 = re.match(r"^\s*\d+\.\s*(.+)$", l)
            if m2:
                items.append(m2.group(1).strip())
                idx += 1
                continue
            if l.endswith(":") and l[:-1].isalpha():
                break
            break
        return items, idx

    i = 0
    while i < n:
        l = lines[i].strip()
        if l.lower() == "materials:":
            mats, ni = collect_bullets(i + 1)
            materials = mats
            i = ni
            continue
        if l.lower() == "steps:":
            stps, ni = collect_numbered(i + 1)
            steps = stps
            i = ni
            continue
        if l.lower() == "cautions:":
            cauts, ni = collect_bullets(i + 1)
            cautions = cauts
            i = ni
            continue
        i += 1

    return {
        "era": era,
        "technique_name": title,
        "materials": materials,
        "steps": steps,
        "cautions": cautions,
    }


def word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b\w+(?:[-']\w+)*\b", text))


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def extract_expected_techniques(workspace: Path) -> Dict[str, Dict]:
    expected: Dict[str, Dict] = {}
    path_1930s = workspace / "input" / "articles" / "1930s_hollywood.html"
    parsed_1930s = parse_1930s_html(path_1930s) if path_1930s.exists() else None
    if parsed_1930s:
        expected["input/articles/1930s_hollywood.html"] = parsed_1930s
    path_victorian = workspace / "input" / "articles" / "victorian_stage.md"
    parsed_victorian = parse_victorian_markdown(path_victorian) if path_victorian.exists() else None
    if parsed_victorian:
        expected["input/articles/victorian_stage.md"] = parsed_victorian
    return expected


def load_techniques_json(workspace: Path) -> Optional[List[Dict]]:
    path = workspace / "output" / "techniques.json"
    data = safe_load_json(path)
    if isinstance(data, list):
        return data
    return None


def validate_techniques_structure(arr: List[Dict]) -> bool:
    required_keys = {"source_file", "era", "technique_name", "materials", "steps", "cautions"}
    for item in arr:
        if not isinstance(item, dict):
            return False
        if set(item.keys()) != required_keys:
            return False
        if not isinstance(item["source_file"], str):
            return False
        if not isinstance(item["era"], str):
            return False
        if not isinstance(item["technique_name"], str):
            return False
        if not (isinstance(item["materials"], list) and all(isinstance(x, str) for x in item["materials"])):
            return False
        if not (isinstance(item["steps"], list) and all(isinstance(x, str) for x in item["steps"])):
            return False
        if not (isinstance(item["cautions"], list) and all(isinstance(x, str) for x in item["cautions"])):
            return False
    return True


def compare_technique(expected: Dict, actual: Dict) -> bool:
    fields = ["era", "technique_name", "materials", "steps", "cautions"]
    for f in fields:
        if isinstance(expected[f], list):
            exp_list = [normalize_ws(x) for x in expected[f]]
            act_list = [normalize_ws(x) for x in actual.get(f, [])]
            if exp_list != act_list:
                return False
        else:
            if normalize_ws(expected[f]) != normalize_ws(actual.get(f, "")):
                return False
    return True


def find_technique_heading_indices(guide_lines: List[str], era: str, name: str) -> List[int]:
    indices = []
    pattern = re.compile(rf"^\s*{re.escape(era)}\s*[—-]\s*{re.escape(name)}\s*$")
    for idx, line in enumerate(guide_lines):
        if pattern.match(line.strip()):
            indices.append(idx)
    return indices


def extract_subsection_text(section_lines: List[str], subsection_name: str, other_names: List[str]) -> str:
    start_idx = None
    sub_pat = re.compile(re.escape(subsection_name), flags=re.IGNORECASE)
    other_pats = [re.compile(re.escape(n), flags=re.IGNORECASE) for n in other_names]
    for idx, line in enumerate(section_lines):
        if sub_pat.search(line):
            start_idx = idx + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(section_lines)
    for idx in range(start_idx, len(section_lines)):
        for op in other_pats:
            if op.search(section_lines[idx]):
                end_idx = idx
                break
        if end_idx != len(section_lines):
            break
    content = "\n".join(section_lines[start_idx:end_idx])
    return content


def contains_all_substrings(container_text: str, items: List[str]) -> float:
    if not items:
        return 1.0
    total = len(items)
    hits = 0
    lc = container_text.lower()
    for it in items:
        if normalize_ws(it).lower() in lc:
            hits += 1
    return hits / total if total > 0 else 1.0


def split_into_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def list_output_files(workspace: Path) -> List[str]:
    output_dir = workspace / "output"
    if not output_dir.exists() or not output_dir.is_dir():
        return []
    return sorted([p.name for p in output_dir.iterdir() if p.is_file()])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "techniques_json_present_and_parseable": 0.0,
        "techniques_json_structure_fields_types": 0.0,
        "techniques_extraction_1930s_exact": 0.0,
        "techniques_extraction_victorian_exact": 0.0,
        "guide_intro_length_and_presence": 0.0,
        "guide_sections_and_subsections_present": 0.0,
        "guide_materials_cautions_coverage": 0.0,
        "guide_quick_steps_coverage": 0.0,
        "guide_sources_section_correct": 0.0,
        "email_word_limit_and_politeness": 0.0,
        "email_references_techniques_in_one_sentence": 0.0,
        "forum_dm_word_limit_and_focus_1930s": 0.0,
        "forum_dm_avoids_victorian_terms": 0.0,
        "output_folder_exact_files": 0.0,
    }

    expected = extract_expected_techniques(workspace)

    techniques = load_techniques_json(workspace)
    if techniques is not None:
        scores["techniques_json_present_and_parseable"] = 1.0
    else:
        techniques = []

    if techniques and validate_techniques_structure(techniques):
        scores["techniques_json_structure_fields_types"] = 1.0

    actual_by_src: Dict[str, Dict] = {}
    for item in techniques:
        if isinstance(item, dict) and "source_file" in item and isinstance(item["source_file"], str):
            actual_by_src[item["source_file"]] = item

    src_1930s = "input/articles/1930s_hollywood.html"
    if src_1930s in expected and src_1930s in actual_by_src:
        if compare_technique(expected[src_1930s], actual_by_src[src_1930s]):
            scores["techniques_extraction_1930s_exact"] = 1.0

    src_victorian = "input/articles/victorian_stage.md"
    if src_victorian in expected and src_victorian in actual_by_src:
        if compare_technique(expected[src_victorian], actual_by_src[src_victorian]):
            scores["techniques_extraction_victorian_exact"] = 1.0

    guide_path = workspace / "output" / "guide.md"
    guide_text = safe_read_text(guide_path)
    if guide_text is not None and techniques:
        guide_lines = guide_text.splitlines()
        heading_indices: Dict[str, int] = {}
        section_list: List[Tuple[str, int]] = []
        for t in techniques:
            era = t.get("era", "")
            name = t.get("technique_name", "")
            idxs = find_technique_heading_indices(guide_lines, era, name)
            if idxs:
                idx = idxs[0]
                key = f"{era} — {name}"
                heading_indices[key] = idx
                section_list.append((key, idx))
        section_list.sort(key=lambda x: x[1])

        if section_list:
            first_idx = section_list[0][1]
            intro_text = "\n".join(guide_lines[:first_idx]).strip()
            wc = word_count(intro_text)
            if wc > 0 and wc <= 120:
                scores["guide_intro_length_and_presence"] = 1.0

        all_sections_present = True
        materials_cautions_coverages: List[float] = []
        steps_coverages: List[float] = []

        for i, (key, start_idx) in enumerate(section_list):
            end_idx = len(guide_lines)
            if i + 1 < len(section_list):
                end_idx = section_list[i + 1][1]
            for j in range(start_idx + 1, end_idx):
                if guide_lines[j].strip().lower() == "sources":
                    end_idx = j
                    break
            section_lines = guide_lines[start_idx:end_idx]
            section_text = "\n".join(section_lines)

            subs = ["Quick Steps", "Materials", "Cautions"]
            for sname in subs:
                if re.search(re.escape(sname), section_text, flags=re.IGNORECASE) is None:
                    all_sections_present = False
                    break

            era_name_match = re.match(r"^\s*(.+?)\s*[—-]\s*(.+?)\s*$", key)
            tdict = None
            if era_name_match:
                era_val = era_name_match.group(1)
                name_val = era_name_match.group(2)
                for t in techniques:
                    if normalize_ws(t.get("era", "")) == normalize_ws(era_val) and normalize_ws(t.get("technique_name", "")) == normalize_ws(name_val):
                        tdict = t
                        break
            if tdict:
                mat_text = extract_subsection_text(section_lines, "Materials", ["Quick Steps", "Cautions"])
                caut_text = extract_subsection_text(section_lines, "Cautions", ["Quick Steps", "Materials"])
                steps_text = extract_subsection_text(section_lines, "Quick Steps", ["Materials", "Cautions"])

                mat_cov = contains_all_substrings(mat_text, tdict.get("materials", []))
                caut_cov = contains_all_substrings(caut_text, tdict.get("cautions", []))
                steps_cov = contains_all_substrings(steps_text, tdict.get("steps", []))

                materials_cautions_coverages.append((mat_cov + caut_cov) / 2.0)
                steps_coverages.append(steps_cov)

        if section_list and all_sections_present:
            scores["guide_sections_and_subsections_present"] = 1.0

        if materials_cautions_coverages:
            avg_mat_caut = sum(materials_cautions_coverages) / len(materials_cautions_coverages)
            scores["guide_materials_cautions_coverage"] = max(0.0, min(1.0, avg_mat_caut))
        if steps_coverages:
            avg_steps = sum(steps_coverages) / len(steps_coverages)
            scores["guide_quick_steps_coverage"] = max(0.0, min(1.0, avg_steps))

        sources_idx = None
        for idx, line in enumerate(guide_lines):
            if line.strip().lower() == "sources":
                sources_idx = idx
        if sources_idx is not None:
            sources_text = "\n".join(guide_lines[sources_idx + 1 :]).strip()
            src_files = sorted({t.get("source_file", "") for t in techniques if isinstance(t, dict)})
            present_all = all((sf and (sf in sources_text)) for sf in src_files)
            if present_all:
                scores["guide_sources_section_correct"] = 1.0

    email_path = workspace / "output" / "email_to_historian.txt"
    email_text = safe_read_text(email_path)
    if email_text is not None:
        wc = word_count(email_text)
        polite = bool(re.search(r"\b(thank|please)\b", email_text, flags=re.IGNORECASE))
        if wc <= 180 and wc > 0 and polite:
            scores["email_word_limit_and_politeness"] = 1.0
        sentences = split_into_sentences(email_text)
        has_ref_sentence = False
        if techniques:
            pairs = [(t.get("era", ""), t.get("technique_name", "")) for t in techniques]
            for s in sentences:
                ok = True
                for (era, name) in pairs:
                    if not era or not name:
                        ok = False
                        break
                    if era not in s or name not in s:
                        ok = False
                        break
                if ok:
                    has_ref_sentence = True
                    break
        if has_ref_sentence:
            scores["email_references_techniques_in_one_sentence"] = 1.0

    forum_path = workspace / "output" / "forum_dm.txt"
    forum_text = safe_read_text(forum_path)
    if forum_text is not None and techniques:
        wc = word_count(forum_text)
        mentions_1930s = "1930s" in forum_text
        asks_tips = bool(re.search(r"\b(tips|advice|help)\b", forum_text, flags=re.IGNORECASE))
        tech_by_era = {t.get("era", ""): t for t in techniques if isinstance(t, dict)}
        t1930s = None
        if "1930s" in tech_by_era:
            t1930s = tech_by_era.get("1930s")
        else:
            for era_val, t in tech_by_era.items():
                if isinstance(era_val, str) and "1930s" in era_val:
                    t1930s = t
                    break
        victorian = None
        for era_val, t in tech_by_era.items():
            if isinstance(era_val, str) and era_val.lower().startswith("victorian"):
                victorian = t
                break

        if wc <= 120 and wc > 0 and mentions_1930s and asks_tips and t1930s:
            allowed_phrases = []
            allowed_phrases.extend(t1930s.get("materials", []))
            allowed_phrases.extend(t1930s.get("steps", []))
            hits = 0
            f_low = forum_text.lower()
            for p in allowed_phrases:
                if normalize_ws(p).lower() in f_low:
                    hits += 1
            if hits >= 2:
                scores["forum_dm_word_limit_and_focus_1930s"] = 1.0

        if forum_text is not None and victorian is not None:
            forbidden = []
            forbidden.extend(victorian.get("materials", []))
            forbidden.extend(victorian.get("steps", []))
            forbidden.append("Victorian")
            ok = True
            f_low = forum_text.lower()
            for p in forbidden:
                if normalize_ws(p).lower() in f_low:
                    ok = False
                    break
            if ok:
                scores["forum_dm_avoids_victorian_terms"] = 1.0
        elif forum_text is not None and victorian is None:
            scores["forum_dm_avoids_victorian_terms"] = 1.0

    expected_files = {"techniques.json", "guide.md", "email_to_historian.txt", "forum_dm.txt"}
    present_files = set(list_output_files(workspace))
    output_dir_exists = (workspace / "output").exists() and (workspace / "output").is_dir()
    if output_dir_exists and present_files == expected_files:
        scores["output_folder_exact_files"] = 1.0
    else:
        scores["output_folder_exact_files"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()