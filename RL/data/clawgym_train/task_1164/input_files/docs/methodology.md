# Scalable Methods for Regional Sales Aggregation

This document describes the initial prototype (v1) for aggregating regional sales metrics and outlines considerations for scaling to larger datasets.

## Pipeline architecture v1 (single-machine pandas)
- Read the CSV into a single pandas DataFrame.
- Compute revenue = units * price.
- Group by region to compute sum of units and revenue.
- Write the aggregated CSV to outputs.

### Open Questions
- How to handle memory constraints for much larger files?
- What should the logging schema be for reproducibility?
- Do we need Dask or Spark for the next phase?
