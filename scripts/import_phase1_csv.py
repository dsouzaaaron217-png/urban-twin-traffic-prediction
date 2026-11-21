"""Validate and import traffic CSV rows into the Phase 1 ingestion store."""
import argparse
from pathlib import Path

from services.phase1_pipeline import import_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="CSV with canonical traffic observation columns")
    args = parser.parse_args()
    print(import_csv(args.csv_path))


if __name__ == "__main__":
    main()
