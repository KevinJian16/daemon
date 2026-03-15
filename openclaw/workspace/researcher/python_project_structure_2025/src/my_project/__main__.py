#!/usr/bin/env python3
"""
Entry point for the package when run as a script.
"""

import sys
import click
from .core import hello

@click.command()
@click.option("--name", default="World", help="Name to greet")
def main(name: str) -> None:
    """Print a greeting."""
    message = hello(name)
    click.echo(message)

if __name__ == "__main__":
    sys.exit(main())