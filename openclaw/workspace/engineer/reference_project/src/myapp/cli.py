"""Command-line interface."""

import sys

from .config import get_settings


def main() -> int:
    """Main entry point for the CLI."""
    settings = get_settings()
    print(f"Starting {settings.app_name} v{settings.version}")
    print(f"Debug mode: {settings.debug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
