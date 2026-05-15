import numpy as np


def fit_oja(X, epochs=800, lr=0.01, seed=None):
    """
    Fit a single-unit Oja's rule on data X.

    Parameters
    ----------
    X : np.ndarray, shape (N, D)
        Input data (here D=2). Assumed reasonably scaled; mean-centering is
        recommended by caller/data.
    epochs : int
        Number of passes over the data.
    lr : float
        Learning rate.
    seed : int or None
        Random seed controlling the initial weights.

    Returns
    -------
    w : np.ndarray, shape (D,)
        Unit-norm weight vector approximating the first principal component.
    """
    raise NotImplementedError("Implement Oja's learning rule in this function.")
