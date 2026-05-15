import sys

def main() -> int:
    # TODO: Implement a local CI runner that:
    # - Reads .ci/config.yaml
    # - Discovers and runs unittest tests under test_dir
    # - Writes full textual output to out/reports/test_results.txt
    # - Writes JSON summary {tests_run, failures, errors, skipped, timestamp} to out/reports/test_summary.json
    # - Prints a one-line summary to stdout (see task instructions)
    # - Exits 0 if no failures/errors, else non-zero
    print("TODO: implement CI runner to execute tests and write reports.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
