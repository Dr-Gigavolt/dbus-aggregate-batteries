#!/usr/bin/env python3

"""
The one place where the unit tests stub Venus OS and load the driver.

Every suite in ``tests/`` imports this module and nothing else touches
``sys.modules``.  That is deliberate: the driver's dependencies (``dbus``,
``gi``/``GLib``, ``vedbus``, ``dbusmonitor``, ``settings``) can only be faked
once per interpreter, so if each suite installed its own fakes the first import
would win and every later suite would silently run against a stand-in that was
built for somebody else's test.  Python imports a module once, so doing the
stubbing here — unconditionally, never with ``setdefault`` — makes the result
identical no matter which suite is imported first, in any combination.

What is provided:

* ``FakeGLib`` - records ``idle_add`` / ``timeout_add_seconds`` instead of
  running a main loop, and can drain the queued idle callbacks on demand, which
  is what makes the reactive coalescing observable without any timing.
  ``patch_glib()`` swaps a fresh recorder into the driver for one test.
* ``dbus`` and ``vedbus`` stubs whose constructors raise, so a test that
  accidentally builds a real bus object fails loudly instead of hanging.
* ``dbusmonitor`` stubbed by ``RecordingDbusMonitor``.  ``dbusmon`` itself is
  *not* stubbed: it is a module under test, and on top of the recorder it
  constructs nothing real.
* ``settings``: the real ``settings.py``, executed from a throwaway directory
  next to a generated ``config.ini`` so the repository's own ``config.ini`` is
  never read or written.  ``make_config_dir()`` / ``load_settings()`` expose the
  same machinery to the settings tests, and ``use_stub_settings()`` swaps in a
  fresh in-memory settings namespace for tests that want to drive the device
  search with values of their own — an explicit, per-test choice instead of a
  global race.
* ``driver`` - ``dbus-aggregate-batteries.py`` loaded by path (its file name
  contains dashes) and cached, so repeated loads are cheap and consistent.
* ``RecordingDbusService`` - a fake of the D-Bus service the publish gate wraps,
  recording registrations and writes separately, and ``new_service()``, the
  ``object.__new__`` helper every suite uses to build a ``DbusAggBatService``
  without running its bus-touching ``__init__``.

No driver logic is re-implemented here: this module only supplies the
scaffolding, so every assertion in the test modules is about what the driver
itself computed.
"""

import importlib
import importlib.util
import itertools
import logging
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
DRIVER_PATH = os.path.join(REPO_ROOT, "dbus-aggregate-batteries.py")
SETTINGS_PATH = os.path.join(REPO_ROOT, "settings.py")
CONFIG_DEFAULT_PATH = os.path.join(REPO_ROOT, "config.default.ini")

DRIVER_MODULE_NAME = "dbus_aggregate_batteries_under_test"

# Number of cells the scripted batteries report. The driver is told the same
# number through the settings patch in DriverTestCase.
NR_OF_CELLS = 4

# The shipped defaults for these two are invalid on purpose ("-1"), forcing the
# installer to set them. Every generated config.ini gets valid values unless the
# caller overrides them itself.
MINIMAL_VALID_CONFIG = {
    "NR_OF_BATTERIES": "2",
    "NR_OF_CELLS_PER_BATTERY": "8",
}

_module_counter = itertools.count()


# ---------------------------------------------------------------------------
# Stand-ins for the modules that only exist on a Venus OS device
# ---------------------------------------------------------------------------


class Unconstructable:
    """Placeholder for symbols the driver imports but a unit test must never build."""

    def __init__(self, *args, **kwargs):  # pragma: no cover - the point is that it never runs
        raise AssertionError("real D-Bus objects must not be constructed in unit tests")


class FakeGLib:
    """Records scheduling calls instead of dispatching them on a main loop."""

    MainLoop = Unconstructable

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

    @property
    def scheduled_callbacks(self):
        """Every callback handed to the main loop, idle and timed alike, in order."""
        return [callback for callback, _ in self.idle_calls] + [callback for _, callback, _ in self.timeout_calls]

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


