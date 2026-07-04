"""Example plugin: announce distant stations (DX) in the status bar.

Whenever a decode arrives from farther than a threshold (default 5000 km),
post a one-line status message. Shows how to read a decode row and use the
plugin context.
"""

from digiham.plugins import Plugin

THRESHOLD_KM = 5000.0


class DxAlert(Plugin):
    name = "dx-alert"
    version = "1.0"
    description = "Status-bar shout when a far-away station is decoded"

    def on_load(self):
        self._announced = set()

    def on_decode(self, row):
        if not row.is_cq or row.distance_km is None:
            return
        if row.distance_km < THRESHOLD_KM:
            return
        if row.de in self._announced:
            return
        self._announced.add(row.de)
        km = row.distance_km
        bearing = "" if row.bearing_deg is None else f", {row.bearing_deg:.0f}°"
        where = f" ({row.country})" if row.country else ""
        self.ctx.status(f"DX: {row.de}{where} at {km:,.0f} km{bearing}")

    def on_band_change(self, band):
        # a new band is a fresh slate for "already announced"
        self._announced.clear()
