# keysignal

A small Mac service that owns the connection to the keyboard, so anything on
this Mac (scripts, CI watchers, agent harnesses) can color keys through a local
HTTP API or the `keysignal` command. It needs the key signals firmware in this
repo (`keyboards/keychron/k2_he/ansi/keymaps/mylayout/features/key_signals.c`) and the USB cable plugged in.

## Install

```bash
uv tool install --editable ~/k2he/host
keysignal install     # starts at login via launchd; log: ~/Library/Logs/keysignal.log
keysignal uninstall   # stops and removes it
```

## Command line

```bash
keysignal set f5 alert --pattern pulse --source ci --id deploy --ttl 600
keysignal set auto warn --source t3 --id thread-42 --label "waiting on approval"
keysignal set space custom --color '#8000ff'
keysignal list
keysignal clear --source t3 --id thread-42   # or --source t3, or nothing for all
keysignal status
keysignal keys                               # key names and the auto pool
```

## HTTP API

The service listens on `http://127.0.0.1:7780` (override with `--port`; clients
honor `KEYSIGNAL_URL`). POST bodies must be `application/json`. Requests carrying
an `Origin` header are rejected, so web pages can't drive your keyboard.

| Method | Path | Does |
|---|---|---|
| `POST` | `/v1/signals` | create or update a signal |
| `DELETE` | `/v1/signals/<source>/<id>` | remove one signal |
| `DELETE` | `/v1/signals/<source>` | remove every signal from a source |
| `DELETE` | `/v1/signals` | remove everything |
| `GET` | `/v1/signals` | list signals |
| `GET` | `/v1/status` | keyboard connection, firmware, lit keys |
| `GET` | `/v1/keys` | key names and the auto pool |

A signal:

```jsonc
{
  "source": "t3",           // required: who owns it
  "id": "thread-42",        // required: unique within the source
  "level": "alert",         // required: good | warn | alert | custom | off
  "key": "auto",            // key name, "row,col", or auto (default)
  "pattern": "pulse",       // solid (default) | blink | pulse
  "ttl": 600,               // seconds until it removes itself; omit to keep it
  "color": "#8000ff",       // only for level custom
  "priority": 3,            // optional; defaults to good/custom 1, warn 2, alert 3
  "label": "needs approval" // optional note shown by `keysignal list`
}
```

```bash
curl -s localhost:7780/v1/signals -H 'Content-Type: application/json' \
  -d '{"source":"ci","id":"main","level":"good","key":"f12"}'
```

Posting the same `source` + `id` again updates that signal. `"level": "off"` removes it.

## How it behaves

- **Sharing keys:** when several signals want the same key, the highest priority wins; ties go to the newest.
- **Auto keys:** `key: "auto"` takes a free key from the pool (F1–F12 by default,
  `--pool` to change) and keeps it until the signal is removed. When the pool is
  full the API answers `409`.
- **Leases:** lights are leased to the keyboard for 30 seconds and refreshed every 10.
  If the service stops, the keys go dark by themselves.
- **Reconnects:** after the keyboard is unplugged, sleeps or reboots, the service puts
  everything back within a few seconds of the keyboard returning.
- **Sharing the device:** the USB device is opened only for each batch of commands,
  so VIA and Keychron Launcher keep working alongside it.
- **Visibility:** lights only show while the RGB backlight is on.

## T3 Code

`keysignal t3` lights a key for each [T3 Code](https://github.com/pingdotgg/t3code)
thread. It pairs with T3 as a read-only client and follows the same live thread
list T3's sidebar shows.

| Thread | Key |
|---|---|
| needs approval, awaiting input, plan ready | red, blinking |
| working (also background subagents) | amber, pulsing |
| finished in the last 12 hours | green |
| failed in the last 12 hours | red |
| settled, archived, deleted, snoozed, or older | off |

Each thread gets its own key from the auto pool (F1–F12) and keeps it while it's
lit. Most urgent threads get a key first when the pool is full.

```bash
# T3 Code → Settings → Connections → Create pairing link, "Read only"
keysignal t3 pair 'http://127.0.0.1:3773/pair#token=…'
keysignal t3 install      # starts at login; log: ~/Library/Logs/keysignal-t3.log
keysignal t3 status
keysignal t3 uninstall
```

The link works once, within 5 minutes. The token it's traded for lasts 30 days
and is stored in `~/Library/Application Support/keysignal/t3.json` (readable only
by you). When it expires or is revoked in T3, the log says so; pair again with a
new link. `--done-hours` changes how long finished threads stay lit.

How it talks to T3: `POST /oauth/token` trades the pairing credential for a bearer
token (scope `orchestration:read`), `POST /api/auth/websocket-ticket` gets a
short-lived ticket, and `ws://…/ws?wsTicket=…` carries Effect RPC JSON messages:
one `orchestration.subscribeShell` request, then a snapshot and thread updates,
each acknowledged with an `Ack`. It follows T3 v0.0.42; when T3 changes this
protocol, this module changes with it. It reconnects on its own when T3 or the
keysignal service restarts, and its signals expire 90 seconds after the bridge
stops.

## Develop

```bash
cd host && uv run --group dev pytest
```
