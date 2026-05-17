from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import product
import math

import pandas as pd

from .tariff import TariffConfig, calculate_bill_components


@dataclass(frozen=True)
class OptimizationConfig:
    flexible_load_fraction: float = 0.15
    shift_window_intervals: int = 4
    battery_kw_options: list[float] = field(default_factory=lambda: [0.0, 100.0, 200.0])
    battery_kwh_options: list[float] = field(default_factory=lambda: [0.0, 200.0, 400.0])
    solar_kwp_options: list[float] = field(default_factory=lambda: [0.0, 100.0, 200.0])
    base_solar_kwp: float = 0.0
    battery_capex_rm_per_kw: float = 1400.0
    battery_capex_rm_per_kwh: float = 900.0
    solar_capex_rm_per_kwp: float = 3200.0
    max_scenarios: int = 27
    use_md_risk_envelope: bool = False
    md_risk_basis: str = "expected"
    tariff: TariffConfig = field(default_factory=TariffConfig)


@dataclass(frozen=True)
class OptimizationResult:
    optimized_schedule: pd.DataFrame
    scenario_summary: pd.DataFrame
    best_scenario: dict[str, float | str | bool]


def _base_profile(frame: pd.DataFrame, config: OptimizationConfig) -> pd.DataFrame:
    working = frame.copy()
    risk_basis = "p95" if config.use_md_risk_envelope else config.md_risk_basis
    if risk_basis == "p90":
        if "calibrated_p90_md_risk_kw" in working.columns:
            working["baseline_kw_import"] = working["calibrated_p90_md_risk_kw"].astype(float)
        elif "p90_md_risk_kw" in working.columns:
            working["baseline_kw_import"] = working["p90_md_risk_kw"].astype(float)
        else:
            raise ValueError("p90 risk basis requires calibrated_p90_md_risk_kw or p90_md_risk_kw")
    elif risk_basis == "p95" and "md_risk_envelope_kw" in working.columns:
        working["baseline_kw_import"] = working["md_risk_envelope_kw"].astype(float)
    elif risk_basis not in {"expected", "p50", "p90", "p95"}:
        raise ValueError("md_risk_basis must be one of expected, p50, p90, or p95")
    elif "forecast_kw_import" in working.columns:
        working["baseline_kw_import"] = working["forecast_kw_import"].astype(float)
    else:
        working["baseline_kw_import"] = working["kw_import"].astype(float)
    return working


def _bill_input_frame(profile: pd.DataFrame, kw_column: str) -> pd.DataFrame:
    return profile.loc[:, ["interval_start", "interval_end", kw_column]].rename(columns={kw_column: "kw_import"})


def _apply_flexible_shift(profile: pd.DataFrame, config: OptimizationConfig) -> pd.DataFrame:
    shifted = profile.copy()
    shifted["flex_shift_out_kw"] = 0.0
    shifted["flex_shift_in_kw"] = 0.0
    shifted["post_shift_kw_import"] = shifted["baseline_kw_import"].astype(float)

    grouped = shifted.groupby(shifted["interval_end"].dt.date, sort=False)
    for _, indices in grouped.groups.items():
        day_slice = shifted.loc[list(indices)].copy()
        threshold = float(day_slice["post_shift_kw_import"].quantile(0.85))
        if threshold <= 0:
            continue

        donor_rows = day_slice.sort_values("post_shift_kw_import", ascending=False).index.tolist()
        receiver_rows = day_slice.sort_values("post_shift_kw_import", ascending=True).index.tolist()

        for donor in donor_rows:
            current = float(shifted.at[donor, "post_shift_kw_import"])
            removable = min(current * config.flexible_load_fraction, max(current - threshold, 0.0))
            if removable <= 0:
                continue

            donor_position = shifted.index.get_loc(donor)
            candidates = []
            for receiver in receiver_rows:
                receiver_position = shifted.index.get_loc(receiver)
                same_day = shifted.at[receiver, "interval_end"].date() == shifted.at[donor, "interval_end"].date()
                within_window = abs(receiver_position - donor_position) <= config.shift_window_intervals
                below_threshold = float(shifted.at[receiver, "post_shift_kw_import"]) < threshold
                if receiver != donor and same_day and within_window and below_threshold:
                    candidates.append(receiver)

            if not candidates:
                continue

            share = removable / len(candidates)
            shifted.at[donor, "post_shift_kw_import"] = max(current - removable, 0.0)
            shifted.at[donor, "flex_shift_out_kw"] += removable
            for receiver in candidates:
                shifted.at[receiver, "post_shift_kw_import"] += share
                shifted.at[receiver, "flex_shift_in_kw"] += share

    return shifted


