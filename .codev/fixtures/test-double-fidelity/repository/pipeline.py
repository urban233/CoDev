"""Tiny, deterministic scientific/ML evaluation-pipeline pieces used by the
evaluation fixture. Nothing here touches disk, the network, or a GPU, and
nothing is randomized."""


class StandardScaler:
    """Z-score scaler fit on precomputed per-feature statistics."""

    def __init__(self, means, stds):
        self.means = means
        self.stds = stds

    def transform(self, row):
        return [(x - m) / s for x, m, s in zip(row, self.means, self.stds)]


class CheckpointedRegressor:
    """A small linear regression model, normally restored from a saved
    checkpoint via `from_checkpoint`."""

    def __init__(self, weights, bias):
        self.weights = weights
        self.bias = bias

    @classmethod
    def from_checkpoint(cls, path):
        """Restore a fitted model from a checkpoint file on disk."""
        raise NotImplementedError(
            "checkpoint loading is not implemented in this fixture"
        )

    def predict(self, row):
        return sum(w * x for w, x in zip(self.weights, row)) + self.bias


def normalized_predictions(model, scaler, rows):
    """Normalize each row, then predict on it."""
    return [model.predict(scaler.transform(row)) for row in rows]


def batch_size(rows):
    """Return the number of rows in a batch."""
    return len(rows)
