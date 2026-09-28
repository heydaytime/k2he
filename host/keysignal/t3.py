"""T3 Code bridge: every T3 thread that is working, needs you, or just finished lights a key.

It pairs with the T3 Code server as a read-only client, subscribes to the same live
thread list the sidebar shows, and turns each thread's state into a keysignal signal
(source "t3", id = thread id, key = auto so each thread keeps its own key).
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

SOURCE = "t3"
SCOPE = "orchestration:read"
CLIENT_LABEL = "K2 HE keyboard"
TOKEN_PATH = Path.home() / "Library" / "Application Support" / "keysignal" / "t3.json"
DONE_HOURS = 12
# Signals are re-sent every RESYNC_S with a SIGNAL_TTL_S expiry, so they clear
# themselves if this bridge dies without cleaning up.
RESYNC_S = 30
SIGNAL_TTL_S = 90
PING_S = 20
PONG_TIMEOUT_S = 60
LABEL_MAX = 60


class NotPaired(Exception):
    pass


class AuthRejected(Exception):
    """T3 refused the stored token: it expired or was revoked. Pair again."""


class T3Unavailable(Exception):
    pass


class StreamEnded(Exception):
    pass


class ServiceUnavailable(Exception):
    pass


class NoFreeKey(Exception):
    pass


# ---- talking to T3 over HTTP ------------------------------------------------

def t3_home():
    return Path(os.environ.get("T3CODE_HOME") or Path.home() / ".t3")


def server_origin(home=None):
    """The running T3 server's http origin, from the runtime file it writes at startup."""
    path = (home or t3_home()) / "userdata" / "server-runtime.json"
    try:
        runtime = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise T3Unavailable(f"T3 Code server not found ({path}: {e})")
    origin = runtime.get("origin")
    if not origin:
        raise T3Unavailable(f"{path} has no origin")
    return origin.rstrip("/")


def pairing_credential(link):
    """The one-time credential from a pairing link (…/pair#token=X), or the bare credential."""
    link = link.strip()
    if "://" not in link:
        return link
    url = urllib.parse.urlsplit(link)
    for params in (url.fragment, url.query):
        token = urllib.parse.parse_qs(params).get("token", [""])[0].strip()
        if token:
            return token
    raise ValueError("that link has no pairing token in it")


def _t3_error(e):
    try:
        body = json.load(e)
        return body.get("reason") or body.get("message") or body.get("code") or e.reason
    except ValueError:
        return e.reason


