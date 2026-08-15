#!/usr/bin/env python3

"""
Unit tests for the cell voltage / cell temperature extrema aggregation inside
``DbusAggBatService._update()``.

These tests exercise the *real* driver code. ``dbus``, ``vedbus`` and
``gi``/``GLib`` are not installed off-device, so they are stubbed in
``sys.modules`` before the driver module is loaded, and the driver is loaded by
path because its file name contains dashes. ``_update()`` is then invoked on an
instance created with ``object.__new__`` and wired to a fake D-Bus monitor that
serves scripted values per (service, path) and a fake gated D-Bus service that
records the published values.

Nothing here re-implements the aggregation logic: every assertion is about what
the driver itself computed and published.
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

# Values that keep every non-extrema part of _update() happy and boring, so the
# only thing a test varies is the cell extrema.
HEALTHY_BATTERY = {
    "/Dc/0/Voltage": 52.0,
    # zero current keeps the Coulomb counter still and avoids any state file write
    "/Dc/0/Current": 0.0,
    "/Dc/0/Power": 0.0,
    "/InstalledCapacity": 100.0,
    "/ConsumedAmphours": -10.0,
    "/Capacity": 90.0,
    "/Soc": 90.0,
    "/TimeToGo": 3600.0,
    "/Dc/0/Temperature": 22.0,
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


class CellExtremaTestCase(unittest.TestCase):
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


class PartialCellVoltageDataTest(CellExtremaTestCase):
    """One battery reports no cell voltages, the other does."""

    def setUp(self):
        super().setUp()
        self.silent = Battery("Stale", max_cell_voltage=None, min_cell_voltage=None)
        self.reporting = Battery(
            "Reporting",
            max_cell_voltage=3.48,
            max_voltage_cell_id=7,
            min_cell_voltage=3.21,
            min_voltage_cell_id=11,
        )
        self.service = self.make_service([self.silent, self.reporting])

    def test_aggregation_uses_the_reporting_battery(self):
        with self.assertLogs(level="WARNING"):
            self.assertTrue(self.service._update())

        published = self.service._dbusservice.published
        self.assertEqual(3.48, published["/System/MaxCellVoltage"])
        self.assertEqual("Reporting: 7", published["/System/MaxVoltageCellId"])
        self.assertEqual(3.21, published["/System/MinCellVoltage"])
        self.assertEqual("Reporting: 11", published["/System/MinVoltageCellId"])
        self.assertEqual(0.27, published["/Voltages/Diff"])

    def test_read_trial_counter_is_not_advanced(self):
        """A single stale constituent is tolerated, not treated as a read failure."""
        with self.assertLogs(level="WARNING"):
            self.service._update()
        self.assertEqual(1, self.service._readTrials)

    def test_skipped_battery_is_named_in_a_warning(self):
        with self.assertLogs(level="WARNING") as captured:
            self.service._update()

        voltage_warnings = [message for message in captured.output if "Cell voltage missing" in message]
        self.assertEqual(1, len(voltage_warnings))
        self.assertIn(self.silent.max_voltage_key, voltage_warnings[0])
        self.assertIn("excluded from aggregation this cycle", voltage_warnings[0])
        # the healthy battery must never be named as skipped
        self.assertNotIn(self.reporting.name, voltage_warnings[0])


class PartialCellTemperatureDataTest(CellExtremaTestCase):
    """Same contract for the temperature dimension."""

    def setUp(self):
        super().setUp()
        self.silent = Battery("Stale", max_cell_temperature=None, min_cell_temperature=None)
        self.reporting = Battery(
            "Reporting",
            max_cell_temperature=31.5,
            max_temperature_cell_id=2,
            min_cell_temperature=17.5,
            min_temperature_cell_id=5,
        )
        self.service = self.make_service([self.silent, self.reporting])

    def test_aggregation_uses_the_reporting_battery(self):
        with self.assertLogs(level="WARNING"):
            self.assertTrue(self.service._update())

        published = self.service._dbusservice.published
        self.assertEqual(31.5, published["/System/MaxCellTemperature"])
        self.assertEqual("Reporting: 2", published["/System/MaxTemperatureCellId"])
        self.assertEqual(17.5, published["/System/MinCellTemperature"])
        self.assertEqual("Reporting: 5", published["/System/MinTemperatureCellId"])

    def test_skipped_battery_is_named_in_a_warning(self):
        with self.assertLogs(level="WARNING") as captured:
            self.service._update()

        temperature_warnings = [message for message in captured.output if "Cell temperature missing" in message]
        self.assertEqual(1, len(temperature_warnings))
        self.assertIn(self.silent.max_temperature_key, temperature_warnings[0])
        self.assertIn("excluded from aggregation this cycle", temperature_warnings[0])


class EveryBatterySkippedTest(CellExtremaTestCase):
    """No battery reports extrema: a real read failure, handed to the caller's retry path."""

    def _all_silent_voltage_service(self, **overrides):
        batteries = [
            Battery("BatteryA", max_cell_voltage=None, min_cell_voltage=None),
            Battery("BatteryB", max_cell_voltage=None, min_cell_voltage=None),
        ]
        return self.make_service(batteries, **overrides)

    def _all_silent_temperature_service(self, **overrides):
        batteries = [
            Battery("BatteryA", max_cell_temperature=None, min_cell_temperature=None),
            Battery("BatteryB", max_cell_temperature=None, min_cell_temperature=None),
        ]
        return self.make_service(batteries, **overrides)

    def test_missing_cell_voltages_raise_into_the_read_failure_handler(self):
        service = self._all_silent_voltage_service()
        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self.assertTrue(
            any("No battery reported cell voltages" in message for message in captured.output),
            "expected the ValueError to be raised and logged by the read-failure handler",
        )
        self.assertEqual(2, service._readTrials, "the read trial must be counted")

    def test_no_none_extrema_escape_to_dbus(self):
        service = self._all_silent_voltage_service()
        with self.assertLogs(level="ERROR"):
            service._update()

        published = service._dbusservice.published
        for path in ("/System/MaxCellVoltage", "/System/MinCellVoltage"):
            # nothing at all is published on a failed read; and most importantly
            # never a None
            self.assertIsNone(published.get(path))
            self.assertNotIn(path, published)

    def test_missing_cell_temperatures_raise_into_the_read_failure_handler(self):
        service = self._all_silent_temperature_service()
        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self.assertTrue(
            any("No battery reported cell temperatures" in message for message in captured.output),
            "expected the ValueError to be raised and logged by the read-failure handler",
        )
        self.assertEqual(2, service._readTrials)
        self.assertNotIn("/System/MaxCellTemperature", service._dbusservice.published)

    def test_exhausted_read_trials_restart_the_driver(self):
        """After READ_TRIALS the existing handler exits so the service manager restarts us."""
        service = self._all_silent_voltage_service(READ_TRIALS=1)
        service._readTrials = 1

        with mock.patch("time.sleep") as sleep:
            with self.assertLogs(level="ERROR"):
                with self.assertRaises(SystemExit) as raised:
                    service._update()

        self.assertEqual(1, raised.exception.code)
        sleep.assert_called_once_with(driver.settings.TIME_BEFORE_RESTART)


