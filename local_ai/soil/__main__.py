"""Allow `python -m local_ai.soil` as an alias for the CLI."""

from local_ai.soil.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
