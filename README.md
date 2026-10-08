# mGBA QoL

mGBA for Game Boy Advance plus a live companion on the second screen of
dual-screen handhelds running [ROCKNIX](https://rocknix.org). The game runs on
the top screen as usual; the bottom screen shows what the game keeps hidden or
buried in menus, read from the running game:

- **Gen 3 Pokémon** (and hacks): your party, the current battle, your bag, the
  region map and the wild Pokémon around you;
- **Fire Emblem 7** (*Fire Emblem*, USA): your units with their hidden growth
  rates, the battle you are choosing with real hit rates and kill odds, the
  enemies and what makes them dangerous, enemy ranges on the map;
- **Advance Wars 2: Black Hole Rising** (USA): the armies and CO powers, a
  damage calculator that follows the game's cursor, your units' fuel, ammo and
  dangers, enemy reach on the map.

Tested on the Anbernic RG DS.

## Installing

There are two ways to get it.

**Firmware build.** The `mgbaqol` branch of
[ddrsoul/distribution](https://github.com/ddrsoul/distribution/tree/mgbaqol)
(a ROCKNIX fork) packages this repository as `mgbaqol-lr`: it adds the core to
EmulationStation and the hook to `runemu.sh`. Build that branch as usual.

**Test install, no rebuild.** For a ROCKNIX build that doesn't include it:

1. Download `mgbaqol-test-install-<version>.zip` from the
   [releases](https://github.com/ddrsoul/mgbaqol/releases) and unpack it to
   `/storage`, so that you get `/storage/mgbaqol-dev/install.sh`.
2. Over SSH: `sh /storage/mgbaqol-dev/install.sh`, then
   `systemctl restart essway`.

The installer:

- links `mgbaqol_libretro.so` to the mgba core in `/storage/cores` (the
  writable layer of `/tmp/cores`) and adds its `.info`;
- writes a copy of the firmware's own `/usr/bin/runemu.sh` with the hook added
  and bind-mounts it over the original; if `runemu.sh` has changed too much to
  find where the hook goes, it leaves it alone and says so;
- rebuilds `/storage/.config/emulationstation/es_systems.cfg` from the
  firmware's list with `mgbaqol` added for Game Boy Advance;
- adds `/storage/.config/autostart/mgbaqol-dev`, which repeats all of this at
  every boot (the mount doesn't survive a reboot), and does nothing once the
  firmware ships mgba-qol itself.

To remove it: `sh /storage/mgbaqol-dev/uninstall.sh` (add `--purge` to delete
its files and caches too), then `systemctl restart essway`.

## Using it

1. In EmulationStation, open a Game Boy Advance game's options and pick the
   `mgbaqol` core (RetroArch). Other games keep their own core.
2. Start the game. The bottom screen lights up with the companion a few
   seconds later; on the first run with a new ROM it scans the ROM, which takes
   up to half a minute, then caches the result.
3. Quit the game as usual; the companion closes and the bottom screen turns
   off.

Only games started with `mgbaqol` get the companion. Everything else in
RetroArch (saves, savestates, hotkeys, shaders, per-game settings) works the
same as with the regular `mgba` core, and saves are shared with it.

## Tabs (Pokémon)

- **Party**: six windows with sprite, types, level, HP and status. Tap one
  for a Summary-style page: stats, held item and the four moves; tap a move
  for its power, accuracy, effect chance, priority and the game's own
  description. Tap the top window to go back.
- **Battle**: the opponent's sprite, types, HP, status and stat stages; your
  active Pokémon; your moves with their effectiveness against the opponent
  (no effect / not very / normal / super), STAB, and the best damaging move
  marked *Best*. Uses the Gen 6+ type chart; abilities such as Levitate are
  not taken into account.
- **Bag**: every pocket the game has, switched with the arrows like in the
  games, items with quantities. Tap an item for its description.
- **Map**: the location name; *Map* shows the game's own region map with
  your location highlighted, *Wild* the wild Pokémon of the current map with
  levels and odds per method (grass, surfing, rock smash, and each rod).
- **Settings** (menu icon at the right of the tab bar): see below.

## Fire Emblem 7

- **Units**: your army with level and HP; *can die* when the enemies that can
  reach a unit on their next phase can deal more than its HP, *N reach* when
  some can. Tap a unit for its page: stats against the class caps, the growth
  rates the game never shows, items with uses left, weapon ranks and how far
  the next rank is.
- **Battle**: the battle the game is forecasting (or the last one fought).
  FE7 rolls two random numbers and hits when their average is below the shown
  rate, so the real chance differs: 82 shown is 93 real, 30 shown is 18.
  Shown here: damage and how many strikes, shown and real hit, crit, the
  chance each side dies, and how many enemies can reach the tile you attack
  from on their next phase.
- **Enemies**: every enemy you can see, bosses first, flagged when they carry
  a weapon effective against one of your units, a high-crit weapon, an item
  they drop, or a long-range weapon; tap one for its stats and inventory.
- **Map**: the chapter map with all units; red where enemies can attack next
  phase, tap an enemy for its own range (gold), tap a tile for its terrain
  bonuses. Fog of war hides here what it hides in the game.

## Advance Wars 2

- **Army**: day and whose turn it is; each army's CO, funds, CO power meter
  (and whether a power is active), unit count and value; your units against
  the enemy's by type.
- **Attack**: follows the game's cursor. On an enemy: which of your units can
  hit it this turn, the damage range with luck, the chance to destroy it and
  the counterattack. On your unit: which enemies can hit it on their turn and
  how much. Damage uses the game's own charts and each CO's modifiers from the
  ROM, including active powers.
- **Units**: your units with HP, fuel and ammo; planes and ships that will
  crash or sink for lack of fuel, units that can be destroyed next turn.
- **Map**: terrain, properties by owner, all units; red where enemies can
  fire next turn, tap an enemy for its own reach. Under fog of war only what
  your units and properties can see is shown. The settings menu picks whose
  side the views take (the first army by default).

## Controls

Touch everything, or use the gamepad's right stick, which GBA games don't
use (the companion reads it alongside RetroArch without taking it away
from the game):

- **left / right**: previous / next tab;
- **up / down**: move through the current list: party, a Pokémon's moves
  (each one's description shows below), the bag's items, Wild's methods;
- **press (R3)**: open / close a Pokémon's details; switch Map / Wild.

Holding a direction repeats after 0.8 s, then every 0.25 s.

## Supported games

Games on the FireRed and Emerald engines, including ROM hacks. The companion
does not need a per-game table for most of what it shows:

- Names, types, base stats, moves and move descriptions, items and item
  descriptions, sprites, location names, wild encounter tables and the region
  map are read from the ROM. Each table is located by its content (for
  example Bulbasaur, Ivysaur and Venusaur in a row), so hacks that move or
  resize tables still work.
- RAM addresses start from the pret decomp values for FireRed (also kept by
  CFRU hacks) and Emerald. Each one is checked against what it holds; if a
  hack moved it, the companion searches RAM for the structure by its shape and
  remembers the address for that ROM.

Checked so far:

| Game | ROM data | Party | Bag | Battle | Map |
|---|---|---|---|---|---|
| Emerald Enhanced v1.1.0.21 | yes | yes | yes | yes | yes |
| Pokémon Odyssey v4.1.1 | yes | yes | yes | yes | yes |
| Pokémon Unbound v2.1.1.1 | yes | yes | yes | yes | yes |

Odyssey stores Pokémon data unencrypted and widens bag pocket sizes; both
are recognised automatically.

The region map is found two ways: FireRed-engine hacks that patch the
FireRed ROM (CFRU: Unbound, Odyssey, …) keep FireRed 1.0's region map code in
place, so its literal pools lead to each hack's own map; Emerald-engine games
keep the map graphics next to the map section table, where they are found by
format and confirmed by the code that loads them. Hacks rebuilt from the
FireRed decomp with moved code show "No region map for this game"; the rest
of the Map tab still works.

## Settings

- **Party data**: which copy of your team in RAM to read. Games keep two: the
  live party and the copy inside the save data, which only changes when you
  save. *Auto* notices which one changes while you play and uses it. If the
  team on the bottom screen ever lags behind the game, pick the other address
  here; each row shows who is stored there.
- **Scan RAM again**: searches for the party again.
- **Forget found addresses**: drops everything the companion found and
  remembered for this ROM; it searches again as needed.
- **Found in RAM**: what has been located so far, plus the ROM's title, game
  code and CRC.

## Look

Made to sit next to the game: everything is laid out on a 320x240 canvas
that SDL doubles without smoothing, in Gen 3 style text windows on a
grey-blue background, with a pixel font and the games' type plates and HP
bars. Pokémon sprites are drawn at their native resolution.

## How it works

```
EmulationStation ──> runemu.sh --core=mgbaqol
                       │  network_cmd_enable = "true" (this core only)
                       ├─> retroarch -L mgbaqol_libretro.so (= mgba_libretro.so)
                       └─> start_mgbaqol.sh ──> python3 /usr/share/mgbaqol/main.py
                                                  │  UDP 55355: READ_CORE_MEMORY
                                                  └─ SDL2 window "mgbaqol" on DSI-1
```

- `mgbaqol_libretro.so` is a symlink to the mgba core, so ES can offer it per
  game and `runemu.sh` knows when to start the companion.
- The companion reads game memory through RetroArch's network commands
  (`READ_CORE_MEMORY`), which the mgba core maps to real GBA addresses. Reads
  are allowed with RetroAchievements hardcore mode on; nothing is written.
- It waits for RetroArch's window, then opens its own straight on the bottom
  screen (sway `for_window` + `no_focus` rules), never takes focus from the
  game (RetroArch reads the gamepad through udev), and exits a few seconds
  after RetroArch does.
- Python 3 standard library and SDL2, SDL2_ttf and SDL2_gfx through ctypes;
  nothing to build.

## Repository

| Path | Contents |
|---|---|
| `companion/main.py` | picks the companion by the ROM's game code |
| `companion/base.py` | window, drawing, tabs, touch and stick input, main loop |
| `companion/pokemon.py`, `screens.py` | Pokémon: Party view; Battle, Bag, Map and Settings views |
| `companion/fe.py`, `fe_data.py` | Fire Emblem 7: views; ROM tables, text, RAM, ranges, odds |
| `companion/aw.py`, `aw_data.py` | Advance Wars 2: views; ROM tables, RAM, damage, reach, fog |
| `companion/memory.py` | finding and reading party, battle, bag and location in RAM |
| `companion/romdata.py` | finding and reading tables in the ROM, sprites, region map |
| `companion/gen3.py` | Gen 3 text encoding and Pokémon data decoding |
| `companion/games.py` | known party addresses (speeds up the first run) |
| `companion/typechart.py` | type effectiveness |
| `companion/stick.py` | right-stick navigation (evdev) |
| `companion/ra.py`, `sdl.py`, `theme.py` | RetroArch client, SDL2 bindings, colours |
| `rocknix/` | `start_mgbaqol.sh` (started by `runemu.sh`) and the core's `.info` |
| `test-install/` | install / uninstall without a firmware rebuild |
| `tools/` | development: deploy to a console, release, probes |

Runtime files on the console:

- `/var/log/mgbaqol.log`: companion log.
- `/storage/.config/mgbaqol/cache/`: ROM table offsets and rendered maps, per ROM CRC.
- `/storage/.config/mgbaqol/games/<crc>.json`: RAM addresses and settings.

## Adding a game

Most FireRed- and Emerald-based games need nothing: start them with
`mgbaqol` and open each tab once. If something stays on "Looking for…":

1. Load a save with Pokémon in the party.
2. In Settings, check that the party shows up under one of the addresses and
   pick it.
3. To skip the search on first start, add the game to `games.py` with its game
   code, title prefix, party address and party count address.

Hacks that change the Pokémon data structures themselves (some
pokeemerald-expansion builds) need code changes.

## Development

- `tools/deploy.sh` builds the test install into `build/mgbaqol-dev` and, over
  SSH (`root@RK3566` with `~/.ssh/id_ed25519_rocknix`), copies it to the
  console and runs `install.sh`.
- `tools/release.sh VERSION` makes `build/mgbaqol-test-install-VERSION.zip`.
- `tools/probe/`: console-side helpers. `dev.sh` starts RetroArch with network
  commands and the companion outside ES (`--tab`, `--detail N`,
  `--map-mode Wild`, `--debug-mapsec N` for testing) and takes screenshots
  with `grim` (`shot` the companion, `top` the game); `dev.sh ra-keys ROM`
  plus `keys.py "a w1 start"` drive the game with a virtual gamepad;
  `dump.py` saves EWRAM / IWRAM for diffing; `probe_mem.py` reads and decodes
  the party; `region_png.py` and `sprite_sheet.py` dump what was found in a
  ROM.

## Limitations

- Double battles show only the first opponent.
- Only the RG DS screen layout (game on DSI-2, companion on DSI-1) has been
  tried; other dual-screen devices may need their output in
  `start_mgbaqol.sh`.
- Ruby and Sapphire have known party addresses but are otherwise untested.
- Fire Emblem: only FE7 USA (AE7E); enemy ranges assume every enemy moves
  (some bosses never do) and ignore rain and snow movement costs.
- Advance Wars 2: only the USA version (AW2E); reach assumes clear weather.

## License and credits

GPL-2.0-or-later, see `LICENSE`. The bundled
[Pixel Operator](https://notabug.org/HarvettFox96/ttf-pixeloperator) font by
Jayvee Enaguas is CC0 (public domain).

Inspired by [PokeDaisy](https://github.com/lidor30/pokedaisy) by Lidor
Itzhari, a dual-screen Pokémon companion for Android, whose notes on Gen 3
RAM and ROM addresses were a useful reference. No PokeDaisy code is used.
