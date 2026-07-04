#!/usr/bin/env python3
"""Live-rig test console for digiham.rigctl.

Runs against a real rigctld (default 127.0.0.1:4532):

    python tests/rig_debug.py                 # smoke test, then interactive console
    python tests/rig_debug.py --smoke-only    # just the smoke test, exit code 0/1
    python tests/rig_debug.py --no-smoke      # straight to the console
    python tests/rig_debug.py --host H --port P

Deliberately NOT named test_*.py so pytest never collects it and starts
driving the radio. Safety rules baked in:

* PTT is never keyed. Reading PTT state is allowed; setting it is refused
  everywhere, including through the `raw` command.
* Frequency, mode, and split are captured at connect and restored on exit
  (pass --no-restore to leave the rig where you put it).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from digiham.rigctl import (  # noqa: E402
    HAMLIB_MODES,
    RigctlClient,
    RigctldError,
    normalize_mode,
)

# Same meters rig.py polls; reading a TX meter while receiving is harmless.
METERS = ("STRENGTH", "RFPOWER_METER_WATTS", "SWR", "ALC", "VD_METER")

# raw-command first tokens that would key the transmitter
_TX_COMMANDS = {"T", "\\set_ptt"}


def parse_freq(text: str) -> float:
    """'14074000', '7074k', '14.074m', '14.074MHz' -> Hz."""
    t = text.strip().lower().replace(",", "").replace("_", "")
    mult = 1.0
    for suffix, m in (("mhz", 1e6), ("khz", 1e3), ("hz", 1.0), ("m", 1e6), ("k", 1e3)):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            mult = m
            break
    return float(t) * mult


def fmt_freq(hz: float) -> str:
    return f"{hz / 1e6:.6f} MHz ({hz:.0f} Hz)"


# -- state capture / restore --------------------------------------------------

def save_state(rig: RigctlClient) -> dict:
    state = {"freq": rig.get_freq()}
    state["mode"], state["width"] = rig.get_mode()
    try:
        state["split"], state["tx_vfo"] = rig.get_split_vfo()
    except (RigctldError, OSError):
        state["split"] = None
    return state


def restore_state(rig: RigctlClient, state: dict) -> None:
    mode, width = rig.get_mode()
    if mode != state["mode"]:
        print(f"restoring mode {state['mode']}")
        try:
            rig.set_mode(state["mode"], state["width"])
        except (RigctldError, ValueError):
            rig.set_mode(state["mode"], 0)
    freq = rig.get_freq()
    if abs(freq - state["freq"]) >= 1:
        print(f"restoring frequency {fmt_freq(state['freq'])}")
        rig.set_freq(state["freq"])
    if state["split"] is not None:
        split, _ = rig.get_split_vfo()
        if split != state["split"]:
            print(f"restoring split {'on' if state['split'] else 'off'}")
            rig.set_split_vfo(state["split"], state["tx_vfo"])


# -- smoke test ---------------------------------------------------------------

def smoke(rig: RigctlClient) -> bool:
    """Exercise the client against the live rig. Never transmits."""
    passed = True

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        passed = passed and ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))

    print("\n-- client-side mode validation (no rig traffic)")
    check("DATA-U aliases to PKTUSB", normalize_mode("DATA-U") == "PKTUSB")
    check("'' passes through", normalize_mode("") == "")
    try:
        normalize_mode("BOGUS-MODE")
        check("bad mode rejected before send", False, "no ValueError raised")
    except ValueError:
        check("bad mode rejected before send", True)

    print("\n-- read current state")
    try:
        vfo = rig.get_vfo()
        freq = rig.get_freq()
        mode, width = rig.get_mode()
        ptt = rig.get_ptt()
        check("vfo/freq/mode/ptt", True,
              f"{vfo}, {fmt_freq(freq)}, {mode} width {width}, PTT {'ON' if ptt else 'off'}")
    except (RigctldError, OSError) as e:
        check("vfo/freq/mode/ptt", False, str(e))
        return False
    try:
        split, tx_vfo = rig.get_split_vfo()
        check("split status", True, f"{'on' if split else 'off'}, TX {tx_vfo}")
    except (RigctldError, OSError) as e:
        check("split status", False, str(e))

    print("\n-- meters")
    for name in METERS:
        try:
            print(f"  {name:22s} {rig.get_level(name):g}")
        except (RigctldError, OSError) as e:
            print(f"  {name:22s} unsupported ({e})")

    print("\n-- frequency round-trip (+500 Hz and back)")
    target = freq + 500
    try:
        rig.set_freq(target)
        back = rig.get_freq()
        check(f"set {fmt_freq(target)}", abs(back - target) < 1, f"read back {fmt_freq(back)}")
        rig.set_freq(freq)
        back = rig.get_freq()
        check("restore", abs(back - freq) < 1, f"read back {fmt_freq(back)}")
    except (RigctldError, OSError) as e:
        check("frequency round-trip", False, str(e))

    print("\n-- mode round-trip (mode changes are slow on the FTDX-10, ~2.5 s each)")
    other = "PKTUSB" if mode != "PKTUSB" else "USB"
    try:
        rig.set_mode(other)
        back, _ = rig.get_mode()
        check(f"set {other}", back == other, f"read back {back}")
        rig.set_mode(mode, width)
        back, back_width = rig.get_mode()
        check(f"restore {mode}", back == mode, f"read back {back} width {back_width}")
    except (RigctldError, OSError, ValueError) as e:
        check("mode round-trip", False, str(e))

    print(f"\nsmoke test {'PASSED' if passed else 'FAILED'}")
    return passed


# -- interactive console --------------------------------------------------------

HELP = """\
commands (get with no argument, set with one):
  f [freq]        frequency; accepts Hz, k, m suffixes: f 14074000 / f 7074k / f 14.074m
  m [mode]        mode; front-panel names OK (DATA-U -> PKTUSB)
  v [vfo]         current VFO / switch VFO (VFOA, VFOB)
  s               split status
  split on <freq> | split off
  l [LEVEL]       read one meter, or all known meters with no argument
  ptt             read PTT state (setting PTT is disabled in this tool)
  poll            one app-style poll: freq + mode + PTT + meters
  raw <cmd>       send a raw rigctld command line (TX commands refused)
  smoke           re-run the smoke test
  restore         restore the state captured at connect
  modes           list valid Hamlib mode names
  q / quit        restore state and exit (Ctrl-D works too)
