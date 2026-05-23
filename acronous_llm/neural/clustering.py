import numpy as np
import torch
from collections import defaultdict
import json
import os

class QueryClusterer:
    def __init__(self, n_clusters=8, max_iter=100):
        self.n_clusters = n_clusters
        self.max_iter = max_iter
        self.centroids = None
        self.labels_ = None
        self.cluster_counts = defaultdict(int)
        self.cluster_keywords = defaultdict(list)

    def fit(self, embeddings):
        if isinstance(embeddings, torch.Tensor):
            embeddings = embeddings.numpy()
        n_samples = embeddings.shape[0]
        indices = np.random.choice(n_samples, self.n_clusters, replace=False)
        self.centroids = embeddings[indices].copy()

        for _ in range(self.max_iter):
            distances = np.linalg.norm(embeddings[:, None] - self.centroids[None, :], axis=2)
            self.labels_ = np.argmin(distances, axis=1)
            new_centroids = np.zeros_like(self.centroids)
            for k in range(self.n_clusters):
                mask = self.labels_ == k
                if mask.sum() > 0:
                    new_centroids[k] = embeddings[mask].mean(axis=0)
            if np.allclose(self.centroids, new_centroids):
                break
            self.centroids = new_centroids

        for i, label in enumerate(self.labels_):
            self.cluster_counts[label] += 1
        return self.labels_

    def fit_predict(self, embeddings):
        self.fit(embeddings)
        return self.labels_

    def predict(self, embedding):
        if isinstance(embedding, torch.Tensor):
            embedding = embedding.numpy()
        if self.centroids is None:
            return 0
        embedding = embedding.reshape(1, -1)
        distances = np.linalg.norm(embedding - self.centroids, axis=1)
        return int(np.argmin(distances))

    def get_cluster_center(self, cluster_id):
        if self.centroids is None:
            return None
        return self.centroids[cluster_id]

    def add_keywords(self, cluster_id, keywords):
        self.cluster_keywords[cluster_id].extend(keywords)

    def get_cluster_summary(self):
        summary = {}
        for k in range(self.n_clusters):
            count = self.cluster_counts.get(k, 0)
            top_keywords = sorted(
                self.cluster_keywords.get(k, []),
                key=lambda x: self.cluster_keywords[k].count(x),
                reverse=True
            )[:5]
            summary[k] = {
                "count": count,
                "keywords": top_keywords
            }
        return summary

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez(
            path,
            centroids=self.centroids,
            labels=self.labels_,
            cluster_counts=dict(self.cluster_counts)
        )

    def load(self, path):
        if os.path.exists(path):
            data = np.load(path, allow_pickle=True)
            self.centroids = data["centroids"]
            self.labels_ = data["labels"]
            self.cluster_counts = defaultdict(int)
            counts = data["cluster_counts"].item()
            for k, v in counts.items():
                self.cluster_counts[k] = v
