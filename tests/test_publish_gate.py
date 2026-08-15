# -*- coding: utf-8 -*-
"""Unit tests for the D-Bus publish gate in dbus-aggregate-batteries.py.

The gate (``_GatedDbusService`` / ``_GatedDbusServiceContext``) deduplicates
exact repeats for every path, suppresses numeric changes below a per-path
threshold and periodically clears its cache so everything is republished.

The driver imports ``dbus``, ``vedbus`` and ``gi.repository`` which are only
available on Venus OS, so those modules are stubbed in ``sys.modules`` before
the driver is loaded (see ``support.py``). The driver file name contains dashes,
so it is loaded by path with ``importlib``.
"""

import atexit
import os
import shutil
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import support  # noqa: E402


_CONFIG_DIR = support.make_config_dir()
atexit.register(shutil.rmtree, _CONFIG_DIR, True)
SETTINGS = support.load_settings(_CONFIG_DIR)
aggbat = support.load_driver(SETTINGS)


class FakeServiceContext(object):
    """Stand-in for velib_python's ``ServiceContext``."""

    def __init__(self, service):
        self._service = service

    def __setitem__(self, path, value):
        self._service.published.append((path, value))
        self._service.values[path] = value

    def __getitem__(self, path):
        return self._service.values[path]


class FakeVeDbusService(object):
    """Records everything that actually reaches the D-Bus layer."""

    def __init__(self):
        self.published = []
        self.values = {}
        self.enter_count = 0
        self.exit_count = 0
        self.registered = False

    def __enter__(self):
        self.enter_count += 1
        return FakeServiceContext(self)

    def __exit__(self, *exc):
        self.exit_count += 1
        return False

    def __setitem__(self, path, value):
        self.published.append((path, value))
        self.values[path] = value

    def __getitem__(self, path):
        return self.values[path]

    def register(self):
        self.registered = True
        return "registered"


class FakeClock(object):
    """Injected in place of the driver's ``time`` module."""

    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# Deterministic thresholds used by the behavioural tests, so they do not break
# when the shipped defaults in config.default.ini are retuned.
TEST_THRESHOLDS = {
    "/Dc/0/Voltage": 0.01,
    "/Dc/0/Current": 0.1,
    "/Dc/0/Power": 5,
    "/Soc": 0.1,
}

UNGATED_PATHS = (
    "/Info/MaxChargeVoltage",
    "/Info/MaxChargeCurrent",
    "/Info/MaxDischargeCurrent",
    "/Alarms/LowVoltage",
    "/Alarms/HighCellVoltage",
    "/Alarms/BmsCable",
    "/System/MaxCellVoltage",
)


