<p align="center">
  <img src="docs/banner.jpg" alt="Counter-Strike 1.5 Web Panel" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Counter--Strike-1.5%20WON2-ffaa00?style=for-the-badge" alt="Counter-Strike 1.5 WON2">
  <img src="https://img.shields.io/badge/HLDS-WON%20%26%20Steam-c8771f?style=for-the-badge" alt="WON & Steam HLDS">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/aiohttp-web%20server-2C5BB4?style=for-the-badge&logo=aiohttp&logoColor=white" alt="aiohttp">
  <br>
  <img src="https://img.shields.io/badge/SQLite-statistics-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/languages-9-b27700?style=for-the-badge" alt="9 languages">
  <img src="https://img.shields.io/badge/Docker-not%20needed-4a4a4a?style=for-the-badge&logo=docker&logoColor=white" alt="Docker not needed">
  <img src="https://img.shields.io/badge/phone-friendly-e36414?style=for-the-badge" alt="Phone-friendly">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f?style=for-the-badge" alt="MIT license"></a>
</p>

<p align="center">
  <b>A web control panel for a Counter-Strike 1.5 dedicated server — the classic WON HLDS 3.1.1.x that still plays on WON2, and the Steam / SteamCMD HLDS too.</b><br>
  One small Python program on the same machine as the game server — open it in a browser and run the server without the console.
</p>

<p align="center">
  <a href="#-screenshots"><b>📸 Screenshots</b></a> ·
  <a href="#-installation-step-by-step"><b>🚀 Install</b></a> ·
  <a href="#-where-everything-is-configured"><b>🧩 Configure</b></a> ·
  <a href="#-troubleshooting"><b>🩺 Troubleshooting</b></a>
</p>

<p align="center"><img src="docs/screenshots/overview.jpg" alt="Overview page in the Counter-Strike 1.5 look" width="92%"></p>

## ✨ What it does

| | |
|---|---|
| 🏠 **Overview** | Status of the server, the current map with its picture and time left, the **round score CT : T**, the next map, who is on the map with team, frags and time, machine load, memory and disk, totals for all time; next map, restart the map, **restart the round**, restart the server. |
| 👥 **Players** | Who is on the server — user id, team (CT / T), address, bot or human — straight from the live log; kick, ban by IP (written to `listip.cfg`), lift bans, message to everyone. **YaPB bots card**: how many bots, players and bots together or exactly that many bots, difficulty, remove all bots. |
| 🗺️ **Maps** | What is playing, how long and what comes next; **load any map** in a click — a window with its picture and the order after it; **your own map order** as tiles with pictures: drag to reorder, switch maps off — the server follows it from the next map change, no restart. |
| ⚙️ **Server settings** | Every setting of `server.cfg` — round time, freeze time, buy time, C4 timer, start money, friendly fire, team balance… — with the value in the file and the live value on the server, plus the bot settings of `yapb.cfg`. A backup copy before every save, applied at once through rcon; if the server only takes it after a map change or a restart, the panel asks — now or later — and keeps a reminder. |
| 💣 **Rounds** | Rounds won by counter-terrorists and terrorists, bombs planted, exploded and defused, hostages rescued, team kills — for the whole server, per map and per player. |
| 📊 **Statistics** | Matches, kills, weapons, maps; **human players by IP address** (nicknames repeat): every visit with exact time, country and flag; a **player card** (visits, play time, K/D, favourite weapons and maps, best visits, where they play best, days of the week, hours); records, top killers, newcomers, how long visits last; a calendar and a weekdays × hours heat map. |
| 📜 **Logs · Console · Audit log** | The live game log, the server's own `L*.log` and the console with filter and auto-refresh (the rcon password the engine writes into its log is cut out); any rcon command with a command reference; every action done in the panel. |
| 🌍 **9 languages** | Russian, English, German, French, Spanish, Portuguese, Polish, Japanese, Chinese — the browser's language by default; country names in the panel's language. |
| 🎨 **Counter-Strike look** | The orange-on-black colours of the old WON menu, a desert, night or current-map background, CC0 background music — and, built from **your own** game, map pictures and the menu sounds. Or the olive **Steam 2003** look of the CS 1.6 menu, or a plain light / dark one. |
| 📱 **Phone-friendly** | Every page fits a phone screen. |

