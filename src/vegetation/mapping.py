"""Maps of the plot design, registered transects and quadrat positions."""

import folium
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Polygon

from common.geo import to_local_xy

COL = {
    "surveyed": "#15803d",
    "registered": "#d97706",
    "not_viable": "#b91c1c",
    "not_registered": "#9ca3af",
    "transect": "#1d4ed8",
    "ok": "#15803d",
    "flag": "#dc2626",
    "belt": "#93c5fd",
    "centroid": "#111827",
    "unsampled": "#7c3aed",
}
POSITION_CHECKS = {"Q03", "Q04", "Q05", "Q06", "Q07"}
BELT_HALF_WIDTH_M = 2.5
MAX_SHIFT_M = 25


def _short(name: str) -> str:
    """Remove the project prefix from a plot name."""
    return name.replace("SavMon_LW_", "")


def plot_state(m: dict) -> pd.Series:
    """Return the state of each plot: surveyed, not viable, and so on."""
    p = m["plots"]
    accepted = m["surveys"]["review_state"] != "rejected"
    surveyed = set(m["surveys"].loc[accepted, "centroid_uuid"])
    state = np.select(
        [
            p["centroid_uuid"].isin(surveyed),
            p["is_viable"].eq("no"),
            p["registered"],
        ],
        ["surveyed", "not_viable", "registered"],
        default="not_registered",
    )
    return pd.Series(state, index=p.index)


def _quadrat_flags(flags: pd.DataFrame) -> pd.Series:
    """Return the position check ids raised for each quadrat."""
    is_pos = flags["check_id"].isin(POSITION_CHECKS)
    f = flags[(flags["level"] == "quadrat") & is_pos]
    return (
        f.groupby("entity_key")["check_id"]
        .apply(lambda x: ", ".join(sorted(set(x))))
        .rename("position_flags")
    )


def _unsampled_strata(p: pd.DataFrame) -> list:
    """Return the strata where no plot was registered."""
    reg = p.groupby("stratum_label")["registered"].sum()
    return sorted(reg[reg == 0].index)


def overview_map(m: dict, path=None):
    """Draw all prescribed locations, coloured by their state.

    Squares are backup locations. A ring marks strata where no plot was
    registered. The title counts are computed from the data.
    """
    p = m["plots"].assign(state=plot_state(m))
    lat0, lon0 = p["centroid_lat"].mean(), p["centroid_lon"].mean()
    unsampled = _unsampled_strata(p)
    fig, ax = plt.subplots(figsize=(12, 6))

    for state, g in p.groupby("state"):
        x, y = to_local_xy(g["centroid_lat"], g["centroid_lon"], lat0, lon0)
        x, y = np.asarray(x) / 1000, np.asarray(y) / 1000
        marker = np.where(g["design_status"] == "primary", "o", "s")
        for mk in set(marker):
            sel = marker == mk
            ax.scatter(
                x[sel],
                y[sel],
                c=COL[state],
                marker=mk,
                s=60,
                edgecolor="white",
                linewidth=0.8,
                zorder=3,
            )

    for r in p.itertuples():
        x, y = to_local_xy(r.centroid_lat, r.centroid_lon, lat0, lon0)
        ax.annotate(
            str(r.plot_number),
            (x / 1000, y / 1000),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=7.5,
            color="#374151",
        )
        if r.stratum_label in unsampled:
            ax.scatter(
                x / 1000,
                y / 1000,
                s=220,
                facecolor="none",
                edgecolor=COL["unsampled"],
                linewidth=1.2,
                zorder=2,
            )

    labels = [
        ("surveyed", "registered and surveyed"),
        ("not_viable", "registered, not viable"),
        ("not_registered", "not registered"),
    ]
    handles = [
        Line2D([], [], marker="o", ls="", color=COL[k], label=t, markersize=8)
        for k, t in labels
    ]
    handles.append(
        Line2D(
            [],
            [],
            marker="s",
            ls="",
            color="#6b7280",
            label="square = backup location",
            markersize=7,
        )
    )
    if unsampled:
        handles.append(
            Line2D(
                [],
                [],
                marker="o",
                ls="",
                markerfacecolor="none",
                markeredgecolor=COL["unsampled"],
                label="ring = stratum never registered",
                markersize=11,
            )
        )
    ax.legend(handles=handles, loc="upper left", fontsize=8.5, framealpha=0.9)
    ax.set_xlabel("km east")
    ax.set_ylabel("km north")
    ax.set_aspect("equal")
    ax.grid(alpha=0.25)

    n_surveyed = int((p["state"] == "surveyed").sum())
    title = (
        f"Herbaceous survey design: {len(p)} prescribed locations, "
        f"{int(p['registered'].sum())} registered, {n_surveyed} surveyed"
    )
    if unsampled:
        title += f"\n(stratum never visited: {', '.join(unsampled)})"
    ax.set_title(title, fontsize=11)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=130)
    return fig


