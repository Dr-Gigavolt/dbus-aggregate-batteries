# -*- coding: utf-8 -*-
"""Shared helpers for the unit tests.

The driver only runs on Venus OS, so the tests have to work around two things:

* ``dbus``, ``vedbus`` and ``gi.repository`` are not installed here, so they are
  stubbed in ``sys.modules`` before the driver is imported.
* ``settings.py`` reads ``config.default.ini`` + ``config.ini`` relative to its
  own location and calls ``sys.exit(1)`` when the resulting configuration is
  invalid (the shipped defaults are deliberately invalid placeholders). The
  helpers below copy ``settings.py`` and ``config.default.ini`` into a throwaway
  directory next to a generated ``config.ini``, so the real config parsing is
  exercised without ever touching the repository's own ``config.ini``.
"""

import importlib.util
import itertools
import os
import shutil
import sys
import tempfile
import types
from unittest import mock


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER_PATH = os.path.join(REPO_ROOT, "dbus-aggregate-batteries.py")
SETTINGS_PATH = os.path.join(REPO_ROOT, "settings.py")
CONFIG_DEFAULT_PATH = os.path.join(REPO_ROOT, "config.default.ini")

# The shipped defaults for these two are invalid on purpose ("-1"), forcing the
# installer to set them. Every generated config.ini gets valid values unless the
# test overrides them itself.
MINIMAL_VALID_CONFIG = {
    "NR_OF_BATTERIES": "2",
    "NR_OF_CELLS_PER_BATTERY": "8",
}

_counter = itertools.count()


def make_config_dir(overrides=None, include_user_config=True):
    """Create a temp dir with settings.py, config.default.ini and a config.ini.

    :param overrides: mapping of option -> value written to the config.ini
    :param include_user_config: when False no config.ini is written at all
    :return: path of the temporary directory (caller is responsible for removal)
    """
    directory = tempfile.mkdtemp(prefix="aggbat-cfg-")
    shutil.copy(SETTINGS_PATH, directory)
    shutil.copy(CONFIG_DEFAULT_PATH, directory)
    if include_user_config:
        options = dict(MINIMAL_VALID_CONFIG)
        options.update(overrides or {})
        lines = ["[DEFAULT]"] + ["%s = %s" % (key, value) for key, value in options.items()]
        with open(os.path.join(directory, "config.ini"), "w") as handle:
            handle.write("\n".join(lines) + "\n")
    return directory


def load_settings(directory):
    """Execute the settings.py copy in ``directory`` and return its module.

    ``time.sleep`` is patched out because settings.py sleeps 60 s before exiting
    on a configuration error. The module object is returned (or raised through)
    even when execution ends in ``SystemExit``, so ``errors_in_config`` can be
    inspected by the caller:

        module = support.new_settings_module(directory)
        with self.assertRaises(SystemExit):
            support.exec_settings(module)
    """
    module = new_settings_module(directory)
    exec_settings(module)
    return module


def new_settings_module(directory):
    """Return a not-yet-executed module object for the settings.py copy."""
    name = "settings_under_test_%d" % next(_counter)
    spec = importlib.util.spec_from_file_location(name, os.path.join(directory, "settings.py"))
    module = importlib.util.module_from_spec(spec)
    module.__spec__ = spec
    return module


def exec_settings(module):
    """Execute a module returned by :func:`new_settings_module`."""
    with mock.patch("time.sleep"):
        module.__spec__.loader.exec_module(module)


def venus_stubs():
    """Minimal stand-ins for the modules that only exist on Venus OS."""
    gi = types.ModuleType("gi")
    gi_repository = types.ModuleType("gi.repository")
    glib = types.ModuleType("gi.repository.GLib")
    glib.MainLoop = object
    glib.timeout_add = lambda *args, **kwargs: None
    glib.timeout_add_seconds = lambda *args, **kwargs: None
    gi_repository.GLib = glib
    gi.repository = gi_repository

    dbus = types.ModuleType("dbus")
    dbus.SystemBus = lambda *args, **kwargs: None
    dbus.SessionBus = lambda *args, **kwargs: None
    dbus_mainloop = types.ModuleType("dbus.mainloop")
    dbus_mainloop_glib = types.ModuleType("dbus.mainloop.glib")
    dbus_mainloop_glib.DBusGMainLoop = lambda *args, **kwargs: None
    dbus_mainloop.glib = dbus_mainloop_glib
    dbus.mainloop = dbus_mainloop

    vedbus = types.ModuleType("vedbus")
    vedbus.VeDbusService = object
    vedbus.VeDbusItemImport = object

    dbusmon = types.ModuleType("dbusmon")
    dbusmon.DbusMon = object

    return {
        "gi": gi,
        "gi.repository": gi_repository,
        "gi.repository.GLib": glib,
        "dbus": dbus,
        "dbus.mainloop": dbus_mainloop,
        "dbus.mainloop.glib": dbus_mainloop_glib,
        "vedbus": vedbus,
        "dbusmon": dbusmon,
    }


def load_driver(settings_module):
    """Load dbus-aggregate-batteries.py with stubbed Venus modules.

    The driver file name contains dashes, so it cannot be imported by name.
    ``settings_module`` is injected as ``settings`` for the duration of the
    import so the driver picks up a valid configuration.
    """
    modules = venus_stubs()
    modules["settings"] = settings_module
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    try:
        spec = importlib.util.spec_from_file_location("aggbat_under_test", DRIVER_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
