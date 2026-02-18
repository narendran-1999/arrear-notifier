"""
Monitoring package for college announcement checks.

This module exposes the main entrypoint used by GitHub Actions.
"""

from .monitor import main

__all__ = ["main"]

