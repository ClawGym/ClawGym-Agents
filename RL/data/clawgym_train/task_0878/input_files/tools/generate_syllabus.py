import json
from pathlib import Path

def main():
    cfg_path = Path("input/qc_training_config.json")
    out_md = Path("output/syllabus.md")

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    lines = []
    lines.append(f"# {cfg['title']}")
    lines.append(f"Date: {cfg.get('workshop_date', 'TBD')}")
    lines.append("")
    total = sum(m.get('duration_minutes', 0) for m in cfg.get('modules', []))
    lines.append(f"Planned total time: {total} minutes")
    lines.append("")

    for idx, m in enumerate(cfg.get('modules', []), start=1):
        title = m.get('title', f"Module {idx}")
        dur = m.get('duration_minutes', 0)
        lines.append(f"## {idx}. {title} ({dur} min)")
        topics = m.get('topics', [])
        if topics:
            lines.append("Topics:")
            for t in topics:
                lines.append(f"- {t}")
        lines.append("")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

if __name__ == "__main__":
    main()
