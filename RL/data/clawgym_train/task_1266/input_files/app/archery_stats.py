import json
from collections import defaultdict
from typing import List, Dict, Any


def load_sessions(path: str) -> List[Dict[str, Any]]:
    sessions = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sessions.append(json.loads(line))
    return sessions


def summarize_sessions(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_ends = []
    dist_ends = defaultdict(list)
    total_arrows = 0
    for s in sessions:
        ends = s.get('end_totals', [])
        arrows_per_end = int(s.get('arrows_per_end', 0) or 0)
        d = str(int(s.get('distance_m'))) if 'distance_m' in s else 'unknown'
        all_ends.extend(ends)
        dist_ends[d].extend(ends)
        total_arrows += len(ends) * arrows_per_end
    total_ends = len(all_ends)
    avg = round(sum(all_ends) / total_ends, 1) if total_ends else 0.0
    best = max(all_ends) if all_ends else 0
    distances = {}
    for d, vals in dist_ends.items():
        if vals:
            distances[d] = {
                'ends': len(vals),
                'avg': round(sum(vals) / len(vals), 1)
            }
        else:
            distances[d] = {'ends': 0, 'avg': 0.0}
    return {
        'total_ends': total_ends,
        'total_arrows': total_arrows,
        'avg_score': avg,
        'best_end': best,
        'distances': distances
    }


def format_status(summary: Dict[str, Any]) -> str:
    """
    Returns a human-readable status line. Currently verbose on purpose; you may revise for brevity.
    """
    total_ends = summary.get('total_ends', 0)
    avg = summary.get('avg_score', 0)
    best = summary.get('best_end', 0)
    d = summary.get('distances', {})
    parts = []
    for k in sorted(d.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        parts.append(f"{k}m avg {d[k]['avg']}")
    dist_text = ", ".join(parts) if parts else "no distances"
    # Intentionally wordy; tests will require a concise rewrite.
    return (
        "Today\'s detailed archery practice summary covers multiple distances and ends; "
        f"your average per end is {avg}, with a best end of {best}. Distance breakdown: {dist_text}. "
        "Stay patient, keep your breath steady, hydrate well, and remember that consistent form leads the way forward."
    )


def main():
    import sys
    if len(sys.argv) != 3:
        print("Usage: python app/archery_stats.py <input_jsonl> <output_json>")
        sys.exit(2)
    inp, outp = sys.argv[1], sys.argv[2]
    sessions = load_sessions(inp)
    summary = summarize_sessions(sessions)
    with open(outp, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(format_status(summary))


if __name__ == '__main__':
    main()