def _make_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _install_module_stubs():
    """Register the fake Venus OS modules in sys.modules and return the GLib recorder.

    Entries are assigned, never ``setdefault``-ed: this function runs exactly
    once (at the first import of this module), and it must not inherit anything
    a previous import happened to leave behind.
    """
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    glib = FakeGLib()
    repository = _make_module("gi.repository", GLib=glib)
    gi = _make_module("gi", repository=repository, require_version=lambda *args, **kwargs: None)

    dbus_glib = _make_module("dbus.mainloop.glib", DBusGMainLoop=lambda *args, **kwargs: None)
    dbus_mainloop = _make_module("dbus.mainloop", glib=dbus_glib)
    dbus = _make_module(
        "dbus",
        mainloop=dbus_mainloop,
        SystemBus=Unconstructable,
        SessionBus=Unconstructable,
        Interface=Unconstructable,
    )

    vedbus = _make_module("vedbus", VeDbusService=Unconstructable, VeDbusItemImport=Unconstructable)

    # dbusmon is deliberately absent: it is a module under test. With
    # dbusmonitor recorded rather than real, importing it is harmless.
    dbusmonitor = _make_module("dbusmonitor", DbusMonitor=RecordingDbusMonitor)

    for name, module in (
        ("gi", gi),
        ("gi.repository", repository),
        ("gi.repository.GLib", glib),
        ("dbus", dbus),
        ("dbus.mainloop", dbus_mainloop),
        ("dbus.mainloop.glib", dbus_glib),
        ("vedbus", vedbus),
        ("dbusmonitor", dbusmonitor),
    ):
        sys.modules[name] = module

    return glib


# ---------------------------------------------------------------------------
# The real settings.py, executed against a throwaway config
# ---------------------------------------------------------------------------


def make_config_dir(overrides=None, include_user_config=True):
    """Create a temp dir with settings.py, config.default.ini and a config.ini.

    settings.py reads config.default.ini and then config.ini relative to its own
    location, and calls sys.exit(1) when the result is invalid (the shipped
    defaults are deliberately invalid placeholders). Copying it next to a
    generated config.ini exercises the real parsing without ever touching the
    repository's own config.ini.

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


def new_settings_module(directory, name=None):
    """Return a not-yet-executed module object for the settings.py copy in ``directory``."""
    if name is None:
        name = "settings_under_test_%d" % next(_module_counter)
    spec = importlib.util.spec_from_file_location(name, os.path.join(directory, "settings.py"))
    module = importlib.util.module_from_spec(spec)
    module.__spec__ = spec
    return module


def exec_settings(module):
    """Execute a module returned by :func:`new_settings_module`.

    ``time.sleep`` is patched out because settings.py sleeps 60 s before exiting
    on a configuration error.
    """
    with mock.patch("time.sleep"):
        module.__spec__.loader.exec_module(module)


def load_settings(directory):
    """Execute the settings.py copy in ``directory`` and return its module.

    The module object is available to the caller even when execution ends in
    ``SystemExit``, so ``errors_in_config`` can be inspected:

        module = driver_harness.new_settings_module(directory)
        with self.assertRaises(SystemExit):
            driver_harness.exec_settings(module)
    """
    module = new_settings_module(directory)
    exec_settings(module)
    return module


def _install_settings():
    """Execute the real settings.py once and register it as ``settings``."""
    directory = make_config_dir()
    try:
        module = new_settings_module(directory, name="settings")
        sys.modules["settings"] = module
        exec_settings(module)
        return module
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# ---------------------------------------------------------------------------
# The driver itself
# ---------------------------------------------------------------------------


def load_driver():
    """Import dbus-aggregate-batteries.py by path (its name is not a valid module name)."""
    if DRIVER_MODULE_NAME not in sys.modules:
        spec = importlib.util.spec_from_file_location(DRIVER_MODULE_NAME, DRIVER_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[DRIVER_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[DRIVER_MODULE_NAME]
            raise
    return sys.modules[DRIVER_MODULE_NAME]


def load_dbusmon():
    """Import the real dbusmon module on top of the recording dbusmonitor."""
    return importlib.import_module("dbusmon")


GLIB = _install_module_stubs()
settings = _install_settings()
driver = load_driver()


def patch_glib(test_case):
    """Give ``test_case`` a fresh GLib recorder for the duration of the test."""
    glib = FakeGLib()
    patcher = mock.patch.object(driver, "GLib", glib)
    patcher.start()
    test_case.addCleanup(patcher.stop)
    return glib


# ---------------------------------------------------------------------------
# An in-memory settings namespace, for tests that drive the device search
# ---------------------------------------------------------------------------

# The device search reads a lot of settings and the tests vary them, so they run
# against a stand-in rather than the parsed config. use_stub_settings() hands out
# a fresh one per test, which is the per-test reset: no test can leak a value
# into the next one, and the real settings module is restored afterwards.
DEFAULT_STUB_SETTINGS = {
    "BATTERY_SERVICE_NAME": "com.victronenergy.battery",
    "DCLOAD_SERVICE_NAME": "com.victronenergy.dcload",
    "BATTERY_PRODUCT_NAME_PATH": "/ProductName",
    "BATTERY_PRODUCT_NAME": "SerialBattery",
    "BATTERY_INSTANCE_NAME_PATH": "/CustomName",
    "SMARTSHUNT_INSTANCE_NAME_PATH": "/CustomName",
    "SMARTSHUNT_NAME_KEYWORD": "SmartShunt",
    "USE_SMARTSHUNTS": False,
    "SEND_CELL_VOLTAGES": 0,
    "NR_OF_CELLS_PER_BATTERY": 16,
    "CAN_batteries": False,
    "NR_OF_BATTERIES": 2,
    "CURRENT_FROM_VICTRON": False,
    "MULTI_KEYWORD": "com.victronenergy.vebus",
    "NR_OF_MPPTS": 0,
    "MPPT_KEYWORD": "com.victronenergy.solarcharger",
    "SEARCH_TRIALS": 10,
    "UPDATE_INTERVAL_DATA": 1000,
    "UPDATE_INTERVAL_FIND_DEVICES": 3,
    "TIME_BEFORE_RESTART": 0,
    "OWN_CHARGE_PARAMETERS": False,
}


def new_stub_settings(**overrides):
    """A fresh settings namespace carrying DEFAULT_STUB_SETTINGS plus ``overrides``."""
    values = dict(DEFAULT_STUB_SETTINGS)
    values.update(overrides)
    return _make_module("settings_stub", **values)


def use_stub_settings(test_case, **overrides):
    """Swap a fresh settings stub into the driver for the duration of ``test_case``."""
    stub = new_stub_settings(**overrides)
    patcher = mock.patch.object(driver, "settings", stub)
    patcher.start()
    test_case.addCleanup(patcher.stop)
    return stub


# ---------------------------------------------------------------------------
# Test doubles for the D-Bus side
# ---------------------------------------------------------------------------


class _RecordingServiceContext:
    """Stand-in for velib_python's ``ServiceContext``."""

    def __init__(self, service):
        self._service = service

    def __setitem__(self, path, value):
        self._service._write(path, value)

    def __getitem__(self, path):
        return self._service[path]


