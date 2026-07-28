import os
import sys

# Add src to sys.path so tests can import from src modules without ModuleNotFoundError
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)