class GateTestCase(unittest.TestCase):
    """Common fixture: a gate over a fake service, with clock and thresholds."""

    def setUp(self):
        self.svc = FakeVeDbusService()
        self.clock = FakeClock()
        patcher = mock.patch.object(aggbat, "tt", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.gate = aggbat._GatedDbusService(self.svc)

    def write(self, *pairs):
        """Write ``(path, value)`` pairs inside one ``with`` block."""
        with self.gate as bus:
            for path, value in pairs:
                bus[path] = value

    def write_each(self, path, values):
        """Write each value in its own ``with`` block, like the update loop."""
        for value in values:
            with self.gate as bus:
                bus[path] = value

    @property
    def published(self):
        return self.svc.published

    def published_for(self, path):
        return [value for pub_path, value in self.svc.published if pub_path == path]


class TestDeduplication(GateTestCase):

    def test_first_write_is_published(self):
        self.write_each("/Dc/0/Voltage", [52.0])
        self.assertEqual(self.published, [("/Dc/0/Voltage", 52.0)])

    def test_same_value_twice_publishes_once(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.0])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0])

    def test_same_value_twice_in_one_context_publishes_once(self):
        self.write(("/Dc/0/Voltage", 52.0), ("/Dc/0/Voltage", 52.0))
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0])

    def test_repeated_writes_of_unchanged_value_publish_once(self):
        self.write_each("/Soc", [77.0] * 50)
        self.assertEqual(self.published_for("/Soc"), [77.0])

    def test_dedup_applies_to_ungated_paths(self):
        for path in UNGATED_PATHS:
            with self.subTest(path=path):
                self.svc.published = []
                self.write_each(path, [12.0, 12.0, 12.0])
                self.assertEqual(self.published_for(path), [12.0])

    def test_int_and_float_of_equal_value_are_deduped(self):
        self.write_each("/Dc/0/Power", [5, 5.0])
        self.assertEqual(self.published_for("/Dc/0/Power"), [5])

    def test_paths_are_cached_independently(self):
        self.write(("/Dc/0/Voltage", 52.0), ("/Dc/0/Current", 52.0))
        self.write(("/Dc/0/Voltage", 52.0), ("/Dc/0/Current", 52.0))
        self.assertEqual(self.published, [("/Dc/0/Voltage", 52.0), ("/Dc/0/Current", 52.0)])


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestThresholdGating(GateTestCase):

    def test_change_below_threshold_is_suppressed(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.005])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0])

    def test_change_exactly_at_threshold_is_published(self):
        # threshold 5 W, exactly 5 W of change (representable, no float slack)
        self.write_each("/Dc/0/Power", [100.0, 105.0])
        self.assertEqual(self.published_for("/Dc/0/Power"), [100.0, 105.0])

    def test_change_above_threshold_is_published(self):
        self.write_each("/Dc/0/Current", [10.0, 11.0])
        self.assertEqual(self.published_for("/Dc/0/Current"), [10.0, 11.0])

    def test_negative_change_below_threshold_is_suppressed(self):
        self.write_each("/Dc/0/Power", [100.0, 96.5])
        self.assertEqual(self.published_for("/Dc/0/Power"), [100.0])

    def test_negative_change_above_threshold_is_published(self):
        self.write_each("/Dc/0/Power", [100.0, 90.0])
        self.assertEqual(self.published_for("/Dc/0/Power"), [100.0, 90.0])

    def test_flicker_around_a_stable_value_is_fully_suppressed(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.004, 52.0, 51.996, 52.0, 52.004])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0])

    def test_threshold_of_zero_publishes_every_change(self):
        with mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, {"/Dc/0/Voltage": 0}):
            self.write_each("/Dc/0/Voltage", [52.0, 52.000001, 52.000002])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0, 52.000001, 52.000002])

    def test_threshold_of_zero_still_suppresses_identical_repeats(self):
        with mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, {"/Dc/0/Voltage": 0}):
            self.write_each("/Dc/0/Voltage", [52.0, 52.0, 52.5, 52.5])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0, 52.5])


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestComparedAgainstLastPublished(GateTestCase):
    """Slow drift must eventually publish: the comparison base is the last
    PUBLISHED value, never the last attempted one."""

    def test_accumulated_sub_threshold_steps_eventually_publish(self):
        # threshold 0.01, steps of 0.004: publishes on the third step.
        self.write_each("/Dc/0/Voltage", [52.0 + 0.004 * i for i in range(4)])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0, 52.0 + 0.004 * 3])

    def test_long_upward_ramp_publishes_every_third_step(self):
        values = [52.0 + 0.004 * i for i in range(250)]
        self.write_each("/Dc/0/Voltage", values)
        published = self.published_for("/Dc/0/Voltage")
        # 1 seed + one publish for every 3 steps of 0.004 (0.012 >= 0.01)
        self.assertEqual(len(published), 1 + 249 // 3)
        self.assertEqual(published[-1], values[-1])
        for previous, current in zip(published, published[1:]):
            self.assertGreaterEqual(abs(current - previous), TEST_THRESHOLDS["/Dc/0/Voltage"])

    def test_long_downward_ramp_publishes(self):
        values = [80.0 - 0.04 * i for i in range(100)]
        self.write_each("/Dc/0/Current", values)
        published = self.published_for("/Dc/0/Current")
        self.assertGreater(len(published), 1)
        # The value on the bus never lags the truth by more than the threshold.
        self.assertLess(abs(published[-1] - values[-1]), TEST_THRESHOLDS["/Dc/0/Current"])

    def test_drift_is_not_measured_against_the_previous_attempt(self):
        # Every consecutive step is sub-threshold (0.0625 < 0.1), yet the total
        # drift is large; comparing against the last attempt would publish
        # nothing after the seed. 0.0625 is exactly representable, so the
        # accumulated steps compare against the threshold without float slack.
        self.write_each("/Soc", [50.0 + 0.0625 * i for i in range(33)])
        published = self.published_for("/Soc")
        self.assertEqual(len(published), 1 + 32 // 2)
        self.assertEqual(published[-1], 52.0)

    def test_published_value_is_the_new_value_not_the_delta(self):
        self.write_each("/Dc/0/Power", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        self.assertEqual(self.published_for("/Dc/0/Power"), [100.0, 105.0])


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestUngatedPaths(GateTestCase):

    def test_control_paths_publish_on_any_change(self):
        for path in ("/Info/MaxChargeVoltage", "/Info/MaxChargeCurrent", "/Info/MaxDischargeCurrent"):
            with self.subTest(path=path):
                self.svc.published = []
                self.write_each(path, [55.2, 55.200001, 55.3])
                self.assertEqual(self.published_for(path), [55.2, 55.200001, 55.3])

    def test_alarm_paths_publish_on_any_change(self):
        self.write_each("/Alarms/HighCellVoltage", [0, 1, 0, 2])
        self.assertEqual(self.published_for("/Alarms/HighCellVoltage"), [0, 1, 0, 2])

    def test_unknown_path_is_never_thresholded(self):
        self.write_each("/Voltages/Cell1", [3.2, 3.200001])
        self.assertEqual(self.published_for("/Voltages/Cell1"), [3.2, 3.200001])

    def test_control_paths_are_absent_from_the_threshold_map(self):
        for path in UNGATED_PATHS:
            with self.subTest(path=path):
                self.assertNotIn(path, aggbat.PUBLISH_GATE_THRESHOLDS)


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestNonNumericValues(GateTestCase):

    def test_none_is_deduped(self):
        self.write_each("/Dc/0/Voltage", [None, None, None])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [None])

    def test_none_to_number_is_published(self):
        self.write_each("/Dc/0/Voltage", [None, 52.0])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [None, 52.0])

    def test_number_to_none_is_published(self):
        self.write_each("/Dc/0/Voltage", [52.0, None])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0, None])

    def test_first_numeric_value_after_none_is_not_thresholded(self):
        self.write_each("/Dc/0/Voltage", [None, 52.0, 52.001])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [None, 52.0])

    def test_strings_are_deduped_but_never_thresholded(self):
        self.write_each("/Dc/0/Voltage", ["52.0", "52.0", "52.000001"])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), ["52.0", "52.000001"])

    def test_string_on_an_ungated_path_is_deduped(self):
        self.write_each("/ProductName", ["aggregate", "aggregate", "aggregate v2"])
        self.assertEqual(self.published_for("/ProductName"), ["aggregate", "aggregate v2"])

    def test_number_to_string_is_published(self):
        self.write_each("/Dc/0/Voltage", [52.0, "52.0"])
        published = self.published_for("/Dc/0/Voltage")
        self.assertEqual(len(published), 2)
        self.assertEqual(published[1], "52.0")


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestHeartbeat(GateTestCase):

    def setUp(self):
        super(TestHeartbeat, self).setUp()
        patcher = mock.patch.object(aggbat, "PUBLISH_HEARTBEAT_S", 900)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unchanged_value_is_republished_after_the_heartbeat(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.0])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0])
        self.clock.advance(900)
        self.write_each("/Dc/0/Voltage", [52.0])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0, 52.0])

    def test_no_republish_before_the_heartbeat_elapses(self):
        self.write_each("/Dc/0/Voltage", [52.0])
        self.clock.advance(899.9)
        self.write_each("/Dc/0/Voltage", [52.0])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0])

    def test_heartbeat_clears_every_cached_path(self):
        self.write(("/Dc/0/Voltage", 52.0), ("/Soc", 77.0), ("/Info/MaxChargeVoltage", 55.2))
        self.svc.published = []
        self.clock.advance(900)
        self.write(("/Dc/0/Voltage", 52.0), ("/Soc", 77.0), ("/Info/MaxChargeVoltage", 55.2))
        self.assertEqual(
            self.published,
            [("/Dc/0/Voltage", 52.0), ("/Soc", 77.0), ("/Info/MaxChargeVoltage", 55.2)],
        )

    def test_heartbeat_is_rearmed_after_firing(self):
        self.write_each("/Soc", [77.0])
        self.clock.advance(900)
        self.write_each("/Soc", [77.0])
        self.clock.advance(100)
        self.write_each("/Soc", [77.0])
        self.assertEqual(self.published_for("/Soc"), [77.0, 77.0])
        self.clock.advance(800)
        self.write_each("/Soc", [77.0])
        self.assertEqual(self.published_for("/Soc"), [77.0, 77.0, 77.0])

    def test_heartbeat_does_not_fire_within_a_single_context(self):
        with self.gate as bus:
            bus["/Soc"] = 77.0
            self.clock.advance(5000)
            bus["/Soc"] = 77.0
        self.assertEqual(self.published_for("/Soc"), [77.0])

    def test_threshold_still_applies_between_heartbeats(self):
        self.write_each("/Dc/0/Voltage", [52.0])
        self.clock.advance(100)
        self.write_each("/Dc/0/Voltage", [52.002])
        self.assertEqual(self.published_for("/Dc/0/Voltage"), [52.0])

    def test_long_stall_clears_the_cache_only_once(self):
        self.write_each("/Soc", [77.0])
        self.clock.advance(10 * 900)
        self.write_each("/Soc", [77.0, 77.0])
        self.assertEqual(self.published_for("/Soc"), [77.0, 77.0])


