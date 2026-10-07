#!/usr/bin/env python3
"""mgba-qol probe: opens an SDL2 window (app_id "mgbaqol") and logs touch/mouse/focus.

Corners are painted red (top-left), green (top-right), blue (bottom-left) and
yellow (bottom-right); a white cross follows the last touch. Touch each corner
and check that the logged coordinates match.

  python3 probe_win.py [seconds]
"""

import ctypes
import os
import struct
import sys
import time

APP_ID = "mgbaqol"
os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
os.environ["SDL_VIDEO_WAYLAND_WMCLASS"] = APP_ID
os.environ["SDL_APP_ID"] = APP_ID

sdl = ctypes.CDLL("libSDL2-2.0.so.0")
c_int, c_void_p, c_char_p, c_uint8, c_uint32 = (ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p,
                                                 ctypes.c_uint8, ctypes.c_uint32)


class Rect(ctypes.Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("w", c_int), ("h", c_int)]


sdl.SDL_GetError.restype = c_char_p
sdl.SDL_GetCurrentVideoDriver.restype = c_char_p
sdl.SDL_SetHint.argtypes = [c_char_p, c_char_p]
sdl.SDL_CreateWindow.restype = c_void_p
sdl.SDL_CreateWindow.argtypes = [c_char_p, c_int, c_int, c_int, c_int, c_uint32]
sdl.SDL_CreateRenderer.restype = c_void_p
sdl.SDL_CreateRenderer.argtypes = [c_void_p, c_int, c_uint32]
sdl.SDL_SetRenderDrawColor.argtypes = [c_void_p, c_uint8, c_uint8, c_uint8, c_uint8]
sdl.SDL_RenderClear.argtypes = [c_void_p]
sdl.SDL_RenderFillRect.argtypes = [c_void_p, ctypes.POINTER(Rect)]
sdl.SDL_RenderPresent.argtypes = [c_void_p]
sdl.SDL_GetRendererOutputSize.argtypes = [c_void_p, ctypes.POINTER(c_int), ctypes.POINTER(c_int)]
sdl.SDL_GetWindowSize.argtypes = [c_void_p, ctypes.POINTER(c_int), ctypes.POINTER(c_int)]
sdl.SDL_PollEvent.argtypes = [c_void_p]

SDL_INIT_VIDEO = 0x20
SDL_WINDOWPOS_UNDEFINED = 0x1FFF0000
SDL_WINDOW_SHOWN, SDL_WINDOW_RESIZABLE = 0x4, 0x20
EV_QUIT, EV_WINDOW = 0x100, 0x200
EV_MOUSEDOWN, EV_MOUSEUP = 0x401, 0x402
EV_FINGERDOWN, EV_FINGERUP, EV_FINGERMOTION = 0x700, 0x701, 0x702
WINDOW_EVENTS = {1: "shown", 3: "exposed", 5: "resized", 6: "size_changed",
                 10: "enter", 11: "leave", 12: "focus_gained", 13: "focus_lost"}


def log(msg):
    print("%8.2f  %s" % (time.monotonic() - T0, msg), flush=True)


def fill(ren, color, x, y, w, h):
    sdl.SDL_SetRenderDrawColor(ren, *color, 255)
    sdl.SDL_RenderFillRect(ren, ctypes.byref(Rect(int(x), int(y), int(w), int(h))))


def output_size(ren):
    w, h = c_int(), c_int()
    sdl.SDL_GetRendererOutputSize(ren, ctypes.byref(w), ctypes.byref(h))
    return w.value, h.value


def draw(ren, touch):
    w, h = output_size(ren)
    sdl.SDL_SetRenderDrawColor(ren, 20, 24, 32, 255)
    sdl.SDL_RenderClear(ren)
    s = 64
    fill(ren, (220, 50, 50), 0, 0, s, s)
    fill(ren, (50, 200, 80), w - s, 0, s, s)
    fill(ren, (60, 110, 230), 0, h - s, s, s)
    fill(ren, (240, 200, 40), w - s, h - s, s, s)
    if touch:
        x, y = touch
        fill(ren, (255, 255, 255), x - 20, y - 2, 40, 4)
        fill(ren, (255, 255, 255), x - 2, y - 20, 4, 40)
    sdl.SDL_RenderPresent(ren)


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120
    sdl.SDL_SetHint(b"SDL_VIDEO_WAYLAND_WMCLASS", APP_ID.encode())
    sdl.SDL_SetHint(b"SDL_APP_NAME", APP_ID.encode())
    if sdl.SDL_Init(SDL_INIT_VIDEO) != 0:
        log("SDL_Init failed: %s" % sdl.SDL_GetError().decode())
        return 1
    log("video driver: %s" % sdl.SDL_GetCurrentVideoDriver().decode())
    win = sdl.SDL_CreateWindow(b"mgbaqol probe", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED,
                               640, 480, SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE)
    if not win:
        log("SDL_CreateWindow failed: %s" % sdl.SDL_GetError().decode())
        return 1
    ren = sdl.SDL_CreateRenderer(win, -1, 0)
    log("touch devices: %d" % sdl.SDL_GetNumTouchDevices())

    ev = (ctypes.c_uint8 * 56)()
    touch = None
    last_size = None
    while time.monotonic() - T0 < seconds:
        while sdl.SDL_PollEvent(ev):
            raw = bytes(ev)
            t = struct.unpack_from("<I", raw, 0)[0]
            if t == EV_QUIT:
                return 0
            if t == EV_WINDOW:
                kind, d1, d2 = raw[12], *struct.unpack_from("<ii", raw, 16)
                log("window %s %s" % (WINDOW_EVENTS.get(kind, kind), (d1, d2) if kind in (5, 6) else ""))
            elif t in (EV_FINGERDOWN, EV_FINGERUP, EV_FINGERMOTION):
                fx, fy = struct.unpack_from("<ff", raw, 24)
                w, h = output_size(ren)
                touch = (fx * w, fy * h)
                if t != EV_FINGERMOTION:
                    log("finger %s norm=(%.3f, %.3f) px=(%d, %d)"
                        % ("down" if t == EV_FINGERDOWN else "up", fx, fy, touch[0], touch[1]))
            elif t in (EV_MOUSEDOWN, EV_MOUSEUP):
                mx, my = struct.unpack_from("<ii", raw, 20)
                touch = (mx, my)
                log("mouse %s (%d, %d)" % ("down" if t == EV_MOUSEDOWN else "up", mx, my))
        size = output_size(ren)
        if size != last_size:
            log("renderer output size: %dx%d" % size)
            last_size = size
        draw(ren, touch)
        sdl.SDL_Delay(16)
    return 0


T0 = time.monotonic()
if __name__ == "__main__":
    sys.exit(main())
