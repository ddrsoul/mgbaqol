# SPDX-License-Identifier: GPL-2.0-or-later
"""Screen geometry, fonts and colours shared by every view."""

APP_ID = "mgbaqol"
W, H = 640, 480
TAB_H, FOOT_H, PAD = 40, 30, 8
TABS = ["Party", "Battle", "Bag", "Map"]
VIEWS = ["party", "battle", "bag", "map", "settings"]
GEAR_W = 56  # settings button at the right end of the tab bar
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"
FONT_BOLD = "/usr/share/fonts/liberation/LiberationSans-Bold.ttf"

BG = (20, 26, 38)
PANEL = (31, 39, 56)
BAR_BG = (14, 19, 28)
LINE = (42, 51, 70)
TEXT = (232, 236, 243)
MUTED = (138, 148, 168)
ACCENT = (91, 156, 240)
GREEN, YELLOW, RED = (76, 195, 106), (229, 193, 58), (224, 82, 74)

TYPE_COLORS = {
    "Normal": (200, 200, 154), "Fighting": (200, 72, 60), "Flying": (143, 168, 240),
    "Poison": (160, 80, 176), "Ground": (216, 184, 96), "Rock": (184, 160, 56),
    "Bug": (168, 184, 32), "Ghost": (154, 136, 200), "Steel": (184, 184, 208),
    "Fire": (232, 128, 58), "Water": (74, 143, 224), "Grass": (92, 184, 92),
    "Electric": (232, 198, 58), "Psychic": (232, 90, 138), "Ice": (127, 208, 208),
    "Dragon": (122, 88, 232), "Dark": (130, 104, 88), "Fairy": (238, 153, 200),
}
STATUS_COLORS = {"PAR": YELLOW, "PSN": (160, 80, 176), "TOX": (160, 80, 176),
                 "BRN": (232, 128, 58), "FRZ": (127, 208, 208), "SLP": MUTED}
