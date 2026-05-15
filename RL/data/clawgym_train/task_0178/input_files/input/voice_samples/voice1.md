Title: Stop guessing—diff the thing

The last alert didn’t need a war room. It needed a diff. We ran the check, saw the divergence, and rolled back. Incident over.

Here’s the pattern we trust:
- Keep desired state in Git.
- Block direct writes to the cluster.
- Prove changes with a diff before merge and a diff at admission.

Operator's note: When you stop pushing “quick fixes” into prod and only accept changes that pass policy, the noise drops overnight. Not magic. Just discipline.

Example policy gate:

```
package cicd.policy

deny[msg] {
  some i
  input.pr.files[i].path == "kube/deploy.yaml"
  not input.pr.labels[_] == "approved-change"
  msg := "Deployment missing approved-change label"
}
```

Push a change that violates the rule. Watch it fail fast. Fix it in Git. Merge clean. Reconcile. Done.