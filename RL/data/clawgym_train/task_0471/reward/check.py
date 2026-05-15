import sys
import json
import csv
import re
import math
from pathlib import Path
from html.parser import HTMLParser
from typing import Optional, Dict, List, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml(text: str) -> Optional[Dict]:
    try:
        data = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove optional quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            # Try to parse numbers
            if re.fullmatch(r"[-+]?\d+", val):
                data[key] = int(val)
            elif re.fullmatch(r"[-+]?\d*\.\d+(e[-+]?\d+)?", val, flags=re.I) or re.fullmatch(r"[-+]?\d+\.?", val):
                try:
                    data[key] = float(val)
                except Exception:
                    data[key] = val
            else:
                data[key] = val
        return data
    except Exception:
        return None


class BenchTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_bench = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.rows = []
        self._table_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self._table_stack.append(attrs_dict.get("id"))
            if attrs_dict.get("id") == "bench":
                self.in_bench = True
        if self.in_bench and tag == "tr":
            self.in_tr = True
            self.current_row = []
        if self.in_bench and self.in_tr and tag in ("td",):
            self.in_td = True

    def handle_endtag(self, tag):
        if self.in_bench and self.in_tr and tag in ("td",):
            self.in_td = False
        if self.in_bench and tag == "tr":
            self.in_tr = False
            # Expect 4 columns per row in tbody; skip header
            if len(self.current_row) >= 3:
                # Trim to 4 if more content combined
                self.rows.append([cell.strip() for cell in self.current_row[:4]])
            self.current_row = []
        if tag == "table":
            last_id = self._table_stack.pop() if self._table_stack else None
            if last_id == "bench":
                self.in_bench = False

    def handle_data(self, data):
        if self.in_bench and self.in_tr and self.in_td:
            self.current_row.append(data)


def _parse_benchmark_html(text: str) -> List[Dict[str, str]]:
    parser = BenchTableParser()
    parser.feed(text)
    parsed = []
    for row in parser.rows:
        if len(row) >= 3:
            scheme = row[0].strip()
            operation = row[1].strip()
            latency = row[2].strip()
            parsed.append({"scheme": scheme, "operation": operation, "latency_ms": latency})
    return parsed


def _load_jsonl_safe(path: Path) -> Optional[List[Dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _parse_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            sniffer = csv.Sniffer()
            sample = f.read(2048)
            f.seek(0)
            dialect = sniffer.sniff(sample) if sample.strip() else csv.excel
            reader = csv.reader(f, dialect)
            header = next(reader, None)
            if header is None:
                return None, None
            rows = []
            for row in reader:
                if len(row) != len(header):
                    # malformed row
                    return header, None
                rows.append({h: v for h, v in zip(header, row)})
            return header, rows
    except Exception:
        return None, None


def _safe_float(x) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _floats_close(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def _compute_laplace_noises(n: int, scale: float, seed: int) -> List[float]:
    # Laplace(0, b) as difference of two independent Exponential(rate=1/b)
    import random
    rnd = random.Random(seed)
    noises = []
    rate = 1.0 / scale if scale != 0 else float('inf')
    for _ in range(n):
        # Handle scale==0 -> noise 0
        if scale == 0:
            noises.append(0.0)
            continue
        L = rnd.expovariate(rate)
        R = rnd.expovariate(rate)
        noises.append(L - R)
    return noises


def _extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def _word_count(text: str) -> int:
    # Simple whitespace-based word count
    parts = re.findall(r"\b\w+\b", text)
    return len(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "results_csv_header": 0.0,
        "results_csv_row_count": 0.0,
        "results_csv_values_correct": 0.0,
        "summary_json_values_correct": 0.0,
        "email_rewrite_constraints": 0.0,
    }

    # Load inputs
    config_path = workspace / "input" / "config.yaml"
    bench_path = workspace / "input" / "benchmark.html"
    queries_path = workspace / "input" / "queries.jsonl"
    results_path = workspace / "output" / "results.csv"
    summary_path = workspace / "output" / "summary.json"
    email_path = workspace / "output" / "email_rewrite.md"

    config_text = _read_text_safe(config_path)
    bench_text = _read_text_safe(bench_path)
    queries_list = _load_jsonl_safe(queries_path)

    config = _parse_simple_yaml(config_text) if config_text is not None else None
    bench_rows = _parse_benchmark_html(bench_text) if bench_text is not None else None

    # Prepare expected computations if possible
    scheme = None
    epsilon = None
    sensitivity = None
    noise_family = None
    seed = None
    if config:
        scheme = str(config.get("scheme")) if "scheme" in config else None
        epsilon = _safe_float(config.get("epsilon"))
        sensitivity = _safe_float(config.get("sensitivity"))
        noise_family = str(config.get("noise")) if "noise" in config else None
        seed = config.get("seed")
        try:
            seed = int(seed) if seed is not None else None
        except Exception:
            seed = None

    latencies: Dict[str, float] = {}
    if bench_rows is not None and scheme is not None:
        for r in bench_rows:
            if r.get("scheme") == scheme:
                op = r.get("operation", "").strip()
                lat = _safe_float(r.get("latency_ms"))
                if op and lat is not None:
                    latencies[op] = lat

    # Compute expected per-query metrics
    expected_by_qid = {}
    mean_overhead_ms = None
    mean_expected_runtime_ms = None
    if queries_list is not None and scheme is not None and epsilon is not None and sensitivity is not None and bench_rows is not None:
        # Ensure required latencies present
        required_ops = ("encrypt", "add", "multiply")
        if all(op in latencies for op in required_ops):
            # Gather overheads
            overheads = []
            expected_runtimes = []
            true_counts = []
            baselines = []
            encrypt_counts = []
            add_counts = []
            multiply_counts = []
            for rec in queries_list:
                qid = rec.get("query_id")
                true_c = _safe_float(rec.get("true_count"))
                base_ms = _safe_float(rec.get("baseline_ms"))
                ops = rec.get("operations", {}) if isinstance(rec.get("operations"), dict) else {}
                enc = _safe_float(ops.get("encrypt"))
                add = _safe_float(ops.get("add"))
                mul = _safe_float(ops.get("multiply"))
                if None in (qid, true_c, base_ms, enc, add, mul):
                    continue
                overhead = enc * latencies["encrypt"] + add * latencies["add"] + mul * latencies["multiply"]
                expected_rt = base_ms + overhead
                expected_by_qid[qid] = {
                    "scheme": scheme,
                    "epsilon": epsilon,
                    "baseline_ms": base_ms,
                    "overhead_ms": overhead,
                    "expected_runtime_ms": expected_rt,
                    "true_count": true_c,
                    "encrypt_ops": enc,
                    "add_ops": add,
                    "multiply_ops": mul,
                }
                overheads.append(overhead)
                expected_runtimes.append(expected_rt)
                true_counts.append(true_c)
                baselines.append(base_ms)
                encrypt_counts.append(enc)
                add_counts.append(add)
                multiply_counts.append(mul)
            if overheads:
                mean_overhead_ms = sum(overheads) / len(overheads)
                mean_expected_runtime_ms = sum(expected_runtimes) / len(expected_runtimes)
            # Add noisy counts
            if noise_family and noise_family.lower() == "laplace" and seed is not None and epsilon not in (None, 0.0):
                scale = sensitivity / epsilon if epsilon != 0 else float("inf")
                noises = _compute_laplace_noises(len(expected_by_qid), scale, seed)
                # Maintain order according to queries_list
                idx = 0
                for rec in queries_list:
                    qid = rec.get("query_id")
                    if qid in expected_by_qid:
                        noise = noises[idx]
                        idx += 1
                        expected_by_qid[qid]["noisy_count"] = expected_by_qid[qid]["true_count"] + noise

    # Check results.csv
    expected_header = [
        "query_id",
        "scheme",
        "epsilon",
        "baseline_ms",
        "overhead_ms",
        "expected_runtime_ms",
        "true_count",
        "noisy_count",
        "encrypt_ops",
        "add_ops",
        "multiply_ops",
    ]
    header, rows = _parse_csv_with_header(results_path) if results_path.exists() else (None, None)
    if header is not None and header == expected_header:
        scores["results_csv_header"] = 1.0
    else:
        scores["results_csv_header"] = 0.0

    if rows is not None and queries_list is not None:
        scores["results_csv_row_count"] = 1.0 if len(rows) == len(queries_list) else 0.0
    else:
        scores["results_csv_row_count"] = 0.0

    # Validate per-row values
    values_score = 0.0
    if rows is not None and expected_by_qid and len(expected_by_qid) > 0:
        total = 0
        correct = 0
        for row in rows:
            qid = row.get("query_id")
            if qid not in expected_by_qid:
                total += 1
                continue
            exp = expected_by_qid[qid]
            # Compare fields
            ok = True
            # scheme exact
            if str(row.get("scheme")) != str(exp["scheme"]):
                ok = False
            # epsilon float
            if not _floats_close(_safe_float(row.get("epsilon")), exp["epsilon"], tol=1e-6):
                ok = False
            # baseline_ms
            if not _floats_close(_safe_float(row.get("baseline_ms")), exp["baseline_ms"], tol=1e-6):
                ok = False
            # overhead_ms
            if not _floats_close(_safe_float(row.get("overhead_ms")), exp["overhead_ms"], tol=1e-6):
                ok = False
            # expected_runtime_ms
            if not _floats_close(_safe_float(row.get("expected_runtime_ms")), exp["expected_runtime_ms"], tol=1e-6):
                ok = False
            # true_count
            if not _floats_close(_safe_float(row.get("true_count")), exp["true_count"], tol=1e-6):
                ok = False
            # noisy_count
            noisy_exp = exp.get("noisy_count")
            if noisy_exp is None:
                ok = False
            else:
                if not _floats_close(_safe_float(row.get("noisy_count")), noisy_exp, tol=1e-6):
                    ok = False
            # encrypt_ops
            if not _floats_close(_safe_float(row.get("encrypt_ops")), exp["encrypt_ops"], tol=1e-9):
                ok = False
            # add_ops
            if not _floats_close(_safe_float(row.get("add_ops")), exp["add_ops"], tol=1e-9):
                ok = False
            # multiply_ops
            if not _floats_close(_safe_float(row.get("multiply_ops")), exp["multiply_ops"], tol=1e-9):
                ok = False
            total += 1
            if ok:
                correct += 1
        if total > 0:
            values_score = correct / total
    scores["results_csv_values_correct"] = values_score

    # Validate summary.json
    summary_score = 0.0
    summary_checks = 0
    summary_pass = 0
    summary_data = None
    if summary_path.exists():
        try:
            summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary_data = None
    if summary_data is not None:
        # scheme
        summary_checks += 1
        if scheme is not None and summary_data.get("scheme") == scheme:
            summary_pass += 1
        # epsilon
        summary_checks += 1
        if epsilon is not None and _floats_close(_safe_float(summary_data.get("epsilon")), epsilon, tol=1e-6):
            summary_pass += 1
        # seed
        summary_checks += 1
        try:
            sd = int(summary_data.get("seed"))
        except Exception:
            sd = None
        if seed is not None and sd == seed:
            summary_pass += 1
        # queries count
        summary_checks += 1
        if queries_list is not None and _safe_float(summary_data.get("queries")) == float(len(queries_list)):
            summary_pass += 1
        # mean_overhead_ms
        summary_checks += 1
        if mean_overhead_ms is not None and _floats_close(_safe_float(summary_data.get("mean_overhead_ms")), mean_overhead_ms, tol=1e-6):
            summary_pass += 1
        # mean_expected_runtime_ms
        summary_checks += 1
        if mean_expected_runtime_ms is not None and _floats_close(_safe_float(summary_data.get("mean_expected_runtime_ms")), mean_expected_runtime_ms, tol=1e-6):
            summary_pass += 1

    if summary_checks > 0:
        summary_score = summary_pass / summary_checks
    else:
        summary_score = 0.0
    scores["summary_json_values_correct"] = summary_score

    # Validate email_rewrite.md
    email_score = 0.0
    email_text = _read_text_safe(email_path)
    if email_text is not None and scheme is not None and epsilon is not None and mean_overhead_ms is not None:
        checks = 0
        passed = 0
        # word count ≤ 120
        checks += 1
        if _word_count(email_text) <= 120:
            passed += 1
        # includes scheme
        checks += 1
        if scheme.lower() in email_text.lower():
            passed += 1
        # includes epsilon mention and numeric epsilon
        checks += 1
        has_eps_word = ("epsilon" in email_text.lower()) or ("ε" in email_text)
        nums = _extract_numbers(email_text)
        has_eps_value = any(abs(n - float(epsilon)) <= 1e-6 for n in nums)
        if has_eps_word and has_eps_value:
            passed += 1
        # includes mean_overhead_ms value (allow small rounding tolerance 1e-2)
        checks += 1
        has_mean_overhead = any(abs(n - float(mean_overhead_ms)) <= 1e-2 for n in nums)
        if has_mean_overhead:
            passed += 1
        email_score = passed / checks if checks > 0 else 0.0
    else:
        email_score = 0.0
    scores["email_rewrite_constraints"] = email_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()