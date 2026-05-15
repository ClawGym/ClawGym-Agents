import json
import os
import sys
import hashlib
import re
from datetime import datetime

def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def is_hex_64(s: str) -> bool:
    return isinstance(s, str) and re.fullmatch(r"[0-9a-fA-F]{64}", s or "") is not None

def is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False

def recompute_block_hash(block: dict) -> str:
    # For archival chain blocks: compute SHA-256 over canonical JSON of the block excluding "hash"
    data = {k: v for k, v in block.items() if k != "hash"}
    # Canonicalize deterministically
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def validate_archival_chain(archival_path: str):
    """
    Returns (valid: bool, head: str|None)
    Validates:
      - file exists and has fields: chain (list), head (hex)
      - each block's hash matches recomputed hash
      - previous_hash linkage correct
      - final head equals last block's hash
    """
    if not os.path.isfile(archival_path):
        return False, None
    try:
        data = load_json(archival_path)
        chain = data.get("chain")
        head = data.get("head")
        if not isinstance(chain, list) or not chain:
            return False, None
        if not is_hex_64(head):
            return False, None
        prev = "0" * 64
        for i, block in enumerate(chain):
            if not isinstance(block, dict):
                return False, None
            # Check linkage
            if i == 0:
                if block.get("previous_hash") != prev:
                    return False, None
            else:
                if block.get("previous_hash") != chain[i - 1].get("hash"):
                    return False, None
            # Check hash recomputation
            stored_h = block.get("hash")
            if not is_hex_64(stored_h):
                return False, None
            recomputed = recompute_block_hash(block)
            if stored_h.lower() != recomputed.lower():
                return False, None
            prev = stored_h
        if chain[-1].get("hash", "").lower() != head.lower():
            return False, None
        return True, head.lower()
    except Exception:
        return False, None

def validate_ledger_chain(ledger_path: str, anchor_hex: str):
    """
    Returns (valid: bool, head: str|None)
    Validates:
      - file exists and has at least 1 JSONL entry
      - each entry's previous_hash equals prior entry's hash
      - first entry's previous_hash equals computed anchor_hex
      - last entry's hash is a 64-hex string and returned as head
    Note: We do not recompute per-entry hashes due to unspecified canonicalization; we validate linkage and root.
    """
    if not os.path.isfile(ledger_path):
        return False, None
    try:
        entries = []
        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entries.append(json.loads(line))
        if not entries:
            return False, None
        # Root check
        first_prev = entries[0].get("previous_hash")
        if not (isinstance(first_prev, str) and first_prev.lower() == anchor_hex.lower()):
            return False, None
        # Linkage checks
        for i in range(1, len(entries)):
            prev_hash = entries[i].get("previous_hash")
            prior_hash = entries[i - 1].get("hash")
            if not (isinstance(prev_hash, str) and isinstance(prior_hash, str)):
                return False, None
            if prev_hash.lower() != prior_hash.lower():
                return False, None
        last_hash = entries[-1].get("hash")
        if not is_hex_64(last_hash or ""):
            return False, None
        return True, last_hash.lower()
    except Exception:
        return False, None

def find_topic_files(dir_path: str):
    """
    Find the two topic files:
      - YYMMDD Lineage-Custody.md
      - YYMMDD Ledger-Best-Practices.md
    Returns dict with keys 'lineage' and 'ledger' mapping to filenames (basename only) if found, else None values.
    """
    result = {"lineage": None, "ledger": None}
    if not os.path.isdir(dir_path):
        return result
    for name in os.listdir(dir_path):
        if not name.lower().endswith(".md"):
            continue
        # skip overview
        if name == "000.Research-Overview.md":
            continue
        # match pattern: 6 digits, space, rest
        if re.match(r"^\d{6}\s.+\.md$", name):
            if name.endswith("Lineage-Custody.md"):
                result["lineage"] = name
            elif name.endswith("Ledger-Best-Practices.md"):
                result["ledger"] = name
    return result

def file_has_inline_link(path: str) -> bool:
    try:
        text = read_text(path)
        return re.search(r"https?://", text) is not None
    except Exception:
        return False

def file_has_generated_line(path: str) -> bool:
    try:
        text = read_text(path)
        # Look for a line starting with "Generated:"
        for line in text.splitlines():
            if line.startswith("Generated:"):
                return True
        return False
    except Exception:
        return False

