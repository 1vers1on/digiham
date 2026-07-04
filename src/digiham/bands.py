"""Amateur-band plan and standard dial frequencies for the digital modes.

Frequencies are the conventional *dial* (suppressed-carrier) frequencies
in Hz that WSJT-X ships with. In USB the audio passband sits above the
dial, so the on-air RF of a signal is ``dial + audio_hz``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BandDial:
    ft8: int | None
    ft4: int | None
    wspr: int | None


# name -> dial frequencies (Hz). None where the mode has no common activity.
BANDS: dict[str, BandDial] = {
    "2200m": BandDial(ft8=None, ft4=None, wspr=136_000),
    "630m":  BandDial(ft8=474_200, ft4=None, wspr=474_200),
    "160m":  BandDial(ft8=1_840_000, ft4=None, wspr=1_836_600),
    "80m":   BandDial(ft8=3_573_000, ft4=3_575_000, wspr=3_568_600),
    "60m":   BandDial(ft8=5_357_000, ft4=None, wspr=5_364_700),
    "40m":   BandDial(ft8=7_074_000, ft4=7_047_500, wspr=7_038_600),
    "30m":   BandDial(ft8=10_136_000, ft4=10_140_000, wspr=10_138_700),
    "20m":   BandDial(ft8=14_074_000, ft4=14_080_000, wspr=14_095_600),
    "17m":   BandDial(ft8=18_100_000, ft4=18_104_000, wspr=18_104_600),
    "15m":   BandDial(ft8=21_074_000, ft4=21_140_000, wspr=21_094_600),
    "12m":   BandDial(ft8=24_915_000, ft4=24_919_000, wspr=24_924_600),
    "10m":   BandDial(ft8=28_074_000, ft4=28_180_000, wspr=28_124_600),
    "6m":    BandDial(ft8=50_313_000, ft4=50_318_000, wspr=50_293_000),
    "4m":    BandDial(ft8=70_100_000, ft4=70_230_000, wspr=70_091_000),
    "2m":    BandDial(ft8=144_174_000, ft4=144_170_000, wspr=144_489_000),
    "70cm":  BandDial(ft8=432_174_000, ft4=None, wspr=432_300_000),
}

# Display order for band pickers.
BAND_ORDER = list(BANDS.keys())


def dial_for(band: str, mode: str) -> int | None:
    """Standard dial frequency (Hz) for *band*/*mode*, or ``None``."""
    entry = BANDS.get(band)
    if entry is None:
        return None
    return getattr(entry, mode.lower(), None)


def first_band_for(mode: str) -> str | None:
    """First band (in display order) that has a standard dial for *mode*."""
    for band in BAND_ORDER:
        if dial_for(band, mode) is not None:
            return band
    return None


def band_for_freq(freq_hz: float) -> str | None:
    """Best-guess band name containing an RF frequency, for logging."""
    edges = [
        ("2200m", 135_700, 137_800), ("630m", 472_000, 479_000),
        ("160m", 1_800_000, 2_000_000), ("80m", 3_500_000, 4_000_000),
        ("60m", 5_250_000, 5_450_000), ("40m", 7_000_000, 7_300_000),
        ("30m", 10_100_000, 10_150_000), ("20m", 14_000_000, 14_350_000),
        ("17m", 18_068_000, 18_168_000), ("15m", 21_000_000, 21_450_000),
        ("12m", 24_890_000, 24_990_000), ("10m", 28_000_000, 29_700_000),
        ("6m", 50_000_000, 54_000_000), ("4m", 70_000_000, 71_000_000),
        ("2m", 144_000_000, 148_000_000), ("70cm", 420_000_000, 450_000_000),
    ]
    for name, lo, hi in edges:
        if lo <= freq_hz <= hi:
            return name
    return None
