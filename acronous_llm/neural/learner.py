import torch
import torch.optim as optim
import torch.nn.functional as F
from collections import deque
import numpy as np

class OnlineLearner:
    def __init__(self, model, lr=0.001, momentum=0.9, buffer_size=1000):
        self.model = model
        self.optimizer = optim.SGD(model.parameters(), lr=lr, momentum=momentum)
        self.buffer = deque(maxlen=buffer_size)
        self.feedback_history = deque(maxlen=500)
        self.step_count = 0
        self.lr = lr

    def update(self, embedding, feedback_score):
        if isinstance(embedding, np.ndarray):
            embedding = torch.from_numpy(embedding).float()
        if embedding.dim() == 1:
            embedding = embedding.unsqueeze(0)
        self.buffer.append((embedding, feedback_score))
        self.feedback_history.append(feedback_score)
        if len(self.buffer) >= 32:
            self._train_step()

    def _train_step(self):
        self.model.train()
        batch = list(self.buffer)[-32:]
        embeddings = torch.cat([e for e, _ in batch])
        scores = torch.tensor([s for _, s in batch], dtype=torch.float32).unsqueeze(1)
        scores = (scores - scores.mean()) / (scores.std() + 1e-8)
        scores = torch.clamp(scores, -2, 2)
        self.optimizer.zero_grad()
        outputs = self.model(embeddings)
        target = outputs.clone().detach()
        target = target * (1 + 0.1 * scores)
        loss = F.mse_loss(outputs, target)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()
        self.step_count += 1

    def get_average_feedback(self):
        if not self.feedback_history:
            return 0.0
        return sum(self.feedback_history) / len(self.feedback_history)

    def adjust_learning_rate(self, factor=0.95):
        for param_group in self.optimizer.param_groups:
            param_group["lr"] *= factor
        self.lr *= factor

class FeedbackCollector:
    def __init__(self, storage_path=None):
        self.storage_path = storage_path
        self.feedback_db = []

    def record(self, query, response, rating, metadata=None):
        entry = {
            "query": query,
            "response": response,
            "rating": rating,
            "metadata": metadata or {}
        }
        self.feedback_db.append(entry)
        return entry

    def get_positive_examples(self, min_rating=3):
        return [f for f in self.feedback_db if f["rating"] >= min_rating]

    def get_negative_examples(self, max_rating=1):
        return [f for f in self.feedback_db if f["rating"] <= max_rating]

    def get_trend(self):
        if len(self.feedback_db) < 10:
            return None
        recent = self.feedback_db[-10:]
        avg = sum(f["rating"] for f in recent) / len(recent)
        return avg
