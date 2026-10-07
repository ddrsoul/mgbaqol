# SPDX-License-Identifier: GPL-2.0-or-later
"""Minimal ctypes bindings for SDL2, SDL2_ttf and SDL2_gfx (only what mgbaqol uses)."""

import ctypes
from ctypes import POINTER, Structure, byref, c_char_p, c_float, c_int, c_int16, c_uint8, c_uint32, c_void_p

_sdl = ctypes.CDLL("libSDL2-2.0.so.0")
_ttf = ctypes.CDLL("libSDL2_ttf-2.0.so.0")
try:
    _gfx = ctypes.CDLL("libSDL2_gfx-1.0.so.0")
except OSError:
    _gfx = None


class Rect(Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("w", c_int), ("h", c_int)]


class Color(Structure):
    _fields_ = [("r", c_uint8), ("g", c_uint8), ("b", c_uint8), ("a", c_uint8)]


class Surface(Structure):
    _fields_ = [("flags", c_uint32), ("format", c_void_p), ("w", c_int), ("h", c_int)]


def _bind(lib, name, res, *args):
    fn = getattr(lib, name)
    fn.restype = res
    fn.argtypes = list(args)
    return fn


INIT_VIDEO = 0x20
WINDOWPOS_UNDEFINED = 0x1FFF0000
WINDOW_SHOWN, WINDOW_RESIZABLE = 0x4, 0x20
RENDERER_ACCELERATED, RENDERER_PRESENTVSYNC = 0x2, 0x4
PIXELFORMAT_ABGR8888 = 0x16762004  # bytes R, G, B, A on little-endian
TEXTUREACCESS_STATIC = 0
BLENDMODE_BLEND = 1

EV_QUIT = 0x100
EV_WINDOW = 0x200
EV_MOUSEDOWN, EV_MOUSEUP = 0x401, 0x402
EV_FINGERDOWN, EV_FINGERUP = 0x700, 0x701
TOUCH_MOUSEID = 0xFFFFFFFF

Init = _bind(_sdl, "SDL_Init", c_int, c_uint32)
Quit = _bind(_sdl, "SDL_Quit", None)
GetError = _bind(_sdl, "SDL_GetError", c_char_p)
SetHint = _bind(_sdl, "SDL_SetHint", c_int, c_char_p, c_char_p)
CreateWindow = _bind(_sdl, "SDL_CreateWindow", c_void_p, c_char_p, c_int, c_int, c_int, c_int, c_uint32)
CreateRenderer = _bind(_sdl, "SDL_CreateRenderer", c_void_p, c_void_p, c_int, c_uint32)
GetRendererOutputSize = _bind(_sdl, "SDL_GetRendererOutputSize", c_int, c_void_p, POINTER(c_int), POINTER(c_int))
SetRenderDrawColor = _bind(_sdl, "SDL_SetRenderDrawColor", c_int, c_void_p, c_uint8, c_uint8, c_uint8, c_uint8)
SetRenderDrawBlendMode = _bind(_sdl, "SDL_SetRenderDrawBlendMode", c_int, c_void_p, c_int)
RenderClear = _bind(_sdl, "SDL_RenderClear", c_int, c_void_p)
RenderFillRect = _bind(_sdl, "SDL_RenderFillRect", c_int, c_void_p, POINTER(Rect))
RenderCopy = _bind(_sdl, "SDL_RenderCopy", c_int, c_void_p, c_void_p, POINTER(Rect), POINTER(Rect))
RenderPresent = _bind(_sdl, "SDL_RenderPresent", None, c_void_p)
CreateTexture = _bind(_sdl, "SDL_CreateTexture", c_void_p, c_void_p, c_uint32, c_int, c_int, c_int)
UpdateTexture = _bind(_sdl, "SDL_UpdateTexture", c_int, c_void_p, POINTER(Rect), c_void_p, c_int)
SetTextureBlendMode = _bind(_sdl, "SDL_SetTextureBlendMode", c_int, c_void_p, c_int)
SetTextureAlphaMod = _bind(_sdl, "SDL_SetTextureAlphaMod", c_int, c_void_p, c_uint8)
CreateTextureFromSurface = _bind(_sdl, "SDL_CreateTextureFromSurface", c_void_p, c_void_p, c_void_p)
DestroyTexture = _bind(_sdl, "SDL_DestroyTexture", None, c_void_p)
FreeSurface = _bind(_sdl, "SDL_FreeSurface", None, c_void_p)
WaitEventTimeout = _bind(_sdl, "SDL_WaitEventTimeout", c_int, c_void_p, c_int)
PollEvent = _bind(_sdl, "SDL_PollEvent", c_int, c_void_p)

TTF_Init = _bind(_ttf, "TTF_Init", c_int)
TTF_OpenFont = _bind(_ttf, "TTF_OpenFont", c_void_p, c_char_p, c_int)
TTF_RenderUTF8_Blended = _bind(_ttf, "TTF_RenderUTF8_Blended", POINTER(Surface), c_void_p, c_char_p, Color)
TTF_SizeUTF8 = _bind(_ttf, "TTF_SizeUTF8", c_int, c_void_p, c_char_p, POINTER(c_int), POINTER(c_int))

if _gfx is not None:
    roundedBoxRGBA = _bind(_gfx, "roundedBoxRGBA", c_int, c_void_p, c_int16, c_int16, c_int16, c_int16,
                           c_int16, c_uint8, c_uint8, c_uint8, c_uint8)
    roundedRectangleRGBA = _bind(_gfx, "roundedRectangleRGBA", c_int, c_void_p, c_int16, c_int16, c_int16,
                                 c_int16, c_int16, c_uint8, c_uint8, c_uint8, c_uint8)
else:
    roundedBoxRGBA = roundedRectangleRGBA = None


def error():
    return GetError().decode("utf-8", "replace")


def output_size(ren):
    w, h = c_int(), c_int()
    GetRendererOutputSize(ren, byref(w), byref(h))
    return w.value, h.value


__all__ = [n for n in dir() if not n.startswith("_")] + ["byref", "c_float"]