class AllBatteriesReportingTest(CellExtremaTestCase):
    """The unchanged happy path: nothing skipped, nothing warned."""

    def setUp(self):
        super().setUp()
        self.low = Battery(
            "BatteryA",
            max_cell_voltage=3.40,
            max_voltage_cell_id=1,
            min_cell_voltage=3.30,
            min_voltage_cell_id=2,
            max_cell_temperature=24.0,
            max_temperature_cell_id=3,
            min_cell_temperature=19.0,
            min_temperature_cell_id=4,
        )
        self.high = Battery(
            "BatteryB",
            max_cell_voltage=3.52,
            max_voltage_cell_id=5,
            min_cell_voltage=3.11,
            min_voltage_cell_id=6,
            max_cell_temperature=27.0,
            max_temperature_cell_id=7,
            min_cell_temperature=15.0,
            min_temperature_cell_id=8,
        )
        self.service = self.make_service([self.low, self.high])

    def test_extrema_are_taken_across_all_batteries_without_warnings(self):
        self.assertTrue(self.assertNothingWarned(self.service))

        published = self.service._dbusservice.published
        self.assertEqual(3.52, published["/System/MaxCellVoltage"])
        self.assertEqual("BatteryB: 5", published["/System/MaxVoltageCellId"])
        self.assertEqual(3.11, published["/System/MinCellVoltage"])
        self.assertEqual("BatteryB: 6", published["/System/MinVoltageCellId"])
        self.assertEqual(27.0, published["/System/MaxCellTemperature"])
        self.assertEqual("BatteryB: 7", published["/System/MaxTemperatureCellId"])
        self.assertEqual(15.0, published["/System/MinCellTemperature"])
        self.assertEqual("BatteryB: 8", published["/System/MinTemperatureCellId"])
        self.assertEqual(1, self.service._readTrials)

    def test_extrema_can_come_from_different_batteries(self):
        """Max from one battery, min from another, which is the normal aggregate case."""
        low = Battery("BatteryA", max_cell_voltage=3.55, max_voltage_cell_id=1, min_cell_voltage=3.40, min_voltage_cell_id=2)
        high = Battery("BatteryB", max_cell_voltage=3.45, max_voltage_cell_id=5, min_cell_voltage=3.05, min_voltage_cell_id=6)
        service = self.make_service([low, high])

        self.assertTrue(self.assertNothingWarned(service))

        published = service._dbusservice.published
        self.assertEqual("BatteryA: 1", published["/System/MaxVoltageCellId"])
        self.assertEqual("BatteryB: 6", published["/System/MinVoltageCellId"])


