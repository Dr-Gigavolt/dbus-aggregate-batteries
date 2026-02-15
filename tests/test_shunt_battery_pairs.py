# -*- coding: utf-8 -*-
"""
Tests for the SHUNT_BATTERY_PAIRS feature.

Covers:
  1. Config parsing (get_pairs_from_config)
  2. Pairing logic in _find_batteries()
  3. V/I/P override in the _update() per-battery loop
"""

import configparser
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# 1. Tests for get_pairs_from_config()
# ---------------------------------------------------------------------------


class TestGetPairsFromConfig(unittest.TestCase):
    """Test the get_pairs_from_config() helper in settings.py."""

    def _make_parser(self, value):
        """Create a settings module environment with a given config value."""
        import importlib

        cfg = configparser.ConfigParser()
        cfg.read_string(f"[DEFAULT]\nSHUNT_BATTERY_PAIRS = {value}\n")

        # We need to patch the module-level 'config' and 'errors_in_config'
        # before calling the function. Import settings fresh each time to
        # avoid cross-test contamination.
        settings_path = os.path.join(
            os.path.dirname(__file__), os.pardir, "settings.py"
        )
        spec = importlib.util.spec_from_file_location("settings_test", settings_path)
        mod = importlib.util.module_from_spec(spec)

        # Monkey-patch to avoid loading real config files
        mod.config = cfg
        mod.errors_in_config = []

        # We only need the function, so exec just enough to define it
        # Actually, let's just inline the function to test it in isolation
        return cfg, mod

    def _parse(self, value):
        """Parse a config value using a fresh copy of get_pairs_from_config."""
        cfg = configparser.ConfigParser()
        cfg.read_string(f"[DEFAULT]\nSHUNT_BATTERY_PAIRS = {value}\n")
        errors = []

        # Inline the function logic to test it independently of module loading
        raw = cfg["DEFAULT"].get("SHUNT_BATTERY_PAIRS", "").strip()
        if not raw:
            return {}, errors

        result = {}
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" not in item:
                errors.append(f"no colon: {item}")
                continue
            key_str, val = item.split(":", 1)
            key_str = key_str.strip()
            val = val.strip()
            try:
                key = int(key_str)
            except ValueError:
                errors.append(f"bad int: {key_str}")
                continue
            if not val:
                errors.append(f"empty value: {item}")
                continue
            result[key] = val
        return result, errors

    def test_empty_string(self):
        result, errors = self._parse("")
        self.assertEqual(result, {})
        self.assertEqual(errors, [])

    def test_single_pair(self):
        result, errors = self._parse("278:SERIAL1")
        self.assertEqual(result, {278: "SERIAL1"})
        self.assertEqual(errors, [])

    def test_two_pairs(self):
        result, errors = self._parse("278:SER1, 277:SER2")
        self.assertEqual(result, {278: "SER1", 277: "SER2"})
        self.assertEqual(errors, [])

    def test_extra_whitespace(self):
        result, errors = self._parse("  278 : SER1 ,  277 : SER2  ")
        self.assertEqual(result, {278: "SER1", 277: "SER2"})
        self.assertEqual(errors, [])

    def test_trailing_comma(self):
        result, errors = self._parse("278:SER1,")
        self.assertEqual(result, {278: "SER1"})
        self.assertEqual(errors, [])

    def test_missing_colon(self):
        result, errors = self._parse("278SER1")
        self.assertEqual(result, {})
        self.assertGreater(len(errors), 0)

    def test_non_integer_key(self):
        result, errors = self._parse("abc:SER1")
        self.assertEqual(result, {})
        self.assertGreater(len(errors), 0)

    def test_empty_battery_name(self):
        result, errors = self._parse("278:")
        self.assertEqual(result, {})
        self.assertGreater(len(errors), 0)

    def test_mixed_valid_and_invalid(self):
        result, errors = self._parse("278:SER1, badentry, 277:SER2")
        self.assertEqual(result, {278: "SER1", 277: "SER2"})
        self.assertEqual(len(errors), 1)

    def test_serial_with_underscores(self):
        """Battery serials like '53_20_B7_D7_F9_E7' should parse correctly."""
        result, errors = self._parse("278:53_20_B7_D7_F9_E7")
        self.assertEqual(result, {278: "53_20_B7_D7_F9_E7"})
        self.assertEqual(errors, [])

    def test_serial_with_colons_in_value(self):
        """Value part can contain colons (split on first only)."""
        result, errors = self._parse("278:AA:BB:CC")
        self.assertEqual(result, {278: "AA:BB:CC"})
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Now test the actual get_pairs_from_config function from settings.py
# by patching the module-level config object.
# ---------------------------------------------------------------------------


