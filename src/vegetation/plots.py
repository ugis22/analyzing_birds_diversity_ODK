"""Figures for the vegetation data quality report, other than maps."""

import matplotlib.pyplot as plt
import numpy as np

from vegetation import summaries

C_MAIN = "#1d4ed8"
C_PLOT = "#64748b"
C_EST = "#c2410c"
C_OK = "#16a34a"


def accumulation_figure(m: dict, path=None):
    """Draw species accumulation inside plots and across plots.

    Left: one rarefaction curve for each plot over its 20 quadrats, and the
    mean. Right: rarefaction over plots, with the Chao2 estimate of the
    total number of taxa.
    """
    curve, ch = summaries.project_accumulation(m)
    pc = summaries.plot_accumulation(m)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))

    for _, g in pc.groupby("plot_name"):
        axes[0].plot(
            g["units"], g["expected_richness"], color=C_PLOT, alpha=0.45, lw=1
        )
    mean_curve = pc.groupby("units")["expected_richness"].mean()
    axes[0].plot(
        mean_curve.index,
        mean_curve.values,
        color=C_MAIN,
        lw=2.5,
        label="mean across plots",
    )
    axes[0].set_xlabel("quadrats")
    axes[0].set_ylabel("expected number of taxa")
    axes[0].set_title("Inside each plot (20 quadrats)")
    axes[0].legend()
    axes[0].grid(alpha=0.2)

    axes[1].plot(
        curve["units"],
        curve["expected_richness"],
        color=C_MAIN,
        lw=2.5,
        label="rarefaction (observed)",
    )
    axes[1].axhline(
        ch["chao2"],
        color=C_EST,
        ls="--",
        label=f"Chao2 estimate = {ch['chao2']:.0f}",
    )
    axes[1].set_xlabel("plots")
    axes[1].set_title(
        f"Across plots: {ch['S_obs']} taxa observed, "
        f"coverage {ch['coverage']:.2f}"
    )
    axes[1].legend()
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


def bearing_figure(m: dict, tolerance_deg: float = 20, path=None):
    """Draw a histogram of the registered transect directions.

    The direction is folded to 0 to 180 degrees, so 0 and 180 are north
    to south and 90 is east to west. The green bands show the tolerance
    around north to south.
    """
    p = m["plots"]
    axis = p["bearing_a_b_deg"].dropna() % 180
    n_ok = int((p["deviation_from_ns_deg"] <= tolerance_deg).sum())
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax.hist(axis, bins=np.arange(0, 181, 10), color=C_MAIN)
    ax.axvspan(0, tolerance_deg, color=C_OK, alpha=0.15)
    ax.axvspan(
        180 - tolerance_deg,
        180,
        color=C_OK,
        alpha=0.15,
        label=f"within {tolerance_deg} deg of north/south (SOP)",
    )
    ax.set_xlabel(
        "transect direction (degrees; 0 = north/south, 90 = east/west)"
    )
    ax.set_ylabel("plots")
    ax.legend()
    ax.set_title(
        f"Registered transect direction: {n_ok} of {len(axis)} "
        "within the tolerance of north/south"
    )
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig
