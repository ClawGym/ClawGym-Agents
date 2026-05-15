import unittest
import time
from app.service import load_config, sync_with_partner


class TestReliability(unittest.TestCase):
    def test_fail_fast_budget(self):
        cfg = load_config()
        timeout_ms = int(cfg["timeouts"]["dependency_timeout_ms"])
        retries = int(cfg["timeouts"]["max_retries"])
        threshold = int(cfg["reliability"]["fail_fast_threshold_ms"])

        t0 = time.perf_counter()
        with self.assertRaises(RuntimeError):
            sync_with_partner(simulate_down=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Always print a measurement line to aid analysis/reporting
        print(f"MEASURED elapsed_ms={elapsed_ms:.1f} threshold={threshold} timeout_ms={timeout_ms} retries={retries}")

        self.assertLessEqual(
            elapsed_ms,
            threshold,
            msg=(
                f"elapsed={elapsed_ms:.1f}ms exceeds budget of {threshold}ms "
                f"with timeout={timeout_ms}ms and retries={retries}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
