#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""mgba-qol bottom-screen companion: live game data for RetroArch + mGBA.

  python3 main.py --rom "/storage/roms/gba/Emerald Enhanced [v11021].gba"

Picks the companion by the game code in the ROM header: Fire Emblem and
Advance Wars have their own; everything else is treated as a Gen 3 Pokemon
game (which also covers hacks that keep a Pokemon game code or none).
"""

import argparse
import os
import signal
import sys

from base import swaymsg

# Game code (ROM header 0xAC) -> (module, App class).
APPS = {
    "AE7E": ("fe", "FireEmblemApp"),     # Fire Emblem (USA, Australia): FE7
    "AW2E": ("aw", "AdvanceWarsApp"),    # Advance Wars 2: Black Hole Rising (USA)
}


def game_code(path):
    try:
        with open(path, "rb") as f:
            return f.read(0xB0)[0xAC:0xB0].decode("ascii", "replace")
    except OSError:
        return ""


def pick_app(rom):
    module, cls = APPS.get(game_code(rom), ("pokemon", "PokemonApp"))
    return getattr(__import__(module), cls)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--ra-pid", type=int, default=0)
    ap.add_argument("--port", type=int, default=55355)
    ap.add_argument("--output", default="DSI-1", help="sway output of the bottom screen")
    ap.add_argument("--tab", help="start on this view (e.g. battle, map, settings), for testing")
    ap.add_argument("--detail", type=int, help="open this list entry's detail view, for testing")
    ap.add_argument("--debug-mapsec", type=int, help="Pokemon: pretend to be in this map section")
    ap.add_argument("--map-mode", choices=("Map", "Wild"), help="Pokemon: start the Map tab in this mode")
    ap.add_argument("--debug-battle", action="store_true", help="Pokemon: fake a battle from the party")
    args = ap.parse_args()

    app = pick_app(args.rom)(args)

    def cleanup(*_):
        swaymsg("output", args.output, "power", "off")
        os._exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    try:
        app.run()
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
