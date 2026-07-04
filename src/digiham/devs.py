"""Developer callsigns, highlighted in the decode tables.

A small easter-egg / shout-out: when a digiham developer is heard on the
air their decode is marked so users can spot (and work) them. Add future
contributors' base callsigns to :data:`DEV_CALLS`.
"""

from __future__ import annotations

from .sequencer import base_call

# Base callsigns (no /P, /QRP … suffixes) of digiham developers.
DEV_CALLS = frozenset({
    "W4NYA",        # Ellie — original author
})


def is_dev(call: str) -> bool:
    """True if *call* belongs to a digiham developer."""
    return bool(call) and base_call(call) in DEV_CALLS