def clear_sky_sine_solar_factor(timestamp: pd.Timestamp) -> float:
    hour = timestamp.hour + timestamp.minute / 60.0
    if hour <= 6 or hour >= 18:
        return 0.0
    daylight_progress = (hour - 6.0) / 12.0
    return max(0.0, math.sin(math.pi * daylight_progress))


def _solar_profile_factor(timestamp: pd.Timestamp) -> float:
    return clear_sky_solar_factor(timestamp)


def clear_sky_solar_factor(timestamp: pd.Timestamp) -> float:
    return clear_sky_sine_solar_factor(timestamp)


def _apply_solar(profile: pd.DataFrame, solar_kwp: float, base_solar_kwp: float) -> pd.DataFrame:
    working = profile.copy()
    total_solar_kwp = max(0.0, float(base_solar_kwp) + float(solar_kwp))
    working["solar_offset_kw"] = working["interval_end"].map(
        lambda ts: total_solar_kwp * _solar_profile_factor(pd.Timestamp(ts))
    )
    working["after_solar_kw_import"] = (working["post_shift_kw_import"] - working["solar_offset_kw"]).clip(lower=0.0)
    return working


def _apply_battery(profile: pd.DataFrame, battery_kw: float, battery_kwh: float) -> pd.DataFrame:
    working = profile.copy()
    working["battery_discharge_kw"] = 0.0
    working["optimized_kw_import"] = working["after_solar_kw_import"].astype(float)

    if battery_kw <= 0 or battery_kwh <= 0:
        return working

    soc_kwh = battery_kwh
    target_kw = float(working["after_solar_kw_import"].quantile(0.85))
    interval_hours = (
        (working["interval_end"] - working["interval_start"]).dt.total_seconds().fillna(1800) / 3600.0
    )

    for idx, row in working.iterrows():
        current_kw = float(row["after_solar_kw_import"])
        excess_kw = max(current_kw - target_kw, 0.0)
        if excess_kw <= 0 or soc_kwh <= 0:
            continue
        max_discharge_by_energy = soc_kwh / float(interval_hours.loc[idx])
        discharge_kw = min(excess_kw, battery_kw, max_discharge_by_energy)
        working.at[idx, "battery_discharge_kw"] = discharge_kw
        working.at[idx, "optimized_kw_import"] = max(current_kw - discharge_kw, 0.0)
        soc_kwh -= discharge_kw * float(interval_hours.loc[idx])

    return working


def _scenario_payback_months(
    savings_rm: float,
    battery_kw: float,
    battery_kwh: float,
    solar_kwp: float,
    config: OptimizationConfig,
) -> float | None:
    capex = (
        battery_kw * config.battery_capex_rm_per_kw
        + battery_kwh * config.battery_capex_rm_per_kwh
        + solar_kwp * config.solar_capex_rm_per_kwp
    )
    if capex <= 0 or savings_rm <= 0:
        return None
    return capex / savings_rm