def plot_detail_axes(
    ax, m: dict, flags: pd.DataFrame, plot_name: str, title_extra: str = ""
):
    """Draw one plot in metres around its prescribed centroid.

    Shows the 25 m limit, the registered transect with its belt, and the
    quadrats of the accepted survey. Quadrats with a position flag are red.
    """
    p = m["plots"].set_index("plot_name").loc[plot_name]
    lat0, lon0 = p["centroid_lat"], p["centroid_lon"]

    def tx(la, lo):
        return to_local_xy(la, lo, lat0, lon0)

    ax.add_patch(
        Circle((0, 0), MAX_SHIFT_M, fill=False, ls="--", ec="#6b7280", lw=0.8)
    )
    ax.scatter([0], [0], marker="x", c=COL["centroid"], s=60, zorder=4)
    ax.annotate(
        "prescribed\ncentroid",
        (0, 0),
        xytext=(4, -16),
        textcoords="offset points",
        fontsize=7,
    )

    # Dotted line: the north/south layout asked for by the SOP.
    ax.plot([0, 0], [-25, 25], color="#6b7280", lw=0.8, ls=":")

    if p["registered"] and pd.notna(p["a_lat"]):
        ax_, ay = tx(p["a_lat"], p["a_lon"])
        mx, my = tx(p["mid_lat"], p["mid_lon"])
        bx, by = tx(p["b_lat"], p["b_lon"])
        ux, uy = bx - ax_, by - ay
        n = np.hypot(ux, uy)
        nx, ny = -uy / n * BELT_HALF_WIDTH_M, ux / n * BELT_HALF_WIDTH_M
        corners = [
            (ax_ + nx, ay + ny),
            (bx + nx, by + ny),
            (bx - nx, by - ny),
            (ax_ - nx, ay - ny),
        ]
        ax.add_patch(
            Polygon(corners, closed=True, fc=COL["belt"], ec="none", alpha=0.5)
        )
        ax.plot(
            [ax_, mx, bx],
            [ay, my, by],
            marker="o",
            color=COL["transect"],
            ms=4,
            lw=1.5,
        )
        ends = {"A": (ax_, ay), "mid": (mx, my), "B": (bx, by)}
        for label, (x, y) in ends.items():
            ax.annotate(
                label,
                (x, y),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=8,
                color=COL["transect"],
            )

    s = m["surveys"]
    keep = (s["plot_name"] == plot_name) & (s["review_state"] != "rejected")
    q = m["quadrats"][
        m["quadrats"]["survey_key"].isin(s.loc[keep, "survey_key"])
    ]
    q = q.join(_quadrat_flags(flags), on="quadrat_key")
    qx, qy = tx(q["lat"], q["lon"])
    qx, qy = np.asarray(qx), np.asarray(qy)
    flagged = q["position_flags"].notna().to_numpy()
    ax.plot(qx, qy, color="#9ca3af", lw=0.6, zorder=1)
    ax.scatter(qx[~flagged], qy[~flagged], c=COL["ok"], s=22, zorder=3)
    ax.scatter(qx[flagged], qy[flagged], c=COL["flag"], s=26, zorder=3)
    for x, y, nq in zip(qx, qy, q["quadrat_number"]):
        ax.annotate(
            str(nq),
            (x, y),
            xytext=(2, 2),
            textcoords="offset points",
            fontsize=6.5,
        )

    ax.set_aspect("equal")
    ax.grid(alpha=0.2)
    lim = max(40, np.nanmax(np.abs(np.r_[qx, qy, 30])) + 5)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_title(f"{_short(plot_name)} {title_extra}", fontsize=9.5)
    ax.set_xlabel("m east of centroid", fontsize=8)
    ax.tick_params(labelsize=7)