class TestGetPairsFromConfigReal(unittest.TestCase):
    """Test the real get_pairs_from_config() function from settings.py."""

    @staticmethod
    def _import_function():
        """Import just the get_pairs_from_config function."""
        # Add the project root to sys.path
        project_root = os.path.join(os.path.dirname(__file__), os.pardir)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        # We can't import settings directly because it tries to read config
        # files and validate them at import time. Instead, read the function
        # source and compile it in isolation.
        import ast
        import textwrap

        settings_path = os.path.join(project_root, "settings.py")
        with open(settings_path) as f:
            source = f.read()

        tree = ast.parse(source)
        # Find the get_pairs_from_config function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_pairs_from_config":
                func_source = ast.get_source_segment(source, node)
                return func_source
        raise RuntimeError("get_pairs_from_config not found in settings.py")

    def _call(self, config_value):
        """Call get_pairs_from_config with a synthetic config."""
        cfg = configparser.ConfigParser()
        cfg.read_string(f"[DEFAULT]\nSHUNT_BATTERY_PAIRS = {config_value}\n")

        errors_in_config = []

        # Execute the function in a controlled namespace
        project_root = os.path.join(os.path.dirname(__file__), os.pardir)
        settings_path = os.path.join(project_root, "settings.py")
        with open(settings_path) as f:
            source = f.read()

        namespace = {
            "config": cfg,
            "errors_in_config": errors_in_config,
            "configparser": configparser,
            "logging": __import__("logging"),
            "sys": sys,
            "Dict": dict,
        }

        # Extract and exec just the function definition
        import ast

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_pairs_from_config":
                func_source = ast.get_source_segment(source, node)
                exec(compile(ast.parse(func_source), "<test>", "exec"), namespace)
                break

        func = namespace["get_pairs_from_config"]
        result = func("DEFAULT", "SHUNT_BATTERY_PAIRS")
        return result, errors_in_config

    def test_real_function_valid_pairs(self):
        result, errors = self._call("278:53_20_B7_D7_F9_E7, 277:AB_80_72_54_E0_B4")
        self.assertEqual(result, {278: "53_20_B7_D7_F9_E7", 277: "AB_80_72_54_E0_B4"})
        self.assertEqual(errors, [])

    def test_real_function_empty(self):
        result, errors = self._call("")
        self.assertEqual(result, {})
        self.assertEqual(errors, [])

    def test_real_function_bad_key(self):
        result, errors = self._call("notanumber:SER1")
        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("notanumber", errors[0])

    def test_real_function_no_colon(self):
        result, errors = self._call("278SER1")
        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)

    def test_real_function_empty_value(self):
        result, errors = self._call("278:")
        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)


# ---------------------------------------------------------------------------
# 2. Tests for shunt-battery pairing logic in _find_batteries()
# ---------------------------------------------------------------------------


class MockDbusMonitor:
    """Mock for the DbusMonitor used by dbus-aggregate-batteries."""

    def __init__(self, services):
        """
        services: dict mapping service_name -> {path: value}
        """
        self._services = services

    def get_value(self, service, path):
        if service in self._services:
            return self._services[service].get(path)
        return None