class RecordingDbusService:
    """Records every registration and every write that reaches the D-Bus layer.

    Registration through ``add_path`` seeds the published value but is not a
    write, which is the distinction the publish gate is built on:
    ``ServiceContext.__getitem__`` returns the currently published value, and
    ``VeDbusItemExport._local_set_value`` drops a write whose value is unchanged
    (so "not written" and "not emitted on D-Bus" are the same thing).
    """

    def __init__(self):
        self.values = {}
        self.written = []
        """list of (path, value) that went through __setitem__, in order"""

        self.add_path_calls = []
        """list of (path, value, kwargs) passed to add_path, in order"""

        self.enter_count = 0
        self.exit_count = 0
        self.registered = False

    # ----- velib-ish API used by the driver -----

    def add_path(self, path, value=None, **kwargs):
        """Register a path with its initial value. Registration is not a write."""
        self.add_path_calls.append((path, value, kwargs))
        self.values[path] = value

    def register(self):
        self.registered = True
        return "registered"

    def __enter__(self):
        self.enter_count += 1
        return _RecordingServiceContext(self)

    def __exit__(self, *exc):
        self.exit_count += 1
        return False

    def __setitem__(self, path, value):
        self._write(path, value)

    def __getitem__(self, path):
        if path not in self.values:
            raise KeyError(path)
        return self.values[path]

    # ----- test helpers -----

    @property
    def published(self):
        """Everything currently on the bus, registered or written."""
        return self.values

    def writes_to(self, path):
        """Every value written to ``path``, in order. Registrations are excluded."""
        return [value for written_path, value in self.written if written_path == path]

    def _write(self, path, value):
        self.written.append((path, value))
        self.values[path] = value

    def foreign_write(self, path, value):
        """Another process writing the path over D-Bus (VeDbusItemExport.SetValue)."""
        self.values[path] = value


