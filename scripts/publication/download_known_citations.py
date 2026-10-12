#!/usr/bin/python3
"""Compatibility entry point for the incoming-citation stage."""
from update import cli

if __name__ == "__main__":
    raise SystemExit(cli(stage="known_citations"))