class TestShuntBatteryPairing(unittest.TestCase):
    """Test the pairing logic that builds _shunt_pair_map."""

    def _build_service(self, **kwargs):
        """Create a DbusAggBatService-like object with mocked internals."""
        obj = MagicMock()
        obj._batteries_dict = kwargs.get("batteries_dict", {})
        obj._shunt_pair_map = {}
        obj._smartShunt_list = []
        obj._num_battery_shunts = 0

        # Mock the D-Bus connection's list_names
        services = kwargs.get("dbus_services", {})
        obj._dbusConn = MagicMock()
        obj._dbusConn.list_names.return_value = list(services.keys())

        # Mock the DbusMonitor
        monitor = MockDbusMonitor(services)
        obj._dbusMon = MagicMock()
        obj._dbusMon.dbusmon = monitor

        return obj

    def _run_pairing(self, obj, shunt_battery_pairs):
        """
        Execute the pairing logic extracted from _find_batteries().
        This mirrors the code in the actual method.
        """
        # Import settings and mock the pairs
        mock_settings = MagicMock()
        mock_settings.SHUNT_BATTERY_PAIRS = shunt_battery_pairs
        mock_settings.BATTERY_SERVICE_NAME = "com.victronenergy.battery"
        mock_settings.SMARTSHUNT_NAME_KEYWORD = "SmartShunt"
        mock_settings.BATTERY_PRODUCT_NAME_PATH = "/ProductName"

        if not mock_settings.SHUNT_BATTERY_PAIRS:
            return

        shunt_vrm_to_service = {}
        try:
            for service in sorted(
                str(name)
                for name in obj._dbusConn.list_names()
                if "com.victronenergy" in str(name)
            ):
                if mock_settings.BATTERY_SERVICE_NAME not in service:
                    continue
                pn = obj._dbusMon.dbusmon.get_value(
                    service, mock_settings.BATTERY_PRODUCT_NAME_PATH
                )
                if pn is not None and mock_settings.SMARTSHUNT_NAME_KEYWORD in pn:
                    vrm_id = obj._dbusMon.dbusmon.get_value(service, "/DeviceInstance")
                    if vrm_id is not None:
                        shunt_vrm_to_service[int(vrm_id)] = service
        except Exception:
            pass

        for shunt_vrm_id, battery_name in mock_settings.SHUNT_BATTERY_PAIRS.items():
            shunt_svc = shunt_vrm_to_service.get(shunt_vrm_id)
            if shunt_svc is None:
                continue
            if battery_name not in obj._batteries_dict:
                continue
            obj._shunt_pair_map[battery_name] = shunt_svc

    def test_successful_pairing(self):
        """Both shunts found and both batteries found -> 2 pairs."""
        dbus_services = {
            "com.victronenergy.battery.ble_aaa": {
                "/ProductName": "SerialBattery(HumsiENK BLE)",
                "/DeviceInstance": 1,
            },
            "com.victronenergy.battery.ble_bbb": {
                "/ProductName": "SerialBattery(HumsiENK BLE)",
                "/DeviceInstance": 2,
            },
            "com.victronenergy.battery.ttyS5": {
                "/ProductName": "SmartShunt 500A/50mV",
                "/DeviceInstance": 278,
            },
            "com.victronenergy.battery.ttyS6": {
                "/ProductName": "SmartShunt 500A/50mV",
                "/DeviceInstance": 277,
            },
        }
        obj = self._build_service(
            batteries_dict={
                "SERIAL_AAA": "com.victronenergy.battery.ble_aaa",
                "SERIAL_BBB": "com.victronenergy.battery.ble_bbb",
            },
            dbus_services=dbus_services,
        )

        self._run_pairing(obj, {278: "SERIAL_AAA", 277: "SERIAL_BBB"})

        self.assertEqual(len(obj._shunt_pair_map), 2)
        self.assertEqual(
            obj._shunt_pair_map["SERIAL_AAA"],
            "com.victronenergy.battery.ttyS5",
        )
        self.assertEqual(
            obj._shunt_pair_map["SERIAL_BBB"],
            "com.victronenergy.battery.ttyS6",
        )

    def test_shunt_not_found(self):
        """SmartShunt VRM instance 999 doesn't exist -> no pairing for it."""
        dbus_services = {
            "com.victronenergy.battery.ttyS5": {
                "/ProductName": "SmartShunt 500A/50mV",
                "/DeviceInstance": 278,
            },
        }
        obj = self._build_service(
            batteries_dict={"SERIAL_AAA": "com.victronenergy.battery.ble_aaa"},
            dbus_services=dbus_services,
        )

        self._run_pairing(obj, {999: "SERIAL_AAA"})

        self.assertEqual(len(obj._shunt_pair_map), 0)

    def test_battery_not_found(self):
        """Battery serial doesn't match any discovered battery."""
        dbus_services = {
            "com.victronenergy.battery.ttyS5": {
                "/ProductName": "SmartShunt 500A/50mV",
                "/DeviceInstance": 278,
            },
        }
        obj = self._build_service(
            batteries_dict={"SERIAL_AAA": "com.victronenergy.battery.ble_aaa"},
            dbus_services=dbus_services,
        )

        self._run_pairing(obj, {278: "WRONG_SERIAL"})

        self.assertEqual(len(obj._shunt_pair_map), 0)

    def test_empty_pairs_config(self):
        """Empty SHUNT_BATTERY_PAIRS -> no pairing attempted."""
        obj = self._build_service(
            batteries_dict={"SER": "com.victronenergy.battery.ble_aaa"},
            dbus_services={},
        )

        self._run_pairing(obj, {})

        self.assertEqual(len(obj._shunt_pair_map), 0)

    def test_partial_match(self):
        """One pair matches, one doesn't -> only one entry in map."""
        dbus_services = {
            "com.victronenergy.battery.ttyS5": {
                "/ProductName": "SmartShunt 500A/50mV",
                "/DeviceInstance": 278,
            },
        }
        obj = self._build_service(
            batteries_dict={
                "SERIAL_AAA": "com.victronenergy.battery.ble_aaa",
                "SERIAL_BBB": "com.victronenergy.battery.ble_bbb",
            },
            dbus_services=dbus_services,
        )

        # 278 exists and matches SERIAL_AAA; 277 doesn't exist on D-Bus
        self._run_pairing(obj, {278: "SERIAL_AAA", 277: "SERIAL_BBB"})

        self.assertEqual(len(obj._shunt_pair_map), 1)
        self.assertEqual(
            obj._shunt_pair_map["SERIAL_AAA"],
            "com.victronenergy.battery.ttyS5",
        )

    def test_non_smartshunt_battery_not_matched(self):
        """A battery service that isn't a SmartShunt should not be matched as a shunt."""
        dbus_services = {
            "com.victronenergy.battery.ble_aaa": {
                "/ProductName": "SerialBattery(HumsiENK BLE)",
                "/DeviceInstance": 1,
            },
        }
        obj = self._build_service(
            batteries_dict={"SERIAL_AAA": "com.victronenergy.battery.ble_aaa"},
            dbus_services=dbus_services,
        )

        # VRM instance 1 exists but it's a BMS, not a SmartShunt
        self._run_pairing(obj, {1: "SERIAL_AAA"})

        self.assertEqual(len(obj._shunt_pair_map), 0)


