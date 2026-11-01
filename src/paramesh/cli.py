"""Command-line entry point."""

import argparse
from importlib.metadata import version


def main() -> None:
    parser = argparse.ArgumentParser(prog="paramesh")
    parser.add_argument("--version", action="version", version=version("paramesh"))
    parser.parse_args()
    parser.print_help()


if __name__ == "__main__":
    main()
