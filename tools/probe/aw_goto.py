#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Moves Advance Wars 2's map cursor to X Y with keys.py (for testing the companion)."""

import subprocess
import sys

sys.path.insert(0, "/storage/mgbaqol-dev/share")
from ra import RetroArch  # noqa: E402

x, y = int(sys.argv[1]), int(sys.argv[2])
cx, cy = RetroArch().read(0x03003140, 2)
keys = []
keys += ["right"] * (x - cx) if x > cx else ["left"] * (cx - x)
keys += ["down"] * (y - cy) if y > cy else ["up"] * (cy - y)
if keys:
    subprocess.run(["python3", "/storage/mgbaqol-probe/keys.py", " ".join(keys) + " w0.5"])
print(RetroArch().read(0x03003140, 2)[:2].hex())
