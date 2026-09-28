import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

from keysignal import protocol
from keysignal.daemon import LEASE_S, REFRESH_S, Syncer, make_server
from keysignal.device import KeyboardNotFound, Session
from keysignal.state import NoFreeKey, Store


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeKeyboard:
    """Stands in for the USB device; remembers what each key shows."""

    def __init__(self):
        self.present = True
        self.protocol = protocol.PROTOCOL_VERSION
        self.lit = {}  # (row, col) -> (level, pattern, ttl, rgb)
        self.opens = 0
        self.sets = 0

    @contextmanager
    def open(self):
        if not self.present:
            raise KeyboardNotFound("unplugged")
        self.opens += 1
        yield self

    def info(self):
        return {"protocol": self.protocol, "rows": 6, "cols": 16}

    def firmware_version(self):
        return "v1.2.1 test"

    def clear_all(self):
        self.lit.clear()

    def set(self, row, col, level, pattern, ttl_s, rgb=(0, 0, 0)):
        self.sets += 1
        if level == "off":
            self.lit.pop((row, col), None)
        else:
            self.lit[(row, col)] = (level, pattern, ttl_s, rgb)


def pos(name):
    return protocol.KEYS[name]


# --- protocol ---------------------------------------------------------------

def test_key_map_covers_84_distinct_keys():
    assert len(protocol.KEYS) == 84
    assert len(set(protocol.KEYS.values())) == 84
    assert protocol.KEYS["esc"] == (0, 0)
    assert protocol.KEYS["space"] == (5, 6)
    assert protocol.KEYS["z"] == (4, 2)


def test_resolve_key_accepts_aliases_and_positions():
    assert protocol.resolve_key("F5") == ("f5", (0, 5))
    assert protocol.resolve_key("lopt") == ("lalt", (5, 1))
    assert protocol.resolve_key("4,2") == ("z", (4, 2))
    with pytest.raises(ValueError):
        protocol.resolve_key("4,1")  # no key there on ANSI
    with pytest.raises(ValueError):
        protocol.resolve_key("hyper")


def test_set_packet_layout_matches_firmware():
    p = protocol.set_packet(0, 1, "custom", "pulse", 300, (10, 20, 30))
    assert len(p) == 32
    assert list(p[:13]) == [0x07, 0x00, 0x01, 0x00, 0, 1, 4, 2, 0x01, 0x2C, 10, 20, 30]
    assert protocol.set_packet(0, 0, "alert", "solid", 10**6)[8:10] == b"\xff\xff"


def test_reply_matching_ignores_other_programs_traffic():
    sent = protocol.signal_packet(protocol.CMD_INFO)
    assert protocol.is_reply_to(sent, bytes([0x07, 0x00, 0x03, 0x00, 1, 6, 16]))
    assert not protocol.is_reply_to(sent, bytes([0x07, 0x03, 0x03, 0x00]))  # VIA RGB channel
    assert not protocol.is_reply_to(sent, bytes([0x12, 0x00, 0x03, 0x00]))


class FakeHidDevice:
    def __init__(self, replies):
        self.replies = list(replies)
        self.written = []

    def write(self, data):
        self.written.append(bytes(data))

    def read(self, size, timeout_ms):
        return self.replies.pop(0) if self.replies else []


def test_session_skips_unrelated_reports_and_checks_status():
    stray = [0x02] + [0] * 31
    ok = [0x07, 0x00, 0x01, 0x00] + [0] * 28
    dev = FakeHidDevice([stray, ok])
    Session(dev).set(0, 0, "alert", "solid", 30)
    assert dev.written[0][0] == 0x00 and len(dev.written[0]) == 33  # report ID + 32 bytes

    bad = [0x07, 0x00, 0x01, 0x02] + [0] * 28
    with pytest.raises(protocol.ProtocolError, match="bad key"):
        Session(FakeHidDevice([bad])).set(0, 0, "alert", "solid", 30)


def test_parse_color():
    assert protocol.parse_color("#FF8000") == (255, 128, 0)
    assert protocol.parse_color([1, 2, 3]) == (1, 2, 3)
    for bad in ("#fff", "zzzzzz", [1, 2], [0, 0, 256]):
        with pytest.raises(ValueError):
            protocol.parse_color(bad)


# --- state ------------------------------------------------------------------

def test_highest_level_wins_then_newest():
    s = Store(clock=Clock())
    s.upsert("ci", "build", "good", key="f5")
    s.upsert("t3", "thread", "alert", key="f5")
    s.upsert("ci", "lint", "warn", key="f5")
    assert s.desired() == {"f5": ("alert", "solid", (255, 0, 0))}
    s.remove("t3")
    assert s.desired()["f5"][0] == "warn"
    s.upsert("ci", "deploy", "custom", key="f5", color="#0000ff", priority=2)
    assert s.desired()["f5"][2] == (0, 0, 255)  # same rank as warn, newer


def test_auto_keys_are_distinct_and_sticky():
    s = Store(pool=["f1", "f2"], clock=Clock())
    a = s.upsert("t3", "a", "warn")
    b = s.upsert("t3", "b", "good")
    assert (a["key"], b["key"]) == ("f1", "f2")
    assert s.upsert("t3", "a", "alert")["key"] == "f1"  # update keeps its key
    with pytest.raises(NoFreeKey):
        s.upsert("t3", "c", "good")
    s.upsert("t3", "a", "off")
    assert s.upsert("t3", "c", "good")["key"] == "f1"


def test_auto_pool_skips_keys_taken_explicitly():
    s = Store(pool=["f1", "f2"], clock=Clock())
    s.upsert("ci", "x", "good", key="f1")
    assert s.upsert("t3", "a", "warn")["key"] == "f2"