"""


def console(rig: RigctlClient, state: dict) -> None:
    try:
        import readline  # noqa: F401  (line editing + history)
    except ImportError:
        pass

    print("\ninteractive console -- 'help' for commands, 'q' to quit")
    while True:
        try:
            line = input("rig> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        cmd, _, arg = line.partition(" ")
        cmd = cmd.lower()
        arg = arg.strip()
        try:
            if cmd in ("q", "quit", "exit"):
                return
            elif cmd == "help":
                print(HELP)
            elif cmd == "f":
                if arg:
                    rig.set_freq(parse_freq(arg))
                print(fmt_freq(rig.get_freq()))
            elif cmd == "m":
                if arg:
                    rig.set_mode(arg)
                mode, width = rig.get_mode()
                print(f"{mode} width {width}")
            elif cmd == "v":
                if arg:
                    rig.set_vfo(arg.upper())
                print(rig.get_vfo())
            elif cmd == "s":
                split, tx_vfo = rig.get_split_vfo()
                print(f"split {'on' if split else 'off'}, TX {tx_vfo}")
            elif cmd == "split":
                sub, _, freq_arg = arg.partition(" ")
                if sub == "on":
                    rig.set_split_vfo(True, "VFOB")
                    if freq_arg:
                        rig.set_split_freq(parse_freq(freq_arg))
                    print(f"split on, TX {fmt_freq(rig.get_split_freq())}")
                elif sub == "off":
                    rig.set_split_vfo(False, "VFOA")
                    print("split off")
                else:
                    print("usage: split on <freq> | split off")
            elif cmd == "l":
                for name in ([arg.upper()] if arg else METERS):
                    try:
                        print(f"{name:22s} {rig.get_level(name):g}")
                    except RigctldError as e:
                        print(f"{name:22s} {e}")
            elif cmd == "ptt":
                print("PTT ON" if rig.get_ptt() else "PTT off")
            elif cmd == "poll":
                freq = rig.get_freq()
                mode, _ = rig.get_mode()
                ptt = rig.get_ptt()
                print(f"{fmt_freq(freq)}  {mode}  PTT {'ON' if ptt else 'off'}")
                for name in ("STRENGTH", "VD_METER"):
                    try:
                        print(f"{name:22s} {rig.get_level(name):g}")
                    except RigctldError:
                        pass
            elif cmd == "raw":
                if not arg:
                    print("usage: raw <rigctld command line>")
                elif arg.split()[0] in _TX_COMMANDS:
                    print("refused: this tool never keys PTT")
                else:
                    reply = rig._raw_command(arg)
                    print(reply if reply else "RPRT 0")
            elif cmd == "smoke":
                smoke(rig)
            elif cmd == "restore":
                restore_state(rig, state)
                print("done")
            elif cmd == "modes":
                print(" ".join(sorted(HAMLIB_MODES)))
            else:
                print(f"unknown command {cmd!r} -- 'help' for commands")
        except (RigctldError, ValueError) as e:
            print(f"error: {e}")
        except TimeoutError:
            print("error: rig timed out (client will resync on the next command)")
        except (ConnectionError, OSError) as e:
            print(f"connection lost: {e}")
            return


def main() -> int:
    ap = argparse.ArgumentParser(description="live-rig debug console for digiham.rigctl")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4532)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--smoke-only", action="store_true", help="run the smoke test and exit")
    ap.add_argument("--no-smoke", action="store_true", help="skip the smoke test")
    ap.add_argument("--no-restore", action="store_true",
                    help="do not restore freq/mode/split on exit")
    args = ap.parse_args()

    rig = RigctlClient(args.host, args.port, timeout=args.timeout)
    try:
        rig.connect()
    except OSError as e:
        print(f"cannot connect to rigctld at {args.host}:{args.port}: {e}")
        print("is rigctld running? (it needs root for the FTDX-10 serial port)")
        return 2
    print(f"connected to rigctld at {args.host}:{args.port}"
          + (" (--vfo mode)" if rig.vfo_mode else ""))

    ok = True
    try:
        state = save_state(rig)
        print(f"captured state: {fmt_freq(state['freq'])}, {state['mode']}"
              f" width {state['width']}"
              + ("" if state["split"] is None
                 else f", split {'on' if state['split'] else 'off'}"))
        if not args.no_smoke:
            ok = smoke(rig)
        if not args.smoke_only:
            console(rig, state)
        if not args.no_restore:
            restore_state(rig, state)
    finally:
        rig.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
