"""Figures for the bird report."""

import matplotlib.pyplot as plt
import numpy as np
from scipy.special import expit, logit

from birds.thresholds import to_logit

C_CURVE = "#1f5fa8"
C_THR = "#c2410c"
C_POS = "#15803d"
C_NEG = "#b91c1c"
C_GLM = "#6b7280"


def plot_species_curves(val, table, fits, cfg, path=None):
    """Plot validated clips and fitted curves, one panel per species.

    Each panel shows the Firth curve with its band, the plain GLM curve
    when it exists, the target precision and the chosen threshold.
    """
    species = list(table["common_name"])
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharey=True)
    rng = np.random.default_rng(1)
    clip = cfg["logit_clip"]
    for ax, sp in zip(axes.ravel(), species):
        df = val[val["commonName"] == sp]
        row = table.set_index("common_name").loc[sp]
        fit = fits[sp]

        # Validated clips, with a small vertical jitter so points overlap
        # less.
        x = to_logit(df["confidence"], clip)
        jitter = rng.uniform(-0.03, 0.03, len(df))
        colors = np.where(df["outcome"] == 1, C_POS, C_NEG)
        ax.scatter(
            x,
            df["outcome"] + jitter,
            s=12,
            alpha=0.5,
            c=colors,
            label="validated clip",
        )

        # Fitted curves over the validated score range.
        grid = np.linspace(df["confidence"].min(), df["confidence"].max(), 400)
        gx = to_logit(grid, clip)
        lo, hi = fit.predict_band(grid, cfg["ci_level"], clip)
        ax.fill_between(
            gx,
            lo,
            hi,
            color=C_CURVE,
            alpha=0.15,
            lw=0,
            label="95% band (Firth)",
        )
        ax.plot(
            gx,
            fit.predict(grid, clip),
            color=C_CURVE,
            lw=2,
            label="Firth logistic fit",
        )
        if np.isfinite(row["glm_b1"]):
            ax.plot(
                gx,
                expit(row["glm_b0"] + row["glm_b1"] * gx),
                color=C_GLM,
                lw=1.2,
                ls="--",
                label="plain GLM fit",
            )

        # Target precision and threshold.
        ax.axhline(cfg["target_precision"], color=C_THR, lw=1, ls=":")
        status = row["threshold_status"]
        if np.isfinite(row["threshold"]):
            ax.axvline(logit(row["threshold"]), color=C_THR, lw=1.5)
            title_thr = f"threshold = {row['threshold']:.3f} ({status})"
        else:
            title_thr = f"no threshold ({status})"
        n_val, n_ok = int(row["n_validated"]), int(row["n_correct"])
        ax.set_title(
            f"{sp}\nn={n_val}, correct={n_ok}; {title_thr}", fontsize=9.5
        )
        ax.set_xlabel("logit(BirdNET confidence)")

        # Top axis shows the confidence on its original scale.
        top = ax.secondary_xaxis("top", functions=(expit, logit))
        top.set_xticks([0.1, 0.25, 0.5, 0.75, 0.9, 0.97, 0.99])
        top.tick_params(labelsize=7)
        ax.grid(alpha=0.2)

    for ax in axes[:, 0]:
        ax.set_ylabel("pr(BirdNET prediction is correct)")
    axes[0, 0].legend(fontsize=7.5, loc="lower right")
    fig.suptitle(
        "Validation outcome vs logit confidence; dotted line = target "
        f"precision {cfg['target_precision']}",
        fontsize=11,
    )
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


def plot_score_distributions(pred, table, path=None):
    """Plot a histogram of prediction scores per species.

    A vertical line marks the threshold, and the title gives the share of
    predictions at or above it.
    """
    thr = table.set_index("common_name")["threshold"]
    species = list(table["common_name"])
    fig, axes = plt.subplots(1, len(species), figsize=(14, 3.2))
    for ax, sp in zip(axes, species):
        c = pred.loc[pred["common_name"] == sp, "confidence"]
        ax.hist(c, bins=np.linspace(0.1, 1, 37), color="#94a3b8")
        if np.isfinite(thr.get(sp, np.nan)):
            ax.axvline(thr[sp], color=C_THR, lw=1.5)
            share = (c >= thr[sp]).mean()
            title = f"{len(c):,} predictions, {share:.0%} >= threshold"
        else:
            title = f"{len(c):,} predictions, no threshold"
        ax.set_title(f"{sp}\n{title}", fontsize=9)
        ax.set_xlabel("confidence")
    axes[0].set_ylabel("predictions")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig
