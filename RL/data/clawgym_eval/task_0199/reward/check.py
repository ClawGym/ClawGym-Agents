import json
import os
import re
import subprocess
import sys

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def first_non_empty_line(text):
    if text is None:
        return None
    for line in text.splitlines():
        if line.strip() != "":
            return line.rstrip("\n")
    return None

def run_ruby(code_str):
    try:
        proc = subprocess.run(
            ["ruby", "-e", code_str],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception:
        return None, "", ""

def run_ruby_script(script_path):
    try:
        proc = subprocess.run(
            ["ruby", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception:
        return None, "", ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    good_path = os.path.join(output_dir, "good_gem.txt")
    test_path = os.path.join(output_dir, "test_good_gem.txt")
    report_path = os.path.join(output_dir, "REFORM_REPORT.md")

    checks = {
        "file_good_exists": False,
        "file_test_exists": False,
        "file_report_exists": False,
        "frozen_pragma": False,
        "preserves_names": False,
        "no_hash_new_array": False,
        "has_hash_new_block": False,
        "has_respond_to_missing": False,
        "no_self_secret": False,
        "uses_lambda_not_proc": False,
        "no_eval_exec": False,
        "runtime_maybe_set": False,
        "runtime_runner": False,
        "runtime_tricky_default": False,
        "runtime_tags_independent": False,
        "runtime_dynamic_missing": False,
        "runtime_call_secret": False,
        "test_script_runs": False,
    }

    # Existence
    good_text = None
    if os.path.isfile(good_path):
        checks["file_good_exists"] = True
        good_text = read_text(good_path)

    if os.path.isfile(test_path):
        checks["file_test_exists"] = True

    if os.path.isfile(report_path):
        checks["file_report_exists"] = True

    # Static checks on good_gem.txt
    if checks["file_good_exists"] and good_text is not None:
        # frozen string literal pragma
        line = first_non_empty_line(good_text)
        if line is not None and line.startswith("# frozen_string_literal: true"):
            checks["frozen_pragma"] = True

        # module BadGem and class Widget within module
        # Ensure module BadGem appears and within it class Widget appears
        preserves = False
        m = re.search(r"module\s+BadGem\b", good_text)
        if m:
            # Search for class Widget after this module declaration
            rest = good_text[m.start():]
            if re.search(r"class\s+Widget\b", rest):
                preserves = True
        checks["preserves_names"] = preserves

        # No "Hash.new([])"
        if "Hash.new([])" not in good_text:
            checks["no_hash_new_array"] = True

        # Has Hash.new block
        if re.search(r"Hash\.new\s*\{", good_text):
            checks["has_hash_new_block"] = True

        # respond_to_missing? defined and method_missing exists
        has_method_missing = re.search(r"def\s+method_missing\s*\(", good_text) is not None
        has_respond_to_missing = re.search(r"def\s+respond_to_missing\?\s*\(", good_text) is not None
        if has_method_missing and has_respond_to_missing:
            checks["has_respond_to_missing"] = True

        # No explicit receiver call to private secret: "self.secret"
        if "self.secret" not in good_text:
            checks["no_self_secret"] = True

        # Use lambda or -> and do not use Proc.new
        no_proc_new = "Proc.new" not in good_text
        has_lambda = ("lambda" in good_text) or ("->" in good_text)
        if no_proc_new and has_lambda:
            checks["uses_lambda_not_proc"] = True

        # No eval( or exec(
        if ("eval(" not in good_text) and ("exec(" not in good_text):
            checks["no_eval_exec"] = True

    # Behavioral checks using Ruby
    if checks["file_good_exists"]:
        # Build Ruby harness
        # Use absolute path and escape backslashes and quotes safely
        abs_good = good_path.replace("\\", "\\\\").replace("'", "\\'")
        ruby_code = f"""
begin
  load '{abs_good}', true
rescue Exception => e
  # If load fails, print zeros for all checks and exit
  puts '0,0,0,0,0,0'
  exit 0
end

results = []

# maybe_set checks
begin
  ms_false = (BadGem.maybe_set(false) == false)
  ms_nil = (BadGem.maybe_set(nil) == true)
  ms_true = (BadGem.maybe_set(true) == true)
  results << (ms_false && ms_nil && ms_true)
rescue Exception
  results << false
end

# runner check
begin
  w1 = BadGem::Widget.new
  results << (w1.runner == :after_proc)
rescue Exception
  results << false
end

# tricky_default: fresh array each time, size==1 on consecutive calls
begin
  w2 = BadGem::Widget.new
  a1 = w2.tricky_default
  a2 = w2.tricky_default
  ok = a1.is_a?(Array) && a2.is_a?(Array) && a1.size == 1 && a2.size == 1
  results << ok
rescue Exception
  results << false
end

# tags independent: add_tag returns per-key arrays not shared
begin
  w3 = BadGem::Widget.new
  arr_a = w3.add_tag(:a, "x")
  arr_b = w3.add_tag(:b, "y")
  independent = false
  if arr_a.respond_to?(:<<)
    begin
      arr_a << "z"
    rescue Exception
    end
    if arr_a.is_a?(Array) && arr_b.is_a?(Array)
      independent = (arr_a.object_id != arr_b.object_id) && !(arr_b.include?("z"))
    end
  end
  # Fallback: if add_tag did not return arrays, try tags accessor if available
  if !independent && w3.respond_to?(:tags)
    t = w3.tags
    if t.is_a?(Hash) && t[:a].is_a?(Array) && t[:b].is_a?(Array)
      t[:a] << "z"
      independent = (t[:a].object_id != t[:b].object_id) && !(t[:b].include?("z"))
    end
  end
  results << independent
rescue Exception
  results << false
end

# method_missing dynamic finders and respond_to?
begin
  w4 = BadGem::Widget.new
  dyn_ok = w4.respond_to?(:find_something)
  if dyn_ok
    res = w4.find_something
    dyn_ok = res.is_a?(String) && res.start_with?("missing:")
  end
  results << dyn_ok
rescue Exception
  results << false
end

# private method access via call_secret
begin
  w5 = BadGem::Widget.new
  results << (w5.call_secret == "shh")
rescue Exception
  results << false
end

puts results.map{{|b| b ? '1' : '0'}}.join(',')
"""
        rc, out, err = run_ruby(ruby_code)
        if rc is not None and rc == 0:
            # Expect 6 comma-separated 0/1 values
            line = ""
            for l in out.splitlines():
                if l.strip():
                    line = l.strip()
            parts = line.split(",") if line else []
            # Map to checks
            if len(parts) == 6:
                checks["runtime_maybe_set"] = (parts[0] == "1")
                checks["runtime_runner"] = (parts[1] == "1")
                checks["runtime_tricky_default"] = (parts[2] == "1")
                checks["runtime_tags_independent"] = (parts[3] == "1")
                checks["runtime_dynamic_missing"] = (parts[4] == "1")
                checks["runtime_call_secret"] = (parts[5] == "1")

    # Run test script: ruby output/test_good_gem.txt must exit 0 and print "All tests passed"
    if checks["file_test_exists"]:
        rc2, out2, err2 = run_ruby_script(test_path)
        if rc2 is not None and rc2 == 0 and ("All tests passed" in (out2 or "")):
            checks["test_script_runs"] = True

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0
    # Ensure no-op baseline: if no output artifacts at all, reward must be 0
    output_exists = any(os.path.exists(os.path.join(output_dir, p)) for p in ["good_gem.txt", "test_good_gem.txt", "REFORM_REPORT.md"])
    if not output_exists:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()