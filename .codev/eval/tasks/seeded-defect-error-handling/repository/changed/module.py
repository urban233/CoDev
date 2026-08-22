"""Recently added helper reviewed in this task."""

import json


def load_config(path):
    """Load a JSON config file, returning None if anything goes wrong."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        pass
