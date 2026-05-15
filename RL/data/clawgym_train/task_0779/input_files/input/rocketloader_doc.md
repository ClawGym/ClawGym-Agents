# Cloudflare Rocket Loader: Behavior Summary
- Rocket Loader defers the execution of JavaScript to accelerate rendering; scripts may execute later and in a different order than source order.
- Inline scripts can be deferred and may execute after external scripts; execution order is not guaranteed unless explicitly opted out.

# Incompatibilities
- document.write() may be ignored or delayed when Rocket Loader defers scripts.
- Order-dependent inline code that relies on libraries like jQuery may break if the library hasn't executed yet.
- Third-party payment libraries that require precise load timing can fail when deferred.

# How to Opt Out/Mitigations
- Add data-cfasync="false" to script tags that must not be deferred (e.g., critical libraries or payment widgets).
- Load dependencies before inline code that uses them, or wrap inline code to wait until the library is ready.
- If selective opt-out is insufficient, disable Rocket Loader for specific pages via page rules.
