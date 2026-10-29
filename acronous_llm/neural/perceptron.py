"""Acronous LLM — perceptron building blocks (single + multi-layer).

CPU-friendly pure-PyTorch implementations used to strengthen the brain:
  * SingleLayerPerceptron  — fast linear classifier / gate (Rosenblatt, 1958)
  * MultiLayerPerceptron   — non-linear feature learner (backprop, ReLU)
Both are deliberately small so they run on the Contabo 4-core CPU box and are
used as auxiliary scorers (intent confidence, fuzzy gating, unsupervised
cluster refinement) on top of the main LLM rather than replacing it.
"""
import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class SingleLayerPerceptron(nn.Module):
    """Rosenblatt perceptron: one linear layer + activation.

    Trained with the perceptron learning rule (or SGD). Acts as a fast,
    interpretable gate: "is this query on-topic / high-confidence / safe?".
    """

    def __init__(self, in_features: int, out_features: int = 1, activation: str = "sigmoid"):
        super().__init__()
        self.linear = nn.Linear(in_features, out_features)
        self.activation = activation
        nn.init.xavier_uniform_(self.linear.weight)
        nn.init.zeros_(self.linear.bias)

    def forward(self, x):
        z = self.linear(x)
        if self.activation == "sigmoid":
            return torch.sigmoid(z)
        if self.activation == "tanh":
            return torch.tanh(z)
        if self.activation == "relu":
            return F.relu(z)
        if self.activation == "step":
            return (z >= 0).float()
        return z

    def predict(self, x):
        with torch.no_grad():
            return self.forward(x)

    def update_rule(self, x, y, lr: float = 0.01):
        """Classic perceptron update: w += lr * (y - yhat) * x."""
        with torch.no_grad():
            yhat = self.forward(x)
            err = (y - yhat)
            self.linear.weight += lr * (err.t() @ x) if err.dim() > 1 else lr * err * x
            self.linear.bias += lr * err.sum(dim=0) if err.dim() > 1 else lr * err


class MultiLayerPerceptron(nn.Module):
    """Feed-forward MLP with configurable depth/width and dropout.

    Used as the non-linear scorer behind fuzzy gating and RAG confidence
    refinement. Small enough to train on CPU between requests.
    """

    def __init__(self, in_features: int, hidden_dims=None, out_features: int = 1,
                 dropout: float = 0.1, activation: str = "relu"):
        super().__init__()
        if hidden_dims is None:
            hidden_dims = [256, 128, 64]
        layers = []
        prev = in_features
        for h in hidden_dims:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.BatchNorm1d(h) if h > 1 else nn.Identity())
            if activation == "relu":
                layers.append(nn.ReLU())
            elif activation == "gelu":
                layers.append(nn.GELU())
            elif activation == "tanh":
                layers.append(nn.Tanh())
            layers.append(nn.Dropout(dropout))
            prev = h
        layers.append(nn.Linear(prev, out_features))
        self.net = nn.Sequential(*layers)
        self._init()

    def _init(self):
        for m in self.net:
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, x):
        return self.net(x)

    def predict_proba(self, x):
        with torch.no_grad():
            return torch.sigmoid(self.forward(x))
