"""A small, safe plugin system for digiham.

Plugins are plain Python files dropped into the user's plugins directory
(``config_dir()/plugins`` by default). Each file defines one or more
subclasses of :class:`Plugin`; the :class:`PluginManager` discovers them,
instantiates them, and calls their hooks as things happen in the app:

    from digiham.plugins import Plugin

    class Hello(Plugin):
        name = "hello"
        def on_qso_logged(self, qso):
            self.ctx.status(f"hello: worked {qso.call}")

Design goals:

* **Isolation** — a plugin that raises never takes the app down. Errors are
  logged and, after a few repeats, the offending plugin is disabled.
* **No hard coupling** — this module imports nothing from the engine, so the
  objects handed to hooks (decode rows, QSOs) stay duck-typed and the
  framework is trivially testable on its own.
* **Least surprise** — hooks are all optional no-ops by default, and plugins
  run on the thread that raised the event (the GUI/engine thread), so they
  must not block for long.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

# A plugin hitting this many errors is disabled so it can't spam or misbehave.
_MAX_ERRORS = 3

# The event hook names a plugin may implement. Kept explicit so the manager
# can validate and so tooling/UI can introspect them. These are fire-and-
# forget: their return value is ignored and a failure is isolated.
HOOKS = (
    "on_load", "on_unload", "on_decode", "on_qso_logged",
    "on_transmit", "on_band_change", "on_config_changed", "on_rig_change",
)


class PluginStore:
    """A tiny JSON-backed key/value store handed to each plugin so it can keep
    settings and state across runs without hand-rolling file I/O.

    Writes are persisted atomically on every ``set``. Values must be
    JSON-serialisable. Reads never raise: a missing or corrupt file just
    starts empty.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError, ValueError):
                logger.warning("plugin store %s unreadable; starting empty",
                               self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def setdefault(self, key: str, default: Any) -> Any:
        if key not in self._data:
            self.set(key, default)
        return self._data[key]

    def delete(self, key: str) -> None:
        if self._data.pop(key, None) is not None:
            self.save()

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        tmp.replace(self.path)

    # dict-style sugar
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return key in self._data


class PluginContext:
    """The app-facing surface handed to every plugin as ``self.ctx``.

    Deliberately small and read-mostly. ``engine`` is exposed for power
    users but most plugins only need ``config``, ``log`` and ``status``.
    """

    def __init__(self, engine: Any, data_root: Path) -> None:
        self._engine = engine
        self._data_root = Path(data_root)
        self._themes: set[str] = set()   # theme names registered via this ctx

    @property
    def engine(self) -> Any:
        return self._engine

    @property
    def config(self) -> Any:
        return self._engine.cfg

    @property
    def log(self) -> Any:
        """The QSO log (read its ``.records``, ``worked_calls()`` etc.)."""
        return self._engine.log

    def status(self, message: str) -> None:
        """Show a message in the app's status bar."""
        try:
            self._engine.statusMessage.emit(str(message))
        except Exception:
            logger.info("plugin status: %s", message)

    def data_dir(self, name: str) -> Path:
        """A private, persistent directory for a plugin to store files in."""
        d = self._data_root / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def store(self, name: str) -> PluginStore:
        """A JSON key/value :class:`PluginStore` in the plugin's data dir.

        Most plugins get at this via ``self.store`` rather than calling here.
        """
        return PluginStore(self.data_dir(name) / "store.json")

    def register_theme(self, name: str, colors: dict) -> dict:
        """Add a colour theme to the app's theme picker.

        ``colors`` maps colour tokens to hex strings (see the theme module's
        ``THEME_TOKENS``); omitted tokens inherit the default dark theme.
        The theme is removed automatically when the plugin is unloaded.
        """
        # Imported lazily so this module stays importable (and unit-testable)
        # without the GUI/PySide stack present.
        from .gui.theme import register_theme
        resolved = register_theme(name, colors)
        self._themes.add(str(name).strip())
        return resolved

    def _clear_registered_themes(self) -> None:
        """Drop every theme registered through this context (on reload/exit)."""
        if not self._themes:
            return
        try:
            from .gui.theme import unregister_theme
            for name in self._themes:
                unregister_theme(name)
        except Exception:
            logger.exception("failed clearing registered themes")
        self._themes.clear()


class Plugin:
    """Base class for digiham plugins. Subclass it and override the hooks.

    All hooks are optional; the defaults do nothing. ``self.ctx`` (a
    :class:`PluginContext`) is injected before :meth:`on_load` is called.
    """

    #: Short unique name; falls back to the class name if unset.
    name: str = ""
    version: str = "0.1"
    description: str = ""
    author: str = ""

    ctx: PluginContext = None  # type: ignore[assignment]
    _store: PluginStore | None = None

    # -- lifecycle --------------------------------------------------------
    def on_load(self) -> None:
        """Called once when the plugin is loaded."""

    def on_unload(self) -> None:
        """Called once when the plugin is unloaded (app exit / reload)."""

    # -- events -----------------------------------------------------------
    def on_decode(self, row: Any) -> None:
        """A single decode arrived (a ``DecodeRow``)."""

    def on_qso_logged(self, qso: Any) -> None:
        """A QSO was written to the log (a ``Qso``)."""

    def on_transmit(self, message: str, mode: str, band: str) -> None:
        """Transmission of *message* just started."""

    def on_band_change(self, band: str) -> None:
        """The operating band changed."""

    def on_config_changed(self, config: Any) -> None:
        """The user changed settings; *config* is the new Config."""

    def on_rig_change(self, connected: bool, dial_hz: float, mode: str) -> None:
        """The rig connected or disconnected."""

    # -- contributions ----------------------------------------------------
    def provide_themes(self) -> dict[str, dict[str, str]]:
        """Return ``{name: {token: colour}}`` to add to the theme picker.

        Called once after loading. Equivalent to calling
        ``self.ctx.register_theme`` for each entry, but declarative.
        """
        return {}

    # -- convenience ------------------------------------------------------
    @property
    def display_name(self) -> str:
        return self.name or type(self).__name__

    @property
    def store(self) -> PluginStore:
        """A lazily-created persistent key/value store for this plugin."""
        if self._store is None:
            self._store = self.ctx.store(self.display_name)
        return self._store


class LoadedPlugin:
    """Bookkeeping wrapper around a live plugin instance."""

    def __init__(self, instance: Plugin, source: Path) -> None:
        self.instance = instance
        self.source = source
        self.errors = 0
        self.disabled = False
        self.themes: list[str] = []     # theme names this plugin contributed

    @property
    def name(self) -> str:
        return self.instance.display_name


class PluginManager:
    """Discovers, loads and dispatches events to plugins."""

    def __init__(self, ctx: PluginContext, dirs: Iterable[Path],
                 disabled: Iterable[str] = ()) -> None:
        self.ctx = ctx
        self.dirs = [Path(d) for d in dirs]
        self.disabled = {d.upper() for d in disabled}
        self.plugins: list[LoadedPlugin] = []
        self.load_errors: list[tuple[str, str]] = []   # (source, message)
        self.loaded = False

    # -- discovery / loading ---------------------------------------------

    def load(self) -> None:
        """Discover and instantiate all plugins, calling their ``on_load``."""
        if self.loaded:
            return
        self.plugins.clear()
        self.load_errors.clear()
        for cls, source in self._discover():
            name = (getattr(cls, "name", "") or cls.__name__)
            if name.upper() in self.disabled:
                logger.info("plugin %s disabled by config", name)
                continue
            try:
                inst = cls()
                inst.ctx = self.ctx
                inst.on_load()
            except Exception as e:
                logger.exception("plugin %s failed to load", name)
                self.load_errors.append((str(source), f"{name}: {e}"))
                continue
            self.plugins.append(LoadedPlugin(inst, source))
            logger.info("loaded plugin %s v%s (%s)", inst.display_name,
                        getattr(inst, "version", "?"), source.name)
        self._register_plugin_themes()
        self.loaded = True

    def _register_plugin_themes(self) -> None:
        """Collect and register every loaded plugin's ``provide_themes``."""
        for lp in self.plugins:
            fn = getattr(lp.instance, "provide_themes", None)
            if fn is None:
                continue
            try:
                themes = fn() or {}
                for name, colors in dict(themes).items():
                    self.ctx.register_theme(name, colors)
                    lp.themes.append(str(name).strip())
            except Exception:
                lp.errors += 1
                logger.exception("plugin %s failed providing themes", lp.name)

    def _discover(self) -> list[tuple[type[Plugin], Path]]:
        found: list[tuple[type[Plugin], Path]] = []
        for d in self.dirs:
            if not d.is_dir():
                continue
            for path in sorted(d.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                module = self._import_file(path)
                if module is None:
                    continue
                for obj in vars(module).values():
                    if (isinstance(obj, type) and issubclass(obj, Plugin)
                            and obj is not Plugin
                            and obj.__module__ == module.__name__):
                        found.append((obj, path))
        return found

    def _import_file(self, path: Path):
        mod_name = f"digiham_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                raise ImportError("could not create import spec")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.exception("failed to import plugin file %s", path)
            self.load_errors.append((str(path), str(e)))
            sys.modules.pop(mod_name, None)
            return None

    # -- dispatch ---------------------------------------------------------

    def dispatch(self, hook: str, *args: Any) -> None:
        """Call *hook* on every live plugin, isolating failures."""
        if not self.plugins:
            return
        for lp in self.plugins:
            if lp.disabled:
                continue
            fn: Callable = getattr(lp.instance, hook, None)
            if fn is None:
                continue
            try:
                fn(*args)
            except Exception:
                lp.errors += 1
                logger.exception("plugin %s failed in %s (%d/%d)",
                                 lp.name, hook, lp.errors, _MAX_ERRORS)
                if lp.errors >= _MAX_ERRORS:
                    lp.disabled = True
                    logger.error("disabling misbehaving plugin %s", lp.name)
                    self.ctx.status(f"plugin {lp.name} disabled after errors")

    # -- teardown / reload ------------------------------------------------

    def unload(self) -> None:
        for lp in self.plugins:
            mod_name = f"digiham_plugin_{lp.source.stem}"
            sys.modules.pop(mod_name, None)
            try:
                lp.instance.on_unload()
            except Exception:
                logger.exception("plugin %s failed in on_unload", lp.name)
        self.ctx._clear_registered_themes()
        self.plugins.clear()
        self.loaded = False

    def reload(self) -> None:
        self.unload()
        self.load()

    def describe(self) -> list[dict]:
        """A snapshot of loaded plugins for the UI."""
        return [{
            "name": lp.name,
            "version": getattr(lp.instance, "version", "?"),
            "description": getattr(lp.instance, "description", ""),
            "author": getattr(lp.instance, "author", ""),
            "source": lp.source.name,
            "disabled": lp.disabled,
            "errors": lp.errors,
            "themes": list(lp.themes),
        } for lp in self.plugins]
