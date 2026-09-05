import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from collections import Counter

INTENTS = [
    "general_chat",
    "web_search",
    "image_analysis",
    "image_generation",
    "voice_command",
    "code_generation",
    "translation",
    "data_analysis",
    "planning_task"
]

class IntentClassifier(nn.Module):
    def __init__(self, embed_dim=384, num_intents=9):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_intents = num_intents

        self.classifier = nn.Sequential(
            nn.Linear(embed_dim, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, num_intents)
        )
        self.intent_labels = INTENTS[:num_intents]
        self.examples = {i: [] for i in range(num_intents)}

    def forward(self, x):
        return self.classifier(x)

    def predict(self, embedding, return_probs=False):
        if isinstance(embedding, np.ndarray):
            embedding = torch.from_numpy(embedding).float()
        if embedding.dim() == 1:
            embedding = embedding.unsqueeze(0)
        with torch.no_grad():
            logits = self.forward(embedding)
            nn_logits = logits.clone()
            probs = F.softmax(logits, dim=-1)
            pred = torch.argmax(probs, dim=-1)

        nn_pred, nn_conf = self._predict_nearest(embedding)
        if nn_conf > float(probs.max()):
            pred = torch.tensor([nn_pred])
            probs = F.softmax(nn_logits, dim=-1) * 0.3
            probs[0, nn_pred] = nn_conf * 0.7 + probs[0, nn_pred] * 0.3

        if return_probs:
            return int(pred), probs.squeeze().tolist()
        return int(pred)

    def _predict_nearest(self, embedding):
        if isinstance(embedding, np.ndarray):
            embedding = torch.from_numpy(embedding).float()
        if embedding.dim() == 1:
            embedding = embedding.unsqueeze(0)

        best_intent = 0
        best_sim = -1.0
        for intent_id, ex_list in self.examples.items():
            if not ex_list:
                continue
            ex_tensor = torch.stack([e if isinstance(e, torch.Tensor) else torch.tensor(e) for e in ex_list])
            if ex_tensor.dim() == 1:
                ex_tensor = ex_tensor.unsqueeze(0)
            sims = F.cosine_similarity(embedding, ex_tensor)
            max_sim = sims.max().item()
            if max_sim > best_sim:
                best_sim = max_sim
                best_intent = intent_id

        confidence = max(0.0, min(1.0, (best_sim + 1.0) / 2.0))
        return best_intent, confidence

    def predict_with_threshold(self, embedding, threshold=0.4):
        if isinstance(embedding, np.ndarray):
            embedding = torch.from_numpy(embedding).float()
        if embedding.dim() == 1:
            embedding = embedding.unsqueeze(0)
        with torch.no_grad():
            logits = self.forward(embedding)
            probs = F.softmax(logits, dim=-1)
            pred = torch.argmax(probs, dim=-1)

        nn_pred, nn_probs = self._predict_nearest(embedding)
        if nn_probs > float(probs.max()):
            pred = nn_pred
            probs = F.one_hot(torch.tensor(pred), num_classes=self.num_intents).float() * nn_probs

        confidence = float(probs.max())
        if confidence < threshold:
            return -1, probs.squeeze().tolist()
        return int(pred), probs.squeeze().tolist()

    def add_example(self, embedding, intent_id):
        if 0 <= intent_id < self.num_intents:
            self.examples[intent_id].append(embedding.cpu() if torch.is_tensor(embedding) else embedding)

    def get_intent_name(self, intent_id):
        if 0 <= intent_id < len(self.intent_labels):
            return self.intent_labels[intent_id]
        return "unknown"

    def get_id_for_intent(self, intent_name):
        if intent_name in self.intent_labels:
            return self.intent_labels.index(intent_name)
        return -1

    def state_dict(self):
        return super().state_dict()

    def load_state_dict(self, state_dict):
        super().load_state_dict(state_dict)
