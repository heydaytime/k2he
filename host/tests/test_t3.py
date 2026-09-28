import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from websockets.sync.server import serve

from keysignal import t3

NOW = 1_800_000_000.0


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def thread(id="t1", **fields):
    base = {
        "id": id, "title": "Fix login", "createdAt": iso(NOW - 3600),
        "deletedAt": None, "archivedAt": None, "settledAt": None,
        "session": {"status": "ready", "updatedAt": iso(NOW - 60)},
        "latestTurn": {"state": "completed", "completedAt": iso(NOW - 60)},
        "hasPendingApprovals": False, "hasPendingUserInput": False,
        "hasActionableProposedPlan": False, "interactionMode": "default",
    }
    base.update(fields)
    return base


# ---- pairing ------------------------------------------------------------------

def test_pairing_credential_from_links():
    assert t3.pairing_credential("http://127.0.0.1:3773/pair#token=abc123") == "abc123"
    assert t3.pairing_credential("https://app.t3.codes/pair?host=x&label=y#token=abc") == "abc"
    assert t3.pairing_credential("http://127.0.0.1:3773/pair?token=q1") == "q1"
    assert t3.pairing_credential("  rawtoken \n") == "rawtoken"
    with pytest.raises(ValueError):
        t3.pairing_credential("http://127.0.0.1:3773/pair")


def test_server_origin_from_runtime_file(tmp_path):
    (tmp_path / "userdata").mkdir()
    (tmp_path / "userdata" / "server-runtime.json").write_text(
        json.dumps({"origin": "http://127.0.0.1:3773/", "port": 3773}))
    assert t3.server_origin(tmp_path) == "http://127.0.0.1:3773"
    with pytest.raises(t3.T3Unavailable):
        t3.server_origin(tmp_path / "missing")


class FakeT3Http(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/oauth/token":
            form = dict(urllib.parse.parse_qsl(body.decode()))
            self.server.form = form
            if form["subject_token"] != "good":
                return self._reply(401, {"code": "auth_invalid", "reason": "invalid_credential"})
            return self._reply(200, {"access_token": "tok", "issued_token_type": form["requested_token_type"],
                                     "token_type": "Bearer", "expires_in": 30 * 86400, "scope": form["scope"]})
        if self.path == "/api/auth/websocket-ticket":
            if self.headers.get("Authorization") != "Bearer tok":
                return self._reply(401, {"code": "auth_invalid", "reason": "invalid_credential"})
            return self._reply(200, {"ticket": "tick", "expiresAt": "2030-01-01T00:00:00.000Z"})
        self._reply(404, {})


@pytest.fixture
def t3_http():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeT3Http)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_exchange_asks_for_read_only_token(t3_http):
    server, origin = t3_http
    token = t3.exchange(origin, "good")
    assert token["access_token"] == "tok" and token["scope"] == "orchestration:read"
    assert token["expires_at"] > time.time() + 29 * 86400
    assert server.form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert server.form["subject_token_type"] == "urn:t3:params:oauth:token-type:environment-bootstrap"
    assert server.form["scope"] == "orchestration:read"
    assert server.form["client_label"] == "K2 HE keyboard"
    with pytest.raises(t3.AuthRejected, match="invalid_credential"):
        t3.exchange(origin, "used-already")


def test_websocket_ticket(t3_http):
    _, origin = t3_http
    assert t3.websocket_ticket(origin, "tok") == "tick"
    with pytest.raises(t3.AuthRejected):
        t3.websocket_ticket(origin, "revoked")
    with pytest.raises(t3.T3Unavailable):
        t3.websocket_ticket("http://127.0.0.1:1", "tok")


