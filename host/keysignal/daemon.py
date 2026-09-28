"""The background service: keeps the keyboard in sync and serves the local API."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from . import protocol
from .device import Keyboard, KeyboardNotFound
from .state import NoFreeKey, Store

# Lights are leased: the keyboard drops them LEASE_S after the last refresh, so
# they clear on their own if this service stops. Refreshed every REFRESH_S.
LEASE_S = 30
REFRESH_S = 10
TICK_S = 1.0
MAX_BODY = 64 * 1024


class Syncer:
    def __init__(self, store, keyboard, clock=time.monotonic, log=print):
        self.store = store
        self.keyboard = keyboard
        self._clock = clock
        self._log = log
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.pushed = {}  # key -> (level, pattern, rgb) the keyboard currently shows
        self.last_refresh = None
        self.connected = False
        self.firmware = None
        self.last_error = None

    def poke(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def run(self):
        while not self._stop.is_set():
            self.sync_once()
            self._wake.wait(TICK_S)
            self._wake.clear()

    def sync_once(self):
        self.store.purge_expired()
        desired = self.store.desired()
        now = self._clock()
        stale = [k for k in self.pushed if k not in desired]
        if not desired and not stale:
            return
        refresh_due = self.last_refresh is None or now - self.last_refresh >= REFRESH_S
        changed = {k: v for k, v in desired.items() if self.pushed.get(k) != v}
        if not changed and not stale and not refresh_due:
            return

        try:
            with self.keyboard.open() as kb:
                if not self.connected:
                    info = kb.info()
                    if info["protocol"] != protocol.PROTOCOL_VERSION:
                        raise protocol.ProtocolError(
                            f"keyboard speaks key-signal protocol {info['protocol']}, "
                            f"this program speaks {protocol.PROTOCOL_VERSION}"
                        )
                    self.firmware = kb.firmware_version()
                    kb.clear_all()  # drop leftovers from a previous run
                    self.pushed, stale, refresh_due = {}, [], True
                for key in stale:
                    row, col = protocol.KEYS[key]
                    kb.set(row, col, "off", "solid", 0)
                    del self.pushed[key]
                for key, (level, pattern, rgb) in (desired if refresh_due else changed).items():
                    row, col = protocol.KEYS[key]
                    kb.set(row, col, level, pattern, LEASE_S, rgb)
                    self.pushed[key] = (level, pattern, rgb)
            if refresh_due:
                self.last_refresh = now
            self._set_connected(True, None)
        except (KeyboardNotFound, protocol.ProtocolError, OSError, ValueError) as e:
            self.pushed = {}
            self.last_refresh = None
            self._set_connected(False, str(e))

    def _set_connected(self, connected, error):
        if connected != self.connected or error != self.last_error:
            self._log(f"keyboard {'connected' if connected else 'unavailable'}"
                      + (f" ({self.firmware})" if connected else f": {error}"))
        self.connected = connected
        self.last_error = error


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "keysignal"

    def log_message(self, format, *args):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        # Web pages can reach localhost too; browsers always send Origin, local tools don't.
        if self.headers.get("Origin"):
            self._reply(403, {"error": "browser requests are not accepted"})
            return False
        return True

    def _path(self):
        return [unquote(p) for p in self.path.split("?")[0].strip("/").split("/") if p]

    def do_GET(self):
        if not self._allowed():
            return
        store, syncer = self.server.store, self.server.syncer
        path = self._path()
        if path == ["v1", "status"]:
            self._reply(200, {
                "connected": syncer.connected,
                "firmware": syncer.firmware,
                "error": syncer.last_error,
                "signals": len(store),
                "lit": sorted(syncer.pushed),
            })
        elif path == ["v1", "signals"]:
            self._reply(200, {"signals": store.list()})
        elif path == ["v1", "keys"]:
            self._reply(200, {"pool": store.pool, "keys": {k: list(v) for k, v in protocol.KEYS.items()}})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            return
        if self._path() != ["v1", "signals"]:
            return self._reply(404, {"error": "not found"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._reply(415, {"error": "Content-Type must be application/json"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._reply(413, {"error": "body too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            unknown = set(body) - {"source", "id", "level", "key", "pattern", "ttl", "color", "priority", "label"}
            if unknown:
                raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
            signal = self.server.store.upsert(
                source=body.get("source"), id=body.get("id"), level=body.get("level"),
                key=body.get("key", "auto"), pattern=body.get("pattern", "solid"),
                ttl=body.get("ttl"), color=body.get("color"), priority=body.get("priority"),
                label=body.get("label", ""),
            )
        except NoFreeKey as e:
            return self._reply(409, {"error": str(e)})
        except (ValueError, TypeError) as e:
            return self._reply(400, {"error": str(e)})
        self.server.syncer.poke()
        self._reply(200, {"signal": signal} if signal else {"removed": True})

    def do_DELETE(self):
        if not self._allowed():
            return
        path = self._path()
        if path[:2] != ["v1", "signals"] or len(path) > 4:
            return self._reply(404, {"error": "not found"})
        source = path[2] if len(path) > 2 else None
        id = path[3] if len(path) > 3 else None
        removed = self.server.store.remove(source, id)
        self.server.syncer.poke()
        self._reply(200, {"removed": removed})


def make_server(host, port, store, syncer):
    server = ThreadingHTTPServer((host, port), ApiHandler)
    server.daemon_threads = True
    server.store = store
    server.syncer = syncer
    return server


def serve(host="127.0.0.1", port=7780, pool=None, log=print):
    store = Store(pool)
    syncer = Syncer(store, Keyboard(), log=log)
    server = make_server(host, port, store, syncer)
    threading.Thread(target=syncer.run, name="keyboard-sync", daemon=True).start()
    log(f"keysignal listening on http://{host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    finally:
        syncer.stop()
