"""Acronous LLM — unsupervised learning helpers (CPU).

  * KMeans clustering (Lloyd) — query/topic grouping
  * PCA (eigendecomposition) — dimensionality reduction for embeddings
  * Self-Organising Map (SOM) — topology-preserving clustering
  * Gaussian Mixture (EM, diagonal covariance) — soft clustering
These complement the supervised intent classifier and let the brain discover
structure in interactions without labels, improving RAG routing and memory.
"""
import math
import numpy as np


class KMeans:
    def __init__(self, n_clusters=8, max_iter=100, seed=42):
        self.n_clusters = n_clusters
        self.max_iter = max_iter
        self.rng = np.random.default_rng(seed)
        self.centroids = None
        self.labels_ = None

    def fit(self, X):
        X = np.asarray(X, dtype=np.float64)
        n = X.shape[0]
        idx = self.rng.choice(n, self.n_clusters, replace=False)
        self.centroids = X[idx].copy()
        for _ in range(self.max_iter):
            d = np.linalg.norm(X[:, None, :] - self.centroids[None, :, :], axis=2)
            labels = np.argmin(d, axis=1)
            new = np.zeros_like(self.centroids)
            for k in range(self.n_clusters):
                m = labels == k
                new[k] = X[m].mean(axis=0) if m.any() else self.centroids[k]
            if np.allclose(new, self.centroids):
                self.centroids = new
                self.labels_ = labels
                break
            self.centroids = new
            self.labels_ = labels
        return self

    def predict(self, X):
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        d = np.linalg.norm(X[:, None, :] - self.centroids[None, :, :], axis=2)
        return np.argmin(d, axis=1)


class PCA:
    def __init__(self, n_components=32):
        self.n_components = n_components
        self.mean_ = None
        self.components_ = None

    def fit(self, X):
        X = np.asarray(X, dtype=np.float64)
        self.mean_ = X.mean(axis=0)
        Xc = X - self.mean_
        cov = (Xc.T @ Xc) / max(X.shape[0] - 1, 1)
        w, v = np.linalg.eigh(cov)
        order = np.argsort(w)[::-1]
        self.components_ = v[:, order[: self.n_components]]
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=np.float64)
        return (X - self.mean_) @ self.components_


class SOM:
    """Self-Organising Map (Kohonen) — small grid, Euclidean distance."""

    def __init__(self, grid=(8, 8), n_iter=200, seed=0):
        self.gw, self.gh = grid
        self.n_iter = n_iter
        self.rng = np.random.default_rng(seed)
        self.weights = None

    def fit(self, X):
        X = np.asarray(X, dtype=np.float64)
        dim = X.shape[1]
        self.weights = self.rng.normal(size=(self.gw, self.gh, dim))
        n = X.shape[0]
        for t in range(self.n_iter):
            lr = 0.5 * (1 - t / self.n_iter)
            sigma = max(1.0, (self.gw / 2.0) * (1 - t / self.n_iter))
            i = self.rng.integers(0, n)
            x = X[i]
            # BMU
            diff = self.weights - x
            dist = np.sum(diff * diff, axis=2)
            bmu = np.unravel_index(np.argmin(dist), dist.shape)
            # update
            for gx in range(self.gw):
                for gy in range(self.gh):
                    d2 = (gx - bmu[0]) ** 2 + (gy - bmu[1]) ** 2
                    h = math.exp(-d2 / (2 * sigma * sigma))
                    self.weights[gx, gy] += lr * h * (x - self.weights[gx, gy])
        return self

    def predict(self, X):
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        out = []
        for x in X:
            diff = self.weights - x
            dist = np.sum(diff * diff, axis=2)
            out.append(np.unravel_index(np.argmin(dist), dist.shape))
        return out


class GaussianMixture:
    """Diagonal-covariance GMM via EM."""

    def __init__(self, n_components=4, max_iter=50, seed=0):
        self.k = n_components
        self.max_iter = max_iter
        self.rng = np.random.default_rng(seed)
        self.means_ = None
        self.vars_ = None
        self.weights_ = None

    def fit(self, X):
        X = np.asarray(X, dtype=np.float64)
        n, d = X.shape
        idx = self.rng.choice(n, self.k, replace=False)
        self.means_ = X[idx].copy()
        self.vars_ = np.ones((self.k, d))
        self.weights_ = np.full(self.k, 1.0 / self.k)
        for _ in range(self.max_iter):
            # E-step
            resp = np.zeros((n, self.k))
            for j in range(self.k):
                var = self.vars_[j] + 1e-6
                diff = X - self.means_[j]
                logp = -0.5 * np.sum(np.log(2 * math.pi * var)) - 0.5 * np.sum(diff * diff / var, axis=1)
                resp[:, j] = self.weights_[j] * np.exp(logp)
            resp /= resp.sum(axis=1, keepdims=True) + 1e-12
            # M-step
            Nk = resp.sum(axis=0)
            self.weights_ = Nk / n
            self.means_ = (resp.T @ X) / (Nk[:, None] + 1e-12)
            for j in range(self.k):
                diff = X - self.means_[j]
                self.vars_[j] = (resp[:, j] @ (diff * diff)) / (Nk[j] + 1e-12) + 1e-6
        return self

    def predict(self, X):
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        resp = np.zeros((X.shape[0], self.k))
        for j in range(self.k):
            var = self.vars_[j] + 1e-6
            diff = X - self.means_[j]
            logp = -0.5 * np.sum(np.log(2 * math.pi * var)) - 0.5 * np.sum(diff * diff / var, axis=1)
            resp[:, j] = self.weights_[j] * np.exp(logp)
        return np.argmax(resp, axis=1)