def evaluate_site_scenarios(
    frame: pd.DataFrame,
    config: OptimizationConfig | None = None,
) -> OptimizationResult:
    config = config or OptimizationConfig()
    baseline_profile = _base_profile(frame, config)
    shifted = _apply_flexible_shift(baseline_profile, config)
    baseline_bill = calculate_bill_components(_bill_input_frame(shifted, "baseline_kw_import"), config.tariff)

    scenario_rows: list[dict[str, float | str | bool | None]] = []
    best_schedule = None
    best_row = None

    combos = list(product(config.battery_kw_options, config.battery_kwh_options, config.solar_kwp_options))
    for scenario_index, (battery_kw, battery_kwh, solar_kwp) in enumerate(combos[: config.max_scenarios], start=1):
        solar_profile = _apply_solar(shifted, solar_kwp, config.base_solar_kwp)
        optimized = _apply_battery(solar_profile, battery_kw, battery_kwh)
        optimized_bill = calculate_bill_components(_bill_input_frame(optimized, "optimized_kw_import"), config.tariff)
        savings_rm = baseline_bill.total_cost_rm - optimized_bill.total_cost_rm
        md_reduction = baseline_bill.md_kw - optimized_bill.md_kw
        payback_months = _scenario_payback_months(savings_rm, battery_kw, battery_kwh, solar_kwp, config)
        row = {
            "scenario_id": f"scenario_{scenario_index}",
            "risk_basis": "p95" if config.use_md_risk_envelope else str(config.md_risk_basis),
            "battery_kw": float(battery_kw),
            "battery_kwh": float(battery_kwh),
            "solar_kwp": float(solar_kwp),
            "bill_before_rm": float(baseline_bill.total_cost_rm),
            "bill_after_rm": float(optimized_bill.total_cost_rm),
            "savings_rm": float(savings_rm),
            "md_before": float(baseline_bill.md_kw),
            "md_after": float(optimized_bill.md_kw),
            "peak_reduction_pct": float((md_reduction / baseline_bill.md_kw) * 100.0) if baseline_bill.md_kw else 0.0,
            "payback_months": float(payback_months) if payback_months is not None else None,
            "has_storage": bool(battery_kw > 0 and battery_kwh > 0),
            "has_new_solar": bool(solar_kwp > 0),
        }
        scenario_rows.append(row)
        if best_row is None or row["savings_rm"] > best_row["savings_rm"]:
            best_row = row
            best_schedule = optimized.copy()

    scenario_summary = pd.DataFrame(scenario_rows).sort_values(
        ["savings_rm", "md_after"], ascending=[False, True]
    ).reset_index(drop=True)
    assert best_row is not None
    assert best_schedule is not None
    return OptimizationResult(
        optimized_schedule=best_schedule.reset_index(drop=True),
        scenario_summary=scenario_summary,
        best_scenario=best_row,
    )


def evaluate_risk_basis_tradeoff(
    frame: pd.DataFrame,
    config: OptimizationConfig | None = None,
    risk_bases: tuple[str, ...] = ("p90", "p95"),
) -> pd.DataFrame:
    base_config = config or OptimizationConfig()
    rows: list[dict[str, float | str | bool | None]] = []
    for risk_basis in risk_bases:
        scenario_config = OptimizationConfig(
            flexible_load_fraction=base_config.flexible_load_fraction,
            shift_window_intervals=base_config.shift_window_intervals,
            battery_kw_options=base_config.battery_kw_options,
            battery_kwh_options=base_config.battery_kwh_options,
            solar_kwp_options=base_config.solar_kwp_options,
            battery_capex_rm_per_kw=base_config.battery_capex_rm_per_kw,
            battery_capex_rm_per_kwh=base_config.battery_capex_rm_per_kwh,
            solar_capex_rm_per_kwp=base_config.solar_capex_rm_per_kwp,
            max_scenarios=base_config.max_scenarios,
            use_md_risk_envelope=False,
            md_risk_basis=risk_basis,
            tariff=base_config.tariff,
        )
        result = evaluate_site_scenarios(frame, scenario_config)
        rows.append(dict(result.best_scenario))
    return pd.DataFrame(rows)


