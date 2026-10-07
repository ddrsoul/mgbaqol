#!/bin/sh
# Dev helper on the console: dev.sh start ROM [args] | stop | shot NAME | ra ROM | ra-stop
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
  ra)
    retroarch --config /storage/.config/retroarch/retroarch.cfg --appendconfig /storage/mgbaqol-probe/test.cfg \
      -L /tmp/cores/mgbaqol_libretro.so "$2" > /storage/mgbaqol-probe/ra.log 2>&1 &
    ;;
  ra-stop)
    kill $(pidof retroarch) 2>/dev/null
    ;;
esac
