# mgba-qol: заметки для разработки

Описание проекта и установки: [README.md](../README.md).

## Цикл разработки

```bash
sh tools/deploy.sh          # собрать build/mgbaqol-dev, скопировать на приставку, запустить install.sh
sh tools/release.sh 0.1.0   # build/mgbaqol-test-install-0.1.0.zip для релиза (нужен python3, например WSL)
```

Приставка: `ssh -i ~/.ssh/id_ed25519_rocknix root@RK3566`.

Запуск без ES (на приставке, `/storage/mgbaqol-probe/dev.sh`):

```bash
sh dev.sh ra "/storage/roms/gba/ИГРА.gba"                  # RetroArch с ядром mgbaqol и сетевыми командами
sh dev.sh start "/storage/roms/gba/ИГРА.gba" --tab bag     # компаньон; --detail N, --map-mode Wild, --debug-mapsec N
sh dev.sh shot NAME                                         # скриншот нижнего экрана в /tmp/NAME.png
sh dev.sh stop; sh dev.sh ra-stop
```

Лог компаньона из `dev.sh`: `/tmp/mgbaqol-dev.log`; из ES: `/var/log/mgbaqol.log`.

## Тестовая установка

- `/storage/mgbaqol-dev/`: `share/` (компаньон), `rocknix/`, `install.sh`, `uninstall.sh`, `patch_runemu.py`.
- `install.sh` при каждой загрузке (через `/storage/.config/autostart/mgbaqol-dev`):
  - ссылка `mgbaqol_libretro.so` и `.info` в `/storage/cores`;
  - патчит копию текущего `/usr/bin/runemu.sh` по двум якорным строкам и монтирует поверх;
    если якоря не найдены, ничего не монтирует;
  - пересобирает `es_systems.cfg` из системного с ядром `mgbaqol`;
  - если ядро уже есть в прошивке, ничего не делает.
- Лог: `/var/log/mgbaqol-install.log`.
- Откат: `uninstall.sh` (`--purge` удаляет всё, включая кеши и `/storage/mgbaqol-probe`).

## Прошивка

Пакет `mgbaqol-lr` в ветке `mgbaqol` форка ddrsoul/distribution скачивает этот репозиторий
по тегу. После нового релиза: поменять `PKG_VERSION` и `PKG_SHA256` в его `package.mk`.
