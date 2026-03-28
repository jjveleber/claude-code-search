import sys
import os

# Ensure the project root is on sys.path so that `eval` resolves to eval/ (not tests/eval/)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
