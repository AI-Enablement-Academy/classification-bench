"""Small, deterministic visuals for the private report overview."""

from html import escape


def _h(value):
    return escape(str(value), quote=True)


def agreement_duration_plot(rows):
    """Plot recorded nonsynthetic client durations; retain the full score denominator."""
    eligible = [row for row in rows if row["plot_state"] == "measured"]
    maximum = max((row["duration_mean"] for row in eligible), default=0) or 1
    points = []
    labels = []
    for index, row in enumerate(rows):
        if row["plot_state"] != "measured":
            continue
        x = 76 + 564 * row["duration_mean"] / maximum
        y = 262 - 216 * row["exact_fraction"]
        label = (f"{row['model']}, {row['prompt']}: {row['exact_numerator']}/"
                 f"{row['exact_denominator']} exact ({row['exact_fraction']:.1%}); "
                 f"mean client request duration {row['duration_mean']:.3f} seconds "
                 f"across {row['duration_measured']}/{row['duration_planned']} planned requests. "
                 "Inspect condition.")
        points.append(
            f"<a class='duration-point' data-plot-id='{index}' href='#{_h(row['anchor'])}' "
            f"aria-label='{_h(label)}'><title>{_h(label)}</title>"
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='7'/></a>")
        labels.append(
            f"<li class='plot-key-row' data-plot-id='{index}'>"
            f"<a href='#{_h(row['anchor'])}'>{_h(row['model'])} · {_h(row['prompt'])}</a>"
            f"<span>{row['exact_numerator']}/{row['exact_denominator']} exact "
            f"({row['exact_fraction']:.1%})</span>"
            f"<span>{row['duration_mean']:.3f} s mean; "
            f"{row['duration_measured']}/{row['duration_planned']} requests measured</span></li>")
    svg = (
        "<svg id='agreement-duration-chart' class='agreement-duration-chart' "
        "viewBox='0 0 700 330' role='group' "
        "aria-label='Exact agreement and measured client request duration by condition'>"
        "<line class='plot-axis' x1='76' y1='46' x2='76' y2='262'/>"
        "<line class='plot-axis' x1='76' y1='262' x2='640' y2='262'/>"
        "<line class='plot-guide' x1='76' y1='154' x2='640' y2='154'/>"
        "<text x='8' y='52'>100%</text><text x='17' y='160'>50%</text>"
        "<text x='25' y='268'>0%</text><text x='70' y='288'>0 s</text>"
        f"<text x='640' y='288' text-anchor='end'>{maximum:.3f} s</text>"
        "<text x='76' y='22'>Exact agreement / all planned positions</text>"
        "<text x='640' y='315' text-anchor='end'>Mean client request duration</text>"
        + "".join(points) + "</svg>")
    return (
        "<section class='duration-overview' aria-labelledby='duration-overview-heading'>"
        "<div class='duration-overview-intro'><div><span class='eyebrow'>Recorded relationship</span>"
        "<h3 id='duration-overview-heading'>Agreement and client request duration</h3></div>"
        "<p>Each point links to a condition. Agreement includes every planned position; "
        "duration averages measured requests only. Client request duration includes network, queueing "
        "and serving context; it is not pure inference time. Different routes may have different timing scopes. "
        "Axes stay fixed when filters change.</p></div>"
        f"{svg}"
        "<ul class='plot-key' aria-label='Plotted conditions and measured coverage'>"
        + "".join(labels) + "</ul>"
        "<p id='plot-empty' hidden>No matching conditions have measured client request duration. "
        "Check the table for unavailable measurements.</p>"
        "<p id='plot-status' class='status-line' role='status' aria-live='polite'></p>"
        "</section>")
