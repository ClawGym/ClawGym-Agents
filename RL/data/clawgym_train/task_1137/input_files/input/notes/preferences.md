# Research preferences for explainability on tree ensembles

Context: I'm evaluating explainability techniques for random forests and gradient-boosted trees on tabular data. I prefer local explanations that are reasonably faithful and computationally efficient. I only want techniques with open-source implementations. For tree compatibility, treat "model-agnostic" and "tree-only" as compatible; methods marked "differentiable-only" are not compatible with my use case.

The following YAML block encodes the filters, scoring weights, mappings, and tie-breakers to use:

```yaml
filters:
  required_explanation_type: local
  exclude_compute_cost: high
  require_open_source: true
  tree_compatibility_definition: ["model-agnostic", "tree-only"]
scoring:
  weights:
    tree_compatibility: 3
    local_explanation: 2
    faithfulness: 2
    compute_efficiency: 1
    open_source: 1
  mappings:
    faithfulness:
      high: 2
      medium: 1
      low: 0
    compute_efficiency:
      low: 2
      medium: 1
      high: 0
  tie_breakers: ["faithfulness", "compute_efficiency", "alphabetical"]
```

Notes:
- Scoring rule: score = 3*(is_tree_compatible) + 2*(is_local) + 2*(faithfulness_score) + 1*(compute_efficiency_score) + 1*(open_source_score).
- is_tree_compatible is 1 if model_compatibility ∈ {model-agnostic, tree-only} else 0. is_local is 1 if explanation_type == local else 0. open_source_score is 1 if open_source == Yes else 0.
- Apply filters first, then score and rank. For ties, prefer higher faithfulness, then higher compute efficiency, then alphabetical by method_name.
