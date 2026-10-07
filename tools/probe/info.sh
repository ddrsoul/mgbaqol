#!/bin/sh
# Collects the facts mgba-qol depends on. Usage: sh info.sh | tee info.txt
cd "$(dirname "$0")"
. ./env.sh

RA_CFG=/storage/.config/retroarch/retroarch.cfg

echo; echo "== outputs"
swaymsg -t get_outputs

echo; echo "== inputs (touch / joypad)"
swaymsg -t get_inputs | grep -iE -A3 'touch|goodix|joypad|gamepad'

echo; echo "== seats"
swaymsg -t get_seats

echo; echo "== windows"
swaymsg -t get_tree | grep -E '"(app_id|name)":' | grep -v '"name": null'

echo; echo "== retroarch"
retroarch --version 2>&1 | head -n 3
grep -E '^(libretro_directory|libretro_info_path|input_joypad_driver|input_driver|video_driver|network_cmd_enable|network_cmd_port|savefile_directory|savestate_directory|sort_savefiles_enable|sort_savefiles_by_content_enable|sort_savestates_enable|savefiles_in_content_dir|config_save_on_exit) ' "${RA_CFG}"

CORES=$(sed -n 's/^libretro_directory *= *"\(.*\)"/\1/p' "${RA_CFG}")
echo "cores dir: ${CORES}"
ls -la "${CORES}"/mgba* 2>&1
ls -ld "${CORES}" 2>&1
find /usr /tmp /storage/.config -name 'mgba_libretro.info' 2>/dev/null

echo; echo "== runemu append config"
grep -n 'RETROARCH_APPEND_CONFIG=' /usr/bin/runemu.sh /etc/profile /etc/profile.d/* 2>/dev/null | head

echo; echo "== es_systems gba entry"
grep -n -A25 '<name>gba</name>' /usr/config/emulationstation/es_systems.cfg 2>/dev/null | head -40

echo; echo "== python / sdl"
python3 --version
ls /usr/lib/libSDL2*.so* 2>&1
python3 -c "import ctypes; [ctypes.CDLL(l) for l in ('libSDL2-2.0.so.0','libSDL2_ttf-2.0.so.0','libSDL2_image-2.0.so.0')]; print('ctypes sdl2/ttf/image ok')"

echo; echo "== evdev touch devices"
grep -E -A5 'Name=.*(Goodix|Touch|touch)' /proc/bus/input/devices
which evtest