def detail_panels(m: dict, flags: pd.DataFrame, plots: dict, path=None):
    """Draw one detail panel for each plot in plots.

    plots maps a plot name to a short text added to the panel title.
    """
    fig, axes = plt.subplots(1, len(plots), figsize=(4.6 * len(plots), 4.9))
    axes = np.atleast_1d(axes)
    for ax, (pn, extra) in zip(axes, plots.items()):
        plot_detail_axes(ax, m, flags, pn, extra)
    axes[0].set_ylabel("m north of centroid", fontsize=8)
    handles = [
        Line2D(
            [],
            [],
            color=COL["transect"],
            marker="o",
            ms=4,
            label="registered A, mid, B",
        ),
        Line2D([], [], color=COL["belt"], lw=6, label="5 m belt"),
        Line2D([], [], color="#6b7280", ls="--", label="25 m from centroid"),
        Line2D([], [], color="#6b7280", ls=":", label="SOP north/south axis"),
        Line2D([], [], marker="o", ls="", color=COL["ok"], label="quadrat"),
        Line2D(
            [],
            [],
            marker="o",
            ls="",
            color=COL["flag"],
            label="quadrat with position flag",
        ),
    ]
    fig.legend(
        handles=handles, loc="lower center", ncol=6, fontsize=8, frameon=False
    )
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    if path:
        fig.savefig(path, dpi=130)
    return fig


def interactive_map(m: dict, flags: pd.DataFrame, path=None) -> folium.Map:
    """Build a web map with centroids, transects and quadrats.

    Each layer can be switched on and off. Clicking a centroid shows the
    plot flags.
    """
    p = m["plots"].assign(state=plot_state(m))
    fmap = folium.Map(
        location=[p["centroid_lat"].mean(), p["centroid_lon"].mean()],
        zoom_start=13,
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.TileLayer("Esri.WorldImagery", name="Satellite").add_to(fmap)
    pflags = (
        flags[flags["level"] == "plot"]
        .groupby("plot_name")["message"]
        .apply(lambda x: "<br>".join(x))
    )
    lay_c = folium.FeatureGroup(name="Prescribed centroids (25 m)").add_to(
        fmap
    )
    lay_t = folium.FeatureGroup(name="Registered transects").add_to(fmap)
    lay_q = folium.FeatureGroup(name="Quadrats").add_to(fmap)

    for r in p.itertuples():
        popup = (
            f"<b>{r.plot_name}</b><br>{r.stratum_label}, {r.design_status}"
            f"<br>state: {r.state}<br>{pflags.get(r.plot_name, '')}"
        )
        folium.CircleMarker(
            [r.centroid_lat, r.centroid_lon],
            radius=6,
            color=COL[r.state],
            fill=True,
            fill_opacity=0.9,
            popup=folium.Popup(popup, max_width=320),
            tooltip=r.plot_name,
        ).add_to(lay_c)
        folium.Circle(
            [r.centroid_lat, r.centroid_lon],
            radius=MAX_SHIFT_M,
            color="#6b7280",
            weight=1,
            fill=False,
            dash_array="4",
        ).add_to(lay_c)
        if r.registered and pd.notna(r.a_lat):
            folium.PolyLine(
                [
                    [r.a_lat, r.a_lon],
                    [r.mid_lat, r.mid_lon],
                    [r.b_lat, r.b_lon],
                ],
                color=COL["transect"],
                weight=3,
                tooltip=(
                    f"{r.plot_name}: A to B {r.len_a_b_m:.0f} m, "
                    f"bearing {r.bearing_a_b_deg:.0f} deg"
                ),
            ).add_to(lay_t)

    s = m["surveys"][["survey_key", "plot_name", "review_state"]]
    q = (
        m["quadrats"]
        .merge(s, on="survey_key")
        .join(_quadrat_flags(flags), on="quadrat_key")
    )
    q = q[q["review_state"] != "rejected"]
    for r in q.itertuples():
        has_flag = isinstance(r.position_flags, str)
        folium.CircleMarker(
            [r.lat, r.lon],
            radius=3,
            color=COL["flag"] if has_flag else COL["ok"],
            fill=True,
            fill_opacity=1,
            tooltip=(
                f"{r.plot_name} Q{r.quadrat_number}: acc {r.accuracy} m, "
                f"offset {r.offset_m:.1f} m, "
                f"{r.position_flags or 'no position flag'}"
            ),
        ).add_to(lay_q)
    folium.LayerControl().add_to(fmap)
    if path:
        fmap.save(str(path))
    return fmap