def verify_formatted_quality(path: str) -> bool:
    """
    Check formatting constraints:
      - no trailing whitespace on any line
      - no occurrence of three or more consecutive blank lines
      - no setext underline (=== or ---) heading lines -> implies headings should be ATX (#)
    """
    try:
        content = read_text(path)
        # Normalize line endings just for detection
        norm = content.replace("\r\n", "\n").replace("\r", "\n")
        # No 3+ consecutive blank lines
        if "\n\n\n" in norm:
            return False
        # No trailing whitespace
        for raw_line in norm.split("\n"):
            # do not consider newline at end, check spaces/tabs at end of line
            if raw_line.rstrip("\t ").rstrip("\n") != raw_line.rstrip("\n"):
                return False
        # No setext style heading underline lines
        for raw_line in norm.split("\n"):
            if re.fullmatch(r"\s*[=-]{3,}\s*", raw_line):
                return False
        return True
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks with False
    checks = {
        # Input-derived validations (do not contribute positive reward directly)
        "anchor_read": False,
        "archival_input_valid": False,
        "ledger_input_valid": False,

        # Output existence/validity checks (contribute to reward)
        "attestation_exists": False,
        "attestation_valid": False,

        "badge_exists": False,
        "badge_valid": False,

        "summary_exists": False,
        "summary_has_confirmation": False,

        "research_overview_exists": False,
        "research_topics_exist_and_named": False,
        "research_topics_content_valid": False,

        "formatted_copies_exist": False,
        "formatted_copies_clean": False,

        "injector_config_valid": False,
        "injector_preview_valid": False,
    }

    # Prepare inputs
    anchor_components_path = os.path.join(input_dir, "anchor_components.txt")
    archival_path = os.path.join(input_dir, "archival_chain.json")
    ledger_path = os.path.join(input_dir, "audit_ledger.jsonl")

    anchor_bytes = None
    anchor_text = None
    anchor_hex = None

    # Read anchor components and compute SHA-256 over exact bytes
    try:
        anchor_bytes = read_bytes(anchor_components_path)
        anchor_text = anchor_bytes.decode("utf-8")
        anchor_hex = hashlib.sha256(anchor_bytes).hexdigest()
        checks["anchor_read"] = True
    except Exception:
        anchor_bytes = None
        anchor_text = None
        anchor_hex = None

    # Validate archival input
    archival_valid, archival_head = validate_archival_chain(archival_path)
    checks["archival_input_valid"] = archival_valid

    # Validate ledger input
    ledger_valid, ledger_head = (False, None)
    if anchor_hex is not None:
        ledger_valid, ledger_head = validate_ledger_chain(ledger_path, anchor_hex)
    checks["ledger_input_valid"] = ledger_valid

    # Output paths
    verification_dir = os.path.join(output_dir, "verification")
    summary_path = os.path.join(verification_dir, "summary.txt")
    attestation_path = os.path.join(verification_dir, "attestation.json")
    badge_path = os.path.join(verification_dir, "badge.json")

    research_base = os.path.join(output_dir, "research", "Governance-Lineage-Audit", "03 - Deep Research")
    overview_path = os.path.join(research_base, "000.Research-Overview.md")
    topics = find_topic_files(research_base)

    formatted_base = os.path.join(output_dir, "research_formatted", "Governance-Lineage-Audit", "03 - Deep Research")

    config_dir = os.path.join(output_dir, "config")
    injector_config_path = os.path.join(config_dir, "injector_config.json")
    injector_preview_path = os.path.join(config_dir, "injector_preview.txt")

    # Check summary.txt
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            summ = read_text(summary_path)
            # Last non-empty line
            last_non_empty = ""
            for line in reversed(summ.splitlines()):
                if line.strip():
                    last_non_empty = line.rstrip("\n")
                    break
            if last_non_empty == "SOVEREIGN CUSTODY CONFIRMED":
                checks["summary_has_confirmation"] = True
        except Exception:
            pass

    # Check attestation.json
    if os.path.isfile(attestation_path):
        checks["attestation_exists"] = True
        try:
            att = load_json(attestation_path)
            la = att.get("lineage_anchor")
            chain_valid = att.get("chain_valid")
            layers = att.get("layers", {})
            live_head_out = att.get("live_ledger_head")
            archival_head_out = att.get("archival_head")
            comp_str = att.get("anchor_components")
            gen_at = att.get("generated_at")

            att_ok = True
            # Basic fields
            if not (isinstance(la, str) and is_hex_64(la) and anchor_hex and la.lower() == anchor_hex.lower()):
                att_ok = False
            if chain_valid is not True:
                att_ok = False
            # Layers statuses must be "OK"
            if not (isinstance(layers, dict) and layers.get("archival") == "OK" and layers.get("anchor") == "OK" and layers.get("live") == "OK"):
                att_ok = False
            # Cross-validate with input-derived validations
            if not (checks["archival_input_valid"] and checks["ledger_input_valid"] and checks["anchor_read"]):
                att_ok = False
            # live_ledger_head equals last hash from input ledger
            if not (isinstance(live_head_out, str) and is_hex_64(live_head_out) and ledger_head and live_head_out.lower() == ledger_head.lower()):
                att_ok = False
            # archival_head equals head from input archival
            if not (isinstance(archival_head_out, str) and is_hex_64(archival_head_out) and archival_head and archival_head_out.lower() == archival_head.lower()):
                att_ok = False
            # anchor_components equals exact file content
            if not (isinstance(comp_str, str) and anchor_text is not None and comp_str == anchor_text):
                att_ok = False
            # generated_at iso
            if not is_iso8601(gen_at):
                att_ok = False

            checks["attestation_valid"] = att_ok
        except Exception:
            checks["attestation_valid"] = False

    # Check badge.json
    if os.path.isfile(badge_path):
        checks["badge_exists"] = True
        try:
            badge = load_json(badge_path)
            la = badge.get("lineage_anchor")
            patent_serial = badge.get("patent_serial")
            doi = badge.get("doi")
            entity = badge.get("entity")
            custody_status = badge.get("custody_status")

            badge_ok = True
            if not (isinstance(la, str) and is_hex_64(la) and anchor_hex and la.lower() == anchor_hex.lower()):
                badge_ok = False
            if not (isinstance(patent_serial, str) and len(patent_serial.strip()) > 0):
                badge_ok = False
            if not (isinstance(doi, str) and len(doi.strip()) > 0):
                badge_ok = False
            if not (isinstance(entity, str) and len(entity.strip()) > 0):
                badge_ok = False
            if custody_status not in ("sovereign", "not-sovereign"):
                badge_ok = False
            # Must be "sovereign" and align with input-derived computed validity
            chain_all_ok = checks["archival_input_valid"] and checks["ledger_input_valid"] and checks["anchor_read"]
            if not (custody_status == "sovereign" and chain_all_ok):
                badge_ok = False

            checks["badge_valid"] = badge_ok
        except Exception:
            checks["badge_valid"] = False

    # Research outputs
    if os.path.isfile(overview_path):
        checks["research_overview_exists"] = True

    topics_exist_named = False
    topics_content_ok = False
    lineage_file = topics.get("lineage")
    ledger_file = topics.get("ledger")
    if lineage_file and ledger_file:
        topics_exist_named = True
        lineage_path = os.path.join(research_base, lineage_file)
        ledger_topic_path = os.path.join(research_base, ledger_file)
        # Validate content requirements for both topic files
        lineage_ok = file_has_inline_link(lineage_path) and file_has_generated_line(lineage_path)
        ledger_ok = file_has_inline_link(ledger_topic_path) and file_has_generated_line(ledger_topic_path)
        topics_content_ok = lineage_ok and ledger_ok

        # Formatted copies checks
        formatted_lineage_path = os.path.join(formatted_base, lineage_file)
        formatted_ledger_path = os.path.join(formatted_base, ledger_file)
        if os.path.isfile(formatted_lineage_path) and os.path.isfile(formatted_ledger_path):
            checks["formatted_copies_exist"] = True
            f_lineage_ok = verify_formatted_quality(formatted_lineage_path)
            f_ledger_ok = verify_formatted_quality(formatted_ledger_path)
            checks["formatted_copies_clean"] = f_lineage_ok and f_ledger_ok

    checks["research_topics_exist_and_named"] = topics_exist_named
    checks["research_topics_content_valid"] = topics_content_ok

    # Injector config and preview
    try:
        cfg = load_json(injector_config_path)
        enabled = cfg.get("enabled")
        prepend = cfg.get("prependText")
        if enabled is True and isinstance(prepend, str) and len(prepend) >= 20:
            # Preview check depends on config
            checks["injector_config_valid"] = True
            if os.path.isfile(injector_preview_path):
                preview = read_text(injector_preview_path)
                if preview.startswith(prepend + "\n") and len(preview) > len(prepend) + 1:
                    checks["injector_preview_valid"] = True
    except Exception:
        pass

    # Compute reward: only count output-dependent checks
    scored_keys = [
        "attestation_valid",
        "badge_valid",
        "summary_has_confirmation",
        "research_overview_exists",
        "research_topics_exist_and_named",
        "research_topics_content_valid",
        "formatted_copies_exist",
        "formatted_copies_clean",
        "injector_config_valid",
        "injector_preview_valid",
    ]
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    total = len(scored_keys)
    reward = (passed / total) if total > 0 else 0.0

    # Print single JSON line
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()