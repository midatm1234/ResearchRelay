# Exact function used by the pilot; invoke with a Path and optional bootstrap count.
import csv, math, random
from pathlib import Path
def paired_comparison(data_path: Path, iterations: int = 2000) -> dict:
    rows = list(csv.DictReader(data_path.open(encoding="utf-8")))
    paired = [r for r in rows if all(r[k] for k in ("observation", "forecast_a", "forecast_b"))]
    a = [float(r["forecast_a"]) - float(r["observation"]) for r in paired]
    b = [float(r["forecast_b"]) - float(r["observation"]) for r in paired]
    rmse = lambda values: math.sqrt(sum(v * v for v in values) / len(values))
    rng = random.Random(1729)
    bootstrap = []
    for _ in range(iterations):
        indices = [rng.randrange(len(a)) for _ in a]
        bootstrap.append(rmse([b[i] for i in indices]) - rmse([a[i] for i in indices]))
    bootstrap.sort()
    return {"sample_size": len(a), "rmse_a": rmse(a), "rmse_b": rmse(b),
            "rmse_difference_b_minus_a": rmse(b) - rmse(a),
            "bootstrap_95_interval": [bootstrap[int(.025 * iterations)], bootstrap[int(.975 * iterations)]],
            "bootstrap_iterations": iterations, "seed": 1729,
            "dates": [r["date"] for r in paired],
            "limitation": "IID resampling of 11 synthetic days does not represent temporal dependence or generalization."}
