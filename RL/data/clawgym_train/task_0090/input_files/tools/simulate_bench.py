#!/usr/bin/env python3
import json
import os
import sys

# Deterministic benchmark simulator that writes successful runs to generated/raw_metrics.jsonl
# and prints failures to stderr. Exits non-zero if any failures occurred.

def main():
    runs = []
    devices = ["nvme0", "nvme1", "nvme2"]
    filesystems = ["ext4", "xfs"]
    qds = [1, 4]

    # Predefined deterministic results; errors are marked with an 'error' key
    metrics = {
        ("nvme0", "ext4", 1): {"throughput_mb_s": 2500.0, "latency_ms": 0.80},
        ("nvme0", "xfs", 1):  {"throughput_mb_s": 2550.0, "latency_ms": 0.78},
        ("nvme0", "ext4", 4): {"throughput_mb_s": 3100.0, "latency_ms": 0.95},
        ("nvme0", "xfs", 4):  {"throughput_mb_s": 3200.0, "latency_ms": 0.90},

        ("nvme1", "ext4", 1): {"throughput_mb_s": 2700.0, "latency_ms": 0.75},
        ("nvme1", "xfs", 1):  {"throughput_mb_s": 2750.0, "latency_ms": 0.73},
        ("nvme1", "ext4", 4): {"error": "fio exited with code 1: write verify mismatch"},
        ("nvme1", "xfs", 4):  {"throughput_mb_s": 3300.0, "latency_ms": 0.88},

        ("nvme2", "ext4", 1): {"throughput_mb_s": 2600.0, "latency_ms": 0.77},
        ("nvme2", "xfs", 1):  {"throughput_mb_s": 2620.0, "latency_ms": 0.76},
        ("nvme2", "ext4", 4): {"throughput_mb_s": 3150.0, "latency_ms": 0.92},
        ("nvme2", "xfs", 4):  {"error": "I/O timeout after 30s (errno=110)"},
    }

    out_dir = os.path.join(os.getcwd(), "generated")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "raw_metrics.jsonl")

    total = len(devices) * len(filesystems) * len(qds)
    failures = 0
    success = 0

    with open(out_path, "w", encoding="utf-8") as f:
        for d in devices:
            for fs in filesystems:
                for qd in qds:
                    key = (d, fs, qd)
                    m = metrics[key]
                    if "error" in m:
                        failures += 1
                        err = f"ERROR device={d} fs={fs} qd={qd}: {m['error']}"
                        print(err, file=sys.stderr)
                    else:
                        rec = {
                            "device": d,
                            "fs": fs,
                            "qd": qd,
                            "throughput_mb_s": m["throughput_mb_s"],
                            "latency_ms": m["latency_ms"],
                        }
                        f.write(json.dumps(rec) + "\n")
                        success += 1
                        msg = (
                            f"OK device={d} fs={fs} qd={qd} "
                            f"throughput_mb_s={rec['throughput_mb_s']} latency_ms={rec['latency_ms']}"
                        )
                        print(msg)

    print(f"Completed {success}/{total} runs; {failures} failures.")
    # Non-zero exit if any failure occurred
    if failures:
        sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
