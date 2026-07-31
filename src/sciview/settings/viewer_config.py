"""Configuration values for stable Qt image viewing and mask drawing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewerColors:
    background: str = "w"
    message: tuple[int, int, int] = (180, 180, 180)
    default_point: str = "#00ffff"
    default_line: str = "#ffffff"
    default_circle: str = "#ff0000"
    default_crosshair: str = "#ff0000"
    default_mask: str = "#ef4444"


@dataclass(frozen=True)
class ViewerBehavior:
    aspect_ratio: float = 1.0
    circle_sample_points: int = 240
    default_point_size: float = 8.0
    default_line_width: float = 1.5
    auto_level_percentiles: tuple[float, float] = (1.0, 99.5)


@dataclass(frozen=True)
class ViewerToolbarAction:
    key: str
    label: str
    tooltip: str


@dataclass(frozen=True)
class ArtistPalette:
    key: str
    label: str
    artist: str
    artwork: str
    source: str
    colors: tuple[str, ...]


VIEWER_COLORS = ViewerColors()
VIEWER_BEHAVIOR = ViewerBehavior()

SUPPORTED_IMAGE_COLORMAPS = (
    "gray",
    "viridis",
    "cividis",
    "plasma",
    "inferno",
    "magma",
    "turbo",
    "jet",
    "coolwarm",
    "Spectral",
    "RdYlBu",
    "cubehelix",
    "gist_earth",
    "terrain",
    "ocean",
    "CMRmap",
    "nipy_spectral",
)
SUPPORTED_IMAGE_SCALES = ("linear", "log")

ARTIST_IMAGE_PALETTES = (
    ArtistPalette(
        "artist:mona_lisa",
        "Mona Lisa",
        "Leonardo da Vinci",
        "Mona Lisa",
        "Color Lisa",
        ("#A88B4C", "#C8B272",  "#A0A584", "#697153", "#43362A"),
    ),
    ArtistPalette(
        "artist:great_wave",
        "Great Wave",
        "Katsushika Hokusai",
        "The Great Wave off Kanagawa",
        "Color Lisa",
        ("#1F284C", "#2D4472", "#6E6352", "#D9CCAC", "#ECE2C6"),
    ),
    ArtistPalette(
        "artist:golden_cloud",
        "Golden Cloud",
        "Gretchen Albrecht",
        "Golden Cloud",
        "Color Lisa",
        ("#171635", "#00225D", "#763262", "#CA7508", "#E9A621"),
    ),
    ArtistPalette(
        "artist:persistence_memory",
        "Persistence of Memory",
        "Salvador Dali",
        "The Persistence of Memory",
        "Color Lisa",
        ("#40798C", "#BCA455", "#BFB37F", "#805730", "#514A2E"),
    ),
    ArtistPalette(
        "artist:monet_parasol",
        "Woman with a Parasol",
        "Claude Monet",
        "Woman with a Parasol",
        "Color Lisa",
        ("#82A4BC", "#4C7899", "#2F5136", "#B1B94C", "#E5DCBE"),
    ),
    ArtistPalette(
        "artist:picasso_dream",
        "The Dream",
        "Pablo Picasso",
        "The Dream",
        "Color Lisa",
        ("#4E7989", "#A9011B", "#E4A826", "#80944E", "#DCD6B2"),
    ),
    ArtistPalette(
        "artist:mondrian_broadway",
        "Broadway Boogie Woogie",
        "Piet Mondrian",
        "Broadway Boogie Woogie",
        "Color Lisa",
        ("#314290", "#4A71C0", "#F1F2ED", "#F0D32D", "#AB3A2C"),
    ),
    ArtistPalette(
        "artist:van_gogh_starry_night",
        "The Starry Night",
        "Vincent van Gogh",
        "The Starry Night",
        "Color Lisa",
        ("#1A3431", "#2B41A7", "#6283C8", "#CCC776", "#C7AD24"),
    ),
    ArtistPalette(
        "artist:van_gogh_bedroom",
        "Bedroom in Arles",
        "Vincent van Gogh",
        "Bedroom in Arles",
        "Color Lisa",
        ("#374D8D", "#93A0CB", "#82A866", "#C4B743", "#A35029"),
    ),
    ArtistPalette(
        "artist:vermeer_pearl_earring",
        "Girl with a Pearl Earring",
        "Johannes Vermeer",
        "Girl with a Pearl Earring",
        "Color Lisa",
        ("#0C0B10", "#707DA6", "#CCAD9D", "#B08E4A", "#863B34"),
    ),
    ArtistPalette(
        "artist:vermeer_milkmaid",
        "The Milkmaid",
        "Johannes Vermeer",
        "The Milkmaid",
        "Color Lisa",
        ("#022F69", "#D6C17A", "#D8D0BE", "#6B724B", "#7C3E2F"),
    ),
    ArtistPalette(
        "artist:warhol_marilyn",
        "Marilyn Monroe",
        "Andy Warhol",
        "Marilyn Monroe, 1967",
        "Color Lisa",
        ("#FD0C81", "#FFED4D", "#C34582", "#EBA49E", "#272324"),
    ),
    ArtistPalette(
        "artist:kahlo_self_portrait",
        "Self-Portrait",
        "Frida Kahlo",
        "Self-Portrait",
        "Color Lisa",
        ("#121510", "#6D8325", "#D6CFB7", "#E5AD4F", "#BD5630"),
    ),
    ArtistPalette(
        "artist:kandinsky_white_zig_zags",
        "White Zig Zags",
        "Wassily Kandinsky",
        "White Zig Zags",
        "Color Lisa",
        ("#C13C53", "#DA73A8", "#4052BD", "#EFE96D", "#D85143"),
    ),
    ArtistPalette(
        "artist:lichtenstein_kiss_ii",
        "Kiss II",
        "Roy Lichtenstein",
        "Kiss II",
        "Color Lisa",
        ("#3229AD", "#BC000E", "#E7CFB7", "#FFEC04", "#090109"),
    ),
    ArtistPalette(
        "artist:rembrandt_night_watch",
        "The Night Watch",
        "Rembrandt",
        "The Night Watch",
        "Color Lisa",
        ("#DBC99A", "#A68329", "#5B5224", "#8A350C", "#090A04"),
    ),
)
ARTIST_IMAGE_COLORMAPS = {palette.key: palette for palette in ARTIST_IMAGE_PALETTES}

VIEWER_TOOLBAR_ACTIONS = (
    ViewerToolbarAction("pan", "Pan", "Pan image: drag with the left mouse button."),
    ViewerToolbarAction("zoom", "Zoom", "Rectangular zoom: drag a box with the left mouse button."),
    ViewerToolbarAction("home", "Home", "Reset the image view to the full detector frame."),
    ViewerToolbarAction("auto", "Auto", "Set color limits from the current image."),
    ViewerToolbarAction("copy", "Copy", "Copy the rendered image view to the clipboard."),
    ViewerToolbarAction("save", "Save", "Save the rendered view with the current colormap and overlays."),
)

VIEWER_TOOL_ICON_FILES = {
    "pan": "viewer_pan.svg",
    "zoom": "viewer_zoom.svg",
    "home": "viewer_home.svg",
    "auto": "viewer_auto.svg",
    "copy": "viewer_copy.svg",
    "save": "viewer_save.svg",
}

MASK_TOOL_NAMES = ("Brush", "Line", "Rectangle", "Circle", "Watershed Fill")
MASK_TOOL_ICON_FILES = {
    "Brush": "tool_pen.svg",
    "Line": "tool_line.svg",
    "Rectangle": "tool_rect.svg",
    "Circle": "tool_circle.svg",
    "Watershed Fill": "tool_fill.svg",
}
MASK_DRAWING_DEFAULTS = {
    "brush_size": 5,
    "corner_zone_ratio": 0.15,
}