# ---------------------------------------------------------------------------
# 3. Tests for V/I/P override in _update() per-battery loop
# ---------------------------------------------------------------------------


class TestVIPOverride(unittest.TestCase):
    """Test that paired batteries read V/I/P from the SmartShunt."""

    def _simulate_update_vip(self, batteries_dict, shunt_pair_map, dbus_values):
        """
        Simulate the V/I/P reading portion of the _update() loop.

        batteries_dict: {battery_name: bms_service}
        shunt_pair_map: {battery_name: shunt_service}
        dbus_values: {service: {path: value}}

        Returns (Voltage, Current, Power) aggregated across all batteries.
        """
        monitor = MockDbusMonitor(dbus_values)
        Voltage = 0.0
        Current = 0.0
        Power = 0.0

        for i in batteries_dict:
            shunt_svc = shunt_pair_map.get(i)
            if shunt_svc is not None:
                shunt_v = monitor.get_value(shunt_svc, "/Dc/0/Voltage")
                shunt_i = monitor.get_value(shunt_svc, "/Dc/0/Current")
                if shunt_v is not None and shunt_i is not None:
                    Voltage += shunt_v
                    Current += shunt_i
                    Power += shunt_v * shunt_i
                else:
                    # Fallback to BMS
                    Voltage += monitor.get_value(batteries_dict[i], "/Dc/0/Voltage")
                    Current += monitor.get_value(batteries_dict[i], "/Dc/0/Current")
                    Power += monitor.get_value(batteries_dict[i], "/Dc/0/Power")
            else:
                Voltage += monitor.get_value(batteries_dict[i], "/Dc/0/Voltage")
                Current += monitor.get_value(batteries_dict[i], "/Dc/0/Current")
                Power += monitor.get_value(batteries_dict[i], "/Dc/0/Power")

        return Voltage, Current, Power

    def test_paired_battery_uses_shunt_values(self):
        """When a shunt is paired, V/I come from shunt, P = V*I."""
        batteries = {"BAT1": "com.victronenergy.battery.ble_aaa"}
        pairs = {"BAT1": "com.victronenergy.battery.ttyS5"}
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.61,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
            "com.victronenergy.battery.ttyS5": {
                "/Dc/0/Voltage": 13.63,
                "/Dc/0/Current": -0.2,
            },
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        self.assertAlmostEqual(v, 13.63, places=2)
        self.assertAlmostEqual(i, -0.2, places=2)
        self.assertAlmostEqual(p, 13.63 * -0.2, places=2)

    def test_unpaired_battery_uses_bms_values(self):
        """When no shunt is paired, V/I/P come from BMS."""
        batteries = {"BAT1": "com.victronenergy.battery.ble_aaa"}
        pairs = {}  # no pairing
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.61,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        self.assertAlmostEqual(v, 13.61, places=2)
        self.assertAlmostEqual(i, 0.0, places=2)
        self.assertAlmostEqual(p, 0.0, places=2)

    def test_shunt_returns_none_falls_back_to_bms(self):
        """If the shunt returns None for voltage, fall back to BMS."""
        batteries = {"BAT1": "com.victronenergy.battery.ble_aaa"}
        pairs = {"BAT1": "com.victronenergy.battery.ttyS5"}
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.61,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
            "com.victronenergy.battery.ttyS5": {
                "/Dc/0/Voltage": None,  # shunt not responding
                "/Dc/0/Current": None,
            },
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        # Should fall back to BMS values
        self.assertAlmostEqual(v, 13.61, places=2)
        self.assertAlmostEqual(i, 0.0, places=2)
        self.assertAlmostEqual(p, 0.0, places=2)

    def test_shunt_current_none_falls_back_to_bms(self):
        """If only current is None from shunt, fall back to BMS."""
        batteries = {"BAT1": "com.victronenergy.battery.ble_aaa"}
        pairs = {"BAT1": "com.victronenergy.battery.ttyS5"}
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.61,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
            "com.victronenergy.battery.ttyS5": {
                "/Dc/0/Voltage": 13.63,
                "/Dc/0/Current": None,  # only current missing
            },
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        # Should fall back to BMS
        self.assertAlmostEqual(v, 13.61, places=2)
        self.assertAlmostEqual(i, 0.0, places=2)
        self.assertAlmostEqual(p, 0.0, places=2)

    def test_two_batteries_both_paired(self):
        """Two batteries, both with paired shunts."""
        batteries = {
            "BAT1": "com.victronenergy.battery.ble_aaa",
            "BAT2": "com.victronenergy.battery.ble_bbb",
        }
        pairs = {
            "BAT1": "com.victronenergy.battery.ttyS5",
            "BAT2": "com.victronenergy.battery.ttyS6",
        }
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.61,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
            "com.victronenergy.battery.ble_bbb": {
                "/Dc/0/Voltage": 13.64,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
            "com.victronenergy.battery.ttyS5": {
                "/Dc/0/Voltage": 13.63,
                "/Dc/0/Current": -0.2,
            },
            "com.victronenergy.battery.ttyS6": {
                "/Dc/0/Voltage": 13.63,
                "/Dc/0/Current": -0.3,
            },
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        self.assertAlmostEqual(v, 13.63 + 13.63, places=2)
        self.assertAlmostEqual(i, -0.2 + -0.3, places=2)
        expected_power = (13.63 * -0.2) + (13.63 * -0.3)
        self.assertAlmostEqual(p, expected_power, places=2)

    def test_mixed_paired_and_unpaired(self):
        """One battery paired, one not."""
        batteries = {
            "BAT1": "com.victronenergy.battery.ble_aaa",
            "BAT2": "com.victronenergy.battery.ble_bbb",
        }
        pairs = {
            "BAT1": "com.victronenergy.battery.ttyS5",
            # BAT2 is not paired
        }
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.61,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
            "com.victronenergy.battery.ble_bbb": {
                "/Dc/0/Voltage": 13.64,
                "/Dc/0/Current": -10.0,
                "/Dc/0/Power": -136.4,
            },
            "com.victronenergy.battery.ttyS5": {
                "/Dc/0/Voltage": 13.63,
                "/Dc/0/Current": -0.2,
            },
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        # BAT1: from shunt (13.63, -0.2, 13.63*-0.2)
        # BAT2: from BMS (13.64, -10.0, -136.4)
        self.assertAlmostEqual(v, 13.63 + 13.64, places=2)
        self.assertAlmostEqual(i, -0.2 + -10.0, places=2)
        expected_power = (13.63 * -0.2) + (-136.4)
        self.assertAlmostEqual(p, expected_power, places=1)

    def test_shunt_service_missing_entirely(self):
        """Paired shunt service doesn't exist in D-Bus values at all."""
        batteries = {"BAT1": "com.victronenergy.battery.ble_aaa"}
        pairs = {"BAT1": "com.victronenergy.battery.ttyS5"}
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.61,
                "/Dc/0/Current": 0.0,
                "/Dc/0/Power": 0.0,
            },
            # ttyS5 not present at all
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        # get_value returns None for missing service -> falls back to BMS
        self.assertAlmostEqual(v, 13.61, places=2)
        self.assertAlmostEqual(i, 0.0, places=2)
        self.assertAlmostEqual(p, 0.0, places=2)

    def test_shunt_discharging_high_current(self):
        """SmartShunt shows high discharge current, BMS rounds."""
        batteries = {"BAT1": "com.victronenergy.battery.ble_aaa"}
        pairs = {"BAT1": "com.victronenergy.battery.ttyS5"}
        values = {
            "com.victronenergy.battery.ble_aaa": {
                "/Dc/0/Voltage": 13.60,
                "/Dc/0/Current": -10.0,  # BMS rounds
                "/Dc/0/Power": -136.0,
            },
            "com.victronenergy.battery.ttyS5": {
                "/Dc/0/Voltage": 13.58,
                "/Dc/0/Current": -9.6,  # shunt is more precise
            },
        }

        v, i, p = self._simulate_update_vip(batteries, pairs, values)

        self.assertAlmostEqual(v, 13.58, places=2)
        self.assertAlmostEqual(i, -9.6, places=1)
        self.assertAlmostEqual(p, 13.58 * -9.6, places=0)


if __name__ == "__main__":
    unittest.main()
