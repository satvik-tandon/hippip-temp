#!/usr/bin/python3
"""Compatibility entry point for missing citing-article metadata."""
from update import cli

if __name__ == "__main__":
    raise SystemExit(cli(stage="citing_articles"))
