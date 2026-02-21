import argparse
import sys
from pathlib import Path

import pandas as pd


def parse_keywords(raw: str):
    if not raw:
        return []
    # Split by comma, strip whitespace, drop empties
    return [k.strip() for k in raw.split(",") if k.strip()]


def build_row_text(df: pd.DataFrame, columns: list[str] | None):
    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValueError(f"Columns not found: {', '.join(missing)}")
        cols = columns
    else:
        # Use all columns by default
        cols = list(df.columns)
    # Convert to string and join with space per row
    return df[cols].astype(str).agg(" ".join, axis=1)


def match_keywords(series: pd.Series, keywords: list[str], mode: str):
    if mode not in ("any", "all"):
        raise ValueError("mode must be 'any' or 'all'")

    if not keywords:
        default = False if mode == "any" else True
        return pd.Series([default] * len(series), index=series.index)

    lowered = series.str.lower()
    kws = [k.lower() for k in keywords]

    if mode == "any":
        mask = pd.Series([False] * len(series), index=series.index)
        for k in kws:
            mask = mask | lowered.str.contains(k, na=False, regex=False)
        return mask
    else:
        mask = pd.Series([True] * len(series), index=series.index)
        for k in kws:
            mask = mask & lowered.str.contains(k, na=False, regex=False)
        return mask


def main():
    parser = argparse.ArgumentParser(
        description="Filter job postings in an Excel file by include/exclude keywords."
    )
    parser.add_argument("--input", required=True, help="Input Excel file path (.xlsx)")
    parser.add_argument("--output", required=True, help="Output Excel file path (.xlsx)")
    parser.add_argument(
        "--include",
        default="",
        help="Comma-separated keywords to include (optional).",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated keywords to exclude (optional).",
    )
    parser.add_argument(
        "--include-mode",
        choices=["any", "all"],
        default="any",
        help="Match any or all include keywords (default: any).",
    )
    parser.add_argument(
        "--exclude-mode",
        choices=["any", "all"],
        default="any",
        help="Match any or all exclude keywords (default: any).",
    )
    parser.add_argument(
        "--columns",
        default="",
        help="Comma-separated column names to search. Default: all columns.",
    )
    parser.add_argument(
        "--output-csv",
        default="",
        help="Optional output CSV path.",
    )
    parser.add_argument(
        "--list-columns",
        action="store_true",
        help="List columns in the Excel file and exit.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_excel(input_path)

    if args.list_columns:
        print("Columns:")
        for c in df.columns:
            print(f"- {c}")
        return

    include_keywords = parse_keywords(args.include)
    exclude_keywords = parse_keywords(args.exclude)
    columns = parse_keywords(args.columns)

    row_text = build_row_text(df, columns)

    if include_keywords:
        include_mask = match_keywords(row_text, include_keywords, args.include_mode)
    else:
        include_mask = pd.Series([True] * len(df), index=df.index)

    if exclude_keywords:
        exclude_mask = match_keywords(row_text, exclude_keywords, args.exclude_mode)
    else:
        exclude_mask = pd.Series([False] * len(df), index=df.index)

    # Exclude takes priority
    filtered = df[include_mask & ~exclude_mask].copy()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_excel(output_path, index=False)

    if args.output_csv:
        csv_path = Path(args.output_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        filtered.to_csv(csv_path, index=False)

    print(f"Input rows: {len(df)}")
    print(f"Filtered rows: {len(filtered)}")
    print(f"Saved: {output_path}")
    if args.output_csv:
        print(f"Saved: {csv_path}")


if __name__ == "__main__":
    main()
