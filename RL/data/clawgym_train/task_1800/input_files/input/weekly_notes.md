# Weekly Notes — Sprint 14

Welcome to the week-in-review for Sprint 14. This document captures highlights, decisions, and next steps.

## Highlights
- Completed the first pass of the onboarding flow
- Fixed flaky integration tests around API retries
- Drafted the newsletter outline for the October issue

> Focus on outcomes, not just output — small, consistent improvements add up.

## Decisions
- Adopt the dark theme for internal dashboards
- Freeze new features on Thursday to stabilize the Friday release

## Next Steps
1. Polish the onboarding error states
2. Add rate-limit headers to API responses
3. Prepare demo scripts for the Friday showcase

### Demo Snippet (Python)
```python
# Simple retry decorator for demonstration purposes
import time
from functools import wraps

def retry(times=3, delay=0.1):
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            last_err = None
            for attempt in range(1, times + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    time.sleep(delay)
            raise last_err
        return inner
    return wrapper

@retry(times=3, delay=0.05)
def maybe_unstable():
    # Pretend to be flaky
    if time.time() % 2 < 1:
        raise RuntimeError("Transient failure")
    return "success"

print(maybe_unstable())
```

## Notes
- Remember to capture metrics for the new onboarding funnel
- Schedule a follow-up with support to review the new FAQ entries