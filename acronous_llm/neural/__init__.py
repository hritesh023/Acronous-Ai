from .network import NeuralNetwork
from .clustering import QueryClusterer
from .classifier import IntentClassifier
from .learner import OnlineLearner

class AcronousNeuralEngine:
    def __init__(self, config):
        self.config = config
        self.network = NeuralNetwork(
            input_dim=config.EMBED_DIM,
            hidden_dims=[512, 256, 128],
            output_dim=config.CLUSTER_COUNT
        )
        self.clusterer = QueryClusterer(n_clusters=config.CLUSTER_COUNT)
        self.classifier = IntentClassifier(
            embed_dim=config.EMBED_DIM,
            num_intents=9
        )
        self.learner = OnlineLearner(
            model=self.network,
            lr=config.LEARNING_RATE
        )
        self.training_data = []

    def forward(self, x):
        return self.network(x)

    def learn(self, query_embedding, feedback, intent=None):
        self.training_data.append((query_embedding, feedback, intent))
        self.learner.update(query_embedding, feedback)
        if intent is not None:
            self.classifier.add_example(query_embedding, intent)

    def cluster_queries(self, embeddings):
        return self.clusterer.fit_predict(embeddings)

    def predict_intent(self, embedding, return_probs=False):
        return self.classifier.predict(embedding, return_probs=return_probs)

    def get_cluster_info(self, embedding):
        return self.clusterer.predict(embedding)

    def save_state(self, path):
        import torch
        torch.save({
            "network": self.network.state_dict(),
            "classifier": self.classifier.state_dict(),
        }, path)

    def load_state(self, path):
        import torch
        import os
        if os.path.exists(path):
            data = torch.load(path, map_location="cpu")
            self.network.load_state_dict(data["network"])
            self.classifier.load_state_dict(data["classifier"])
