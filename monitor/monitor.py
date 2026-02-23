"""
CLI entry point for the monitoring script.
"""

import sys
from .monitor_core import run_monitor


def main() -> None:
    """CLI entrypoint."""
    sys.exit(run_monitor())


if __name__ == "__main__":
    main()
