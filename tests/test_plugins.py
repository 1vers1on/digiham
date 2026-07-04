"""Tests for the plugin framework: discovery, dispatch, isolation, disabling."""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import plugins  # noqa: E402
from digiham.plugins import PluginContext, PluginManager  # noqa: E402


def _ctx(data_dir):
    engine = types.SimpleNamespace()
    engine.cfg = types.SimpleNamespace()
    engine.log = None
    engine.status_msgs = []
    engine.statusMessage = types.SimpleNamespace(
        emit=lambda m: engine.status_msgs.append(m))
    return PluginContext(engine, data_dir), engine


GOOD = """
from digiham.plugins import Plugin
class Good(Plugin):
    name = "good"
    version = "2.0"
    description = "records"
    def on_load(self): self.events = ["load"]
    def on_qso_logged(self, qso): self.events.append(("qso", qso))
    def on_decode(self, row): self.events.append(("decode", row))
    def on_unload(self): self.events.append("unload")
"""

BAD = """
from digiham.plugins import Plugin
class Bad(Plugin):
    name = "bad"
    def on_decode(self, row): raise RuntimeError("boom")
"""

COUNTER = """
from digiham.plugins import Plugin
class Counter(Plugin):
    name = "counter"
    def on_load(self): self.n = self.store.get("n", 0)
    def on_qso_logged(self, qso):
        self.n += 1
        self.store["n"] = self.n
"""

HOOKY = """
from digiham.plugins import Plugin
class Hooky(Plugin):
    name = "hooky"
    def on_load(self): self.events = []
    def on_config_changed(self, cfg): self.events.append(("config", cfg))
    def on_rig_change(self, c, dial, mode):
        self.events.append(("rig", c, dial, mode))
"""

THEMER = """
from digiham.plugins import Plugin
class Themer(Plugin):
    name = "themer"
    def provide_themes(self):
        return {"Test Neon": {"bg": "#010203", "accent": "#39ff14"}}
"""


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.data = self.dir / "data"

    def tearDown(self):
        # keep sys.modules tidy between tests
        for k in [k for k in sys.modules if k.startswith("digiham_plugin_")]:
            del sys.modules[k]
        self.tmp.cleanup()

    def _write(self, name, body):
        (self.dir / name).write_text(body)

    def _mgr(self, **kw):
        ctx, self.engine = _ctx(self.data)
        return PluginManager(ctx, dirs=[self.dir], **kw)


class DiscoveryTests(_Fixture):
    def test_loads_plugin_and_calls_on_load(self):
        self._write("good.py", GOOD)
        m = self._mgr()
        m.load()
        self.assertEqual([p["name"] for p in m.describe()], ["good"])
        self.assertEqual(m.plugins[0].instance.events, ["load"])

    def test_underscore_files_skipped(self):
        self._write("_helper.py", "x = 1")
        self._write("good.py", GOOD)
        m = self._mgr()
        m.load()
        self.assertEqual([p["name"] for p in m.describe()], ["good"])

    def test_broken_file_recorded_not_fatal(self):
        self._write("broken.py", "this is not python !!!")
        self._write("good.py", GOOD)
        m = self._mgr()
        m.load()
        self.assertEqual([p["name"] for p in m.describe()], ["good"])
        self.assertEqual(len(m.load_errors), 1)

    def test_disabled_by_name(self):
        self._write("good.py", GOOD)
        m = self._mgr(disabled=["good"])
        m.load()
        self.assertEqual(m.describe(), [])