def test_token_file_is_private(tmp_path):
    path = tmp_path / "sub" / "t3.json"
    t3.save_token({"access_token": "tok", "scope": "orchestration:read", "expires_at": 1.0}, path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert t3.load_token(path)["access_token"] == "tok"
    with pytest.raises(t3.NotPaired):
        t3.load_token(tmp_path / "nope.json")


# ---- thread state -> signal ---------------------------------------------------

@pytest.mark.parametrize("fields, expected", [
    ({}, ("good", "solid", "done")),
    ({"hasPendingApprovals": True}, ("alert", "blink", "needs approval")),
    ({"hasPendingUserInput": True}, ("alert", "blink", "awaiting input")),
    ({"session": {"status": "running"}, "latestTurn": {"state": "running", "completedAt": None}},
     ("warn", "pulse", "working")),
    ({"session": {"status": "starting"}, "latestTurn": None}, ("warn", "pulse", "working")),
    ({"interactionMode": "plan", "hasActionableProposedPlan": True}, ("alert", "blink", "plan ready")),
    ({"backgroundLiveness": "working"}, ("warn", "pulse", "working in background")),
    ({"latestTurn": {"state": "error", "completedAt": iso(NOW - 60)}}, ("alert", "solid", "failed")),
    ({"session": {"status": "error", "updatedAt": iso(NOW - 60)}, "latestTurn": None},
     ("alert", "solid", "failed")),
    ({"latestTurn": {"state": "interrupted", "completedAt": iso(NOW - 60)}}, None),
    ({"latestTurn": {"state": "completed", "completedAt": iso(NOW - 13 * 3600)}}, None),
    ({"latestTurn": None, "session": None}, None),
    ({"settledAt": iso(NOW)}, None),
    ({"archivedAt": iso(NOW)}, None),
    ({"deletedAt": iso(NOW)}, None),
    ({"snoozedUntil": iso(NOW + 600)}, None),
    ({"snoozedUntil": iso(NOW - 600)}, ("good", "solid", "done")),
    # A snoozed thread still lights when it needs you.
    ({"snoozedUntil": iso(NOW + 600), "hasPendingUserInput": True}, ("alert", "blink", "awaiting input")),
    # Needing you outranks working.
    ({"session": {"status": "running"}, "hasPendingApprovals": True}, ("alert", "blink", "needs approval")),
])
def test_thread_state(fields, expected):
    assert t3.thread_state(thread(**fields), NOW) == expected


def test_desired_signals_most_urgent_first_with_titles():
    threads = {
        "done": thread("done"),
        "busy": thread("busy", title="Refactor", session={"status": "running"}),
        "ask": thread("ask", title="x" * 80, hasPendingUserInput=True),
        "old": thread("old", latestTurn={"state": "completed", "completedAt": iso(NOW - 86400)}),
    }
    desired = t3.desired_signals(threads, NOW)
    assert list(desired) == ["ask", "busy", "done"]
    assert desired["busy"] == {"level": "warn", "pattern": "pulse", "label": "Refactor (working)"}
    assert desired["ask"]["label"] == "x" * 59 + "… (awaiting input)"
    assert t3.desired_signals(threads, NOW, done_window=2 * 86400).keys() == {"ask", "busy", "done", "old"}


# ---- reconciling with the keysignal service -------------------------------------

class FakeService:
    def __init__(self, pool=2):
        self.signals = {}
        self.pool = pool
        self.calls = []
        self.up = True

    def __call__(self, method, path, body=None):
        if not self.up:
            raise t3.ServiceUnavailable("keysignal service not reachable")
        self.calls.append((method, path, body))
        if method == "POST":
            if body["id"] not in self.signals and len(self.signals) >= self.pool:
                raise t3.NoFreeKey("every key in the auto pool is in use")
            self.signals[body["id"]] = body
        elif method == "DELETE":
            parts = [urllib.parse.unquote(p) for p in path.split("/")[3:]]
            if len(parts) == 2:
                self.signals.pop(parts[1], None)
            else:
                self.signals.clear()
        return {}


def sig(level="good", label="a"):
    return {"level": level, "pattern": "solid", "label": label}


def test_reconciler_sends_changes_only():
    service, logs = FakeService(pool=5), []
    r = t3.Reconciler(call=service, log=logs.append)
    r.apply({"a": sig(), "b/1": sig("warn")})
    assert service.signals["a"] == {"source": "t3", "id": "a", "key": "auto", "ttl": t3.SIGNAL_TTL_S, **sig()}
    assert "b/1" in service.signals
    service.calls.clear()
    r.apply({"a": sig(), "b/1": sig("warn")})
    assert service.calls == []
    r.apply({"a": sig("alert")})
    assert [c[0] for c in service.calls] == ["DELETE", "POST"]
    assert service.calls[0][1] == "/v1/signals/t3/b%2F1"
    assert service.signals == {"a": {"source": "t3", "id": "a", "key": "auto", "ttl": t3.SIGNAL_TTL_S,
                                     **sig("alert")}}
    service.calls.clear()
    r.apply({"a": sig("alert")}, resend=True)
    assert [c[0] for c in service.calls] == ["POST"]


def test_reconciler_waits_for_a_free_key_and_logs_once():
    service, logs = FakeService(pool=1), []
    r = t3.Reconciler(call=service, log=logs.append)
    r.apply({"a": sig(label="A"), "b": sig(label="B")})
    r.apply({"a": sig(label="A"), "b": sig(label="B")}, resend=True)
    assert set(service.signals) == {"a"}
    assert logs == ["no free key for B; waiting for one"]
    r.apply({"b": sig(label="B")})  # a finished, its key frees up
    assert set(service.signals) == {"b"} and r.waiting == set()


def test_reconciler_resends_everything_after_service_outage():
    service, logs = FakeService(pool=5), []
    r = t3.Reconciler(call=service, log=logs.append)
    r.apply({"a": sig()})
    service.up = False
    r.apply({"a": sig(), "b": sig()})
    r.apply({"a": sig(), "b": sig()})
    assert logs == ["keysignal service not reachable"]
    service.up, service.signals = True, {}  # the service restarted empty
    r.apply({"a": sig(), "b": sig()})
    assert set(service.signals) == {"a", "b"}
    assert logs[-1] == "keysignal service reachable again"


def test_reconciler_clear_removes_the_whole_source():
    service = FakeService(pool=5)
    r = t3.Reconciler(call=service, log=lambda m: None)
    r.apply({"a": sig(), "b": sig()})
    r.clear()
    assert service.signals == {} and r.posted == {}
    assert service.calls[-1][:2] == ("DELETE", "/v1/signals/t3")


# ---- the RPC stream over a real websocket ----------------------------------------

def fake_t3_ws(script):
    """A websocket server that answers a subscribeShell request with `script`'s chunks."""
    received = []

    def handler(ws):
        request = json.loads(ws.recv())
        received.append(request)
        for message in script(request["id"]):
            ws.send(json.dumps(message))
            if message["_tag"] == "Chunk":
                ack = json.loads(ws.recv())
                received.append(ack)
        time.sleep(0.2)

    server = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def test_follow_shell_applies_snapshot_and_events_and_acks():
    snapshot = {"snapshotSequence": 5, "projects": [], "updatedAt": iso(NOW),
                "threads": [thread("a"), thread("b", session={"status": "running"})]}

    def script(request_id):
        yield {"_tag": "Chunk", "requestId": request_id,
               "values": [{"kind": "snapshot", "snapshot": snapshot}]}
        yield {"_tag": "Chunk", "requestId": request_id, "values": [
            {"kind": "thread-upserted", "sequence": 6, "thread": thread("c", hasPendingApprovals=True)},
            {"kind": "thread-removed", "sequence": 7, "threadId": "a"},
            {"kind": "project-upserted", "sequence": 8, "project": {"id": "p"}},
        ]}
        yield {"_tag": "Exit", "requestId": request_id, "exit": {"_tag": "Failure", "cause": [
            {"_tag": "Fail", "error": {"_tag": "EnvironmentAuthorizationError", "message": "scope missing"}}]}}

    server, received = fake_t3_ws(script)
    seen = []
    from websockets.sync.client import connect
    with connect(f"ws://127.0.0.1:{server.socket.getsockname()[1]}/ws") as ws:
        with pytest.raises(t3.StreamEnded, match="scope missing"):
            t3.follow_shell(ws, lambda threads: seen.append(sorted(threads)), lambda threads: None)
    server.shutdown()

    request = received[0]
    assert request["_tag"] == "Request" and request["tag"] == "orchestration.subscribeShell"
    assert request["payload"] == {} and request["headers"] == []
    assert received[1:] == [{"_tag": "Ack", "requestId": request["id"]}] * 2
    assert seen == [["a", "b"], ["b", "c"]]


class SilentWs:
    """A socket that never answers; records what was sent."""

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(json.loads(data))

    def recv(self, timeout=None):
        raise TimeoutError


def test_follow_shell_pings_and_notices_silence():
    ws = SilentWs()
    times = iter([0, 1, t3.PING_S, t3.PING_S + 1, t3.PONG_TIMEOUT_S + 1])
    with pytest.raises(t3.StreamEnded, match="stopped answering"):
        t3.follow_shell(ws, lambda threads: None, lambda threads: None, clock=lambda: next(times))
    assert [m["_tag"] for m in ws.sent] == ["Request", "Ping"]