> [!TIP]
> All you need is a **Counter-Strike 1.5 dedicated server that already runs** — started however you like — and
> Python. No Docker, no watchdogs or helper scripts on the game server's side; no web server and no database
> server for the panel either. Statistics live in an SQLite file next to the panel. Docker (restart button,
> container card) is supported when you have it — otherwise those buttons simply do not appear.

## 📸 Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/login.jpg" alt="Login"><br><b>Login</b> — the Counter-Strike 1.5 look with the desert background</td>
    <td width="50%"><img src="docs/screenshots/maps.jpg" alt="Maps"><br><b>Maps</b> — what is playing, a map picker with pictures and your own map order</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/load-map.jpg" alt="Load a map"><br><b>Load a map</b> — its picture and what the server plays after it</td>
    <td><img src="docs/screenshots/players.jpg" alt="Players"><br><b>Players</b> — teams, kick, ban by IP, YaPB bots (night background)</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/rounds.jpg" alt="Rounds"><br><b>Rounds</b> — CT and T wins, the bomb, hostages, team kills</td>
    <td><img src="docs/screenshots/humans.jpg" alt="Human players"><br><b>Human players</b> — every visit with time, country and IP; totals per address</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/summary.jpg" alt="Summary"><br><b>Summary</b> — weapons, countries, records, top killers, maps of humans</td>
    <td><img src="docs/screenshots/player-card.jpg" alt="Player card"><br><b>Player card</b> — visits, K/D, weapons, maps, best visits, days and hours</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/calendar.jpg" alt="Calendar"><br><b>Calendar</b> — visits per day, a weekdays × hours heat map, the visits of a day</td>
    <td><img src="docs/screenshots/server-settings.jpg" alt="Server settings"><br><b>Server settings</b> — <code>server.cfg</code> as a form, live values next to the file</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/prefs.jpg" alt="Panel settings"><br><b>Panel settings</b> — 9 languages, 3 looks, backgrounds, music and menu sounds</td>
    <td><img src="docs/screenshots/steam.jpg" alt="Steam 2003 look"><br><b>Steam 2003</b> — the olive look of the Counter-Strike 1.6 menu</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/plain-dark.jpg" alt="Plain look, dark"><br><b>Plain look</b> — dark…</td>
    <td><img src="docs/screenshots/plain-light.jpg" alt="Plain look, light"><br>…and light</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/japanese.jpg" alt="Japanese interface"><br><b>日本語</b> — and eight more languages</td>
    <td><img src="docs/screenshots/russian.jpg" alt="Russian interface"><br><b>Русский</b> — the panel's source language</td>
  </tr>
</table>

<p align="center">
  <img src="docs/screenshots/mobile-overview.jpg" alt="Overview on a phone" width="31%">
  <img src="docs/screenshots/mobile-stats.jpg" alt="Rounds on a phone" width="31%">
  <img src="docs/screenshots/mobile-maps.jpg" alt="Maps on a phone" width="31%">
  <br><b>On a phone</b> — overview, rounds, maps
</p>

<sub>The screenshots were taken with demo data: nicknames and IP addresses (from the ranges reserved for documentation) are made up. Map pictures are rendered by the panel's own tool from the maps of the game.</sub>

---

## 📖 Contents

