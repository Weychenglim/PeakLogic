from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TariffConfig:
    md_rate_rm_per_kw: float = 97.06
    offpeak_energy_rate_rm_per_kwh: float = 0.365
    peak_energy_rate_rm_per_kwh: float = 0.455
    peak_start_hour: int = 14
    peak_end_hour: int = 22
    md_period_intervals: int = 30 * 48


@dataclass(frozen=True)
class BillBreakdown:
    md_kw: float
    md_cost_rm: float
    energy_kwh: float
    energy_cost_rm: float
    total_cost_rm: float


def calculate_bill_components(frame: pd.DataFrame, tariff: TariffConfig) -> BillBreakdown:
    if frame.empty:
        return BillBreakdown(md_kw=0.0, md_cost_rm=0.0, energy_kwh=0.0, energy_cost_rm=0.0, total_cost_rm=0.0)
    if tariff.md_period_intervals <= 0:
        raise ValueError("md_period_intervals must be positive")

    working = frame.sort_values("interval_end").reset_index(drop=True).copy()
    if "optimized_kw_import" in working.columns:
        kw_column = "optimized_kw_import"
    elif "forecast_kw_import" in working.columns:
        kw_column = "forecast_kw_import"
    else:
        kw_column = "kw_import"

    interval_hours = (
        (working["interval_end"] - working["interval_start"]).dt.total_seconds().fillna(1800) / 3600.0
    )
    hours = working["interval_end"].dt.hour
    is_peak = (hours >= tariff.peak_start_hour) & (hours < tariff.peak_end_hour)
    rates = is_peak.map(
        lambda value: tariff.peak_energy_rate_rm_per_kwh if value else tariff.offpeak_energy_rate_rm_per_kwh
    )

    energy_kwh_series = working[kw_column].clip(lower=0) * interval_hours
    energy_cost_rm = float((energy_kwh_series * rates).sum())
    period_ids = pd.Series(range(len(working)), index=working.index) // tariff.md_period_intervals
    monthly_md_peaks = working[kw_column].clip(lower=0).groupby(period_ids).max()
    md_kw = float(monthly_md_peaks.max()) if not monthly_md_peaks.empty else 0.0
    md_cost_rm = float(monthly_md_peaks.sum()) * tariff.md_rate_rm_per_kw
    total_cost_rm = md_cost_rm + energy_cost_rm

    return BillBreakdown(
        md_kw=md_kw,
        md_cost_rm=md_cost_rm,
        energy_kwh=float(energy_kwh_series.sum()),
        energy_cost_rm=energy_cost_rm,
        total_cost_rm=total_cost_rm,
    )
