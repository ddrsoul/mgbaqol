# SPDX-License-Identifier: GPL-2.0-or-later
"""Look of the companion: Gen 3 style windows on a slate background.

Everything is laid out on a 320x240 canvas that SDL doubles without
smoothing, so borders, bars and the pixel font come out in 2x2 pixels like the
game on the other screen; Pokemon sprites are drawn at half size there, i.e.
at their native resolution.
"""

import os

APP_ID = "mgbaqol"
SCREEN_W, SCREEN_H = 640, 480   # the window / bottom screen
W, H = 320, 240                  # the canvas everything is laid out on
TAB_H = 22                       # tab bar incl. its bottom line
PAD = 4
LINE_H = 16                      # one line of text
GEAR_W = 28                      # settings button at the right end of the tab bar
TABS = ["Party", "Battle", "Bag", "Map"]
VIEWS = ["party", "battle", "bag", "map", "settings"]

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "PixelOperator.ttf")
FONT_SIZE = 16

# Slate: grey-blue like the Gen 3 battle menus, light grey windows, dark ink.
BG = (124, 135, 152)
BAR = (93, 104, 120)
WIN = (223, 225, 227)
WIN_DIM = (201, 205, 210)       # inactive chips, empty slots
INK = (58, 63, 72)
LINE = (154, 161, 171)          # the inner frame line of a window
SHADOW = (184, 188, 194)        # text shadow on windows
TAB_TEXT = (232, 234, 238)
TAB_SHADOW = (64, 72, 84)
MUTED = (120, 126, 136)
HP_BG = (238, 240, 242)
GREEN, YELLOW, RED = (88, 192, 112), (232, 192, 48), (224, 80, 56)
BEST = (61, 154, 88)
WHITE = (248, 248, 248)

# Classic Gen 3 type colours; text on them is white with an ink shadow.
TYPE_COLORS = {
    "Normal": (168, 168, 120), "Fighting": (192, 48, 40), "Flying": (168, 144, 240),
    "Poison": (160, 64, 160), "Ground": (200, 168, 88), "Rock": (184, 160, 56),
    "Bug": (168, 184, 32), "Ghost": (112, 88, 152), "Steel": (160, 160, 184),
    "Fire": (240, 128, 48), "Water": (104, 144, 240), "Grass": (104, 176, 72),
    "Electric": (216, 176, 32), "Psychic": (232, 80, 128), "Ice": (120, 192, 192),
    "Dragon": (112, 56, 248), "Dark": (112, 88, 72), "Fairy": (224, 136, 168),
}
STATUS_COLORS = {"PAR": (200, 168, 32), "PSN": (160, 64, 160), "TOX": (160, 64, 160),
                 "BRN": (224, 104, 48), "FRZ": (104, 176, 192), "SLP": (128, 128, 136)}
