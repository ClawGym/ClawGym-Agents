#!/usr/bin/env python3
import argparse
import time
import random
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    run_id = args.run_id

    random.seed(run_id)
    duration_ms = 300 + (run_id % 5) * 120
    print(f"RUN run_id={run_id} phase=start", flush=True)
    time.sleep(duration_ms / 1000.0)

    if run_id % 2 == 1:
        # Success path: emit deterministic metrics
        acc = round(0.72 + (run_id % 7) * 0.02, 3)
        loss = round(1.0 / (run_id % 4 + 1), 3)
        print(f"METRIC accuracy={acc} loss={loss}", flush=True)
        print("STATUS ok", flush=True)
        return 0
    else:
        # Failure path: deterministic exception type by run_id
        print("STATUS error", flush=True)
        err_case = run_id % 3
        if err_case == 0:
            _ = 1 / 0  # ZeroDivisionError
        elif err_case == 1:
            d = {}
            _ = d["missing"]  # KeyError('missing')
        else:
            raise ValueError("Invalid input shape for batch")

if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        # Propagate to produce traceback and non-zero exit code
        raise
    else:
        sys.exit(0 if rc is None else rc)
