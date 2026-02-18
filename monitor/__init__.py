"""
Monitoring package for college announcement checks.

This file marks `monitor/` as a Python package.

Note: We intentionally avoid importing `monitor.monitor` here to prevent
side-effects during `python -m monitor.monitor` execution (which can trigger
`runpy` warnings about modules being loaded twice).
"""

