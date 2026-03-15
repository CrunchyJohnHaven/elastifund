"""Classifier wrappers with optional sklearn/xgboost dependencies."""

from __future__ import annotations

import math
from typing import Any

try:  # pragma: no cover - optional dependency
    from sklearn.ensemble import RandomForestClassifier  # type: ignore
    from sklearn.linear_model import LogisticRegression  # type: ignore
except Exception:  # pragma: no cover
    LogisticRegression = None
    RandomForestClassifier = None

try:  # pragma: no cover - optional dependency
    from xgboost import XGBClassifier  # type: ignore
except Exception:  # pragma: no cover
    XGBClassifier = None


class _MatrixBuilder:
    def __init__(self, feature_names: list[str]):
        self.feature_names = feature_names

    def transform(self, rows: list[dict[str, float]]) -> list[list[float]]:
        return [[float(row.get(name, 0.0)) for name in self.feature_names] for row in rows]


class LogisticClassifier:
    """Logistic classifier with sklearn or gradient-descent fallback."""

    def __init__(
        self,
        feature_names: list[str],
        learning_rate: float = 0.05,
        epochs: int = 250,
        random_state: int = 42,
    ):
        self.builder = _MatrixBuilder(feature_names)
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.random_state = random_state
        self.weights: list[float] = [0.0] * (len(feature_names) + 1)
        self._model: Any | None = None

    @staticmethod
    def _sigmoid(value: float) -> float:
        value = max(-50.0, min(50.0, value))
        return 1.0 / (1.0 + math.exp(-value))

    def fit(self, rows: list[dict[str, float]], labels: list[int]) -> None:
        x = self.builder.transform(rows)
        if not x:
            return

        if LogisticRegression is not None:
            model = LogisticRegression(max_iter=500, random_state=self.random_state)
            model.fit(x, labels)
            self._model = model
            return

        # Fallback gradient descent logistic regression.
        for _ in range(self.epochs):
            grad = [0.0] * len(self.weights)
            for feats, y in zip(x, labels, strict=False):
                z = self.weights[0] + sum(w * v for w, v in zip(self.weights[1:], feats, strict=False))
                p = self._sigmoid(z)
                err = p - y
                grad[0] += err
                for i, feat in enumerate(feats, start=1):
                    grad[i] += err * feat

            inv_n = 1.0 / max(len(x), 1)
            for i in range(len(self.weights)):
                self.weights[i] -= self.learning_rate * grad[i] * inv_n

    def predict_proba(self, rows: list[dict[str, float]]) -> list[float]:
        x = self.builder.transform(rows)
        if self._model is not None:
            probs = self._model.predict_proba(x)
            return [float(item[1]) for item in probs]

        out: list[float] = []
        for feats in x:
            z = self.weights[0] + sum(w * v for w, v in zip(self.weights[1:], feats, strict=False))
            out.append(self._sigmoid(z))
        return out


class TreeClassifier:
    """Tree baseline with sklearn RF fallback to decision stump."""

    def __init__(self, feature_names: list[str], random_state: int = 42):
        self.builder = _MatrixBuilder(feature_names)
        self.random_state = random_state
        self._model: Any | None = None
        self._feature_idx = 0
        self._threshold = 0.0
        self._left_prob = 0.5
        self._right_prob = 0.5

    def fit(self, rows: list[dict[str, float]], labels: list[int]) -> None:
        x = self.builder.transform(rows)
        if not x:
            return

        if RandomForestClassifier is not None:
            model = RandomForestClassifier(
                n_estimators=100,
                random_state=self.random_state,
                min_samples_leaf=5,
            )
            model.fit(x, labels)
            self._model = model
            return

        # Fallback: one-level threshold split.
        best_score = float("inf")
        for feature_idx in range(len(x[0])):
            values = sorted(v[feature_idx] for v in x)
            threshold = values[len(values) // 2]
            left = [labels[i] for i, row in enumerate(x) if row[feature_idx] <= threshold]
            right = [labels[i] for i, row in enumerate(x) if row[feature_idx] > threshold]
            if not left or not right:
                continue
            left_prob = sum(left) / len(left)
            right_prob = sum(right) / len(right)
            score = sum((y - left_prob) ** 2 for y in left) + sum((y - right_prob) ** 2 for y in right)
            if score < best_score:
                best_score = score
                self._feature_idx = feature_idx
                self._threshold = threshold
                self._left_prob = left_prob
                self._right_prob = right_prob

    def predict_proba(self, rows: list[dict[str, float]]) -> list[float]:
        x = self.builder.transform(rows)
        if self._model is not None:
            probs = self._model.predict_proba(x)
            return [float(item[1]) for item in probs]

        out: list[float] = []
        for feats in x:
            if feats[self._feature_idx] <= self._threshold:
                out.append(self._left_prob)
            else:
                out.append(self._right_prob)
        return out


class GradientBoostClassifier:
    """XGBoost wrapper with tree fallback."""

    def __init__(self, feature_names: list[str], random_state: int = 42):
        self.builder = _MatrixBuilder(feature_names)
        self.random_state = random_state
        self._tree_fallback = TreeClassifier(feature_names, random_state=random_state)
        self._model: Any | None = None

    def fit(self, rows: list[dict[str, float]], labels: list[int]) -> None:
        x = self.builder.transform(rows)
        if not x:
            return
        if XGBClassifier is not None:
            model = XGBClassifier(
                n_estimators=150,
                learning_rate=0.05,
                max_depth=3,
                subsample=0.9,
                colsample_bytree=0.9,
                objective="binary:logistic",
                eval_metric="logloss",
                random_state=self.random_state,
                n_jobs=1,
            )
            model.fit(x, labels)
            self._model = model
            return

        self._tree_fallback.fit(rows, labels)

    def predict_proba(self, rows: list[dict[str, float]]) -> list[float]:
        x = self.builder.transform(rows)
        if self._model is not None:
            probs = self._model.predict_proba(x)
            return [float(item[1]) for item in probs]
        return self._tree_fallback.predict_proba(rows)
