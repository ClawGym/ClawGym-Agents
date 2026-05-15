import argparse
import csv
import datetime
import json
import os


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    required_top = ["event_title", "proposed_date", "max_minutes", "modules"]
    for k in required_top:
        if k not in cfg:
            raise ValueError(f"Missing required config key: {k}")
    for i, m in enumerate(cfg["modules"]):
        for k in ["title", "duration", "facilitator", "risk_flag"]:
            if k not in m:
                raise ValueError(f"Module {i} missing key: {k}
")
    return cfg


def scale_modules(modules, max_minutes):
    # Returns (adjusted_modules, total_before, total_after)
    total_before = sum(int(m["duration"]) for m in modules)
    if total_before <= max_minutes:
        # copy modules to avoid mutating input
        adjusted = [dict(m) for m in modules]
        return adjusted, total_before, total_before

    scale = max_minutes / float(total_before)
    adjusted = []
    for m in modules:
        new_m = dict(m)
        new_duration = max(5, int(round(int(m["duration"]) * scale)))
        new_m["duration"] = new_duration
        adjusted.append(new_m)

    total_after = sum(m["duration"] for m in adjusted)
    # If rounding caused overflow, reduce longest items down to min 5 until we fit
    adjusted.sort(key=lambda x: x["duration"], reverse=True)
    idx = 0
    while total_after > max_minutes and any(m["duration"] > 5 for m in adjusted):
        if adjusted[idx]["duration"] > 5:
            adjusted[idx]["duration"] -= 1
            total_after -= 1
        idx = (idx + 1) % len(adjusted)
    # Restore original order by referencing original titles
    title_order = [m["title"] for m in modules]
    adjusted.sort(key=lambda m: title_order.index(m["title"]))
    return adjusted, total_before, total_after


def write_agenda(out_dir, cfg, modules, total_before, total_after):
    os.makedirs(out_dir, exist_ok=True)
    agenda_path = os.path.join(out_dir, "agenda.md")
    lines = []
    lines.append(f"# {cfg['event_title']} - Dialogue Workshop Agenda")
    lines.append("")
    lines.append(f"Date: {cfg['proposed_date']}")
    lines.append(f"Max minutes: {cfg['max_minutes']}")
    lines.append(f"Total scheduled minutes: {total_after} (from {total_before})")
    lines.append("")
    lines.append("Modules:")
    risk_count = 0
    for i, m in enumerate(modules, start=1):
        risk = "Yes" if m.get("risk_flag") else "No"
        if m.get("risk_flag"):
            risk_count += 1
        lines.append(f"{i}. {m['title']} — {m['duration']} minutes — Facilitator: {m['facilitator']} — Risk: {risk}")
    lines.append("")
    lines.append(f"Risk-flagged modules: {risk_count}")

    with open(agenda_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    return agenda_path


def compute_topics(concerns_csv_path):
    totals = {}
    top_item = {}
    with open(concerns_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = row['category'].strip()
            concern = row['concern'].strip()
            votes = int(row['votes'])
            totals[category] = totals.get(category, 0) + votes
            # Track highest-vote concern per category
            prev = top_item.get(category)
            if prev is None or votes > prev['votes']:
                top_item[category] = {'concern': concern, 'votes': votes}
    # Select top 3 categories by total votes
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    top_categories = []
    for cat, total in ranked:
        top_categories.append({
            'category': cat,
            'total_votes': total,
            'top_concern': top_item[cat]
        })
    return top_categories


def write_topics(out_dir, top_categories):
    os.makedirs(out_dir, exist_ok=True)
    topics_path = os.path.join(out_dir, 'topics.json')
    data = {
        'top_categories': top_categories,
        'generated_at': datetime.date.today().isoformat()
    }
    with open(topics_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return topics_path


def main():
    parser = argparse.ArgumentParser(description='Build workshop agenda and top concerns.')
    parser.add_argument('--config', required=True, help='Path to workshop_config.json')
    parser.add_argument('--concerns', required=True, help='Path to concerns CSV')
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    cfg = load_config(args.config)
    adjusted_modules, total_before, total_after = scale_modules(cfg['modules'], int(cfg['max_minutes']))

    agenda_path = write_agenda(args.out, cfg, adjusted_modules, total_before, total_after)
    top_categories = compute_topics(args.concerns)
    topics_path = write_topics(args.out, top_categories)

    print(f"Wrote {agenda_path}")
    print(f"Wrote {topics_path}")
    if total_after > int(cfg['max_minutes']):
        raise SystemExit('Error: total_after exceeds max_minutes after scaling.')


if __name__ == '__main__':
    main()
