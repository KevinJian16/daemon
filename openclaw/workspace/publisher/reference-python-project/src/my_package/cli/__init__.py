"""Command-line interface for my_package."""
import sys

from my_package.core import process


def main() -> int:
    """Entry point for CLI."""
    if len(sys.argv) > 1:
        result = process(sys.argv[1])
        print(result)
        return 0
    print("Usage: my-package <text>")
    return 1


if __name__ == "__main__":
    sys.exit(main())
