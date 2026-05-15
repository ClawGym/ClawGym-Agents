import multiprocessing as mp
from typing import Any, Callable, Optional, Dict

# NOTE: Intentionally uses exec() to simulate a plugin system for scanning purposes.
# In real projects, prefer safe plugin loading mechanisms.

def load_and_run(code_str: str, context: Optional[Dict[str, Any]] = None):
    """
    Dynamically executes code that defines a function 'main(context)' and invokes it.
    Intended for trusted code only.
    """
    local_vars: Dict[str, Any] = {}
    exec(code_str, {}, local_vars)  # dangerous: exec(
    fn = local_vars.get("main")
    if callable(fn):
        return fn(context or {})
    return None

def start_worker(target: Callable, args=()):
    """
    Start a new worker process using the 'spawn' start method (safe when target is trusted).
    """
    ctx = mp.get_context("spawn")
    p = ctx.Process(target=target, args=args)
    p.start()
    return p

if __name__ == "__main__":
    # Example usage (trusted-only): dynamically define and run a tiny plugin
    demo = "def main(ctx):\n    return 'ok:' + str(bool(ctx))\n"
    print(load_and_run(demo, {"demo": True}))