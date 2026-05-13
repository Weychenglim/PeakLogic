from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ValidationReport:
    site_id: str
    row_count: int
    gap_count: int
    duplicate_count: int
    missing_value_count: int
    expected_interval_minutes: int = 30


def validate_intervals(frame: pd.DataFrame, expected_interval_minutes: int = 30) -> ValidationReport:
    if frame.empty:
        return ValidationReport(
            site_id="unknown",
            row_count=0,
            gap_count=0,
            duplicate_count=0,
            missing_value_count=0,
            expected_interval_minutes=expected_interval_minutes,
        )

    ordered = frame.sort_values("interval_end").reset_index(drop=True)
    deltas = ordered["interval_end"].diff().dropna()
    gap_count = int((deltas != pd.Timedelta(minutes=expected_interval_minutes)).sum())
    duplicate_count = int(ordered["interval_end"].duplicated().sum())
    missing_value_count = int(
        ordered[["interval_start", "interval_end", "kw_import", "kw_export", "kvar_import", "kvar_export"]]
        .isna()
        .sum()
        .sum()
    )

    return ValidationReport(
        site_id=str(ordered["site_id"].iloc[0]),
        row_count=len(ordered),
        gap_count=gap_count,
        duplicate_count=duplicate_count,
        missing_value_count=missing_value_count,
        expected_interval_minutes=expected_interval_minutes,
    )
