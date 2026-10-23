"""Deterministic analytics over compact KPI facts."""

from __future__ import annotations

from typing import Any


def run_rate_projection(mtd: float, working_elapsed: int, working_remaining: int) -> dict[str, Any]:
    elapsed = max(working_elapsed, 1)
    daily = mtd / elapsed
    return {
        "mtd": mtd,
        "daily_run_rate": round(daily, 2),
        "projected_month_end": round(mtd + daily * max(working_remaining, 0), 2),
    }


def project_series(values: list[float], periods_ahead: int = 1) -> dict[str, Any]:
    series = [float(v) for v in values if v is not None]
    if len(series) < 2:
        last = series[-1] if series else 0.0
        return run_rate_projection(last, max(len(series), 1), periods_ahead)
    try:
        import statsmodels.api as sm

        x = list(range(len(series)))
        model = sm.OLS(series, sm.add_constant(x)).fit()
        future_x = [[1.0, len(series) + i] for i in range(periods_ahead)]
        preds = model.predict(future_x)
        return {
            "method": "ols",
            "slope": round(float(model.params[1]), 4),
            "projected": [round(float(p), 2) for p in preds],
        }
    except Exception:
        last = series[-1]
        return run_rate_projection(last, len(series), periods_ahead)
