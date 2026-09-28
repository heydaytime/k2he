"""keysignal: color keys on the Keychron K2 HE from anything on this Mac."""

import argparse
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import protocol

DEFAULT_PORT = 7780
LAUNCHD_LABEL = "dev.heydaytime.keysignal"
T3_LAUNCHD_LABEL = "dev.heydaytime.keysignal-t3"


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


def _agent_paths(label):
    return (Path.home() / "Library" / "LaunchAgents" / f"{label}.plist",
            Path.home() / "Library" / "Logs" / f"{label.rsplit('.', 1)[-1]}.log")


def _install_agent(label, args):
    """Run `keysignal <args>` at login under launchd, restarting it if it exits."""
    plist, log = _agent_paths(label)
    program = [shutil.which("keysignal") or os.path.abspath(sys.argv[0]), *args]
    plist.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(plist, "wb") as f:
        plistlib.dump({
            "Label": label,
            "ProgramArguments": program,
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(log),
            "StandardErrorPath": str(log),
        }, f)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print(f"installed {plist}\nrunning `{' '.join(program)}`, log: {log}")


def _uninstall_agent(label):
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
    _agent_paths(label)[0].unlink(missing_ok=True)
    print("uninstalled")


def cmd_install(args):
    program = ["serve", "--port", str(args.port)]
    if args.pool:
        program += ["--pool", args.pool]
    _install_agent(LAUNCHD_LABEL, program)


def cmd_uninstall(args):
    _uninstall_agent(LAUNCHD_LABEL)


def cmd_t3_pair(args):
    from . import t3

    try:
        origin = args.server or t3.server_origin()
        token = t3.exchange(origin, t3.pairing_credential(args.link), args.label)
    except (ValueError, t3.T3Unavailable, t3.AuthRejected) as e:
        sys.exit(f"keysignal: {e}")
    t3.save_token(token)
    days = (token["expires_at"] - time.time()) / 86400
    print(f"paired with {origin} as \"{args.label}\" ({token['scope']}), "
          f"token valid for {days:.0f} days, saved to {t3.TOKEN_PATH}")


def cmd_t3_run(args):
    from . import t3

    # launchctl stops the agent with SIGTERM; exit normally so the lights get cleared.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    t3.run(done_hours=args.done_hours, log=lambda msg: print(msg, flush=True))


def cmd_t3_status(args):
    from . import t3

    try:
        token = t3.load_token()
    except t3.NotPaired as e:
        sys.exit(f"keysignal: {e}")
    left = token["expires_at"] - time.time()
    if left <= 0:
        print("paired, but the token has expired: pair again with a new link")
    else:
        print(f"paired ({token['scope']}), token expires in {left / 86400:.1f} days")
    running = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{T3_LAUNCHD_LABEL}"],
                             capture_output=True).returncode == 0
    print(f"bridge:  {'running at login' if running else 'not installed (keysignal t3 install)'}")


def cmd_t3_install(args):
    _install_agent(T3_LAUNCHD_LABEL, ["t3", "run", "--done-hours", str(args.done_hours)])


def cmd_t3_uninstall(args):
    _uninstall_agent(T3_LAUNCHD_LABEL)


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

    t3 = sub.add_parser("t3", help="light a key for each T3 Code thread").add_subparsers(
        dest="t3_command", required=True)
    p = t3.add_parser("pair", help="pair with T3 Code using a read-only pairing link")
    p.add_argument("link", help="the pairing link (or just its token) from T3 Code's Connections settings")
    p.add_argument("--label", default="K2 HE keyboard", help="name shown in T3's connected clients")
    p.add_argument("--server", help="T3 server origin (default: the running T3 Code)")
    p.set_defaults(func=cmd_t3_pair)
    p = t3.add_parser("run", help="run the bridge in the foreground")
    p.add_argument("--done-hours", type=float, default=12, help="how long a finished thread stays lit")
    p.set_defaults(func=cmd_t3_run)
    t3.add_parser("status", help="show pairing and bridge state").set_defaults(func=cmd_t3_status)
    p = t3.add_parser("install", help="run the bridge at login (launchd)")
    p.add_argument("--done-hours", type=float, default=12)
    p.set_defaults(func=cmd_t3_install)
    t3.add_parser("uninstall", help="stop and remove the bridge").set_defaults(func=cmd_t3_uninstall)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