1. [Requirements](#-requirements)
2. [Installation, step by step](#-installation-step-by-step)
3. [Where everything is configured](#-where-everything-is-configured)
4. [Updating](#-updating)
5. [How it works](#-how-it-works)
6. [Security](#-security)
7. [Troubleshooting](#-troubleshooting)
8. [Translations](#-translations)
9. [Project layout](#-project-layout)
10. [Legal](#-legal)

---

## 🧰 Requirements

| What | Notes |
|---|---|
| **A Counter-Strike 1.5 dedicated server that already works** | WON HLDS 3.1.1.x (protocol 46) with Counter-Strike 1.5 (`cstrike`) — the version that still plays on WON2. A Steam HLDS (protocol 48) with Counter-Strike 1.6 works too; the protocol is detected automatically. |
| **Linux** | The panel reads `/proc` for machine load and the server's uptime. Any distribution; the commands below are for Debian / Ubuntu. |
| **The same machine as the server** | The panel edits `server.cfg` and `mapcycle.txt`, reads the maps folder and the logs. |
| **Python 3.10+** | With `aiohttp` (and optionally `maxminddb` for countries), installed below into a virtual environment. |
| **rcon password** set on the server | The panel sends commands through rcon. |
| A Counter-Strike game client or the server files *(optional)* | Only to build map pictures and menu sounds (step 11). |

The examples below assume:

- the server runs as the Linux user **`hlds`**;
- it is installed in **`/home/hlds/hlds_l`** (with `hlds_run` and the game folder `cstrike/` that holds `server.cfg`,
  `mapcycle.txt` and `maps/`);
- the panel goes to **`/opt/cs-panel`**.

Replace these with your own paths and user everywhere.

---

## 🚀 Installation, step by step

### Step 1. Look at your server

```bash
ls /home/hlds/hlds_l/cstrike
```

You should see `server.cfg`, `mapcycle.txt` and the `maps` folder. This folder is `HL_DIR` in the settings.

```bash
grep -E '^\s*(rcon_password|log|logaddress)' /home/hlds/hlds_l/cstrike/server.cfg
```

### Step 2. Install Python and git

```bash
sudo apt update
```

```bash
sudo apt install -y git python3 python3-venv
```

Check the version — it must be 3.10 or newer:

```bash
python3 --version
```

### Step 3. Download the panel and install its packages

```bash
sudo git clone https://github.com/bboyJohnn/Counter-Strike-1.5-Servak-AdminPanel.git /opt/cs-panel
```

```bash
sudo chown -R hlds:hlds /opt/cs-panel
```

```bash
sudo -u hlds python3 -m venv /opt/cs-panel/venv
```

```bash
sudo -u hlds /opt/cs-panel/venv/bin/pip install -r /opt/cs-panel/requirements.txt
```

### Step 4. Turn on rcon and the live log in `server.cfg`

The panel learns who joins, leaves and kills whom from the **live log**: the server sends every log line over UDP
to the panel. Add to `/home/hlds/hlds_l/cstrike/server.cfg` (keep your own rcon password if you have one):

```
rcon_password "put-a-long-password-here"
log on
logaddress 127.0.0.1 27500
```

On a **Steam** server use `logaddress_add 127.0.0.1 27500` instead of `logaddress`. Add `mp_logmessages 1` to see
the chat on the Logs page. Counter-Strike writes its rounds, the bomb and the hostages into the same log by itself.
Restart the game server once so it reads the file.

### Step 5. Write the settings file `.env`

All settings of the panel are in **one file**, `.env`, next to `app.py`:

```bash
cd /opt/cs-panel
```

```bash
sudo -u hlds cp .env.example .env
```

```bash
sudo -u hlds chmod 600 .env
```

```bash
sudo -u hlds nano .env
```

Usually only **one line** is needed — the game folder:

```
HL_DIR=/home/hlds/hlds_l/cstrike
```

Everything else (server.cfg, mapcycle.txt, maps, logs, the rcon password from server.cfg) is found from it. If the
server listens on another port, set `HL_PORT`; to show the address players connect to, set `PUBLIC_ADDRESS`.
The full list is in [Where everything is configured](#-where-everything-is-configured).

### Step 6. Set the panel password

A random password (printed on the screen and saved to `data/panel-password.txt`):

```bash
sudo -u hlds venv/bin/python app.py --init
```

Or choose your own:

```bash
sudo -u hlds venv/bin/python tools/passwd.py
```

Both write only a hash of the password and a session key into `.env`.

### Step 7. Check the setup

Start the game server first, then:

```bash
sudo -u hlds venv/bin/python app.py --check
```

It prints what the panel found and what it can reach, for example:

```
[OK  ] .env
[OK  ] panel password           set
[OK  ] HL_DIR                   /home/hlds/hlds_l/cstrike
[OK  ] server.cfg               /home/hlds/hlds_l/cstrike/server.cfg
[OK  ] mapcycle.txt             /home/hlds/hlds_l/cstrike/mapcycle.txt
[OK  ] maps (*.bsp)             26 in /home/hlds/hlds_l/cstrike/maps
[ -  ] map order                /opt/cs-panel/data/mappool.txt (created on first save)
[OK  ] server 127.0.0.1:27015   My CS server, de_dust2, 0/16 players, protocol 46 (won)
[OK  ] rcon                     "mapcyclefile" is "mapcycle.txt"
[ -  ] live log                 the panel listens on 127.0.0.1:27500 and writes /opt/cs-panel/data/live.log ...
[ -  ] Docker                   no
[ -  ] server restart           not configured
[ -  ] bots                     no
[ -  ] countries (GeoLite2)     no database: countries are not shown
All good.
```

`FAIL` lines must be fixed; `-` lines are optional features that are off.

### Step 8. Run the panel as a service

```bash
sudo cp deploy/cs-panel.service /etc/systemd/system/
```

Edit `User`, `Group` and the paths in it if yours differ:

```bash
sudo nano /etc/systemd/system/cs-panel.service
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now cs-panel
```

```bash
systemctl status cs-panel
```

### Step 9. Open the panel in your browser

By default the panel listens only on `127.0.0.1:8094` — nothing from the internet can reach it. The simplest
safe way in is an **SSH tunnel** from your computer:

```bash
ssh -L 8094:127.0.0.1:8094 hlds@your-server
```

and then open <http://127.0.0.1:8094> on your computer, while that SSH session is open.

Other ways:

- **Home network.** Set `PANEL_HOST=0.0.0.0` and allow your network:
  `PANEL_ALLOWED_PEERS=127.0.0.1,::1,192.168.0.0/24`. Open `http://<server-ip>:8094`.
- **Reverse proxy with HTTPS** (nginx, Caddy) on the same machine: keep `PANEL_HOST=127.0.0.1` and proxy to it.
  Do not open the plain-HTTP port to the internet.

### Step 10 (optional). The restart button

Without it the panel works the same, just without "Restart the server".

- **Server in Docker:** `CONTAINER=<container name>`. You also get the container card (CPU, memory, restarts),
  stop / start, and `docker logs` as the server console. The panel's user must be allowed to run `docker`.
- **Server without Docker:** run it so that something starts it again when it stops — `hlds_run` (it restarts
  the server after a crash) or systemd with `Restart=always` (see `deploy/hlds.service`). Then let the panel
  stop the process:

  ```
  RESTART_CMD=pkill -x hlds_i686
  ```

  That is the WON server's binary (`hlds_run` may pick `hlds_amd` or `hlds_i486` instead — see `ps -e | grep hlds`);
  on a Steam server it is `hlds_linux`.

  With `deploy/hlds.service` the console output goes to a file; show it in the panel with
  `CONSOLE_LOG=/home/hlds/hlds_l/console.log`.

### Step 11 (optional). Map pictures and menu sounds from your game

These are Valve's files, so they are not in the repository. Build them from **your own** copy of the game (the folder
with `cstrike/` and `valve/` inside — a client install or the server itself):

```bash
sudo -u hlds venv/bin/pip install numpy pillow
```

```bash
sudo -u hlds venv/bin/python tools/build_assets.py --game /path/to/Half-Life
```

- **Map pictures** — a rendered view of every map of your server (from `MAPS_DIRS` and the game's `cstrike/maps`),
  textures from the `.wad` files of `cstrike/` and `valve/`. Without them the panel shows "no picture". Maps get an
  automatic view from a spawn point; you can pick your own in `tools/map_cameras.txt`.
- **Menu sounds** — `cstrike/media/launch_*.wav` (or `valve/media`) of the old WON menu: hover, click, error,
  window open/close.
- Counter-Strike 1.5 has no spinning menu logo (its `logo.avi` is an empty placeholder), so the login screen has
  none. With `--mod valve` the same script builds the Half-Life one.

You can also run the script on your PC and copy `static/maps` and `static/hl` to the server. Then reload the panel page.

### Step 12 (optional). Countries of IP addresses

Download the free **GeoLite2 Country** database from MaxMind (needs a free account), put
`GeoLite2-Country.mmdb` into `/opt/cs-panel/data/` (or set `GEOIP_DB`), and restart the panel. Lookups happen on
your server; addresses are not sent anywhere.

### Step 13 (optional). Bots

The panel has a card for [YaPB](https://github.com/yapb/yapb) bots. Install YaPB as a Metamod plugin
(`addons/yapb`, a line `linux addons/yapb/bin/yapb.so` in `plugins.ini`) and point the panel at its settings file:

```ini
BOTS_CFG=/home/hlds/hlds_l/cstrike/addons/yapb/conf/yapb.cfg
```

- **Players** page: how many bots (`yb_quota`), the mode — *players and bots together* (`fill`: an empty server has
  that many bots, a player joins and one bot leaves) or *exactly that many bots* (`normal`) — the difficulty from
  0 (newbie) to 4 (expert), and **Remove all bots** (until the server restarts; `yapb.cfg` is not changed).
- **Server settings** page: the other bot settings — which team bots join, buying, chat, radio, a name prefix.
- Every change is written to `yapb.cfg` (a backup copy first, in `data/cfg-backups`) and applied at once through
  rcon. The panel user must be able to write `yapb.cfg`.

> ⚠️ On Counter-Strike 1.5 use YaPB **4.8 or newer** (the *continuous* build). The stable 4.4.957 crashes the
> server as soon as a bot picks a team: the CS 1.5 game library of 2002 aligns the stack differently.
> The bundled waypoint graphs are made for the CS 1.6 versions of the maps; if bots stand still on a map, move its
> `addons/yapb/data/graph/<map>.graph` away and set `yb_graph_url ""` — YaPB then builds its own graph.

Bots that write `BOT` instead of an ID into the log (YaPB, PODBot and others) are recognised by themselves: they are
marked on the Players page and counted separately in the statistics. `BOTS_CFG` also takes `jk_botti.cfg` of
[jk_botti](https://github.com/Bots-United/jk_botti), a Half-Life Deathmatch bot.

---

## 🧩 Where everything is configured

Everything is in **`.env`** (see `.env.example` for comments). Paths may use `${KEY}` of a key above; relative
paths start at the folder of `.env`. Check with `python3 app.py --check`.

| Key | Default | What it is |
|---|---|---|
| `HL_DIR` | — (**required**) | The server's game folder (`cstrike`) with `server.cfg`, `mapcycle.txt`, `maps/`. |
| `PANEL_PASSWORD_HASH`, `PANEL_SECRET` | — (**required**) | Written by `app.py --init` / `tools/passwd.py`. |
| `HL_HOST`, `HL_PORT` | `127.0.0.1`, `27015` | Where the panel queries the server. |
| `PUBLIC_ADDRESS` | | Address players connect to, shown on the Overview. |
| `RCON_PASSWORD` | from `RCON_CFG` | The rcon password; empty = read `rcon_password` from `RCON_CFG`. |
| `RCON_CFG` | `${SERVER_CFG}` | File with `rcon_password` (if you keep it outside server.cfg). |
| `LOG_UDP` | `127.0.0.1:27500` | Where the panel receives the live log. Empty = do not listen. |
| `LIVE_LOG` | `${PANEL_DATA}/live.log` | The live log file (written by the panel, or by something else when `LOG_UDP` is empty). |
| `PANEL_HOST`, `PANEL_PORT` | `127.0.0.1`, `8094` | Where the panel listens. |
| `PANEL_ALLOWED_PEERS` | `127.0.0.1,::1` | Addresses / networks allowed to connect at all. |
| `PANEL_TITLE` | server's hostname | Name in the menu and on the login screen. |
| `PANEL_HUB` | | Optional "All panels" link: a URL or `:port` on the same host. |
| `SERVER_CFG` | `${HL_DIR}/server.cfg` | The settings page. Sections are lines `// 1. Name` (optional). |
| `MAPCYCLE` | `${HL_DIR}/mapcycle.txt` | The engine's map list (rewritten by the panel). |
| `MAPPOOL` | `${PANEL_DATA}/mappool.txt` | The panel's map order (first time taken from mapcycle.txt). |
| `MAPS_DIRS` | `${HL_DIR}/maps` | Folders with `.bsp` maps, comma separated. |
| `LISTIP_CFG` | `${HL_DIR}/listip.cfg` | IP bans (written by `writeip`). |
| `HLDS_LOGS` | `${HL_DIR}/logs` | The server's `L*.log` files. |
| `PANEL_DATA` | `./data` | Panel database, map order, live log, copies of edited files. |
| `PASSWORD_FILE` | `${PANEL_DATA}/panel-password.txt` | Where `--init` saves the new password. |
| `CONTAINER` | | Docker container of the server (restart / stop / start, container card, docker logs). |
| `RESTART_CMD` | | Without Docker: command that restarts the server, e.g. `pkill -x hlds_i686`. |
| `CONSOLE_LOG` | | File with the server's console output (Logs page, crash list). |
| `BOTS_CFG` | | `yapb.cfg` of YaPB — bots card and bot settings (or `jk_botti.cfg` for Half-Life Deathmatch). |
| `GEOIP_DB` | `${PANEL_DATA}/GeoLite2-Country.mmdb` | GeoLite2 country database, comma-separated list allowed. |

Settings of the **look** (language, style, background, music) are not on the server: each browser keeps its own,
on the **Panel settings** page (also reachable from the login screen).

---

## 🔄 Updating

```bash
cd /opt/cs-panel
```

```bash
sudo -u hlds git pull
```

```bash
sudo -u hlds venv/bin/pip install -r requirements.txt
```

```bash
sudo systemctl restart cs-panel
```

`.env`, `data/` and the files built by `tools/build_assets.py` are not touched by `git pull`. Press F5 in the browser
— the page links carry the file versions, so the browser picks up the new panel.

---

## ⚙️ How it works

- **Queries.** Status, players and settings come from the public queries every server browser uses (`info`,
  `players`, `rules` on WON; `A2S_INFO`, `A2S_PLAYER`, `A2S_RULES` with the challenge on Steam) — a few
  milliseconds each. Actions go through **rcon** (`challenge rcon` + `rcon`). The panel figures out which protocol
  your server speaks by itself.
- **Live log.** The old engine writes every rcon command into its log together with the password, so the panel does
  *not* poll `rcon status`: who is on the server, their user id and address come from the live log (connect / enter
  / disconnect / kick lines), frags and time from the public `players` query. Visits of human players are stored with
  exact times; when the server restarts, open visits are closed at the last moment the player was seen.
- **Map names.** A Steam server writes them into its log (`Loading map`, `Started map`) and the panel takes them
  from there. A WON server's log has no map names — the panel asks the server (`info`) when it sees
  "Log file started" and remembers which map was loaded at that moment.
- **Map order.** The game library reads `mapcycle.txt` once and re-reads it only when the name in the
  `mapcyclefile` setting changes. So after saving the order the panel writes `mapcycle.txt` rotated so that **the
  next map comes first** and switches `mapcyclefile` between `mapcycle.txt` and `./mapcycle.txt` (the same file):
  at the next map change the server takes the first map of the new list. If someone changes the map past the list
  (console, `changelevel`), the panel rotates the list again. Disabled maps are left out of `mapcycle.txt`. The
  file is written in place (same inode), so a server in a container with a single-file bind mount sees it too.
  Keep the list short: the WON 1.1.1.0 client reads only ~8 KB of the map list the server sends.
- **Settings.** `server.cfg` is changed line by line — comments, order and layout stay; a copy goes to
  `data/cfg-backups` before every write. The new value is sent by rcon at once; then the panel compares it with the
  live value from `rules` and tells you if the server only takes it after a map change or a restart.
- **Counter-Strike events.** The game writes them into the same log: `joined team "CT"`, `triggered
  "Planted_The_Bomb"` / `"Defused_The_Bomb"` / `"Rescued_A_Hostage"`, and at the end of every round
  `Team "CT" triggered "CTs_Win" (CT "3") (T "1")`. From them the panel knows each player's team, the round score of
  the current map, who won every round and how, and who killed a teammate (a team kill is not counted as a frag).
  "Restart round" sends `sv_restartround 1`.
- **Statistics.** Matches (one map from start to change), rounds, kills, weapons and maps are parsed from the live log
  once a minute into SQLite (`data/panel.db`). The live log is trimmed when it grows over 10 MB.

---

## 🔒 Security

- Out of the box the panel accepts connections **only from the same machine** (`PANEL_HOST=127.0.0.1`,
  `PANEL_ALLOWED_PEERS=127.0.0.1,::1`). Reach it with an SSH tunnel or a reverse proxy with HTTPS.
- Login with one password, stored only as an scrypt hash; signed session cookie (`HttpOnly`, `SameSite=Strict`),
  CSRF token on every change; 5 wrong passwords lock the login for 5 minutes.
- Strict Content-Security-Policy (no inline scripts, nothing from other sites); everything from the server
  (player names, log lines) is shown as text, never as HTML.
- The rcon password never reaches the browser; it is cut out of every log line the panel shows.
- Every action (kick, ban, settings, maps, console commands, logins) goes to the audit log.
- `.env` and `data/` should be readable only by the panel's user (`chmod 600 .env`).

---

## 🩺 Troubleshooting

| Problem | What to do |
|---|---|
| `--check`: **server … no answer** | Is the server running? Right `HL_HOST` / `HL_PORT`? On a machine with a firewall, the query goes to the server's UDP port from the same machine — nothing to open. |
| `--check`: **rcon … rejected the rcon password** | `rcon_password` in server.cfg (or `RCON_PASSWORD`) must match the running server; restart the server after changing it. |
| Nobody shows up on **Players**, statistics stay empty | The live log is not arriving: check `log on` and `logaddress 127.0.0.1 27500` (`logaddress_add` on Steam) in server.cfg, restart the server, and look at `data/live.log`. Only one program can listen on the port. |
| The map order does not change the next map | The server must allow the `mapcyclefile` change by rcon (it does by default). The order applies **from the next** map change; "Next map" applies it at once. |
| "Restart the server" is missing | Set `CONTAINER` or `RESTART_CMD` (step 10). |
| No pictures on Maps | Build them from your game (step 11), or put your own 640×360 JPEGs into `static/maps/` and 192×108 ones into `static/maps/thumb/`. |
| The page looks old after an update | Press F5. |
| Logs of the panel itself | `journalctl -u cs-panel -f` |

---

## 🌍 Translations

The source language is Russian; the dictionaries are `static/i18n/<code>.js` (`en de fr es pt pl ja zh`). Every
text of the panel is wrapped in `L('…')` in `static/app.js` and that Russian text is the key; server messages are
translated with the same dictionary. To check or extend them:

```bash
python3 tools/i18n.py check
```

```bash
python3 tools/i18n.py keys > keys.txt
```

A missing translation just shows the Russian text — nothing breaks. Keys starting with `#` are plural forms
(an object with the language's plural categories, e.g. `{"one": "{0} visit", "other": "{0} visits"}`).

---

## 🗂️ Project layout

```
app.py            web server, API, background tasks, live-log receiver; --init and --check (cli.py)
config.py         reads .env, defaults, which optional features exist
hl.py             talking to HLDS: WON and Steam queries, rcon, command reference
live.py           live log -> who is online, visits of human players
stats.py          live log -> matches, rounds, kills, weapons, maps (SQLite)
humans.py         per-IP player summaries, player card, records
cfg.py            server.cfg / yapb.cfg / jk_botti.cfg editing with backups, map order
mapcycle.py       map order file and the engine's mapcycle.txt
sysinfo.py        machine, Docker or process uptime, restart, logs
geo.py            country by IP (GeoLite2)
logline.py        parsing of log lines: kills, teams, rounds, bomb, hostages; rcon password redaction
audit.py          audit log
passwords.py      password hash
static/           the web page: app.js, app.css, boot.js, i18n/, fonts/, music/, hl/, flags/
tools/            i18n.py, passwd.py, build_assets.py (+ bsp_render.py, map_cameras.txt)
deploy/           systemd units for the panel and (example) for HLDS
docs/             the banner and screenshots of this README
```

---

## ⚖️ Legal

The panel's code is under the [MIT license](LICENSE).

Counter-Strike® and Half-Life® are trademarks of Valve Corporation. This panel is not affiliated with or endorsed by Valve.
Map pictures and menu sounds are Valve's and are **not** included — the panel builds
them from your own copy of the game (`tools/build_assets.py`).

Included third-party files: background music by Ruskerdax, yd, isaiah658 and vitalezzz from OpenGameArt under
**CC0** (`static/music/CREDITS.txt`); fonts Exo 2, Russo One (as "Panel Display") and Share Tech Mono (as "Panel
Mono") under the **SIL Open Font License 1.1** (`static/fonts/`); country flags from
[flag-icons](https://github.com/lipis/flag-icons) under the **MIT** license (`static/flags/LICENSE.txt`).
The backgrounds and the crosshair icon are drawn for this panel.
