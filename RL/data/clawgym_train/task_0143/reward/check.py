import json
import os
import sys
import csv
from datetime import date, datetime
from typing import Dict, List, Tuple

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def joinp(*parts):
    return os.path.join(*parts)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def slugify(name: str) -> str:
    import re
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def parse_yaml_thresholds(yaml_text: str) -> Dict[str, int]:
    # Minimal YAML key: value parser for flat mappings
    thresholds = {}
    for line in yaml_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove quotes if present
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        # Try int
        try:
            thresholds[key] = int(val)
        except ValueError:
            # ignore non-int
            pass
    return thresholds

def load_inputs(input_dir: str):
    # contacts.json
    contacts_path = joinp(input_dir, "contacts.json")
    relationships_path = joinp(input_dir, "relationships.csv")
    notes_path = joinp(input_dir, "notes.jsonl")
    thresholds_path = joinp(input_dir, "stale_thresholds.yaml")
    as_of_path = joinp(input_dir, "as_of.txt")

    with open(contacts_path, "r", encoding="utf-8") as f:
        contacts = json.load(f)

    # Build nodes
    nodes = {}
    display_by_slug = {}
    for c in contacts:
        name = c.get("name", "").strip()
        slug = slugify(name)
        display_by_slug[slug] = name
        tags = c.get("tags", []) or []
        tags_lc = [t.lower() for t in tags]
        org = c.get("org", "") or ""
        role = c.get("role", "") or ""
        tier = (c.get("tier", "") or "").lower()
        met = c.get("met", "") or ""
        last_contact = c.get("last_contact", "") or ""
        node = {
            "displayName": name,
            "tags": tags_lc,
            "org": org,
            "role": role,
            "met": met,
            "lastContact": last_contact,
            "tier": tier,
            "notes": [],
            "file": f"_{slug}.md",
        }
        nodes[slug] = node

    # Notes
    if os.path.isfile(notes_path):
        with open(notes_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                person = obj.get("person", "").strip()
                text = obj.get("text", "").strip()
                nd = obj.get("date", "").strip()
                if not person or not text or not nd:
                    continue
                slug = slugify(person)
                if slug not in nodes:
                    # Skip notes for unknown people
                    continue
                nodes[slug]["notes"].append({"date": nd, "text": text})
                # Update lastContact if note date later
                try:
                    note_dt = date.fromisoformat(nd)
                except ValueError:
                    note_dt = None
                try:
                    current_lc_dt = date.fromisoformat(nodes[slug]["lastContact"]) if nodes[slug]["lastContact"] else None
                except ValueError:
                    current_lc_dt = None
                if note_dt:
                    if current_lc_dt is None or note_dt > current_lc_dt:
                        nodes[slug]["lastContact"] = note_dt.isoformat()

    # Edges
    edges = []
    if os.path.isfile(relationships_path):
        with open(relationships_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                from_name = (row.get("from") or row.get("From") or "").strip()
                to_name = (row.get("to") or row.get("To") or "").strip()
                label = (row.get("label") or row.get("Label") or "").strip()
                if not from_name or not to_name:
                    continue
                fs = slugify(from_name)
                ts = slugify(to_name)
                if fs in nodes and ts in nodes:
                    edges.append({"from": fs, "to": ts, "label": label})

    # Thresholds
    thresholds = {"close": 14, "regular": 30, "acquaintance": 90}
    if os.path.isfile(thresholds_path):
        yaml_text = read_text(thresholds_path)
        t = parse_yaml_thresholds(yaml_text)
        # merge known keys only
        for k in ["close", "regular", "acquaintance"]:
            if k in t and isinstance(t[k], int):
                thresholds[k] = t[k]

    # As-of date
    as_of_str = read_text(as_of_path).strip() if os.path.isfile(as_of_path) else ""
    as_of = None
    try:
        as_of = date.fromisoformat(as_of_str)
    except Exception:
        as_of = None

    return nodes, edges, thresholds, as_of

def normalize_tags(tags: List[str]) -> List[str]:
    return [t.lower() for t in tags]

def compare_notes_set(a: List[Dict], b: List[Dict]) -> bool:
    sa = {(n.get("date",""), n.get("text","")) for n in a}
    sb = {(n.get("date",""), n.get("text","")) for n in b}
    return sa == sb

def read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_markdown_person(md_text: str):
    # Returns dict with keys: title, bullets, notes, connections
    lines = [ln.rstrip("\n") for ln in md_text.splitlines()]
    title = lines[0].strip() if lines else ""
    bullets = {}
    section = None
    notes = []
    connections = []
    for i, ln in enumerate(lines[1:], start=1):
        s = ln.strip()
        if s.startswith("## "):
            header = s[3:].strip().lower()
            if header == "notes":
                section = "notes"
            elif header == "connections":
                section = "connections"
            else:
                section = None
            continue
        if s.startswith("- **Tags:**"):
            bullets["tags"] = s[len("- **Tags:**"):].strip()
            continue
        if s.startswith("- **Org:**"):
            bullets["org"] = s[len("- **Org:**"):].strip()
            continue
        if s.startswith("- **Role:**"):
            bullets["role"] = s[len("- **Role:**"):].strip()
            continue
        if s.startswith("- **Met:**"):
            bullets["met"] = s[len("- **Met:**"):].strip()
            continue
        if s.startswith("- **Last contact:**"):
            bullets["last_contact"] = s[len("- **Last contact:**"):].strip()
            continue
        if s.startswith("- **Tier:**"):
            bullets["tier"] = s[len("- **Tier:**"):].strip()
            continue
        if section == "notes" and s.startswith("- "):
            # "- YYYY-MM-DD — text"
            payload = s[2:].strip()
            # Split on ' — '
            sep = " — "
            if sep in payload:
                date_part, text_part = payload.split(sep, 1)
                notes.append({"date": date_part.strip(), "text": text_part.strip()})
            else:
                # Fallback: treat whole as text with empty date
                notes.append({"date": "", "text": payload})
        if section == "connections" and s.startswith("- "):
            # "- [[Other Name]] — label"
            payload = s[2:].strip()
            # Expect [[Name]] — label
            other_name = None
            label = ""
            if payload.startswith("[["):
                # find closing ]]
                end = payload.find("]]")
                if end != -1:
                    other_name = payload[2:end].strip()
                    rem = payload[end+2:].strip()
                    if rem.startswith("—"):
                        label = rem[1:].strip()
                    elif rem.startswith("— "):
                        label = rem[2:].strip()
                    elif rem.startswith("—"):
                        label = rem[1:].strip()
                    elif rem.startswith("—"):
                        label = rem[1:].strip()
                    elif rem.startswith("-"):
                        # hyphen instead of em dash, try split on '—' later
                        parts = rem.split("—", 1)
                        if len(parts) == 2:
                            label = parts[1].strip()
                        else:
                            label = rem.strip("— -").strip()
                    else:
                        # Try split with em dash explicitly
                        if " — " in payload:
                            _, label = payload.split(" — ", 1)
                            label = label.strip()
                else:
                    other_name = None
            # If we couldn't parse with brackets, try fallback
            if other_name is None:
                # attempt to split on ' — '
                if " — " in payload:
                    left, label = payload.split(" — ", 1)
                    other_name = left.strip().strip("[]")
                else:
                    other_name = payload.strip().strip("[]")
            connections.append({"other": other_name, "label": label})
    return {
        "title": title,
        "bullets": bullets,
        "notes": notes,
        "connections": connections,
    }

def parse_mermaid(md_text: str):
    lines = [ln.strip() for ln in md_text.splitlines() if ln.strip() != ""]
    if not lines:
        return None, set(), set()
    header = lines[0]
    node_defs = set()
    edge_defs = set()
    for ln in lines[1:]:
        # Node pattern: slug["Display Name"]
        if "[" in ln and "]" in ln and "--" not in ln and "-->" not in ln:
            # Extract slug before first [
            try:
                slug = ln.split("[", 1)[0].strip()
                disp = ln.split("[", 1)[1]
                disp = disp.split("]", 1)[0]
                # Strip quotes inside if present
                disp = disp.strip().strip('"').strip("'")
                node_defs.add((slug, disp))
                continue
            except Exception:
                pass
        # Edge pattern: from -- "label" --> to OR from --> to
        if "-->" in ln:
            try:
                left, to_part = ln.split("-->", 1)
                left = left.strip()
                to_slug = to_part.strip()
                if "--" in left:
                    frm, label_part = left.split("--", 1)
                    frm = frm.strip()
                    label = label_part.strip()
                    # label in quotes: "text"
                    if label.startswith('"') and '"' in label[1:]:
                        # Extract within quotes
                        first = label.find('"')
                        second = label.find('"', first + 1)
                        if second > first:
                            label_text = label[first+1:second]
                        else:
                            label_text = label.strip('"')
                    else:
                        label_text = label.strip('"')
                    edge_defs.add((frm, to_slug, label_text))
                else:
                    frm = left.strip()
                    edge_defs.add((frm, to_slug, ""))  # no label
            except Exception:
                pass
    return header, node_defs, edge_defs

def compute_stale(nodes: Dict[str, Dict], thresholds: Dict[str, int], as_of: date) -> List[Tuple[str, str, int]]:
    if as_of is None:
        return []
    stale = []
    for slug, node in nodes.items():
        tier = (node.get("tier") or "acquaintance").lower()
        lc_str = node.get("lastContact") or ""
        try:
            lc = date.fromisoformat(lc_str)
        except Exception:
            continue
        days = (as_of - lc).days
        th = thresholds.get(tier, thresholds.get("acquaintance", 90))
        if days > th:
            stale.append((node["displayName"], tier, days))
    # Sort by tier order
    order = {"close": 0, "regular": 1, "acquaintance": 2}
    stale.sort(key=lambda x: (order.get(x[1], 99), x[0].lower()))
    return stale

def main():
    workspace_root = get_workspace_root()
    input_dir = joinp(workspace_root, "input")
    output_dir = joinp(workspace_root, "output")
    people_dir = joinp(output_dir, "people")

    checks = {
        "graph_exists_and_valid": False,
        "nodes_match": False,
        "edges_match": False,
        "markdown_people_files_exist": False,
        "markdown_bullets_match": False,
        "markdown_notes_match": False,
        "markdown_connections_match": False,
        "mermaid_valid": False,
        "stale_report_valid": False,
    }

    # Load expected from inputs
    try:
        expected_nodes, expected_edges, thresholds, as_of = load_inputs(input_dir)
    except Exception:
        # If inputs are unreadable, no positive reward
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Compute expected stale list
    expected_stale = compute_stale(expected_nodes, thresholds, as_of)

    # Check graph file
    graph_path = joinp(people_dir, "_graph.json")
    graph = read_json_file(graph_path)
    if isinstance(graph, dict) and "nodes" in graph and "edges" in graph:
        checks["graph_exists_and_valid"] = True

        # Nodes match
        try:
            out_nodes: Dict[str, Dict] = graph["nodes"]
            out_edges: List[Dict] = graph["edges"] if isinstance(graph["edges"], list) else []
            expected_slugs = set(expected_nodes.keys())
            out_slugs = set(out_nodes.keys())

            nodes_ok = out_slugs == expected_slugs and len(out_slugs) == len(expected_slugs)
            # Field-by-field checks
            fields_ok = True
            if nodes_ok:
                for slug in expected_slugs:
                    exp = expected_nodes[slug]
                    got = out_nodes.get(slug, {})
                    # Required fields presence
                    required_fields = ["displayName", "tags", "org", "role", "met", "lastContact", "tier", "notes", "file"]
                    for rf in required_fields:
                        if rf not in got:
                            fields_ok = False
                            break
                    if not fields_ok:
                        break
                    # displayName
                    if got["displayName"] != exp["displayName"]:
                        fields_ok = False
                        break
                    # tags lowercased set
                    exp_tags = set([t.lower() for t in exp.get("tags", [])])
                    got_tags = got.get("tags", [])
                    if not isinstance(got_tags, list):
                        fields_ok = False
                        break
                    got_tags_set = set([str(t).lower() for t in got_tags])
                    if got_tags_set != exp_tags:
                        fields_ok = False
                        break
                    # org, role, met, lastContact, tier
                    for key in ["org", "role", "met", "lastContact", "tier"]:
                        if (got.get(key) or "") != (exp.get(key) or ""):
                            fields_ok = False
                            break
                    if not fields_ok:
                        break
                    # file name
                    if got.get("file") != f"_{slug}.md":
                        fields_ok = False
                        break
                    # notes compare as set of (date, text)
                    got_notes = got.get("notes", [])
                    if not isinstance(got_notes, list):
                        fields_ok = False
                        break
                    exp_notes = exp.get("notes", [])
                    if compare_notes_set(got_notes, exp_notes) is False:
                        fields_ok = False
                        break
            if nodes_ok and fields_ok:
                checks["nodes_match"] = True

            # Edges match (as set)
            exp_edges_set = {(e["from"], e["to"], e.get("label", "")) for e in expected_edges}
            out_edges_set = set()
            try:
                for e in out_edges:
                    out_edges_set.add((e.get("from",""), e.get("to",""), e.get("label","")))
            except Exception:
                out_edges_set = set()
            if out_edges_set == exp_edges_set and len(out_edges_set) == len(exp_edges_set):
                checks["edges_match"] = True
        except Exception:
            pass

    # Check Markdown cards
    md_all_exist = True
    bullets_ok = True
    notes_ok = True
    conns_ok = True
    if expected_nodes:
        for slug, node in expected_nodes.items():
            md_path = joinp(people_dir, f"_{slug}.md")
            if not os.path.isfile(md_path):
                md_all_exist = False
                bullets_ok = False
                notes_ok = False
                conns_ok = False
                break
            md_text = read_text(md_path)
            parsed = parse_markdown_person(md_text)
            # Title line
            if parsed["title"] != f"# {node['displayName']}":
                bullets_ok = False
            # Bullets presence and correctness
            b = parsed["bullets"]
            # Validate presence of required bullet keys
            required_bullets = ["tags", "org", "role", "met", "last_contact", "tier"]
            for rb in required_bullets:
                if rb not in b:
                    bullets_ok = False
                    break
            if bullets_ok:
                # Tags
                tag_line = b["tags"]
                # parse tags as '#tag' tokens
                tags_found = [t[1:] for t in tag_line.split() if t.startswith("#")]
                if set([t.lower() for t in tags_found]) != set([t.lower() for t in node.get("tags", [])]):
                    bullets_ok = False
                # Org, Role, Met, Last contact, Tier
                if b["org"] != (node.get("org","")):
                    bullets_ok = False
                if b["role"] != (node.get("role","")):
                    bullets_ok = False
                if b["met"] != (node.get("met","")):
                    bullets_ok = False
                if b["last_contact"] != (node.get("lastContact","")):
                    bullets_ok = False
                if b["tier"] != (node.get("tier","")):
                    bullets_ok = False
            # Notes
            # parsed notes as list of dicts with date,text
            if compare_notes_set(parsed["notes"], node.get("notes", [])) is False:
                notes_ok = False
            # Connections
            # Build expected connections for this node
            expected_conns = set()
            for e in (e for e in expected_edges if e["from"] == slug or e["to"] == slug):
                other_slug = e["to"] if e["from"] == slug else e["from"]
                other_name = expected_nodes.get(other_slug, {}).get("displayName", other_slug)
                label = e.get("label","")
                expected_conns.add((other_name, label))
            actual_conns = set((c.get("other",""), c.get("label","")) for c in parsed["connections"])
            # If there are no expected connections, allow missing section (actual_conns may be empty)
            if actual_conns != expected_conns:
                conns_ok = False

    if expected_nodes:
        if md_all_exist:
            checks["markdown_people_files_exist"] = True
        if md_all_exist and bullets_ok:
            checks["markdown_bullets_match"] = True
        if md_all_exist and notes_ok:
            checks["markdown_notes_match"] = True
        if md_all_exist and conns_ok:
            checks["markdown_connections_match"] = True

    # Mermaid
    mermaid_path = joinp(people_dir, "mermaid.md")
    if os.path.isfile(mermaid_path):
        mermaid_text = read_text(mermaid_path)
        header, node_defs, edge_defs = parse_mermaid(mermaid_text)
        try:
            header_ok = header == "graph LR"
            # Nodes set
            exp_node_defs = set((slug, expected_nodes[slug]["displayName"]) for slug in expected_nodes.keys())
            nodes_ok = node_defs == exp_node_defs
            # Edges with labels must include labels in quotes in file,
            # Our parse has captured labels without quotes. We only compare content.
            exp_edge_defs = set((e["from"], e["to"], e.get("label","")) for e in expected_edges)
            edges_ok = edge_defs == exp_edge_defs
            if header_ok and nodes_ok and edges_ok:
                checks["mermaid_valid"] = True
        except Exception:
            pass

    # Staleness report
    stale_path = joinp(output_dir, "stale_report.txt")
    if os.path.isfile(stale_path):
        text = read_text(stale_path)
        lines = [ln.rstrip("\n") for ln in text.splitlines()]
        # Remove trailing/leading empty lines
        lines = [ln for ln in lines if ln is not None]
        # Expected formatting
        ok = True
        if not lines:
            ok = False
        else:
            if lines[0].strip() != "🔔 *Relationship check-in*":
                ok = False
            # Build expected lines
            tier_emoji = {"close": "❤️", "regular": "👋", "acquaintance": "📇"}
            expected_lines = []
            for name, tier, days in expected_stale:
                emoji = tier_emoji.get(tier, "•")
                expected_lines.append(f"{emoji} *{name}* ({tier}) — last contact: {days}d ago")
            # Closing line:
            closing = "Consider reaching out to keep these connections warm!"
            # Now compare
            # lines structure: header, stale lines..., closing
            # Allow no extra blank lines
            if len(lines) != (1 + len(expected_lines) + 1):
                ok = False
            else:
                # Compare stale lines
                for i, exp_line in enumerate(expected_lines, start=1):
                    if lines[i].strip() != exp_line:
                        ok = False
                        break
                if lines[-1].strip() != closing:
                    ok = False
        if ok:
            checks["stale_report_valid"] = True

    # Compute reward as fraction of passed checks, baseline 0 if nothing produced
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if passed > 0 else 0.0
    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()