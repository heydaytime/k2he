"""Key signals wire format. Mirrors features/key_signals.h in the keymap."""

VENDOR_ID = 0x3434
RAW_USAGE_PAGE = 0xFF60
RAW_USAGE = 0x61
REPORT_SIZE = 32
PROTOCOL_VERSION = 1

VIA_CUSTOM_SET_VALUE = 0x07
VIA_CUSTOM_CHANNEL = 0x00
KEYCHRON_GET_FIRMWARE_VERSION = 0xA1

CMD_SET = 0x01
CMD_CLEAR_ALL = 0x02
CMD_INFO = 0x03

STATUS_TEXT = {0: "ok", 1: "bad command", 2: "bad key", 3: "bad level or pattern"}

LEVELS = {"off": 0, "good": 1, "warn": 2, "alert": 3, "custom": 4}
PATTERNS = {"solid": 0, "blink": 1, "pulse": 2}

# Physical keys of the K2 HE ANSI board in LAYOUT_ansi_84 order, with their
# matrix positions. Names follow the keycaps, not the active keymap.
_ROWS = [
    ["esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "print", "del", "light"],
    ["grave", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "minus", "equal", "backspace", "pgup"],
    ["tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "lbracket", "rbracket", "backslash", "pgdn"],
    ["caps", "a", "s", "d", "f", "g", "h", "j", "k", "l", "semicolon", "quote", "enter", "home"],
    ["lshift", "z", "x", "c", "v", "b", "n", "m", "comma", "dot", "slash", "rshift", "up", "end"],
    ["lctrl", "lalt", "lcmd", "space", "rcmd", "fn", "rctrl", "left", "down", "right"],
]
_MATRIX = [
    [(0, c) for c in range(16)],
    [(1, c) for c in range(15)],
    [(2, c) for c in range(15)],
    [(3, c) for c in range(14)],
    [(4, 0)] + [(4, c) for c in range(2, 15)],
    [(5, 0), (5, 1), (5, 2), (5, 6), (5, 9), (5, 10), (5, 11), (5, 12), (5, 13), (5, 14)],
]
KEYS = {name: pos for names, positions in zip(_ROWS, _MATRIX) for name, pos in zip(names, positions)}
ALIASES = {
    "escape": "esc", "`": "grave", "bksp": "backspace", "ret": "enter", "return": "enter",
    "lopt": "lalt", "lgui": "lcmd", "lwin": "lcmd", "ralt": "rcmd", "ropt": "rcmd",
    "prtsc": "print", "delete": "del", "pageup": "pgup", "pagedown": "pgdn",
}


class ProtocolError(Exception):
    pass


def resolve_key(name):
    """Returns (canonical name, (row, col)) for a key name or "row,col"."""
    name = name.strip().lower()
    name = ALIASES.get(name, name)
    if name in KEYS:
        return name, KEYS[name]
    parts = name.split(",")
    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
        pos = (int(parts[0]), int(parts[1]))
        for known, known_pos in KEYS.items():
            if known_pos == pos:
                return known, pos
    raise ValueError(f"unknown key {name!r}")


def _packet(prefix):
    if len(prefix) > REPORT_SIZE:
        raise ValueError("packet too long")
    return bytes(prefix) + bytes(REPORT_SIZE - len(prefix))


def signal_packet(command, args=()):
    return _packet([VIA_CUSTOM_SET_VALUE, VIA_CUSTOM_CHANNEL, command, 0, *args])


def set_packet(row, col, level, pattern, ttl_s, rgb=(0, 0, 0)):
    ttl_s = max(0, min(int(ttl_s), 0xFFFF))
    return signal_packet(
        CMD_SET, [row, col, LEVELS[level], PATTERNS[pattern], ttl_s >> 8, ttl_s & 0xFF, *rgb]
    )


def firmware_version_packet():
    return _packet([KEYCHRON_GET_FIRMWARE_VERSION])


def is_reply_to(sent, reply):
    """Other programs (VIA, Keychron Launcher) share this channel, so only a
    reply echoing our header counts as ours."""
    if len(reply) < 4:
        return False
    if sent[0] == VIA_CUSTOM_SET_VALUE:
        return bytes(reply[:3]) == bytes(sent[:3])
    return reply[0] == sent[0]


def check_status(reply):
    status = reply[3]
    if status != 0:
        raise ProtocolError(f"keyboard rejected command: {STATUS_TEXT.get(status, status)}")


def parse_color(value):
    """Accepts "#rrggbb", "rrggbb" or [r, g, b]."""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        rgb = tuple(int(v) for v in value)
    elif isinstance(value, str):
        text = value.lstrip("#")
        if len(text) != 6:
            raise ValueError(f"bad color {value!r}")
        rgb = tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
    else:
        raise ValueError(f"bad color {value!r}")
    if not all(0 <= v <= 255 for v in rgb):
        raise ValueError(f"bad color {value!r}")
    return rgb
