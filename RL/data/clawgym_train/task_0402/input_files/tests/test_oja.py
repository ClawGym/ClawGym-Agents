import numpy as np
from src.oja import fit_oja


def load_data():
    X = np.loadtxt("input/sensory_signals.csv", delimiter=",", skiprows=1)
    return X


def principal_component(X):
    # Covariance with features as columns
    C = np.cov(X, rowvar=False, bias=False)
    eigvals, eigvecs = np.linalg.eigh(C)
    v = eigvecs[:, np.argmax(eigvals)]
    v = v / np.linalg.norm(v)
    return v


def test_output_shape_and_norm():
    X = load_data()
    w = fit_oja(X, epochs=800, lr=0.01, seed=0)
    assert w.shape == (2,)
    norm = np.linalg.norm(w)
    assert np.isclose(norm, 1.0, atol=1e-3)


def test_alignment_with_pc1():
    X = load_data()
    w = fit_oja(X, epochs=800, lr=0.01, seed=0)
    v = principal_component(X)
    cos = np.abs(np.dot(w, v))
    assert cos > 0.999


def test_reproducibility_across_seeds():
    X = load_data()
    w0 = fit_oja(X, epochs=800, lr=0.01, seed=0)
    w1 = fit_oja(X, epochs=800, lr=0.01, seed=1)
    # Orientation may flip; compare absolute dot
    assert np.abs(np.dot(w0, w1)) > 0.99
