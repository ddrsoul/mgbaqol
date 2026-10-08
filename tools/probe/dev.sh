#!/bin/sh
# Dev helper on the console: dev.sh start ROM [args] | stop | shot NAME | top NAME | ra ROM | ra-keys ROM | ra-stop
cd /storage/mgbaqol-probe && . ./env.sh >/dev/null
PIDFILE=/tmp/mgbaqol-dev.pid

case "$1" in
  start)
    shift
    [ -f "${PIDFILE}" ] && kill "$(cat "${PIDFILE}")" 2>/dev/null && sleep 1
    cd /storage/mgbaqol-dev/share
    python3 main.py --rom "$@" > /tmp/mgbaqol-dev.log 2>&1 &
    echo $! > "${PIDFILE}"
    ;;
  stop)
    [ -f "${PIDFILE}" ] && kill "$(cat "${PIDFILE}")" 2>/dev/null
    rm -f "${PIDFILE}"
    ;;
  shot)
    grim -o DSI-1 "/tmp/$2.png"
    ;;
  top)
    grim -o DSI-2 "/tmp/$2.png"
    ;;
  ra)
    retroarch --config /storage/.config/retroarch/retroarch.cfg --appendconfig /storage/mgbaqol-probe/test.cfg \
      -L /tmp/cores/mgbaqol_libretro.so "$2" > /storage/mgbaqol-probe/ra.log 2>&1 &
    ;;
  ra-keys)
    # Player 1 is keys.py's virtual pad, started here and kept for later runs.
    if ! { [ -f /tmp/mgbaqol-keys.pid ] && kill -0 "$(cat /tmp/mgbaqol-keys.pid)" 2>/dev/null; }; then
      rm -f /tmp/mgbaqol-keys.fifo
      setsid python3 /storage/mgbaqol-probe/keys.py serve > /tmp/keys.log 2>&1 < /dev/null &
      echo $! > /tmp/mgbaqol-keys.pid
      sleep 2
    fi
    printf 'input_player1_joypad_index = "1"
input_player2_joypad_index = "0"
' > /tmp/mgbaqol-keys.cfg
    retroarch --config /storage/.config/retroarch/retroarch.cfg       --appendconfig "/storage/mgbaqol-probe/test.cfg|/tmp/mgbaqol-keys.cfg"       -L /tmp/cores/mgbaqol_libretro.so "$2" > /storage/mgbaqol-probe/ra.log 2>&1 &
    ;;
  ra-stop)
    kill $(pidof retroarch) 2>/dev/null
    ;;
esac
