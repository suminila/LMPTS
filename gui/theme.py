"""Shared visual theme so every screen looks consistent (purple/indigo palette)."""

PRIMARY = "#5B4FE9"        # main purple (buttons, active nav, accents)
PRIMARY_DARK = "#4338CA"
PRIMARY_LIGHT = "#EEF0FF"  # light purple backgrounds (icon chips, cards)
SUCCESS = "#16A34A"
SUCCESS_LIGHT = "#DCFCE7"
WARNING = "#D97706"
WARNING_LIGHT = "#FEF3C7"
DANGER = "#DC2626"
DANGER_LIGHT = "#FEE2E2"
INFO_LIGHT = "#F0F1FE"

BG = "#F7F8FC"             # page background
SURFACE = "#FFFFFF"        # cards / sidebar / header
BORDER = "#E5E7EB"
TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#6B7280"
TEXT_ON_PRIMARY = "#FFFFFF"

FONT_FAMILY = "Segoe UI" if False else "Helvetica"  # falls back cleanly across platforms
FONT_TITLE = (FONT_FAMILY, 18, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 10)
FONT_HEADING = (FONT_FAMILY, 13, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_BUTTON = (FONT_FAMILY, 10, "bold")

DIFFICULTY_COLORS = {
    "Beginner": (SUCCESS, SUCCESS_LIGHT),
    "Intermediate": (PRIMARY_DARK, PRIMARY_LIGHT),
    "Advanced": (WARNING, WARNING_LIGHT),
}
