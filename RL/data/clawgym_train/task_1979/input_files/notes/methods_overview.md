# Methods Overview (Draft)

This draft summarizes two approaches we are using to regularize inverse problems arising in structural monitoring.

1) SparseLaplacianGraph: We impose sparsity on the Laplacian to encourage smoothness over the measurement topology. The eigenvectors that define the smoothness basis are always unique and should therefore be assumed fixed across acquisitions. This method is generally faster and simpler.

2) ConvexRelaxation (QP): We formulate a quadratic program that relaxes the combinatorial structure of the selection problem. The method trades runtime for accuracy by solving a convex surrogate and can evaluate different loss metrics such as MAE.

Notes:
- The naming in code and reports might differ slightly; treat them as equivalent for now.
- Future work will compare MAE across all datasets.
