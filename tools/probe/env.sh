# Source me over SSH: . ./env.sh
# Borrows the Wayland/sway session variables from a running GUI process
# so swaymsg and SDL work from an SSH shell.
. /etc/profile 2>/dev/null

for p in $(pidof retroarch) $(pidof emulationstation) $(pidof sway); do
  [ -r /proc/$p/environ ] || continue
  eval "$(tr '\0' '\n' < /proc/$p/environ \
    | grep -E '^(XDG_RUNTIME_DIR|WAYLAND_DISPLAY|SWAYSOCK)=' \
    | sed 's/^/export /; s/=\(.*\)$/="\1"/')"
  [ -n "${SWAYSOCK}" ] && break
done

if [ -z "${SWAYSOCK}" ] && [ -n "${XDG_RUNTIME_DIR}" ]; then
  SWAYSOCK=$(ls -1 "${XDG_RUNTIME_DIR}"/sway-ipc.*.sock 2>/dev/null | head -n 1)
  export SWAYSOCK
fi

echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}"
echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"
echo "SWAYSOCK=${SWAYSOCK}"
echo "QUIRK_DEVICE=${QUIRK_DEVICE} DEVICE_HAS_DUAL_SCREEN=${DEVICE_HAS_DUAL_SCREEN}"