def test_ttl_expiry():
    clock = Clock()
    s = Store(clock=clock)
    s.upsert("ci", "x", "alert", key="esc", ttl=5)
    clock.now += 4.9
    assert s.purge_expired() == 0
    clock.now += 0.2
    assert s.purge_expired() == 1 and s.desired() == {}


@pytest.mark.parametrize("kwargs", [
    {"level": "purple"},
    {"level": "good", "pattern": "strobe"},
    {"level": "custom"},
    {"level": "good", "ttl": 0},
    {"level": "good", "ttl": True},
    {"level": "good", "key": "hyper"},
    {"level": "good", "key": 5},
    {"level": "good", "priority": "high"},
])
def test_invalid_signals_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Store().upsert("ci", "x", **kwargs)


# --- syncer -----------------------------------------------------------------

def make_syncer():
    clock = Clock()
    store = Store(clock=clock)
    kb = FakeKeyboard()
    return store, kb, Syncer(store, kb, clock=clock, log=lambda _: None), clock


def test_idle_service_never_touches_the_keyboard():
    store, kb, syncer, clock = make_syncer()
    for _ in range(3):
        syncer.sync_once()
        clock.now += REFRESH_S
    assert kb.opens == 0


def test_pushes_changes_and_turns_off_removed_keys():
    store, kb, syncer, clock = make_syncer()
    kb.lit[pos("space")] = ("alert", "solid", 30, (255, 0, 0))  # left over from an old run
    store.upsert("ci", "x", "alert", key="esc", pattern="pulse")
    syncer.sync_once()
    assert syncer.connected and syncer.firmware == "v1.2.1 test"
    assert kb.lit == {pos("esc"): ("alert", "pulse", LEASE_S, (255, 0, 0))}

    sets = kb.sets
    syncer.sync_once()  # nothing changed, lease still fresh
    assert kb.sets == sets

    store.remove("ci")
    syncer.sync_once()
    assert kb.lit == {} and syncer.pushed == {}


def test_lease_is_refreshed_before_it_runs_out():
    store, kb, syncer, clock = make_syncer()
    store.upsert("ci", "x", "good", key="f1")
    syncer.sync_once()
    assert REFRESH_S < LEASE_S
    clock.now += REFRESH_S
    kb.lit.clear()  # as if the lease had lapsed on the keyboard
    syncer.sync_once()
    assert pos("f1") in kb.lit


def test_resyncs_after_keyboard_comes_back():
    store, kb, syncer, clock = make_syncer()
    store.upsert("ci", "x", "warn", key="f2")
    kb.present = False
    syncer.sync_once()
    assert not syncer.connected and "unplugged" in syncer.last_error
    kb.present = True
    syncer.sync_once()
    assert syncer.connected and pos("f2") in kb.lit


def test_expired_signal_turns_key_off():
    store, kb, syncer, clock = make_syncer()
    store.upsert("ci", "x", "alert", key="f3", ttl=3)
    syncer.sync_once()
    clock.now += 3
    syncer.sync_once()
    assert kb.lit == {}


def test_refuses_firmware_with_other_protocol():
    store, kb, syncer, clock = make_syncer()
    kb.protocol = 9
    store.upsert("ci", "x", "good", key="f1")
    syncer.sync_once()
    assert not syncer.connected and "protocol 9" in syncer.last_error
    assert kb.lit == {}


# --- HTTP API ---------------------------------------------------------------

@pytest.fixture
def api():
    store, kb, syncer, clock = make_syncer()
    server = make_server("127.0.0.1", 0, store, syncer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    yield call, store, syncer
    server.shutdown()
    server.server_close()


def test_api_set_list_clear(api):
    call, store, syncer = api
    code, body = call("POST", "/v1/signals", {"source": "t3", "id": "thread/1", "level": "alert"})
    assert code == 200 and body["signal"]["key"] == "f1"
    code, body = call("GET", "/v1/signals")
    assert [s["id"] for s in body["signals"]] == ["thread/1"]
    code, body = call("DELETE", "/v1/signals/t3/thread%2F1")
    assert body == {"removed": 1}


def test_api_off_level_removes(api):
    call, store, syncer = api
    call("POST", "/v1/signals", {"source": "ci", "id": "x", "level": "good", "key": "f9"})
    code, body = call("POST", "/v1/signals", {"source": "ci", "id": "x", "level": "off"})
    assert (code, body) == (200, {"removed": True}) and len(store) == 0


def test_api_rejects_bad_input(api):
    call, store, syncer = api
    assert call("POST", "/v1/signals", {"source": "ci", "id": "x", "level": "nope"})[0] == 400
    assert call("POST", "/v1/signals", {"source": "ci", "id": "x", "level": "good", "colour": "#fff"})[0] == 400
    assert call("POST", "/v1/signals", ["not", "an", "object"])[0] == 400
    assert call("GET", "/v1/nope")[0] == 404


def test_api_reports_full_pool(api):
    call, store, syncer = api
    for i in range(12):
        assert call("POST", "/v1/signals", {"source": "t3", "id": str(i), "level": "good"})[0] == 200
    code, body = call("POST", "/v1/signals", {"source": "t3", "id": "13", "level": "good"})
    assert code == 409 and "pool" in body["error"]


def test_api_blocks_browsers(api):
    call, store, syncer = api
    code, _ = call("POST", "/v1/signals", {"source": "evil", "id": "x", "level": "alert"},
                   headers={"Origin": "https://example.com"})
    assert code == 403 and len(store) == 0


def test_api_status(api):
    call, store, syncer = api
    call("POST", "/v1/signals", {"source": "ci", "id": "x", "level": "good", "key": "esc"})
    syncer.sync_once()
    code, body = call("GET", "/v1/status")
    assert body["connected"] and body["lit"] == ["esc"] and body["signals"] == 1