class TestServiceProxy(GateTestCase):

    def test_direct_setitem_writes_through_and_seeds_the_cache(self):
        self.gate["/Soc"] = 77.0
        self.assertEqual(self.published_for("/Soc"), [77.0])
        self.write_each("/Soc", [77.0])
        self.assertEqual(self.published_for("/Soc"), [77.0])

    def test_direct_setitem_is_not_deduplicated(self):
        self.gate["/Soc"] = 77.0
        self.gate["/Soc"] = 77.0
        self.assertEqual(self.published_for("/Soc"), [77.0, 77.0])

    def test_getitem_reads_through_to_the_service(self):
        self.gate["/Soc"] = 77.0
        self.assertEqual(self.gate["/Soc"], 77.0)
        with self.gate as bus:
            self.assertEqual(bus["/Soc"], 77.0)

    def test_unknown_attributes_are_delegated(self):
        self.assertEqual(self.gate.register(), "registered")
        self.assertTrue(self.svc.registered)

    def test_context_manager_delegates_enter_and_exit(self):
        with self.gate:
            pass
        self.assertEqual(self.svc.enter_count, 1)
        self.assertEqual(self.svc.exit_count, 1)

    def test_exception_inside_the_context_still_exits_the_service(self):
        with self.assertRaises(ValueError):
            with self.gate as bus:
                bus["/Soc"] = 77.0
                raise ValueError("boom")
        self.assertEqual(self.svc.exit_count, 1)


class TestGateConfiguration(unittest.TestCase):
    """The threshold map and heartbeat come from settings.py / the ini file."""

    def setUp(self):
        self.settings = SETTINGS

    def test_thresholds_come_from_settings(self):
        expected = {
            "/Dc/0/Voltage": self.settings.PUBLISH_GATE_VOLTAGE,
            "/Dc/0/Current": self.settings.PUBLISH_GATE_CURRENT,
            "/Dc/0/Power": self.settings.PUBLISH_GATE_POWER,
            "/Dc/0/Temperature": self.settings.PUBLISH_GATE_TEMPERATURE,
            "/TimeToGo": self.settings.PUBLISH_GATE_TIME_TO_GO,
            "/ConsumedAmphours": self.settings.PUBLISH_GATE_CONSUMED_AMPHOURS,
            "/Soc": self.settings.PUBLISH_GATE_SOC,
        }
        self.assertEqual(aggbat.PUBLISH_GATE_THRESHOLDS, expected)

    def test_heartbeat_comes_from_settings(self):
        self.assertEqual(aggbat.PUBLISH_HEARTBEAT_S, self.settings.PUBLISH_HEARTBEAT)

    def test_all_thresholds_are_non_negative(self):
        for path, threshold in aggbat.PUBLISH_GATE_THRESHOLDS.items():
            with self.subTest(path=path):
                self.assertGreaterEqual(threshold, 0)


if __name__ == "__main__":
    unittest.main()
