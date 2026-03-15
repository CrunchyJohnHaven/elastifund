"""Bootstrap ensemble predictor for uncertainty-aware classification."""

from __future__ import annotations

from dataclasses import dataclass
import random
import statistics
from typing import Any

from .classifiers import GradientBoostClassifier, LogisticClassifier, TreeClassifier


@dataclass(frozen=True)
class EnsemblePrediction:
    mean_prob: float
    std_prob: float
    p10_prob: float
    p90_prob: float
    consensus_fraction: float
    members: int


class BootstrapEnsembleClassifier:
    """Estimate prediction uncertainty from repeated bootstrap refits."""

    def __init__(
        self,
        feature_names: list[str],
        *,
        members: int = 15,
        sample_ratio: float = 0.8,
        min_rows: int = 80,
        seed: int = 42,
        model_families: tuple[str, ...] = ("logistic", "tree", "xgb"),
    ):
        self.feature_names = list(feature_names)
        self.members = max(3, int(members))
        self.sample_ratio = max(0.2, min(1.0, float(sample_ratio)))
        self.min_rows = max(20, int(min_rows))
        self.seed = seed
        self.model_families = model_families or ("tree",)

    def predict_distribution(
        self,
        train_rows: list[dict[str, Any]],
        labels: list[int],
        predict_rows: list[dict[str, Any]],
    ) -> list[EnsemblePrediction]:
        if not predict_rows:
            return []

        if len(train_rows) < self.min_rows or len(labels) != len(train_rows):
            return [self._neutral_prediction()] * len(predict_rows)

        sample_size = max(10, int(len(train_rows) * self.sample_ratio))
        member_probs: list[list[float]] = [[] for _ in predict_rows]

        for member_idx in range(self.members):
            rng = random.Random(self.seed + (member_idx * 7_919))
            sample_indices = [rng.randrange(0, len(train_rows)) for _ in range(sample_size)]
            sampled_rows = [train_rows[idx] for idx in sample_indices]
            sampled_labels = [labels[idx] for idx in sample_indices]

            if len(set(sampled_labels)) < 2:
                probs = [float(sampled_labels[0])] * len(predict_rows)
            else:
                model = self._make_model(
                    family=self.model_families[member_idx % len(self.model_families)],
                    random_state=self.seed + member_idx,
                )
                model.fit(sampled_rows, sampled_labels)
                probs = model.predict_proba(predict_rows)

            for row_idx, prob in enumerate(probs):
                member_probs[row_idx].append(max(0.001, min(0.999, float(prob))))

        return [self._summarize(probs) for probs in member_probs]

    def _make_model(self, *, family: str, random_state: int) -> Any:
        family = str(family or "tree").strip().lower()
        if family == "logistic":
            return LogisticClassifier(self.feature_names, random_state=random_state)
        if family == "xgb":
            return GradientBoostClassifier(self.feature_names, random_state=random_state)
        return TreeClassifier(self.feature_names, random_state=random_state)

    @staticmethod
    def _neutral_prediction() -> EnsemblePrediction:
        return EnsemblePrediction(
            mean_prob=0.5,
            std_prob=0.0,
            p10_prob=0.5,
            p90_prob=0.5,
            consensus_fraction=0.0,
            members=0,
        )

    @staticmethod
    def _quantile(sorted_probs: list[float], quantile: float) -> float:
        if not sorted_probs:
            return 0.5
        idx = int(round((len(sorted_probs) - 1) * quantile))
        return float(sorted_probs[max(0, min(idx, len(sorted_probs) - 1))])

    def _summarize(self, probs: list[float]) -> EnsemblePrediction:
        if not probs:
            return self._neutral_prediction()

        sorted_probs = sorted(probs)
        up_votes = sum(1 for prob in probs if prob >= 0.5)
        down_votes = len(probs) - up_votes
        return EnsemblePrediction(
            mean_prob=float(statistics.fmean(probs)),
            std_prob=float(statistics.pstdev(probs)) if len(probs) > 1 else 0.0,
            p10_prob=self._quantile(sorted_probs, 0.10),
            p90_prob=self._quantile(sorted_probs, 0.90),
            consensus_fraction=max(up_votes, down_votes) / len(probs),
            members=len(probs),
        )
