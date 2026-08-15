#!/usr/bin/env python3

"""
Test harness for driving the real ``DbusAggBatService._update()`` off-device.

``dbus``, ``vedbus`` and ``gi``/``GLib`` are not installed off a Venus OS
device, so they are stubbed in ``sys.modules`` before the driver module is
loaded, and the driver is loaded by path because its file name contains dashes.
``_update()`` can then be invoked on an instance created with
``object.__new__`` and wired to a fake D-Bus monitor that serves scripted
values per (service, path) and a fake gated D-Bus service that records what was
published.

No driver logic is re-implemented here: this module only supplies the
scaffolding, so every assertion in the test modules is about what the driver
itself computed.
"""

import importlib.util
import logging
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER_PATH = os.path.join(REPO_ROOT, "dbus-aggregate-batteries.py")

NR_OF_CELLS = 4


def _install_module_stubs():
    """Put stand-ins for the Venus OS only imports into sys.modules."""

    glib = types.ModuleType("gi.repository.GLib")
    glib.MainLoop = mock.MagicMock(name="GLib.MainLoop")
    glib.timeout_add = mock.MagicMock(name="GLib.timeout_add", return_value=0)
    glib.timeout_add_seconds = mock.MagicMock(name="GLib.timeout_add_seconds", return_value=0)

    repository = types.ModuleType("gi.repository")
    repository.GLib = glib

    gi = types.ModuleType("gi")
    gi.repository = repository
    gi.require_version = mock.MagicMock(name="gi.require_version")

    dbus_mainloop_glib = types.ModuleType("dbus.mainloop.glib")
    dbus_mainloop_glib.DBusGMainLoop = mock.MagicMock(name="DBusGMainLoop")

    dbus_mainloop = types.ModuleType("dbus.mainloop")
    dbus_mainloop.glib = dbus_mainloop_glib

    dbus = types.ModuleType("dbus")
    dbus.SystemBus = mock.MagicMock(name="dbus.SystemBus")
    dbus.SessionBus = mock.MagicMock(name="dbus.SessionBus")
    dbus.Interface = mock.MagicMock(name="dbus.Interface")
    dbus.mainloop = dbus_mainloop

    vedbus = types.ModuleType("vedbus")
    vedbus.VeDbusService = mock.MagicMock(name="VeDbusService")
    vedbus.VeDbusItemImport = mock.MagicMock(name="VeDbusItemImport")

    dbusmon = types.ModuleType("dbusmon")
    dbusmon.DbusMon = mock.MagicMock(name="DbusMon")

    for name, module in (
        ("gi", gi),
        ("gi.repository", repository),
        ("gi.repository.GLib", glib),
        ("dbus", dbus),
        ("dbus.mainloop", dbus_mainloop),
        ("dbus.mainloop.glib", dbus_mainloop_glib),
        ("vedbus", vedbus),
        ("dbusmon", dbusmon),
    ):
        sys.modules[name] = module


def _load_settings():
    """
    Import the real settings module against a throwaway config.

    settings.py refuses to import (sys.exit(1)) unless a config.ini supplies
    NR_OF_BATTERIES and NR_OF_CELLS_PER_BATTERY, and it resolves both config
    files relative to its own __file__. So it is loaded from a temporary copy
    of the repo's settings.py + config.default.ini next to a minimal config.ini,
    which leaves the working tree untouched. The individual settings each test
    depends on are patched anyway.
    """

    tmpdir = tempfile.mkdtemp(prefix="dbus_agg_bat_settings_")
    try:
        shutil.copy(os.path.join(REPO_ROOT, "settings.py"), tmpdir)
        shutil.copy(os.path.join(REPO_ROOT, "config.default.ini"), tmpdir)
        with open(os.path.join(tmpdir, "config.ini"), "w") as config:
            config.write("[DEFAULT]\nNR_OF_BATTERIES = 2\nNR_OF_CELLS_PER_BATTERY = %d\n" % NR_OF_CELLS)

        spec = importlib.util.spec_from_file_location("settings", os.path.join(tmpdir, "settings.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules["settings"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _load_driver():
    """Load dbus-aggregate-batteries.py by path, with the stubs already in place."""

    _install_module_stubs()
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    _load_settings()

    spec = importlib.util.spec_from_file_location("dbus_aggregate_batteries_under_test", DRIVER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


driver = _load_driver()


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


class FakeDbusMonitor:
    """Stands in for DbusMon().dbusmon: scripted get_value per (service, path)."""

    def __init__(self, values):
        self._values = values
        self.set_calls = []

    def get_value(self, service, path):
        return self._values.get((service, path), 0)

    def set_value(self, service, path, value):
        self.set_calls.append((service, path, value))
        return 0


class FakeDbusMon:
    def __init__(self, values):
        self.dbusmon = FakeDbusMonitor(values)


class FakeDbusService:
    """Stands in for the VeDbusService used as `with self._dbusservice as bus`."""

    def __init__(self):
        self.published = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def __setitem__(self, path, value):
        self.published[path] = value

    def __getitem__(self, path):
        return self.published[path]


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

        service = object.__new__(driver.DbusAggBatService)
        service._fn = driver.Functions()
        service._batteries_dict = {battery.name: battery.service for battery in batteries}
        service._dbusMon = FakeDbusMon(values)
        service._dbusservice = FakeDbusService()
        service._readTrials = 1
        service._multi = None
        service._multi_connected = False
        service._mppts_list = []
        service._smartShunt_list = []
        service._num_battery_shunts = 0
        service._ownCharge = 90.0
        service._ownCharge_old = 90.0
        service._timeOld = driver.tt.time()
        service._balancing = 0
        service._lastBalancing = 0
        service._dynamicCVL = False
        service._dynCVLactivated = False
        service._DCfeedActive = False
        service._fullyDischarged = False
        service._logLastPrintTimeStamp = int(driver.tt.time())
        return service

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