class DispatchTests(_Fixture):
    def test_events_reach_plugin(self):
        self._write("good.py", GOOD)
        m = self._mgr()
        m.load()
        m.dispatch("on_qso_logged", "Q")
        m.dispatch("on_decode", "R")
        events = m.plugins[0].instance.events
        self.assertIn(("qso", "Q"), events)
        self.assertIn(("decode", "R"), events)

    def test_one_plugin_error_does_not_block_others(self):
        self._write("bad.py", BAD)
        self._write("good.py", GOOD)
        m = self._mgr()
        m.load()
        m.dispatch("on_decode", "R")
        good = next(p for p in m.plugins if p.name == "good")
        self.assertIn(("decode", "R"), good.instance.events)

    def test_repeated_errors_disable_plugin(self):
        self._write("bad.py", BAD)
        m = self._mgr()
        m.load()
        for _ in range(plugins._MAX_ERRORS):
            m.dispatch("on_decode", "R")
        bad = m.plugins[0]
        self.assertTrue(bad.disabled)
        self.assertGreaterEqual(bad.errors, plugins._MAX_ERRORS)
        # a disabled plugin is skipped from then on
        before = bad.errors
        m.dispatch("on_decode", "R")
        self.assertEqual(bad.errors, before)


class LifecycleTests(_Fixture):
    def test_unload_calls_on_unload(self):
        self._write("good.py", GOOD)
        m = self._mgr()
        m.load()
        inst = m.plugins[0].instance
        m.unload()
        self.assertIn("unload", inst.events)
        self.assertFalse(m.loaded)
        self.assertEqual(m.plugins, [])

    def test_reload(self):
        self._write("good.py", GOOD)
        m = self._mgr()
        m.load()
        m.reload()
        self.assertTrue(m.loaded)
        self.assertEqual(len(m.plugins), 1)

    def test_data_dir_created(self):
        ctx, _ = _ctx(self.data)
        d = ctx.data_dir("myplugin")
        self.assertTrue(d.is_dir())
        self.assertEqual(d.name, "myplugin")

    def test_store_persists_across_reload(self):
        self._write("counter.py", COUNTER)
        m = self._mgr()
        m.load()
        m.dispatch("on_qso_logged", "Q")
        m.dispatch("on_qso_logged", "Q")
        self.assertEqual(m.plugins[0].instance.n, 2)
        m.reload()
        # a fresh instance reads the persisted count back from disk
        self.assertEqual(m.plugins[0].instance.n, 2)


class ContextTests(_Fixture):
    def test_store_get_set_defaults(self):
        ctx, _ = _ctx(self.data)
        s = ctx.store("p")
        self.assertEqual(s.get("k", 7), 7)
        s["k"] = 9
        self.assertEqual(ctx.store("p")["k"], 9)   # re-read from disk
        self.assertEqual(s.setdefault("k", 1), 9)
        self.assertEqual(s.setdefault("m", 3), 3)
        s.delete("k")
        self.assertNotIn("k", ctx.store("p"))


class HookTests(_Fixture):
    def test_new_hooks_dispatch(self):
        self._write("hooky.py", HOOKY)
        m = self._mgr()
        m.load()
        m.dispatch("on_config_changed", "CFG")
        m.dispatch("on_rig_change", True, 14074000.0, "PKTUSB")
        ev = m.plugins[0].instance.events
        self.assertIn(("config", "CFG"), ev)
        self.assertIn(("rig", True, 14074000.0, "PKTUSB"), ev)


class ThemeTests(_Fixture):
    def test_provide_themes_registered_and_cleared(self):
        from digiham.gui import theme
        self._write("themer.py", THEMER)
        m = self._mgr()
        m.load()
        self.assertIn("Test Neon", theme.available_themes())
        self.assertEqual(theme.resolve_colors("Test Neon")["bg"], "#010203")
        self.assertEqual([p["themes"] for p in m.describe()], [["Test Neon"]])
        m.unload()
        self.assertNotIn("Test Neon", theme.available_themes())

    def test_invalid_theme_tokens_dropped(self):
        from digiham.gui import theme
        got = theme.register_theme("Junk", {"bg": "#111111", "nope": "x",
                                             "accent": "notacolour"})
        self.assertEqual(got, {"bg": "#111111"})
        theme.unregister_theme("Junk")


if __name__ == "__main__":
    unittest.main()
