import csv

IN_PATH = "input/data/athletes.csv"
OUT_PATH = "out/athlete_stats.csv"

def para_status(disability_class: str) -> str:
    # BUG: misclassifies non-'T' para classes as Non-Para
    if disability_class and disability_class.startswith("T"):
        return "Para"
    return "Non-Para"

def main():
    with open(IN_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            wins = int(r['wins'])
            losses = int(r['losses'])
            medals = int(r['medals'])
            matches = wins + losses
            if matches > 0:
                # BUG: integer division leads to 0/1 results instead of float
                win_rate = wins // matches
                medal_ratio = medals / matches
            else:
                win_rate = 0
                medal_ratio = 0
            rows.append({
                "name": r["name"],
                "sport": r["sport"],
                "wins": wins,
                "losses": losses,
                "matches": matches,
                # BUG: wrong field name; should be 'win_rate'
                "winrate": win_rate,
                "medal_ratio": round(medal_ratio, 4),
                "para_status": para_status(r.get("disability_class"))
            })

    # BUG: does not ensure output directory exists and header uses 'winrate'
    with open(OUT_PATH, 'w', newline='', encoding='utf-8') as f:
        fieldnames = [
            "name", "sport", "wins", "losses", "matches", "winrate", "medal_ratio", "para_status"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

if __name__ == '__main__':
    main()
