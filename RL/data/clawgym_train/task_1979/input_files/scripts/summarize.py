import sys
import csv
from collections import defaultdict

def main():
    if len(sys.argv) != 2:
        print("ERROR expected usage: python3 scripts/summarize.py <path-to-csv>")
        sys.exit(2)
    path = sys.argv[1]
    groups = defaultdict(list)  # key=(method,dataset) -> list of (rmse,runtime)
    warnings = []
    try:
        with open(path, newline='') as f:
            reader = csv.DictReader(f)
            row_idx = 2  # header is line 1
            for row in reader:
                method = (row.get('method') or '').strip()
                dataset = (row.get('dataset') or '').strip()
                metric_name = (row.get('metric_name') or '').strip().lower()
                metric_value = (row.get('metric_value') or '').strip()
                runtime_val = (row.get('runtime_sec') or '').strip()
                # parse numbers where applicable
                rmse = None
                runtime = None
                if metric_name != 'rmse':
                    if metric_name:
                        warnings.append(f"WARN ignored non-rmse metric at row {row_idx}: {metric_name}")
                    row_idx += 1
                    continue
                # rmse row
                if metric_value == '' or metric_value is None:
                    warnings.append(f"WARN missing or invalid rmse at row {row_idx}")
                else:
                    try:
                        rmse = float(metric_value)
                    except Exception:
                        warnings.append(f"WARN missing or invalid rmse at row {row_idx}")
                if runtime_val != '' and runtime_val is not None:
                    try:
                        runtime = float(runtime_val)
                    except Exception:
                        # ignore bad runtime silently; it is optional for aggregation
                        pass
                if rmse is not None:
                    groups[(method, dataset)].append((rmse, runtime))
                row_idx += 1
    except FileNotFoundError:
        print(f"ERROR file not found: {path}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR failed to read CSV: {e}")
        sys.exit(1)

    # Print summaries sorted for determinism
    keys = sorted(groups.keys(), key=lambda k: (k[0], k[1]))
    for (method, dataset) in keys:
        vals = groups[(method, dataset)]
        if not vals:
            continue
        rmses = [v[0] for v in vals if v[0] is not None]
        runtimes = [v[1] for v in vals if v[1] is not None]
        mean_rmse = sum(rmses) / len(rmses)
        mean_runtime = sum(runtimes) / len(runtimes) if runtimes else None
        mean_runtime_str = f"{mean_runtime}" if mean_runtime is not None else "NA"
        print(f"SUMMARY method={method} dataset={dataset} count={len(rmses)} mean_rmse={round(mean_rmse, 3)} mean_runtime_sec={round(mean_runtime, 3) if mean_runtime is not None else mean_runtime_str}")
    for w in warnings:
        print(w)
    print(f"DONE groups={len(keys)} warnings={len(warnings)}")

if __name__ == '__main__':
    main()
