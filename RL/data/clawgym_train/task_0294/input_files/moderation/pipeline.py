import argparse
import json
import os

try:
    import yaml
except Exception:
    yaml = None


def load_posts(path):
    posts = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            posts.append(json.loads(line))
    return posts


def summarize(posts):
    total = len(posts)
    anonymous_sources = 0
    total_sources = 0
    for p in posts:
        srcs = p.get('sources', [])
        total_sources += len(srcs)
        anonymous_sources += sum(1 for s in srcs if s.get('anonymous'))
    return {
        'posts': total,
        'total_sources': total_sources,
        'anonymous_sources': anonymous_sources
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='input_path', required=True)
    ap.add_argument('--config', dest='config_path', required=True)
    ap.add_argument('--out_dir', dest='out_dir', required=True)
    args = ap.parse_args()

    posts = load_posts(args.input_path)

    # Load config (current behavior: just load; scoring not yet implemented)
    config = {}
    if args.config_path and os.path.exists(args.config_path):
        if yaml is None:
            raise RuntimeError('PyYAML is required to load configuration')
        with open(args.config_path, 'r', encoding='utf-8') as cf:
            config = yaml.safe_load(cf) or {}

    os.makedirs(args.out_dir, exist_ok=True)

    # Existing behavior: write a basic summary for visibility
    summary_path = os.path.join(args.out_dir, 'summary.json')
    with open(summary_path, 'w', encoding='utf-8') as out:
        json.dump(summarize(posts), out, indent=2)
    print('Wrote', summary_path)

    # TODO: Implement credibility scoring and write:
    #  - flagged.csv (ONLY flagged posts)
    #  - flags_report.json (config_used, flagged_count, post_scores)


if __name__ == '__main__':
    main()
