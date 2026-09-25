"""Apply application readability settings to native PyQtGraph plots."""
from sciview.interfaces.theme.app_style import AppStyle


def style_plot(plot):
    colors = AppStyle.theme_colors()
    font = AppStyle.make_font("body")
    size = AppStyle.font_px("body")
    for name in ("bottom", "left", "top", "right"):
        axis = plot.getAxis(name)
        axis.setTickFont(font)
        axis.setPen(colors["text"])
        axis.setTextPen(colors["text"])
        axis.labelStyle.update({"color": colors["text"].name(), "font-size": f"{size}pt"})
        axis.setLabel(axis.labelText, units=axis.labelUnits, **axis.labelStyle)
    plot.titleLabel.setText(plot.titleLabel.text, color=colors["text"].name(), size=f"{size}pt")
    if plot.legend is not None:
        plot.legend.setLabelTextSize(f"{size}pt")
        plot.legend.setLabelTextColor(colors["text"])
    return colors
