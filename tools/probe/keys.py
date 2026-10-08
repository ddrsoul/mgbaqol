#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Presses GBA buttons in RetroArch through a virtual gamepad (uinput), for testing.

  python3 keys.py serve &          # before starting RetroArch: creates the pad
  python3 keys.py "a*3 w1 down a"  # sends a sequence to it

Tokens: a b l r start select up down left right, NAME*N to repeat, wN to wait
N seconds, ff to toggle fast forward (hotkey + R2), hold:NAME:SECS to hold.

RetroArch's udev driver here ignores keyboards, so the pad copies the RG DS's
built-in one (name, ids, buttons), which makes RetroArch use the same
autoconfig for it. It becomes joypad index 1: run RetroArch with
input_player1_joypad_index = "1" (dev.sh ra-keys) to play with it.
"""

import fcntl
import os
import struct
import sys
import time

KEYS = {"a": 0x131, "b": 0x130, "l": 0x136, "r": 0x137, "start": 0x13B, "select": 0x13A,
        "up": 0x220, "down": 0x221, "left": 0x222, "right": 0x223}
HOTKEY, FF = 0x13C, 0x139
# Every button of retrogame_joypad, so button indexes match its autoconfig.
PAD_KEYS = (0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x138, 0x139, 0x13A, 0x13B, 0x13C, 0x13D, 0x13E,
            0x220, 0x221, 0x222, 0x223)
UI_SET_EVBIT, UI_SET_KEYBIT, UI_DEV_CREATE, UI_DEV_DESTROY = 0x40045564, 0x40045565, 0x5501, 0x5502
EV_SYN, EV_KEY = 0, 1
EVENT = struct.Struct("llHHi")
FIFO = "/tmp/mgbaqol-keys.fifo"


def key(fd, code, value):
    os.write(fd, EVENT.pack(0, 0, EV_KEY, code, value))
    os.write(fd, EVENT.pack(0, 0, EV_SYN, 0, 0))


def play(fd, seq):
    for tok in seq.split():
        if tok[0] == "w" and tok[1:].replace(".", "").isdigit():
            time.sleep(float(tok[1:]))
        elif tok == "ff":
            key(fd, HOTKEY, 1)
            time.sleep(0.1)
            key(fd, FF, 1)
            time.sleep(0.1)
            key(fd, FF, 0)
            key(fd, HOTKEY, 0)
            time.sleep(0.1)
        elif tok.startswith("hold:"):
            _, name, secs = tok.split(":")
            key(fd, KEYS[name], 1)
            time.sleep(float(secs))
            key(fd, KEYS[name], 0)
            time.sleep(0.1)
        else:
            name, _, n = tok.partition("*")
            for _ in range(int(n or 1)):
                key(fd, KEYS[name], 1)
                time.sleep(0.07)
                key(fd, KEYS[name], 0)
                time.sleep(0.13)


def create():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    for code in PAD_KEYS:
        fcntl.ioctl(fd, UI_SET_KEYBIT, code)
    os.write(fd, b"retrogame_joypad".ljust(80, b"\0") + struct.pack("<HHHH", 0x19, 0x484B, 0x1101, 0x100)
             + bytes(4 + 256 * 4))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


def serve():
    fd = create()
    if not os.path.exists(FIFO):
        os.mkfifo(FIFO)
    while True:
        with open(FIFO) as f:  # blocks until a sender writes
            for line in f:
                play(fd, line)


def main():
    arg = " ".join(sys.argv[1:])
    if arg == "serve":
        serve()
    elif os.path.exists(FIFO):
        with open(FIFO, "w") as f:
            f.write(arg + "\n")
        # The sender returns at once; wait for the sequence to play out.
        time.sleep(sum(float(t[1:]) for t in arg.split() if t[0] == "w" and t[1:].replace(".", "").isdigit())
                   + 0.2 * sum(int(t.partition("*")[2] or 1) for t in arg.split() if not t.startswith("w")) + 0.3)
    else:
        sys.exit("start 'keys.py serve' first")


if __name__ == "__main__":
    main()
