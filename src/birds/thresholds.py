"""Species specific confidence thresholds following Wood & Kahl (2024).

For each species, logit(pr(correct)) = b0 + b1 * logit(confidence) is fitted
on validated clips. The threshold is the confidence at which pr(correct)
reaches the target precision.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.special import expit, logit
from scipy.stats import beta as beta_dist
from scipy.stats import norm
from statsmodels.tools.sm_exceptions import PerfectSeparationError

from birds.firth import firth_logit


def to_logit(conf, clip: float = 1e-4):
    """Return logit(confidence), with scores clipped away from 0 and 1."""
    return logit(np.clip(np.asarray(conf, dtype=float), clip, 1 - clip))


def solve_threshold(b0: float, b1: float, target: float) -> float:
    """Return the confidence at which the curve reaches `target`.

    Returns NaN when the slope is missing or not positive, because the
    curve then never rises to the target.
    """
    if not np.isfinite(b1) or b1 <= 0:
        return np.nan
    return float(expit((logit(target) - b0) / b1))


def clopper_pearson_lower(k: int, n: int, level: float = 0.95) -> float:
    """Return the one sided lower bound for a binomial proportion k / n."""
    if n == 0 or k == 0:
        return 0.0
    return float(beta_dist.ppf(1 - level, k, n - k + 1))


def plain_glm(x: np.ndarray, y: np.ndarray) -> dict:
    """Fit the plain binomial GLM from Wood & Kahl, kept for comparison.

    The status column says whether the fit is usable, did not converge,
    shows quasi separation or failed.
    """
    if y.min() == y.max():
        return {
            "glm_b0": np.nan,
            "glm_b1": np.nan,
            "glm_status": "no_variation_in_outcome",
        }
    try:
        res = sm.GLM(
            y, sm.add_constant(x), family=sm.families.Binomial()
        ).fit()
    except (PerfectSeparationError, np.linalg.LinAlgError, ValueError) as e:
        return {
            "glm_b0": np.nan,
            "glm_b1": np.nan,
            "glm_status": f"failed: {type(e).__name__}",
        }
    status = "ok" if res.converged else "not_converged"

    # Quasi separation shows up as very large coefficients or standard
    # errors.
    if np.any(np.abs(res.params) > 25) or np.any(res.bse > 1e3):
        status = "quasi_separation"
    return {
        "glm_b0": float(res.params[0]),
        "glm_b1": float(res.params[1]),
        "glm_status": status,
    }


@dataclass
class SpeciesFit:
    """Fitted curve and threshold for one species."""

    species: str
    n: int
    n_correct: int
    conf_min: float
    conf_max: float
    b0: float
    b1: float
    cov: np.ndarray
    raw_threshold: float
    threshold: float
    status: str
    notes: list[str] = field(default_factory=list)

    def predict(self, conf, clip: float = 1e-4) -> np.ndarray:
        """Return the fitted pr(correct) for each confidence score."""
        x = to_logit(conf, clip)
        return expit(self.b0 + self.b1 * x)

    def predict_band(self, conf, level: float = 0.95, clip: float = 1e-4):
        """Return the lower and upper pointwise band of pr(correct).

        The Wald band is built on the logit scale and then transformed back
        to probabilities.
        """
        x = to_logit(conf, clip)
        design = np.column_stack([np.ones_like(x), x])
        eta = design @ np.array([self.b0, self.b1])
        se = np.sqrt(np.einsum("ij,jk,ik->i", design, self.cov, design))
        z = norm.ppf(0.5 + level / 2)
        return expit(eta - z * se), expit(eta + z * se)


def _start_of_passing_tail(ok: np.ndarray):
    """Return the index where the final run of True values starts.

    Returns None when the last value is False.
    """
    if not ok[-1]:
        return None
    bad = np.nonzero(~ok)[0]
    return 0 if len(bad) == 0 else int(bad[-1]) + 1


def threshold_in_range(
    b0: float,
    b1: float,
    lo: float,
    hi: float,
    target: float,
    clip: float = 1e-4,
    n_grid: int = 2000,
) -> float:
    """Return the lowest score c in [lo, hi] that keeps the curve high.

    From c up to hi the fitted pr(correct) stays at or above target. This
    works for a flat or falling curve too, and never goes outside the
    validated range.
    """
    if not (np.isfinite(b0) and np.isfinite(b1)) or hi <= lo:
        return np.nan
    grid = np.linspace(lo, hi, n_grid)
    ok = expit(b0 + b1 * to_logit(grid, clip)) >= target
    idx = _start_of_passing_tail(ok)
    if idx is None:
        return np.nan
    if idx == 0:
        return float(grid[0])

    # Use the exact crossing when it falls between two grid points.
    closed = solve_threshold(b0, b1, target)
    if np.isfinite(closed) and grid[idx - 1] <= closed <= grid[idx]:
        return closed
    return float(grid[idx])


def apply_rules(
    b0: float, b1: float, conf_min: float, conf_max: float, cfg: dict
) -> tuple[float, str, list[str]]:
    """Return the threshold, its status and notes for one fitted curve.

    The threshold is kept inside the validated range. Notes explain when
    the curve never reaches the target or is above it everywhere.
    """
    target, clip = cfg["target_precision"], cfg["logit_clip"]
    raw = solve_threshold(b0, b1, target)
    thr = threshold_in_range(b0, b1, conf_min, conf_max, target, clip)
    notes = []
    if not np.isfinite(thr):
        if np.isfinite(raw) and raw > conf_max:
            notes.append(
                f"curve reaches {target} only at {raw:.4f}, above the "
                f"highest validated score {conf_max:.3f}; not extrapolated"
            )
        else:
            notes.append(
                f"fitted curve does not reach {target} within the "
                "validated score range"
            )
        return np.nan, "not_reached_in_validated_range", notes
    if thr <= conf_min + 1e-12:
        notes.append(
            f"curve is above {target} across the whole validated range; "
            f"threshold set to the lowest validated score {conf_min:.3f}"
        )
        return thr, "floored_at_min_validated", notes
    return thr, "ok", notes


def fit_species(df: pd.DataFrame, species: str, cfg: dict) -> SpeciesFit:
    """Fit the Firth curve for one species and apply the threshold rules.

    Species with too few validations or negatives get no curve.
    """
    clip = cfg["logit_clip"]
    x = to_logit(df["confidence"], clip)
    y = df["outcome"].to_numpy(dtype=float)
    n, k = len(y), int(y.sum())
    conf_min = float(df["confidence"].min())
    conf_max = float(df["confidence"].max())
    too_few = (
        n < cfg["min_validations"] or (n - k) < cfg["min_negatives_for_curve"]
    )
    if too_few:
        note = (
            f"{n} validations ({n - k} negatives) is below the "
            "configured minimum"
        )
        return SpeciesFit(
            species,
            n,
            k,
            conf_min,
            conf_max,
            np.nan,
            np.nan,
            np.full((2, 2), np.nan),
            np.nan,
            np.nan,
            "insufficient_validations",
            [note],
        )
    res = firth_logit(np.column_stack([np.ones_like(x), x]), y)
    b0, b1 = map(float, res.coef)
    raw = solve_threshold(b0, b1, cfg["target_precision"])
    thr, status, notes = apply_rules(b0, b1, conf_min, conf_max, cfg)
    if not res.converged:
        notes.append("Firth fit did not converge")
    return SpeciesFit(
        species,
        n,
        k,
        conf_min,
        conf_max,
        b0,
        b1,
        res.cov,
        raw,
        thr,
        status,
        notes,
    )


def bootstrap_threshold(
    df: pd.DataFrame, species: str, cfg: dict
) -> np.ndarray:
    """Resample the validations and refit to get a threshold distribution.

    Each draw applies the same rules as the main fit, so a draw can give
    NaN when no threshold is found.
    """
    rng = np.random.default_rng(cfg["bootstrap"]["seed"])
    out = np.empty(cfg["bootstrap"]["n"])
    for i in range(len(out)):
        sample = df.sample(len(df), replace=True, random_state=rng)
        out[i] = fit_species(sample, species, cfg).threshold
    return out


def conservative_threshold(fit: SpeciesFit, cfg: dict) -> float:
    """Return the lowest score where the lower band reaches the target."""
    if not np.isfinite(fit.b1):
        return np.nan
    grid = np.linspace(fit.conf_min, fit.conf_max, 2000)
    lower, _ = fit.predict_band(grid, cfg["ci_level"], cfg["logit_clip"])
    idx = _start_of_passing_tail(lower >= cfg["target_precision"])
    return np.nan if idx is None else float(grid[idx])


def fit_all(
    val: pd.DataFrame, cfg: dict, bootstrap: bool = True
) -> tuple[pd.DataFrame, dict]:
    """Fit every species and build the threshold table.

    Returns the table, one row per species, and a dictionary of fits keyed
    by species name.
    """
    rows, fits = [], {}
    clip = cfg["logit_clip"]
    target = cfg["target_precision"]
    for species, df in val.groupby("commonName"):
        fit = fit_species(df, species, cfg)
        fits[species] = fit
        glm = plain_glm(
            to_logit(df["confidence"], clip), df["outcome"].to_numpy(float)
        )

        # Validated clips at or above the threshold, used to check the
        # precision directly.
        if np.isfinite(fit.threshold):
            above = df[df["confidence"] >= fit.threshold]
        else:
            above = df.iloc[0:0]
        n_above = len(above)

        row = {
            "common_name": species,
            "scientific_name": df["scientificName"].iloc[0],
            "n_validated": fit.n,
            "n_correct": fit.n_correct,
            "n_incorrect": fit.n - fit.n_correct,
            "validated_conf_min": fit.conf_min,
            "validated_conf_max": fit.conf_max,
            "firth_b0": fit.b0,
            "firth_b1": fit.b1,
            **glm,
            "glm_threshold": threshold_in_range(
                glm["glm_b0"],
                glm["glm_b1"],
                fit.conf_min,
                fit.conf_max,
                target,
                clip,
            ),
            "raw_threshold": fit.raw_threshold,
            "threshold": fit.threshold,
            "threshold_status": fit.status,
            "conservative_threshold": conservative_threshold(fit, cfg),
            "n_validated_above_threshold": n_above,
            "empirical_precision_above_threshold": (
                above["outcome"].mean() if n_above else np.nan
            ),
            "precision_lower_95_above_threshold": clopper_pearson_lower(
                int(above["outcome"].sum()), n_above
            ),
            "notes": "; ".join(fit.notes),
        }

        # Bootstrap interval of the threshold, from draws that found one.
        if bootstrap:
            bs = bootstrap_threshold(df, species, cfg)
            ok = np.isfinite(bs)
            a = (1 - cfg["ci_level"]) / 2
            row["bootstrap_share_with_threshold"] = ok.mean()
            row["bootstrap_ci_low"] = (
                np.quantile(bs[ok], a) if ok.any() else np.nan
            )
            row["bootstrap_ci_high"] = (
                np.quantile(bs[ok], 1 - a) if ok.any() else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows), fits
