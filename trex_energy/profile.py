from __future__ import annotations

from pathlib import Path

import pandas as pd

from .ingestion import load_site_workbook
from .validation import validate_intervals


def load_workspace_datasets(root: str | Path) -> list[dict[str, object]]:
    workspace = Path(root)
    datasets: list[dict[str, object]] = []
    for path in sorted(workspace.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        frame, metadata = load_site_workbook(path)
        validation = validate_intervals(frame)
        datasets.append(
            {
                "path": path,
                "frame": frame,
                "metadata": metadata,
                "validation": validation,
            }
        )
    return datasets


def build_site_summary(frame: pd.DataFrame) -> dict[str, object]:
    ordered = frame.sort_values("interval_end").reset_index(drop=True)
    return {
        "rows": len(ordered),
        "start": ordered["interval_end"].min(),
        "end": ordered["interval_end"].max(),
        "peak_kw_import": float(ordered["kw_import"].max()),
        "avg_kw_import": float(ordered["kw_import"].mean()),
        "weekday_avg_kw_import": float(ordered.loc[ordered["interval_end"].dt.dayofweek < 5, "kw_import"].mean()),
        "weekend_avg_kw_import": float(ordered.loc[ordered["interval_end"].dt.dayofweek >= 5, "kw_import"].mean()),
    }
