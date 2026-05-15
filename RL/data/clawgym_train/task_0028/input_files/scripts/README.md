# Newsroom Scheduler Conventions

- Put the main runner in `src/` (e.g., `src/holistic_monitor.py`). It must read YAML under `config/` and write into `logs/` and `outputs/`.
- Raw HTML should live under `outputs/raw_html/<domain>/` with date-stamped filenames: `<YYYY-MM-DD>_home.html` and `<YYYY-MM-DD>_about.html`.
- Structured results should be appended to `outputs/structured/<YYYY-MM-DD>.jsonl` (one JSON object per line).
- The wrapper script must be `schedule/run_holistic_monitor.sh`. It should:
  - ensure needed directories exist,
  - enforce a simple lock at the `runtime.lockfile` path from `config/schedule.yaml`,
  - call the Python runner once,
  - write stdout/stderr to the `paths.log_path` from `config/schedule.yaml`.
- The cron definition must be written to `schedule/holistic_monitor.cron` and contain a single line using the `schedule.cron` expression from `config/schedule.yaml` to invoke the wrapper.
- Retention: remove files older than the retention days in `config/schedule.yaml` for both logs and raw HTML.
- Don’t hardcode deep URLs; derive the homepage from the configured domain and find the internal About/Mission link by on-page text keywords within allowed domains.