class FakeBus:
    """Stands in for the D-Bus connection: only ``list_names`` is ever used."""

    def __init__(self, names=()):
        self._names = list(names)

    def list_names(self):
        return list(self._names)


class FakeDbusMonitor:
    """Stands in for DbusMon().dbusmon: scripted get_value per (service, path)."""

    def __init__(self, values=None, default=0):
        self._values = dict(values or {})
        self._default = default
        self.set_calls = []

    def get_value(self, service, path):
        return self._values.get((service, path), self._default)

    def set_value(self, service, path, value):
        self.set_calls.append((service, path, value))
        return 0


class FakeDbusMon:
    def __init__(self, values=None, default=0):
        self.dbusmon = FakeDbusMonitor(values, default)


class WarningCollector(logging.Handler):
    """Collects records so a test can assert that nothing was warned."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    @property
    def messages(self):
        return [record.getMessage() for record in self.records]


def new_service(**attributes):
    """Build a DbusAggBatService without running its D-Bus touching __init__.

    Only the attributes a test's code path actually reads have to be set, which
    is why the real ``__init__`` (it opens a bus) is bypassed entirely.
    """
    service = object.__new__(driver.DbusAggBatService)
    for name, value in attributes.items():
        setattr(service, name, value)
    return service


# ---------------------------------------------------------------------------
# Scripted constituent batteries and the base class that drives _update()
# ---------------------------------------------------------------------------

# Alarm paths the driver reads for every battery.
ALARM_PATHS = (
    "/Alarms/LowVoltage",
    "/Alarms/HighVoltage",
    "/Alarms/LowCellVoltage",
    "/Alarms/HighCellVoltage",
    "/Alarms/LowSoc",
    "/Alarms/HighChargeCurrent",
    "/Alarms/HighDischargeCurrent",
    "/Alarms/CellImbalance",
    "/Alarms/InternalFailure",
    "/Alarms/HighChargeTemperature",
    "/Alarms/LowChargeTemperature",
    "/Alarms/HighTemperature",
    "/Alarms/LowTemperature",
    "/Alarms/BmsCable",
)

# Values that keep every part of _update() a test is not interested in happy
# and boring, so that a test only has to vary the values it is about.
HEALTHY_BATTERY = {
    "/InstalledCapacity": 100.0,
    "/ConsumedAmphours": -10.0,
    "/Capacity": 90.0,
    "/Soc": 90.0,
    "/TimeToGo": 3600.0,
    "/Voltages/Sum": 52.0,
    "/System/NrOfModulesOnline": 1,
    "/System/NrOfModulesOffline": 0,
    "/System/NrOfModulesBlockingCharge": 0,
    "/System/NrOfModulesBlockingDischarge": 0,
    "/Info/MaxChargeCurrent": 50.0,
    "/Info/MaxDischargeCurrent": 50.0,
    "/Info/MaxChargeVoltage": 55.2,
    "/Info/ChargeMode": "Bulk",
    "/Io/AllowToCharge": 1,
    "/Io/AllowToDischarge": 1,
    "/Io/AllowToBalance": 1,
}


class Battery:
    """Scripted D-Bus answers for one constituent battery."""

    def __init__(
        self,
        name,
        voltage=52.0,
        # zero current by default keeps the Coulomb counter still
        current=0.0,
        power=0.0,
        temperature=22.0,
        max_cell_voltage=3.35,
        max_voltage_cell_id=1,
        min_cell_voltage=3.30,
        min_voltage_cell_id=2,
        max_cell_temperature=25.0,
        max_temperature_cell_id=3,
        min_cell_temperature=20.0,
        min_temperature_cell_id=4,
    ):
        self.name = name
        self.service = "com.victronenergy.battery.%s" % name
        self.voltage = voltage
        self.current = current
        self.power = power
        self.temperature = temperature
        self.max_cell_voltage = max_cell_voltage
        self.max_voltage_cell_id = max_voltage_cell_id
        self.min_cell_voltage = min_cell_voltage
        self.min_voltage_cell_id = min_voltage_cell_id
        self.max_cell_temperature = max_cell_temperature
        self.max_temperature_cell_id = max_temperature_cell_id
        self.min_cell_temperature = min_cell_temperature
        self.min_temperature_cell_id = min_temperature_cell_id

    @property
    def max_voltage_key(self):
        """The dictionary key the driver builds for this battery's max cell voltage."""
        return "%s: %s" % (self.name, self.max_voltage_cell_id)

    @property
    def min_voltage_key(self):
        return "%s: %s" % (self.name, self.min_voltage_cell_id)

    @property
    def max_temperature_key(self):
        return "%s: %s" % (self.name, self.max_temperature_cell_id)

    @property
    def min_temperature_key(self):
        return "%s: %s" % (self.name, self.min_temperature_cell_id)

    def values(self):
        values = {(self.service, path): value for path, value in HEALTHY_BATTERY.items()}
        values[(self.service, "/CustomName")] = self.name
        values[(self.service, "/Dc/0/Voltage")] = self.voltage
        values[(self.service, "/Dc/0/Current")] = self.current
        values[(self.service, "/Dc/0/Power")] = self.power
        values[(self.service, "/Dc/0/Temperature")] = self.temperature
        values[(self.service, "/System/MaxCellVoltage")] = self.max_cell_voltage
        values[(self.service, "/System/MaxVoltageCellId")] = self.max_voltage_cell_id
        values[(self.service, "/System/MinCellVoltage")] = self.min_cell_voltage
        values[(self.service, "/System/MinVoltageCellId")] = self.min_voltage_cell_id
        values[(self.service, "/System/MaxCellTemperature")] = self.max_cell_temperature
        values[(self.service, "/System/MaxTemperatureCellId")] = self.max_temperature_cell_id
        values[(self.service, "/System/MinCellTemperature")] = self.min_cell_temperature
        values[(self.service, "/System/MinTemperatureCellId")] = self.min_temperature_cell_id
        for cell in range(1, NR_OF_CELLS + 1):
            values[(self.service, "/Voltages/Cell%d" % cell)] = 3.3
        for alarm in ALARM_PATHS:
            values[(self.service, alarm)] = 0
        return values


