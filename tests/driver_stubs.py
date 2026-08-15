"""Test support: stub the Venus-OS-only modules, then load the driver.

``dbus``, ``vedbus``, ``dbusmonitor`` and ``gi``/``GLib`` only exist on a Venus OS
device, so fakes are installed in ``sys.modules`` before anything under test is
imported.  The driver's file name contains dashes, so it cannot be imported by
module name and is loaded through importlib's file loader instead.

The GLib stub does not run a main loop: it records what the code under test
schedules, so a test can run a queued idle callback deliberately.  That is what
makes the coalescing behaviour observable without any timing.
"""

import importlib
import importlib.util
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER_PATH = os.path.join(REPO_ROOT, "dbus-aggregate-batteries.py")


class FakeGLib:
    """Records scheduling calls instead of dispatching them on a main loop."""

    def __init__(self):
        self.idle_calls = []
        """list of (callback, args) queued via idle_add"""

        self.timeout_calls = []
        """list of (interval, callback, args) queued via timeout_add[_seconds]"""

        self._next_source_id = 0

    def _source_id(self):
        self._next_source_id += 1
        return self._next_source_id

    def idle_add(self, callback, *args):
        self.idle_calls.append((callback, args))
        return self._source_id()

    def timeout_add(self, interval, callback, *args):
        self.timeout_calls.append((interval, callback, args))
        return self._source_id()

    def timeout_add_seconds(self, interval, callback, *args):
        self.timeout_calls.append((interval, callback, args))
        return self._source_id()

    def run_pending_idle(self):
        """Run each queued idle callback once, the way the main loop would, and return their results."""
        pending, self.idle_calls = self.idle_calls, []
        return [callback(*args) for callback, args in pending]


class RecordingDbusMonitor:
    """Stand-in for velib_python's DbusMonitor that records its constructor arguments."""

    last_instance = None

    def __init__(self, monitorlist, *args, **kwargs):
        self.monitorlist = monitorlist
        self.args = args
        self.kwargs = kwargs
        RecordingDbusMonitor.last_instance = self


class _Unused:
    """Placeholder for classes the tests never instantiate (VeDbusService and friends)."""

    def __init__(self, *args, **kwargs):  # pragma: no cover - never constructed in tests
        raise AssertionError("stubbed class must not be constructed in tests")


def _make_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def install_stubs():
    """Register the fake Venus OS modules in sys.modules (idempotent)."""
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    if "dbus" not in sys.modules:
        dbus_glib = _make_module("dbus.mainloop.glib", DBusGMainLoop=lambda *a, **kw: None)
        dbus_mainloop = _make_module("dbus.mainloop", glib=dbus_glib)
        dbus_module = _make_module(
            "dbus",
            mainloop=dbus_mainloop,
            SystemBus=_Unused,
            SessionBus=_Unused,
            Interface=_Unused,
        )
        sys.modules["dbus"] = dbus_module
        sys.modules["dbus.mainloop"] = dbus_mainloop
        sys.modules["dbus.mainloop.glib"] = dbus_glib

    if "gi" not in sys.modules:
        gi_repository = _make_module("gi.repository", GLib=FakeGLib())
        sys.modules["gi"] = _make_module("gi", repository=gi_repository)
        sys.modules["gi.repository"] = gi_repository

    if "vedbus" not in sys.modules:
        sys.modules["vedbus"] = _make_module("vedbus", VeDbusService=_Unused, VeDbusItemImport=_Unused)

    if "dbusmonitor" not in sys.modules:
        sys.modules["dbusmonitor"] = _make_module("dbusmonitor", DbusMonitor=RecordingDbusMonitor)

    if "settings" not in sys.modules:
        # settings.py validates the config at import time and calls sys.exit(1) unless a
        # site-specific config.ini exists (config.default.ini ships sentinel values).  The
        # reactive scheduling path reads no settings value, and nothing at module or class
        # body level does either, so a minimal stand-in keeps the tests hermetic.
        sys.modules["settings"] = _make_module(
            "settings",
            NR_OF_BATTERIES=2,
            NR_OF_CELLS_PER_BATTERY=16,
            UPDATE_INTERVAL_DATA=1,
            UPDATE_INTERVAL_FIND_DEVICES=5,
        )


def load_driver():
    """Import dbus-aggregate-batteries.py by path (its name is not a valid module name)."""
    install_stubs()
    if "driver_under_test" not in sys.modules:
        spec = importlib.util.spec_from_file_location("driver_under_test", DRIVER_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules["driver_under_test"] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules["driver_under_test"]
            raise
    return sys.modules["driver_under_test"]


def load_dbusmon():
    """Import the real dbusmon module on top of the stubbed dbusmonitor."""
    install_stubs()
    return importlib.import_module("dbusmon")
