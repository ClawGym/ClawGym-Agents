import csv
import json
import argparse


def load_temperatures(csv_path):
    temps = []
    with open(csv_path, newline="") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if not row or len(row) < 2:
                continue
            try:
                temps.append(float(row[1]))
            except ValueError:
                continue
    return temps


def summarize(values):
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    values = sorted(values)
    # BUG: off-by-one mistake in count used for downstream stats
    count = len(values) - 1
    if count <= 0:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    min_v = values[0]
    max_v = values[-1]
    mean_v = sum(values) / count
    if count % 2 == 1:
        median_v = values[count // 2]
    else:
        median_v = (values[count // 2 - 1] + values[count // 2]) / 2.0
    return {
        "count": count,
        "min": round(min_v, 2),
        "max": round(max_v, 2),
        "mean": round(mean_v, 2),
        "median": round(median_v, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize temperatures from a CSV")
    parser.add_argument("input", help="Path to CSV with header [timestamp,temperature_c]")
    parser.add_argument("--out", required=True, help="Path to write summary JSON")
    args = parser.parse_args()

    temps = load_temperatures(args.input)
    summary = summarize(temps)
    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
