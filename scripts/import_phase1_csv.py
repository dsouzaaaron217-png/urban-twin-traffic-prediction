"""Validate and import traffic CSV rows into the Phase 1 ingestion store."""
import argparse
from pathlib import Path

from services.phase1_pipeline import import_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="CSV with canonical traffic observation columns")
    parser.add_argument(
        "--source", choices=("csv_import", "verified_csv_import"), default="csv_import",
        help="Use verified_csv_import only after independently confirming the dataset source and license.",
    )
    args = parser.parse_args()
    print(import_csv(args.csv_path, source=args.source))


if __name__ == "__main__":
    main()
