"""Sample Python module for chunker tests."""
import os

CONSTANT = 42


def add(a, b):
    """Add two numbers."""
    return a + b


def multiply(a, b):
    """Multiply two numbers."""
    return a * b


class Calculator:
    """A simple calculator."""

    def __init__(self):
        self.result = 0

    def add(self, x):
        """Add x to result."""
        self.result += x
        return self

    def reset(self):
        """Reset result."""
        self.result = 0
