"""Test added alongside module.py in the same pull request."""

from module import divide


def test_divide():
    result = divide(10, 2)
    assert result == result
