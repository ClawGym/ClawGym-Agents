import json
import sys
import re
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
        return json.loads(text)
    except Exception:
        return None


def parse_simple_yaml_topics(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Minimal YAML parser tailored to the given topics.yaml format.
    Expected structure:
    topics:
      - topic: "Title"
        slug: "slug"
        expect_keywords:
          - "kw1"
          - "kw2"
    """
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    # Find 'topics:' line
    has_topics = any(l.strip().startswith("topics:") for l in lines)
    if not has_topics:
        return None

    topics: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_expect_keywords = False

    def strip_quotes(s: str) -> str:
        s = s.strip()
        if (len(s) >= 2) and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            return s[1:-1]
        return s

    for line in lines:
        s = line.rstrip("\n")
        stripped = s.strip()

        if not stripped:
            continue

        # Start of a new topic item
        m_topic = re.match(r'^\s*-\s*topic:\s*(.+)$', s)
        if m_topic:
            # Save previous
            if current:
                # Ensure required fields present minimally
                if "topic" in current and "slug" in current and "expect_keywords" in current:
                    topics.append(current)
            current = {"expect_keywords": []}
            in_expect_keywords = False
            topic_val = strip_quotes(m_topic.group(1).strip())
            current["topic"] = topic_val
            continue

        if current is None:
            # Not yet in a topic item; skip until one starts
            continue

        # slug line
        m_slug = re.match(r'^\s*slug:\s*(.+)$', s)
        if m_slug:
            slug_val = strip_quotes(m_slug.group(1).strip())
            current["slug"] = slug_val
            in_expect_keywords = False
            continue

        # expect_keywords start
        if re.match(r'^\s*expect_keywords:\s*$', s):
            in_expect_keywords = True
            continue

        # keywords entries
        if in_expect_keywords:
            m_kw = re.match(r'^\s*-\s*(.+)$', s)
            if m_kw:
                kw_val = strip_quotes(m_kw.group(1).strip())
                current.setdefault("expect_keywords", []).append(kw_val)
                continue
            else:
                # End of keywords block if indentation changes
                in_expect_keywords = False
                # fall through for other fields

    # Append last
    if current and "topic" in current and "slug" in current and "expect_keywords" in current:
        topics.append(current)

    # Basic validation
    if not topics:
        return None
    for t in topics:
        if not isinstance(t.get("topic"), str) or not isinstance(t.get("slug"), str) or not isinstance(t.get("expect_keywords"), list):
            return None
        # Normalize keywords to strings
        t["expect_keywords"] = [str(x) for x in t["expect_keywords"]]
    return topics


def parse_makefile_targets(path: Path) -> Tuple[Optional[set], Optional[str]]:
    """
    Parse a Makefile to extract target names and the content for 'clean' target for heuristics.
    Returns (set_of_targets, makefile_text)
    """
    text = safe_read_text(path)
    if text is None:
        return None, None
    targets = set()
    # Match target lines like "target:" not starting with a tab or a variable assignment, and not a pattern rule with '%'
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = re.match(r'^([A-Za-z0-9_\-\.]+)\s*:\s*(.*)$', line)
        if m:
            name = m.group(1)
            # ignore .PHONY and pattern rules
            if "%" in name:
                continue
            targets.add(name)
    return targets, text


def compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def parse_checksums(path: Path) -> Optional[List[Tuple[str, str]]]:
    """
    Parse a checksums file with lines like '<hash>  <path>'.
    Returns list of (hash_hex, path_string).
    """
    text = safe_read_text(path)
    if text is None:
        return None
    entries: List[Tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r'^([A-Fa-f0-9]{64})\s+(.+)$', stripped)
        if not m:
            continue
        entries.append((m.group(1).lower(), m.group(2)))
    return entries


def extract_wikidata_facts(entity_json: Dict[str, Any], qid: str) -> Dict[str, Any]:
    """
    Extract needed fields from a Wikidata entity JSON object returned by the WD API.
    entity_json is expected to be the payload loaded from artifacts/raw/wikidata/<QID>.json,
    which should be a dict with 'entities' key mapping QID to an entity dict.
    Returns a dict with keys: label_en, description_en, instance_of_qids (list), sitelinks_count (int).
    Missing fields default to sensible empty structures.
    """
    result = {
        "label_en": None,
        "description_en": None,
        "instance_of_qids": [],
        "sitelinks_count": 0,
    }
    try:
        entities = entity_json.get("entities", {})
        ent = entities.get(qid)
        if not isinstance(ent, dict):
            return result
        # labels
        labels = ent.get("labels", {})
        if isinstance(labels, dict):
            en = labels.get("en")
            if isinstance(en, dict):
                val = en.get("value")
                if isinstance(val, str):
                    result["label_en"] = val
        # descriptions
        descriptions = ent.get("descriptions", {})
        if isinstance(descriptions, dict):
            en = descriptions.get("en")
            if isinstance(en, dict):
                val = en.get("value")
                if isinstance(val, str):
                    result["description_en"] = val
        # P31 claims
        claims = ent.get("claims", {})
        p31 = claims.get("P31", [])
        inst_qids = []
        if isinstance(p31, list):
            for claim in p31:
                try:
                    mainsnak = claim.get("mainsnak", {})
                    datavalue = mainsnak.get("datavalue", {})
                    value = datavalue.get("value", {})
                    q = value.get("id")
                    if isinstance(q, str) and re.match(r'^Q[1-9]\d*$', q):
                        inst_qids.append(q)
                except Exception:
                    continue
        result["instance_of_qids"] = inst_qids
        # sitelinks
        sitelinks = ent.get("sitelinks", {})
        if isinstance(sitelinks, dict):
            result["sitelinks_count"] = len(sitelinks)
    except Exception:
        # Return whatever collected
        pass
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "makefile_targets_present": 0.0,
        "found_qids_json_valid": 0.0,
        "search_html_artifacts": 0.0,
        "raw_wikidata_json_valid": 0.0,
        "processed_entities_correct": 0.0,
        "validation_report_correct": 0.0,
        "checksums_complete_and_correct": 0.0,
    }

    # Load topics
    topics_yaml_path = workspace / "input" / "topics.yaml"
    topics = parse_simple_yaml_topics(topics_yaml_path)
    if not isinstance(topics, list):
        # If we cannot load topics, many checks cannot proceed.
        return scores

    # Check Makefile targets
    makefile_path = workspace / "Makefile"
    targets, makefile_text = parse_makefile_targets(makefile_path)
    if targets is not None and makefile_text is not None:
        required_targets = {"fetch", "process", "validate", "all", "clean"}
        has_all_targets = required_targets.issubset(targets)
        # Check that clean removes artifacts directory (heuristic)
        clean_mentions_artifacts = False
        if "clean" in targets:
            # Find clean target block and see if it mentions artifacts
            # Simple heuristic: check lines after 'clean:' up to next target definition for 'artifacts' and 'rm'
            lines = makefile_text.splitlines()
            in_clean = False
            for line in lines:
                if re.match(r'^clean\s*:', line):
                    in_clean = True
                    continue
                if in_clean:
                    if re.match(r'^[A-Za-z0-9_\-\.]+\s*:', line):
                        # next target starts
                        break
                    if "artifacts" in line and ("rm" in line or "del" in line or "rmdir" in line):
                        clean_mentions_artifacts = True
                        break
        if has_all_targets and clean_mentions_artifacts:
            scores["makefile_targets_present"] = 1.0

    # Load found_qids.json
    mapping_path = workspace / "artifacts" / "search" / "found_qids.json"
    mapping = safe_load_json(mapping_path)
    mapping_valid = False
    mapping_by_slug: Dict[str, Dict[str, Any]] = {}
    if isinstance(mapping, list):
        # Validate structure
        idx_valid = True
        # Expect exactly one record per topic from topics.yaml
        if len(mapping) == len(topics):
            # Build checking
            for item in mapping:
                if not isinstance(item, dict):
                    idx_valid = False
                    break
                for key in ("topic", "slug", "query", "source_url", "qid"):
                    if key not in item:
                        idx_valid = False
                        break
                if not idx_valid:
                    break
                # Validate QID and source_url
                qid = item.get("qid")
                src = item.get("source_url")
                if not (isinstance(qid, str) and re.match(r'^Q[1-9]\d*$', qid)):
                    idx_valid = False
                    break
                if not (isinstance(src, str) and re.match(r'^https?://(www\.)?wikidata\.org/wiki/%s$' % re.escape(qid), src)):
                    idx_valid = False
                    break
                if not (isinstance(item.get("query"), str) and item.get("query").strip()):
                    idx_valid = False
                    break
                if not (isinstance(item.get("topic"), str) and isinstance(item.get("slug"), str)):
                    idx_valid = False
                    break
                mapping_by_slug[item["slug"]] = item
            # Verify coverage of all topics
            if idx_valid:
                for t in topics:
                    slug = t["slug"]
                    topic_name = t["topic"]
                    if slug not in mapping_by_slug:
                        idx_valid = False
                        break
                    if mapping_by_slug[slug].get("topic") != topic_name:
                        idx_valid = False
                        break
        else:
            idx_valid = False

        if idx_valid:
            mapping_valid = True
            scores["found_qids_json_valid"] = 1.0

    # Check search HTML files
    search_ok = True
    if mapping_valid:
        for t in topics:
            slug = t["slug"]
            html_path = workspace / "artifacts" / "search" / f"{slug}_search.html"
            content = safe_read_text(html_path)
            if not content or len(content) == 0:
                search_ok = False
                break
            # Optional validation: content includes the Wikidata URL or QID
            m = mapping_by_slug.get(slug, {})
            qid = m.get("qid", "")
            src_url = m.get("source_url", "")
            if (qid and (qid in content)) or (src_url and (src_url in content)) or ("wikidata.org/wiki/Q" in content):
                pass
            else:
                # Still accept if content is non-empty, but to be stricter we require some Wikidata hint.
                search_ok = False
                break
    else:
        search_ok = False
    if search_ok:
        scores["search_html_artifacts"] = 1.0

    # Check raw Wikidata JSON files
    raw_ok = True
    raw_facts: Dict[str, Dict[str, Any]] = {}
    if mapping_valid:
        for t in topics:
            slug = t["slug"]
            m = mapping_by_slug.get(slug)
            if not m:
                raw_ok = False
                break
            qid = m["qid"]
            raw_path = workspace / "artifacts" / "raw" / "wikidata" / f"{qid}.json"
            data = safe_load_json(raw_path)
            if not isinstance(data, dict):
                raw_ok = False
                break
            # Must contain entities with the QID key
            if not isinstance(data.get("entities"), dict) or qid not in data.get("entities", {}):
                raw_ok = False
                break
            facts = extract_wikidata_facts(data, qid)
            # We require sitelinks_count integer, instance_of_qids list
            if not isinstance(facts.get("sitelinks_count"), int) or not isinstance(facts.get("instance_of_qids"), list):
                raw_ok = False
                break
            raw_facts[qid] = facts
    else:
        raw_ok = False
    if raw_ok:
        scores["raw_wikidata_json_valid"] = 1.0

    # Check processed/entities.json
    processed_ok = True
    processed_path = workspace / "artifacts" / "processed" / "entities.json"
    processed = safe_load_json(processed_path)
    if not (isinstance(processed, list) and mapping_valid and raw_ok):
        processed_ok = False
    else:
        # Must have exactly one entry per topic and match expected fields
        if len(processed) != len(topics):
            processed_ok = False
        else:
            # Index by qid for easier matching
            items_by_qid: Dict[str, Dict[str, Any]] = {}
            for item in processed:
                if isinstance(item, dict) and isinstance(item.get("qid"), str):
                    items_by_qid[item["qid"]] = item
            for t in topics:
                m = mapping_by_slug.get(t["slug"])
                if not m:
                    processed_ok = False
                    break
                qid = m["qid"]
                item = items_by_qid.get(qid)
                if not isinstance(item, dict):
                    processed_ok = False
                    break
                # Required fields presence
                required_fields = ["topic", "slug", "qid", "label_en", "description_en", "instance_of_qids", "sitelinks_count", "source_url"]
                for f in required_fields:
                    if f not in item:
                        processed_ok = False
                        break
                if not processed_ok:
                    break
                # Topic/slug/qid match mapping
                if item["topic"] != m["topic"] or item["slug"] != m["slug"] or item["qid"] != qid:
                    processed_ok = False
                    break
                # source_url matches mapping
                if item["source_url"] != m["source_url"]:
                    processed_ok = False
                    break
                # Types
                if not isinstance(item.get("instance_of_qids"), list) or not isinstance(item.get("sitelinks_count"), int):
                    processed_ok = False
                    break
                # Compare with raw facts
                facts = raw_facts.get(qid, {})
                # label_en and description_en should match if present in raw
                if facts.get("label_en") is not None and item.get("label_en") != facts.get("label_en"):
                    processed_ok = False
                    break
                if facts.get("description_en") is not None and item.get("description_en") != facts.get("description_en"):
                    processed_ok = False
                    break
                # instance_of_qids compare as sets (unique)
                expected_inst = sorted(set(facts.get("instance_of_qids", [])))
                got_inst = sorted(set([x for x in item.get("instance_of_qids", []) if isinstance(x, str)]))
                if expected_inst != got_inst:
                    processed_ok = False
                    break
                # sitelinks_count must match
                if item.get("sitelinks_count") != facts.get("sitelinks_count"):
                    processed_ok = False
                    break
    if processed_ok:
        scores["processed_entities_correct"] = 1.0

    # Check validation report correctness
    report_ok = True
    report_path = workspace / "artifacts" / "report.md"
    report_text = safe_read_text(report_path)
    if not (isinstance(report_text, str) and processed_ok and mapping_valid and raw_ok):
        report_ok = False
    else:
        lines = report_text.splitlines()
        # Build a map of qid -> (line_idx, text around)
        text_by_qid: Dict[str, Tuple[int, List[str]]] = {}
        for i, line in enumerate(lines):
            for t in topics:
                m = mapping_by_slug.get(t["slug"])
                if not m:
                    continue
                qid = m["qid"]
                if qid in line:
                    neighborhood = [lines[i]]
                    if i + 1 < len(lines):
                        neighborhood.append(lines[i + 1])
                    if i + 2 < len(lines):
                        neighborhood.append(lines[i + 2])
                    text_by_qid[qid] = (i, neighborhood)
        # For each topic, determine expected pass/fail from description_en and check report mentions
        for t in topics:
            m = mapping_by_slug.get(t["slug"])
            if not m:
                report_ok = False
                break
            qid = m["qid"]
            facts = raw_facts.get(qid, {})
            desc = facts.get("description_en") or ""
            expected_keywords = [kw for kw in t.get("expect_keywords", []) if isinstance(kw, str)]
            matched = [kw for kw in expected_keywords if kw.lower() in desc.lower()]
            expected_pass = len(matched) > 0

            if qid not in text_by_qid:
                report_ok = False
                break
            _, neigh = text_by_qid[qid]
            blob = "\n".join(neigh)
            blob_l = blob.lower()
            has_pass_word = bool(re.search(r'\bpass\b', blob_l))
            has_fail_word = bool(re.search(r'\bfail\b', blob_l))
            # Must include either pass or fail
            if expected_pass:
                if not has_pass_word or has_fail_word:
                    report_ok = False
                    break
                # Should include at least one matched keyword in vicinity
                has_kw_in_report = any(kw.lower() in blob_l for kw in expected_keywords)
                if not has_kw_in_report:
                    report_ok = False
                    break
            else:
                if not has_fail_word or has_pass_word:
                    report_ok = False
                    break
                # Should not include any expected keyword near this entry
                has_kw_in_report = any(kw.lower() in blob_l for kw in expected_keywords)
                # Allow keywords to appear if clearly marked as empty? We can't detect structure, so be strict: no keywords should appear.
                if has_kw_in_report:
                    report_ok = False
                    break
    if report_ok:
        scores["validation_report_correct"] = 1.0

    # Check checksums completeness and correctness
    checksums_ok = True
    checksums_path = workspace / "artifacts" / "checksums.sha256"
    entries = parse_checksums(checksums_path)
    if entries is None:
        checksums_ok = False
    else:
        # Build a lookup from normalized end path to list of hashes
        recorded: List[Tuple[str, str]] = []
        for h, p in entries:
            recorded.append((h, p))

        # Collect actual files under artifacts/raw and artifacts/processed
        to_check: List[Path] = []
        for base_rel in ["artifacts/raw", "artifacts/processed"]:
            base = workspace / base_rel
            if base.exists() and base.is_dir():
                for fp in base.rglob("*"):
                    if fp.is_file():
                        to_check.append(fp)

        if len(to_check) == 0:
            checksums_ok = False
        else:
            for f in to_check:
                rel = f.relative_to(workspace).as_posix()
                actual_hash = compute_sha256(f)
                if actual_hash is None:
                    checksums_ok = False
                    break
                # Find a matching entry
                found_match = False
                for h, p in recorded:
                    # Normalize path token: check if it endswith the relative path or equals it
                    p_norm = p.replace("\\", "/")
                    if p_norm.endswith("/" + rel) or p_norm.endswith(rel) or p_norm == rel:
                        if h.lower() == actual_hash.lower():
                            found_match = True
                            break
                if not found_match:
                    checksums_ok = False
                    break
    if checksums_ok:
        scores["checksums_complete_and_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()