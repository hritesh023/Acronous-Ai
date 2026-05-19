import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from collections import Counter

INTENTS = [
    "general_chat",
    "web_search",
    "image_analysis",
    "voice_command",
    "code_generation",
    "translation",
    "data_analysis",
    "planning_task"
]

class IntentClassifier(nn.Module):
    def __init__(self, embed_dim=384, num_intents=8):
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
            probs = F.softmax(logits, dim=-1)
            pred = torch.argmax(probs, dim=-1)
        if return_probs:
            return int(pred), probs.squeeze().tolist()
        return int(pred)

    def predict_with_threshold(self, embedding, threshold=0.4):
        pred, probs = self.predict(embedding, return_probs=True)
        if max(probs) < threshold:
            return -1, probs
        return pred, probs

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