class DriverTestCase(unittest.TestCase):
    """Base class that builds a runnable DbusAggBatService around scripted batteries."""

    def setUp(self):
        # never touch the filesystem from a unit test
        patcher = mock.patch.object(driver, "_write_atomic")
        self.write_atomic = patcher.start()
        self.addCleanup(patcher.stop)

    def _patch_settings(self, **overrides):
        defaults = {
            "NR_OF_CELLS_PER_BATTERY": NR_OF_CELLS,
            "CAN_batteries": False,
            "OWN_SOC": False,
            "OWN_CHARGE_PARAMETERS": False,
            "CURRENT_FROM_VICTRON": False,
            "KEEP_MAX_CVL": False,
            "SEND_CELL_VOLTAGES": 0,
            "LOG_PERIOD": 0,
            "READ_TRIALS": 10,
            "CHARGE_SAVE_PRECISION": 0.01,
            "TIME_BEFORE_RESTART": 0,
        }
        defaults.update(overrides)
        for name, value in defaults.items():
            patcher = mock.patch.object(driver.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_service(self, batteries, **settings_overrides):
        """Build a DbusAggBatService wired to `batteries`, ready for _update()."""

        settings_overrides.setdefault("NR_OF_BATTERIES", len(batteries))
        self._patch_settings(**settings_overrides)

        values = {}
        for battery in batteries:
            values.update(battery.values())

        return new_service(
            _fn=driver.Functions(),
            _batteries_dict={battery.name: battery.service for battery in batteries},
            _dbusMon=FakeDbusMon(values),
            _dbusservice=RecordingDbusService(),
            _readTrials=1,
            _multi=None,
            _multi_connected=False,
            _mppts_list=[],
            _smartShunt_list=[],
            _num_battery_shunts=0,
            _ownCharge=90.0,
            _ownCharge_old=90.0,
            _timeOld=driver.tt.time(),
            _balancing=0,
            _lastBalancing=0,
            _dynamicCVL=False,
            _dynCVLactivated=False,
            _DCfeedActive=False,
            _fullyDischarged=False,
            _logLastPrintTimeStamp=int(driver.tt.time()),
            _reactive_ready=True,
            _updating=False,
        )

    def assertNothingWarned(self, service):
        """Run _update() and assert not a single warning was emitted."""
        collector = WarningCollector()
        root = logging.getLogger()
        root.addHandler(collector)
        try:
            result = service._update()
        finally:
            root.removeHandler(collector)
        self.assertEqual([], collector.messages)
        return result