class AsymmetricExtremaTest(CellExtremaTestCase):
    """A battery that reports a max but no min must not yield a mismatched pair."""

    def test_single_battery_with_max_but_no_min_voltage_is_a_read_failure(self):
        battery = Battery("Solo", max_cell_voltage=3.44, max_voltage_cell_id=1, min_cell_voltage=None, min_voltage_cell_id=2)
        service = self.make_service([battery])

        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self.assertTrue(any("No battery reported cell voltages" in message for message in captured.output))
        published = service._dbusservice.published
        # neither half of the pair may reach D-Bus: no 3.44 max with a stale min
        self.assertNotIn("/System/MaxCellVoltage", published)
        self.assertNotIn("/System/MinCellVoltage", published)
        self.assertNotIn("/Voltages/Diff", published)
        self.assertEqual(2, service._readTrials)

    def test_single_battery_with_max_but_no_min_temperature_is_a_read_failure(self):
        battery = Battery("Solo", max_cell_temperature=30.0, max_temperature_cell_id=1, min_cell_temperature=None, min_temperature_cell_id=2)
        service = self.make_service([battery])

        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self.assertTrue(any("No battery reported cell temperatures" in message for message in captured.output))
        published = service._dbusservice.published
        self.assertNotIn("/System/MaxCellTemperature", published)
        self.assertNotIn("/System/MinCellTemperature", published)
        self.assertEqual(2, service._readTrials)

    def test_min_only_missing_is_dropped_without_a_warning(self):
        """
        Characterisation of a gap in the current implementation.

        The warning loops iterate only over the *max* dictionaries, so a battery
        that reports a max but no min is dropped from the min aggregation
        silently. The aggregate below is still arithmetically defensible (a true
        bank max and the best known min), but the skip is not loud, which is at
        odds with the "deliberately loud, never silent" intent of this code.
        """
        partial = Battery("Partial", max_cell_voltage=3.60, max_voltage_cell_id=1, min_cell_voltage=None, min_voltage_cell_id=2)
        healthy = Battery("Healthy", max_cell_voltage=3.40, max_voltage_cell_id=5, min_cell_voltage=3.25, min_voltage_cell_id=6)
        service = self.make_service([partial, healthy])

        collector = WarningCollector()
        root = logging.getLogger()
        root.addHandler(collector)
        try:
            self.assertTrue(service._update())
        finally:
            root.removeHandler(collector)

        published = service._dbusservice.published
        self.assertEqual("Partial: 1", published["/System/MaxVoltageCellId"])
        self.assertEqual("Healthy: 6", published["/System/MinVoltageCellId"])
        self.assertEqual([], collector.messages, "today's behaviour: the dropped min is not announced")


if __name__ == "__main__":
    unittest.main()
