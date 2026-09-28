"""keysignal: color keys on the Keychron K2 HE from anything on this Mac."""

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import protocol

DEFAULT_PORT = 7780
LAUNCHD_LABEL = "dev.heydaytime.keysignal"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "keysignal.log"


def _base_url():
    return os.environ.get("KEYSIGNAL_URL", f"http://127.0.0.1:{DEFAULT_PORT}").rstrip("/")


def _call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(_base_url() + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"keysignal: {json.load(e).get('error', e.reason)}")
    except urllib.error.URLError:
        sys.exit(f"keysignal: service not reachable at {_base_url()} (start it with `keysignal serve` or `keysignal install`)")


def _quote(part):
    return urllib.request.quote(part, safe="")


def cmd_serve(args):
    from .daemon import serve

    pool = args.pool.split(",") if args.pool else None
    serve(args.host, args.port, pool, log=lambda msg: print(msg, flush=True))


def cmd_set(args):
    body = {
        "source": args.source,
        "id": args.id or args.key,
        "key": args.key,
        "level": args.level,
        "pattern": args.pattern,
    }
    for field in ("ttl", "color", "priority", "label"):
        if getattr(args, field) is not None:
            body[field] = getattr(args, field)
    result = _call("POST", "/v1/signals", body)
    if "signal" in result:
        s = result["signal"]
        print(f"{s['key']}: {s['level']} {s['pattern']} ({s['source']}/{s['id']})")
    else:
        print("cleared")


def cmd_clear(args):
    if args.id and not args.source:
        sys.exit("keysignal: --id needs --source")
    path = "/v1/signals"
    if args.source:
        path += "/" + _quote(args.source)
        if args.id:
            path += "/" + _quote(args.id)
    print(f"removed {_call('DELETE', path)['removed']}")


def cmd_list(args):
    signals = _call("GET", "/v1/signals")["signals"]
    if not signals:
        print("no signals")
    for s in signals:
        expiry = "" if s["expires_in"] is None else f"  expires in {s['expires_in']}s"
        label = f"  {s['label']}" if s["label"] else ""
        print(f"{s['key']:<10} {s['level']:<6} {s['pattern']:<6} {s['source']}/{s['id']}{label}{expiry}")


def cmd_status(args):
    s = _call("GET", "/v1/status")
    if s["connected"]:
        print(f"keyboard: connected ({s['firmware']})")
    else:
        print(f"keyboard: not reachable{': ' + s['error'] if s['error'] else ' yet (nothing to show)'}")
    print(f"signals:  {s['signals']}, lit keys: {', '.join(s['lit']) or 'none'}")


def cmd_keys(args):
    keys = _call("GET", "/v1/keys")
    print("auto pool: " + " ".join(keys["pool"]))
    print("keys:      " + " ".join(keys["keys"]))


def cmd_install(args):
    exe = shutil.which("keysignal") or os.path.abspath(sys.argv[0])
    program = [exe, "serve", "--port", str(args.port)]
    if args.pool:
        program += ["--pool", args.pool]
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump({
            "Label": LAUNCHD_LABEL,
            "ProgramArguments": program,
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(LOG_PATH),
            "StandardErrorPath": str(LOG_PATH),
        }, f)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], check=True)
    print(f"installed {PLIST_PATH}\nrunning `{' '.join(program)}`, log: {LOG_PATH}")


def cmd_uninstall(args):
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], capture_output=True)
    PLIST_PATH.unlink(missing_ok=True)
    print("uninstalled")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="keysignal", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the service in the foreground")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--pool", help="comma-separated keys handed out for key=auto (default f1..f12)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("set", help="light a key")
    p.add_argument("key", help='key name (see `keysignal keys`), "row,col", or "auto"')
    p.add_argument("level", choices=list(protocol.LEVELS))
    p.add_argument("--pattern", choices=list(protocol.PATTERNS), default="solid")
    p.add_argument("--ttl", type=float, help="seconds until it turns off by itself")
    p.add_argument("--color", help="#rrggbb, for level custom")
    p.add_argument("--priority", type=int, help="higher wins when signals share a key")
    p.add_argument("--label")
    p.add_argument("--source", default="cli")
    p.add_argument("--id", help="signal id within the source (default: the key)")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("clear", help="remove signals (all of them with no options)")
    p.add_argument("--source")
    p.add_argument("--id")
    p.set_defaults(func=cmd_clear)

    sub.add_parser("list", help="show active signals").set_defaults(func=cmd_list)
    sub.add_parser("status", help="show keyboard connection").set_defaults(func=cmd_status)
    sub.add_parser("keys", help="show key names").set_defaults(func=cmd_keys)

    p = sub.add_parser("install", help="run the service at login (launchd)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--pool")
    p.set_defaults(func=cmd_install)
    sub.add_parser("uninstall", help="stop and remove the login service").set_defaults(func=cmd_uninstall)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
