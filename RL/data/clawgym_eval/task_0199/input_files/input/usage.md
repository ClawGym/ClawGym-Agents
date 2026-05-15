BadGem refactor targets (keep public API: module BadGem; class Widget; same method names and arity)

Overview
- This utility exposes a module helper and a simple Widget class.
- The public API and method names must remain the same while fixing reliability traps.

Intended semantics
- BadGem.maybe_set(value)
  - If value is nil → return true
  - If value is false → return false (must not be overwritten)
  - If value is true → return true
- BadGem::Widget#initialize
  - Internally maintains a Hash of tags keyed by symbol or string.
  - Each key should have its own independent Array; no sharing across keys.
- BadGem::Widget#add_tag(key, value) → Array
  - Pushes value onto the array for that key and returns that per-key array.
  - Modifying one key’s array must not affect any other key’s array.
- BadGem::Widget#tricky_default(arr = [])
  - When no argument is passed, it should return a fresh array each call that contains :x exactly once.
  - When an array is passed, it should append :x to that passed array and return it.
- BadGem::Widget#call_secret → "shh"
  - Should call a private method without violating privacy rules (no explicit receiver on private calls).
- BadGem::Widget#runner → :after_proc
  - Uses a callable that does not cause an early return from the method. The method must complete and return :after_proc.
- Dynamic finders
  - Methods with names starting with find_ should be handled by method_missing.
  - They should return a String that starts with "missing:" followed by the method name.
  - respond_to?(:find_something) should return true for any method that matches the find_* pattern.
- Safety and best practices
  - Add the frozen string literal magic comment.
  - Do not use Hash.new([]) for defaults — ensure per-key arrays are not shared by using the block form.
  - Do not rely on default-argument arrays that are evaluated once (def foo(arr = [])); use a nil default and initialize inside.
  - Do not call private methods with an explicit receiver.
  - Do not let Proc return escape the enclosing method; use a lambda instead.
  - Pair method_missing with a correct respond_to_missing? implementation aligned with the dynamic finder behavior.
  - Fix false/nil handling so ||= does not clobber false values while nil still maps to true.
  - Do not introduce eval/exec or other dangerous metaprogramming.