def exchange(origin, credential, label=CLIENT_LABEL):
    """Trade a one-time pairing credential for a read-only access token."""
    form = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": credential,
        "subject_token_type": "urn:t3:params:oauth:token-type:environment-bootstrap",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "scope": SCOPE,
        "client_label": label,
        "client_device_type": "bot",
        "client_os": "macOS",
    }).encode()
    req = urllib.request.Request(origin + "/oauth/token", data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as e:
        raise AuthRejected(f"T3 refused the pairing credential ({_t3_error(e)}); make a new link")
    except urllib.error.URLError as e:
        raise T3Unavailable(f"T3 Code server not reachable at {origin}: {e.reason}")
    return {
        "access_token": result["access_token"],
        "scope": result["scope"],
        "expires_at": time.time() + result["expires_in"],
    }


def save_token(token, path=TOKEN_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(token, f)
    os.chmod(path, 0o600)


def load_token(path=TOKEN_PATH):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise NotPaired("not paired with T3 Code yet: run `keysignal t3 pair '<pairing link>'`")


def websocket_ticket(origin, access_token):
    req = urllib.request.Request(origin + "/api/auth/websocket-ticket", data=b"", method="POST")
    req.add_header("Authorization", "Bearer " + access_token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)["ticket"]
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthRejected(f"T3 rejected the stored token ({_t3_error(e)}); pair again")
        raise T3Unavailable(f"T3 websocket ticket failed: HTTP {e.code} {_t3_error(e)}")
    except urllib.error.URLError as e:
        raise T3Unavailable(f"T3 Code server not reachable at {origin}: {e.reason}")


# ---- thread state -> key signal ---------------------------------------------

def _ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def thread_state(thread, now, done_window=DONE_HOURS * 3600):
    """(level, pattern, what) for one T3 thread, or None when it should not be lit.

    Follows the order of T3's own sidebar status: needs-you first, then working,
    then a recent finish.
    """
    if thread.get("deletedAt") or thread.get("archivedAt") or thread.get("settledAt"):
        return None
    session = thread.get("session") or {}
    status = session.get("status")
    turn = thread.get("latestTurn") or {}

    if thread.get("hasPendingApprovals"):
        return ("alert", "blink", "needs approval")
    if thread.get("hasPendingUserInput"):
        return ("alert", "blink", "awaiting input")
    if status in ("running", "starting"):
        return ("warn", "pulse", "working")
    if (thread.get("interactionMode") == "plan" and thread.get("hasActionableProposedPlan")
            and turn.get("state") != "running"):
        return ("alert", "blink", "plan ready")
    if thread.get("backgroundLiveness") in ("working", "monitoring"):
        return ("warn", "pulse", "working in background")

    snoozed_until = _ts(thread.get("snoozedUntil"))
    if snoozed_until is not None and snoozed_until > now:
        return None
    if turn.get("state") == "error" or status == "error":
        finished = _ts(turn.get("completedAt")) or _ts(session.get("updatedAt"))
        what = ("alert", "solid", "failed")
    elif turn.get("state") == "completed":
        finished = _ts(turn.get("completedAt"))
        what = ("good", "solid", "done")
    else:
        return None
    if finished is None or now - finished > done_window:
        return None
    return what


_URGENCY = {"alert": 0, "warn": 1, "good": 2}


def desired_signals(threads, now, done_window=DONE_HOURS * 3600):
    """{thread id: signal body} for every thread that should be lit, most urgent first."""
    lit = []
    for thread in threads.values():
        state = thread_state(thread, now, done_window)
        if state is None:
            continue
        level, pattern, what = state
        title = thread.get("title") or thread["id"]
        if len(title) > LABEL_MAX:
            title = title[:LABEL_MAX - 1] + "…"
        lit.append((_URGENCY[level], thread.get("createdAt") or "", thread["id"], {
            "level": level, "pattern": pattern, "label": f"{title} ({what})",
        }))
    lit.sort(key=lambda item: item[:3])
    return {tid: body for _, _, tid, body in lit}


# ---- pushing signals to the keysignal service -------------------------------

def _keysignal_url():
    return os.environ.get("KEYSIGNAL_URL", "http://127.0.0.1:7780").rstrip("/")


def keysignal_call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(_keysignal_url() + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise NoFreeKey(json.load(e).get("error", "no free key"))
        raise ServiceUnavailable(f"keysignal answered HTTP {e.code}: {json.load(e).get('error', e.reason)}")
    except urllib.error.URLError as e:
        raise ServiceUnavailable(f"keysignal service not reachable at {_keysignal_url()}: {e.reason}")


class Reconciler:
    """Keeps the keysignal service's "t3" signals equal to the desired set."""

    def __init__(self, call=keysignal_call, log=print):
        self._call = call
        self._log = log
        self.posted = {}      # thread id -> body last accepted by the service
        self.waiting = set()  # thread ids refused because every auto key is taken
        self._service_error = None

    def _path(self, id=None):
        path = "/v1/signals/" + urllib.parse.quote(SOURCE, safe="")
        return path if id is None else path + "/" + urllib.parse.quote(id, safe="")

    def apply(self, desired, resend=False):
        """Remove what is no longer wanted, then send what changed (everything when resend)."""
        try:
            for id in [id for id in self.posted if id not in desired]:
                self._call("DELETE", self._path(id))
                del self.posted[id]
            self.waiting &= set(desired)
            for id, body in desired.items():
                if not resend and self.posted.get(id) == body:
                    continue
                try:
                    self._call("POST", "/v1/signals", {
                        "source": SOURCE, "id": id, "key": "auto", "ttl": SIGNAL_TTL_S, **body,
                    })
                except NoFreeKey:
                    self.posted.pop(id, None)
                    if id not in self.waiting:
                        self.waiting.add(id)
                        self._log(f"no free key for {body['label']}; waiting for one")
                    continue
                self.posted[id] = body
                self.waiting.discard(id)
            self._service_ok()
        except ServiceUnavailable as e:
            # Forget what was sent so everything goes out again once it is back.
            self.posted = {}
            self._service_failed(str(e))

    def clear(self):
        self.posted = {}
        self.waiting = set()
        try:
            self._call("DELETE", self._path())
            self._service_ok()
        except ServiceUnavailable as e:
            self._service_failed(str(e))

    def _service_ok(self):
        if self._service_error is not None:
            self._log("keysignal service reachable again")
        self._service_error = None

    def _service_failed(self, error):
        if error != self._service_error:
            self._log(error)
        self._service_error = error


# ---- the live subscription --------------------------------------------------

SUBSCRIBE_ID = "1"


class Shell:
    """T3's thread list as the shell stream describes it."""

    def __init__(self):
        self.threads = {}

    def handle(self, item):
        kind = item.get("kind")
        if kind == "snapshot":
            self.threads = {t["id"]: t for t in item["snapshot"]["threads"]}
        elif kind == "thread-upserted":
            self.threads[item["thread"]["id"]] = item["thread"]
        elif kind == "thread-removed":
            self.threads.pop(item["threadId"], None)


def _describe_exit(exit):
    if exit.get("_tag") == "Success":
        return "T3 ended the thread subscription"
    parts = []
    for cause in exit.get("cause", []):
        detail = cause.get("error") or cause.get("defect") or cause
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("_tag") or json.dumps(detail)
        parts.append(str(detail))
    return "T3 subscription failed: " + ("; ".join(parts) or json.dumps(exit))


def follow_shell(ws, on_change, on_tick, clock=time.monotonic):
    """Subscribe to T3's thread list on an open socket and report every change until it ends."""
    shell = Shell()
    ws.send(json.dumps({
        "_tag": "Request", "id": SUBSCRIBE_ID, "tag": "orchestration.subscribeShell",
        "payload": {}, "headers": [],
    }))
    last_ping = last_pong = clock()
    while True:
        try:
            raw = ws.recv(timeout=1)
        except TimeoutError:
            raw = None
        now = clock()
        if raw is not None:
            last_pong = now  # any traffic proves the socket is alive
            messages = json.loads(raw)
            for message in messages if isinstance(messages, list) else [messages]:
                tag = message.get("_tag")
                if tag == "Chunk" and str(message.get("requestId")) == SUBSCRIBE_ID:
                    for item in message["values"]:
                        shell.handle(item)
                    # The server sends the next chunk only after this ack.
                    ws.send(json.dumps({"_tag": "Ack", "requestId": SUBSCRIBE_ID}))
                    on_change(shell.threads)
                elif tag == "Exit" and str(message.get("requestId")) == SUBSCRIBE_ID:
                    raise StreamEnded(_describe_exit(message["exit"]))
                elif tag in ("Defect", "ClientProtocolError"):
                    raise StreamEnded(f"T3 protocol error: {json.dumps(message)[:300]}")
        if now - last_pong > PONG_TIMEOUT_S:
            raise StreamEnded("T3 stopped answering")
        if now - last_ping >= PING_S:
            ws.send(json.dumps({"_tag": "Ping"}))
            last_ping = now
        on_tick(shell.threads)


# ---- the bridge -------------------------------------------------------------

def _connect(origin, ticket):
    from websockets.sync.client import connect

    ws_origin = "ws" + origin[len("http"):] if origin.startswith("http") else origin
    query = urllib.parse.urlencode({"wsTicket": ticket})
    return connect(f"{ws_origin}/ws?{query}", open_timeout=10, max_size=None)


def run(done_hours=DONE_HOURS, log=print, token_path=TOKEN_PATH, home=None):
    """Keep T3's threads mirrored onto the keyboard until stopped. Reconnects forever."""
    import websockets

    reconciler = Reconciler(log=log)
    done_window = done_hours * 3600
    backoff = 1
    last_problem = None

    def problem(message, wait):
        nonlocal last_problem
        if message != last_problem:
            log(message)
        last_problem = message
        time.sleep(wait)

    reconciler.clear()  # leftovers from a previous run
    try:
        while True:
            try:
                token = load_token(token_path)
                origin = server_origin(home)
                ticket = websocket_ticket(origin, token["access_token"])
                with _connect(origin, ticket) as ws:
                    log(f"following T3 Code at {origin}")
                    last_problem = None
                    backoff = 1
                    last_resend = [time.monotonic()]

                    def on_change(threads):
                        reconciler.apply(desired_signals(threads, time.time(), done_window))

                    def on_tick(threads):
                        # Re-send everything now and then: it renews the signal expiry,
                        # restores lights after a keysignal restart, and ages out old "done".
                        if time.monotonic() - last_resend[0] >= RESYNC_S:
                            last_resend[0] = time.monotonic()
                            reconciler.apply(desired_signals(threads, time.time(), done_window), resend=True)

                    follow_shell(ws, on_change, on_tick)
            except (NotPaired, AuthRejected) as e:
                reconciler.clear()
                problem(str(e), 60)
            except (T3Unavailable, StreamEnded, OSError, websockets.exceptions.WebSocketException) as e:
                reconciler.clear()
                problem(f"T3 connection lost: {e}" if not isinstance(e, T3Unavailable) else str(e), backoff)
                backoff = min(backoff * 2, 30)
    finally:
        reconciler.clear()
