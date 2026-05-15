#!/usr/bin/env python3
"""
Buggy starter script for generating a simple forensics scoreboard.
Known issues (to be fixed by refactor):
- Brittle CSV parsing (splits on whitespace, breaks on names with spaces)
- Hardcoded output directory and CDN link
- Fails if Chart.js local asset isn't present instead of fetching it
- Poor aggregation and rounding of speaker points
- Minimal error handling and unclear logs
"""
import sys
import os
import json
import subprocess

# NOTE: Intentionally fragile parsing function

def read_csv_brittle(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().strip().splitlines()
    if not lines:
        return []
    header = lines[0]
    rows = []
    # WRONG: splits on whitespace for roster, which breaks on names with spaces
    for line in lines[1:]:
        if not line.strip():
            continue
        # try splitting on space first (wrong), fallback to comma
        parts = line.strip().split(' ')
        if len(parts) < 2:
            parts = line.strip().split(',')
        rows.append(parts)
    return header.split(','), rows


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/scoreboard.py <roster.csv> <ballots.csv> --outdir <out>")
        sys.exit(1)
    roster_path = sys.argv[1]
    ballots_path = sys.argv[2]
    outdir = 'output'
    if '--outdir' in sys.argv:
        try:
            outdir = sys.argv[sys.argv.index('--outdir') + 1]
        except Exception:
            pass

    os.makedirs(outdir, exist_ok=True)
    assets = os.path.join(outdir, 'assets')
    os.makedirs(assets, exist_ok=True)

    # Intentionally fail if Chart.js isn't present instead of downloading it
    chart_js = os.path.join(assets, 'chart.umd.min.js')
    # This will raise CalledProcessError if the file doesn't exist
    subprocess.check_call(['test', '-f', chart_js])

    # Read roster (brittle: splits on whitespace)
    roster_header, roster_rows = read_csv_brittle(roster_path)
    # Expecting exactly 3 columns (but brittle split may break)
    # competitor_id, competitor_name, school
    roster_map = {}
    for row in roster_rows:
        try:
            cid, name, school = row[0], row[1], row[2]
        except Exception as e:
            # Will often fail here for names with spaces
            raise ValueError(f"Bad roster row: {row}")
        roster_map[cid] = { 'competitor_name': name, 'school': school }

    # Read ballots (assumes comma split works here)
    with open(ballots_path, 'r', encoding='utf-8') as f:
        blines = f.read().strip().splitlines()
    ballots = []
    for i, line in enumerate(blines):
        if i == 0:
            continue
        parts = line.strip().split(',')
        if len(parts) != 4:
            continue
        rid, competitor, result, sp = parts
        ballots.append((rid, competitor, result, float(sp)))

    # Aggregate (round speaker points to int incorrectly)
    stats = {}
    for _, cid, result, sp in ballots:
        if cid not in stats:
            stats[cid] = { 'wins': 0, 'losses': 0, 'points': [] }
        if result == 'W':
            stats[cid]['wins'] += 1
        else:
            stats[cid]['losses'] += 1
        stats[cid]['points'].append(sp)

    # Prepare summary but with lossy rounding
    summary = []
    for cid, s in stats.items():
        pts = s['points'] if s['points'] else [0.0]
        avg = int(sum(pts) / len(pts))  # WRONG: truncates to integer
        name = roster_map.get(cid, {}).get('competitor_name', cid)
        school = roster_map.get(cid, {}).get('school', '')
        summary.append({
            'competitor_id': cid,
            'competitor_name': name,
            'school': school,
            'total_rounds': s['wins'] + s['losses'],
            'wins': s['wins'],
            'losses': s['losses'],
            'avg_speaker_points': avg
        })

    # Write JSON (unsorted)
    with open(os.path.join(outdir, 'summary.json'), 'w', encoding='utf-8') as jf:
        json.dump(summary, jf)

    # Write HTML that incorrectly links a CDN version of Chart.js
    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\" />
<title>Forensics Scoreboard</title>
</head>
<body>
<h1>Average Speaker Points</h1>
<canvas id=\"chart\" width=\"600\" height=\"400\"></canvas>
<!-- WRONG: external CDN link (offline use will fail) -->
<script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
<script>
const data = {labels: {labels}, datasets: [{label: 'Avg SP', data: {data}, backgroundColor: 'rgba(54, 162, 235, 0.5)'}]};
const ctx = document.getElementById('chart').getContext('2d');
new Chart(ctx, {{type: 'bar', data: data}});
</script>
</body>
</html>
"""
    labels = [roster_map.get(c['competitor_id'], {}).get('competitor_name', c['competitor_id']) for c in summary]
    data = [c['avg_speaker_points'] for c in summary]
    html = html.replace('{labels}', json.dumps(labels)).replace('{data}', json.dumps(data))
    with open(os.path.join(outdir, 'index.html'), 'w', encoding='utf-8') as hf:
        hf.write(html)

    print(f"Wrote outputs to {outdir}")

if __name__ == '__main__':
    main()