def _copy_config_with(
    config: OptimizationConfig,
    *,
    tariff: TariffConfig | None = None,
    battery_capex_rm_per_kw: float | None = None,
    battery_capex_rm_per_kwh: float | None = None,
    solar_capex_rm_per_kwp: float | None = None,
    base_solar_kwp: float | None = None,
) -> OptimizationConfig:
    return OptimizationConfig(
        flexible_load_fraction=config.flexible_load_fraction,
        shift_window_intervals=config.shift_window_intervals,
        battery_kw_options=config.battery_kw_options,
        battery_kwh_options=config.battery_kwh_options,
        solar_kwp_options=config.solar_kwp_options,
        base_solar_kwp=config.base_solar_kwp if base_solar_kwp is None else base_solar_kwp,
        battery_capex_rm_per_kw=(
            config.battery_capex_rm_per_kw if battery_capex_rm_per_kw is None else battery_capex_rm_per_kw
        ),
        battery_capex_rm_per_kwh=(
            config.battery_capex_rm_per_kwh if battery_capex_rm_per_kwh is None else battery_capex_rm_per_kwh
        ),
        solar_capex_rm_per_kwp=config.solar_capex_rm_per_kwp if solar_capex_rm_per_kwp is None else solar_capex_rm_per_kwp,
        max_scenarios=config.max_scenarios,
        use_md_risk_envelope=config.use_md_risk_envelope,
        md_risk_basis=config.md_risk_basis,
        tariff=config.tariff if tariff is None else tariff,
    )


def evaluate_assumption_sensitivity(
    frame: pd.DataFrame,
    config: OptimizationConfig | None = None,
) -> pd.DataFrame:
    """Evaluate active-analysis sensitivity for tariff and CAPEX assumptions."""
    base_config = config or OptimizationConfig()
    variants: list[tuple[str, str, str, float, OptimizationConfig]] = [
        ("base", "Current assumptions", "base", 0.0, base_config),
        (
            "md_rate_minus_10",
            "MD rate -10%",
            "md_rate_rm_per_kw",
            -10.0,
            _copy_config_with(
                base_config,
                tariff=replace(base_config.tariff, md_rate_rm_per_kw=base_config.tariff.md_rate_rm_per_kw * 0.9),
            ),
        ),
        (
            "md_rate_plus_10",
            "MD rate +10%",
            "md_rate_rm_per_kw",
            10.0,
            _copy_config_with(
                base_config,
                tariff=replace(base_config.tariff, md_rate_rm_per_kw=base_config.tariff.md_rate_rm_per_kw * 1.1),
            ),
        ),
        (
            "battery_capex_minus_10",
            "Battery CAPEX -10%",
            "battery_capex",
            -10.0,
            _copy_config_with(
                base_config,
                battery_capex_rm_per_kw=base_config.battery_capex_rm_per_kw * 0.9,
                battery_capex_rm_per_kwh=base_config.battery_capex_rm_per_kwh * 0.9,
            ),
        ),
        (
            "battery_capex_plus_10",
            "Battery CAPEX +10%",
            "battery_capex",
            10.0,
            _copy_config_with(
                base_config,
                battery_capex_rm_per_kw=base_config.battery_capex_rm_per_kw * 1.1,
                battery_capex_rm_per_kwh=base_config.battery_capex_rm_per_kwh * 1.1,
            ),
        ),
        (
            "solar_capex_minus_10",
            "Solar CAPEX -10%",
            "solar_capex_rm_per_kwp",
            -10.0,
            _copy_config_with(base_config, solar_capex_rm_per_kwp=base_config.solar_capex_rm_per_kwp * 0.9),
        ),
        (
            "solar_capex_plus_10",
            "Solar CAPEX +10%",
            "solar_capex_rm_per_kwp",
            10.0,
            _copy_config_with(base_config, solar_capex_rm_per_kwp=base_config.solar_capex_rm_per_kwp * 1.1),
        ),
    ]

    rows: list[dict[str, float | str | bool | None]] = []
    for sensitivity_id, label, changed_assumption, change_pct, variant_config in variants:
        result = evaluate_site_scenarios(frame, variant_config)
        best = result.best_scenario
        rows.append(
            {
                "sensitivity_id": sensitivity_id,
                "label": label,
                "scope": "active_analysis",
                "changed_assumption": changed_assumption,
                "change_pct": change_pct,
                "savings_rm": float(best["savings_rm"]),
                "payback_months": best["payback_months"],
                "bill_before_rm": float(best["bill_before_rm"]),
                "bill_after_rm": float(best["bill_after_rm"]),
                "md_before": float(best["md_before"]),
                "md_after": float(best["md_after"]),
                "battery_kw": float(best["battery_kw"]),
                "battery_kwh": float(best["battery_kwh"]),
                "solar_kwp": float(best["solar_kwp"]),
            }
        )
    return pd.DataFrame(rows)
