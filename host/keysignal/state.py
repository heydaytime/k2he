"""Signals from every source, and which one each key shows."""

import threading
import time
from dataclasses import dataclass

from . import protocol

# Default rank per level; the highest rank on a key wins.
LEVEL_RANK = {"good": 1, "custom": 1, "warn": 2, "alert": 3}
DEFAULT_POOL = ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"]


class NoFreeKey(Exception):
    pass


@dataclass
class Signal:
    source: str
    id: str
    key: str
    auto: bool
    level: str
    pattern: str
    color: tuple
    priority: int
    label: str
    expires_at: float  # monotonic seconds, or None for no expiry
    updated_at: float

    def to_json(self, now):
        return {
            "source": self.source,
            "id": self.id,
            "key": self.key,
            "auto": self.auto,
            "level": self.level,
            "pattern": self.pattern,
            "color": "#%02x%02x%02x" % self.color,
            "priority": self.priority,
            "label": self.label,
            "expires_in": None if self.expires_at is None else max(0, round(self.expires_at - now)),
        }


LEVEL_COLORS = {"good": (0, 255, 0), "warn": (255, 170, 0), "alert": (255, 0, 0)}


class Store:
    def __init__(self, pool=None, clock=time.monotonic):
        self.pool = [protocol.resolve_key(k)[0] for k in (pool or DEFAULT_POOL)]
        self._clock = clock
        self._signals = {}  # (source, id) -> Signal
        self._lock = threading.Lock()
        self._seq = 0

    def upsert(self, source, id, level, key="auto", pattern="solid", ttl=None, color=None,
               priority=None, label=""):
        if not (isinstance(source, str) and source and isinstance(id, str) and id):
            raise ValueError("source and id are required strings")
        if not isinstance(key, str):
            raise ValueError("key must be a key name, \"row,col\" or \"auto\"")
        if label is not None and not isinstance(label, str):
            raise ValueError("label must be a string")
        if level not in protocol.LEVELS:
            raise ValueError(f"level must be one of {', '.join(protocol.LEVELS)}")
        if pattern not in protocol.PATTERNS:
            raise ValueError(f"pattern must be one of {', '.join(protocol.PATTERNS)}")
        if level == "custom":
            if color is None:
                raise ValueError("custom level needs a color")
            rgb = protocol.parse_color(color)
        else:
            rgb = LEVEL_COLORS.get(level, (0, 0, 0))
        if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0):
            raise ValueError("ttl must be a positive number of seconds")
        if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)):
            raise ValueError("priority must be an integer")

        with self._lock:
            if level == "off":
                self._signals.pop((source, id), None)
                return None
            now = self._clock()
            existing = self._signals.get((source, id))
            if key == "auto":
                if existing is not None and existing.auto:
                    name, auto = existing.key, True
                else:
                    name, auto = self._free_pool_key(), True
            else:
                name, auto = protocol.resolve_key(key)[0], False
            # Monotonic clocks can repeat a value; the sequence keeps "newest wins" exact.
            self._seq += 1
            signal = Signal(
                source=source, id=id, key=name, auto=auto, level=level, pattern=pattern,
                color=rgb, priority=LEVEL_RANK[level] if priority is None else priority,
                label=label or "", expires_at=None if ttl is None else now + ttl,
                updated_at=self._seq,
            )
            self._signals[(source, id)] = signal
            return signal.to_json(now)

    def _free_pool_key(self):
        used = {s.key for s in self._signals.values()}
        for name in self.pool:
            if name not in used:
                return name
        raise NoFreeKey("every key in the auto pool is in use")

    def remove(self, source=None, id=None):
        with self._lock:
            doomed = [
                k for k in self._signals
                if (source is None or k[0] == source) and (id is None or k[1] == id)
            ]
            for k in doomed:
                del self._signals[k]
            return len(doomed)

    def purge_expired(self):
        with self._lock:
            now = self._clock()
            expired = [k for k, s in self._signals.items() if s.expires_at is not None and s.expires_at <= now]
            for k in expired:
                del self._signals[k]
            return len(expired)

    def list(self):
        with self._lock:
            now = self._clock()
            return [s.to_json(now) for s in sorted(self._signals.values(), key=lambda s: (s.source, s.id))]

    def desired(self):
        """{key name: (level, pattern, rgb)} for the winning signal on each key."""
        with self._lock:
            best = {}
            for s in self._signals.values():
                current = best.get(s.key)
                if current is None or (s.priority, s.updated_at) > (current.priority, current.updated_at):
                    best[s.key] = s
            return {k: (s.level, s.pattern, s.color) for k, s in best.items()}

    def __len__(self):
        with self._lock:
            return len(self._signals)
