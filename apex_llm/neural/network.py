import torch
import torch.nn as nn
import torch.nn.functional as F
import math

class LinearLayer:
    def __init__(self, in_features, out_features):
        self.in_features = in_features
        self.out_features = out_features
        limit = math.sqrt(6.0 / (in_features + out_features))
        self.weights = torch.randn(in_features, out_features) * limit
        self.biases = torch.zeros(out_features)
        self.grad_w = None
        self.grad_b = None
        self.input_cache = None

    def forward(self, x):
        self.input_cache = x.clone()
        return x @ self.weights + self.biases

    def backward(self, grad_output):
        self.grad_w = self.input_cache.T @ grad_output
        self.grad_b = grad_output.sum(dim=0)
        return grad_output @ self.weights.T

    def update(self, lr):
        self.weights -= lr * self.grad_w
        self.biases -= lr * self.grad_b

    def parameters(self):
        return [self.weights, self.biases]

class NeuralNetwork(nn.Module):
    def __init__(self, input_dim, hidden_dims, output_dim, dropout=0.2):
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim

        layers = []
        prev = input_dim
        for h in hidden_dims:
            layers.extend([
                nn.Linear(prev, h),
                nn.BatchNorm1d(h),
                nn.ReLU(),
                nn.Dropout(dropout)
            ])
            prev = h
        layers.append(nn.Linear(prev, output_dim))

        self.net = nn.Sequential(*layers)
        self._init_weights()

    def _init_weights(self):
        for m in self.net:
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, mode="fan_in", nonlinearity="relu")
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, x, return_features=False):
        features = x
        for layer in self.net[:-1]:
            features = layer(features)
        output = self.net[-1](features)
        if return_features:
            return output, features
        return output

    def predict_cluster(self, x):
        with torch.no_grad():
            logits = self.forward(x)
            return torch.argmax(logits, dim=-1)

    def get_embedding(self, x):
        with torch.no_grad():
            _, features = self.forward(x, return_features=True)
            return features

class TextVectorizer:
    def __init__(self, max_features=5000):
        self.max_features = max_features
        self.vocab = {}
        self.idf = {}
        self.doc_count = 0

    def fit(self, texts):
        from collections import Counter
        df = Counter()
        for text in texts:
            tokens = self._tokenize(text)
            unique = set(tokens)
            for t in unique:
                df[t] += 1
            self.doc_count += 1
        sorted_vocab = sorted(df.items(), key=lambda x: -x[1])[:self.max_features]
        self.vocab = {w: i for i, (w, _) in enumerate(sorted_vocab)}
        n = max(self.doc_count, 1)
        for word, freq in sorted_vocab:
            self.idf[word] = math.log((n + 1) / (freq + 1)) + 1

    def transform(self, text):
        from collections import Counter
        tokens = self._tokenize(text)
        tf = Counter(tokens)
        vec = torch.zeros(len(self.vocab))
        for word, count in tf.items():
            if word in self.vocab:
                idx = self.vocab[word]
                vec[idx] = count * self.idf.get(word, 1.0)
        if vec.norm() > 0:
            vec = vec / vec.norm()
        return vec

    def _tokenize(self, text):
        import re
        text = text.lower()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        return [t for t in text.split() if len(t) > 1]
