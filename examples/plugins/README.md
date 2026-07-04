# digiham plugins

Plugins are plain Python files that react to what happens in digiham —
decodes, logged QSOs, transmissions and band changes.

## Installing

Copy any `.py` file from this folder into your plugins directory:

- **Linux:** `~/.config/digiham/plugins/`
- **macOS:** `~/Library/Application Support/digiham/plugins/`
- **Windows:** `%APPDATA%\digiham\plugins\`

Then open **Tools → Plugins…** in digiham and click **Reload** (or restart).
That dialog lists what loaded, shows any errors, and has an
**Open plugins folder…** button that takes you straight there.

Files whose names start with `_` are ignored, so use them for shared
helpers.

## Writing one

Subclass `Plugin` and override any hooks you care about — they are all
optional no-ops by default:

```python
from digiham.plugins import Plugin

class MyPlugin(Plugin):
    name = "my-plugin"           # shown in the Plugins dialog
    version = "1.0"
    description = "what it does"

    def on_load(self):
        # self.ctx is a PluginContext (config, log, status, data_dir)
        self.ctx.status("my-plugin loaded")

    def on_decode(self, row):
        # row is a DecodeRow: .de .message .snr .grid .distance_km ...
        ...

    def on_qso_logged(self, qso):
        # qso is a Qso: .call .band .mode .gridsquare .freq_mhz ...
        ...

    def on_transmit(self, message, mode, band):
        ...

    def on_band_change(self, band):
        ...
```

### The context (`self.ctx`)

| Attribute            | What it gives you                                  |
|----------------------|----------------------------------------------------|
| `ctx.config`         | the live `Config` (read your settings)             |
| `ctx.log`            | the `QsoLog` (`.records`, `.worked_calls()`, …)     |
| `ctx.status(msg)`    | show a message in the status bar                   |
| `ctx.data_dir(name)` | a private folder for your plugin to write files    |
| `ctx.engine`         | the full engine, for advanced use                  |

## Safety

Hooks run on the app thread, so **don't block** — no long sleeps or slow
network calls inline (spawn a thread if you must). If a plugin raises, the
error is logged and the app keeps running; a plugin that keeps failing is
disabled automatically.
