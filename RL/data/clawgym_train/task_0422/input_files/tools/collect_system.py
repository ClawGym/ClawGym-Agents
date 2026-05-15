from __future__ import annotations
import json
import os
import platform
import shutil
from pathlib import Path
from datetime import datetime, timezone

def main() -> None:
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(Path("."))
    report = {
        "system": {
            "os_name": platform.system(),
            "kernel": platform.release(),
            "machine": platform.machine(),
        },
        "python": {
            "version": platform.python_version(),
        },
        "cpu": {
            "logical_cores": os.cpu_count() or 0,
        },
        "disk": {
            "total_bytes": int(disk.total),
            "used_bytes": int(disk.used),
            "free_bytes": int(disk.free),
        },
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    with (out_dir / "system_report.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)

if __name__ == "__main__":
    main()
