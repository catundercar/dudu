#!/usr/bin/env python3
"""A stand-in for herdr-core's `hc` CLI, for replay.py: answers from a JSON state file and logs every call.

FAKE_HC_STATE: {"terminals": {"t1": {...}}, "next": 2}, a terminal as `hc get --json` prints it (state, labels,
status, cwd, name, argv, foreground). FAKE_HC_LOG: one JSON line per call, the arguments without `--json`.
Covers get, ls, run, send, label, keep, keys, read, kill, rm, interrupt and `server status`; anything else
(`connect` included) fails the way an hc without that command would. Standard library only, Python 3.9.
"""
import contextlib
import fcntl
import json
import os
import sys


def fail(kind, message, code=1):
    sys.stderr.write(json.dumps({"error": {"kind": kind, "message": message}}) + "\n")
    sys.exit(code)


@contextlib.contextmanager
def locked_state():
    path = os.environ["FAKE_HC_STATE"]
    with open(path + ".lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {"terminals": {}, "next": 1}
        before = json.dumps(state, sort_keys=True)
        yield state
        if json.dumps(state, sort_keys=True) != before:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(state, f, indent=1, sort_keys=True)
            os.replace(path + ".tmp", path)


def row(address, term):
    return {"address": address, "id": address, **term}


def take_options(args, flags_with_value):
    """(options, rest): leading `--flag value` (for flags_with_value) and bare `--flag` arguments, up to the first
    other argument or a `--`."""
    opts, rest = {}, list(args)
    while rest and rest[0].startswith("--") and rest[0] != "--":
        flag = rest.pop(0)
        if flag in flags_with_value and rest:
            opts.setdefault(flag, []).append(rest.pop(0))
        else:
            opts[flag] = True
    return opts, rest


def main():
    args = sys.argv[1:]
    cut = args.index("--") if "--" in args else len(args)
    head = [a for a in args[:cut] if a != "--json"]
    args = head + args[cut:]
    with open(os.environ["FAKE_HC_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(args, ensure_ascii=False) + "\n")
    if not args:
        fail("usage", "no command", 2)
    cmd, rest = args[0], args[1:]
    out = None
    with locked_state() as state:
        terms = state.setdefault("terminals", {})

        def term_of(address):
            address = address[3:] if address.startswith("hc:") else address
            if address not in terms:
                fail("not_found", f"no terminal {address}")
            return address, terms[address]

        if cmd == "get":
            address, term = term_of(rest[0])
            out = row(address, term)
        elif cmd == "ls":
            every = "--all" in rest
            out = {"terminals": [row(a, t) for a, t in sorted(terms.items())
                                 if every or t.get("state", "live") == "live"]}
        elif cmd == "run":
            opts, argv = take_options(rest, {"--name", "--cwd", "--label", "--parent", "--tab", "--space"})
            argv = argv[1:] if argv[:1] == ["--"] else argv
            address = f"t{state.get('next', 1)}"
            state["next"] = state.get("next", 1) + 1
            labels = dict(kv.split("=", 1) for kv in opts.get("--label", []) if "=" in kv)
            terms[address] = {"state": "live", "name": (opts.get("--name") or [address])[0],
                              "cwd": (opts.get("--cwd") or [""])[0], "argv": argv, "labels": labels,
                              "status": {"state": "idle"}, "foreground": {"argv": argv}}
            out = row(address, terms[address])
        elif cmd == "send":
            opts, rest = take_options(rest, {"--if"})
            rest = rest[1:] if rest[:1] == ["--"] else rest
            address, term = term_of(rest[0])
            if term.get("state") != "live":
                fail("not_live", f"terminal {address} is not live")
            term.setdefault("received", []).append(rest[1] if len(rest) > 1 else "")
            out = {"ok": True, "started": True}
        elif cmd == "label":
            address, term = term_of(rest[0])
            labels = term.setdefault("labels", {})
            for kv in rest[1:]:
                key, _, value = kv.partition("=")
                if value:
                    labels[key] = value
                else:
                    labels.pop(key, None)
            out = row(address, term)
        elif cmd == "keep":
            address, term = term_of(rest[0])
            term["keep"] = True
            out = {"ok": True}
        elif cmd in ("keys", "interrupt"):
            term_of(rest[0])
            out = {"ok": True}
        elif cmd == "read":
            address, term = term_of(rest[0])
            out = {"text": term.get("screen", "")}
        elif cmd == "kill":
            address, term = term_of(rest[0])
            term["state"] = "exited"
            out = {"ok": True}
        elif cmd == "rm":
            address, _ = term_of(rest[0])
            del terms[address]
            out = {"ok": True}
        elif cmd == "server" and rest[:1] == ["status"]:
            out = {"running": True}
        else:
            fail("unknown_command", f"fake hc has no {cmd}", 2)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
