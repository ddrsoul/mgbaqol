# SPDX-License-Identifier: GPL-2.0-or-later
"""The gamepad's right stick as menu navigation.

GBA games have no use for it, and RetroArch passes it to mGBA, which
ignores it. We read the same evdev device in parallel, without grabbing
it, so the game keeps every input. If no pad with a right stick exists,
this quietly does nothing.
"""

import fcntl
import os
import select
import struct
import threading
import time

EV_KEY, EV_ABS = 1, 3
ABS_RX, ABS_RY = 3, 4
BTN_THUMBR = 0x13E
EVENT = struct.Struct("llHHi")       # struct input_event (timeval, type, code, value)
ABSINFO = struct.Struct("6i")        # value, min, max, fuzz, flat, resolution
DEADZONE = 0.5                       # of full deflection
FIRST_REPEAT, REPEAT = 0.80, 0.25    # seconds of holding before the first repeat, between repeats


def eviocgabs(code):
    return 0x80000000 | (ABSINFO.size << 16) | (ord("E") << 8) | (0x40 + code)


def find_pad(preferred="retrogame_joypad"):
    """/dev/input/eventN of a pad with a right stick, preferring the built-in one."""
    try:
        with open("/proc/bus/input/devices") as f:
            blocks = f.read().split("\n\n")
    except OSError:
        return None
    found = []
    for b in blocks:
        name = next((l.split("=", 1)[1].strip('"') for l in b.splitlines() if l.startswith("N: Name=")), "")
        handlers = next((l.split("=", 1)[1].split() for l in b.splitlines() if l.startswith("H: Handlers=")), [])
        abs_bits = next((int(l.split("=", 1)[1].split()[-1], 16) for l in b.splitlines() if l.startswith("B: ABS=")), 0)
        event = next((h for h in handlers if h.startswith("event")), None)
        if event and abs_bits & (1 << ABS_RX) and abs_bits & (1 << ABS_RY):
            found.append((name != preferred, "/dev/input/" + event))
    return min(found)[1] if found else None


class RightStick(threading.Thread):
    """Calls on_action("up" | "down" | "left" | "right" | "press") from its own thread."""

    def __init__(self, on_action):
        super().__init__(daemon=True)
        self.on_action = on_action
        self.path = find_pad()

    def run(self):
        if not self.path:
            return
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return
        ranges = {}
        for code in (ABS_RX, ABS_RY):
            buf = bytearray(ABSINFO.size)
            try:
                fcntl.ioctl(fd, eviocgabs(code), buf)
                _, lo, hi, *_ = ABSINFO.unpack(buf)
            except OSError:
                lo, hi = -32768, 32767
            ranges[code] = (lo, hi)
        axis = {ABS_RX: 0.0, ABS_RY: 0.0}
        held, next_fire = None, 0.0
        while True:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except OSError:
                    return  # pad unplugged
                for off in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, etype, code, value = EVENT.unpack_from(data, off)
                    if etype == EV_ABS and code in axis:
                        lo, hi = ranges[code]
                        mid, half = (lo + hi) / 2, max(1, (hi - lo) / 2)
                        axis[code] = (value - mid) / half
                    elif etype == EV_KEY and code == BTN_THUMBR and value == 1:
                        self.on_action("press")
            x, y = axis[ABS_RX], axis[ABS_RY]
            if max(abs(x), abs(y)) < DEADZONE:
                direction = None
            elif abs(x) > abs(y):
                direction = "right" if x > 0 else "left"
            else:
                direction = "down" if y > 0 else "up"
            now = time.monotonic()
            if direction != held:
                held = direction
                if direction:
                    self.on_action(direction)
                    next_fire = now + FIRST_REPEAT
            elif direction and now >= next_fire:
                self.on_action(direction)
                next_fire = now + REPEAT
