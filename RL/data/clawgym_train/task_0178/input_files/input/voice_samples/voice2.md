Title: Guardrails first, heroics second

We don’t celebrate midnight saves. We celebrate boring pipelines that refuse unsafe configs.

Three habits that stick:
- Pre-merge diff: catch drift before it ships.
- Admission checks: block dangerous manifests.
- Continuous audit: reconcile desired vs. live and log the gap.

Shell glue we keep close:

```
#!/usr/bin/env bash
set -euo pipefail
git fetch origin
git diff --exit-code origin/main -- kube/ || echo "drift-detected"
```

If “drift-detected” shows up, the change doesn’t land. Fix the intent in Git, not by hand on the cluster.