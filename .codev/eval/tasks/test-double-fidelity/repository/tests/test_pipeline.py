import unittest
from unittest.mock import MagicMock

from pipeline import batch_size, normalized_predictions


class BatchSizeTests(unittest.TestCase):
    def test_counts_rows(self):
        self.assertEqual(3, batch_size([[1, 2], [3, 4], [5, 6]]))

    def test_empty_batch_is_zero(self):
        self.assertEqual(0, batch_size([]))


class NormalizedPredictionsTests(unittest.TestCase):
    def test_normalizes_and_predicts(self):
        scaler = MagicMock()
        scaler.transform.side_effect = lambda row: [x / 2 for x in row]
        model = MagicMock()
        model.predict.side_effect = lambda row: sum(row)
        rows = [[2, 4], [6, 8]]
        self.assertEqual([3, 7], normalized_predictions(model, scaler, rows))


if __name__ == "__main__":
    unittest.main()
