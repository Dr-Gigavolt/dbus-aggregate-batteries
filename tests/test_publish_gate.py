# -*- coding: utf-8 -*-
"""Unit tests for the D-Bus publish gate in dbus-aggregate-batteries.py.

The gate (``_GatedDbusService`` / ``_GatedDbusServiceContext``) suppresses
numeric changes below a per-path threshold, compared against the value
currently published on D-Bus, and bypasses those thresholds once every
``PUBLISH_HEARTBEAT_S``.

``driver_harness.RecordingDbusService`` mirrors the parts of velib_python that
matter here: ``ServiceContext.__getitem__`` returns the currently published
value, and ``VeDbusItemExport._local_set_value`` drops a write whose value is
unchanged (so "not written" and "not emitted on D-Bus" are the same thing).

The driver imports ``dbus``, ``vedbus`` and ``gi.repository`` which are only
available on Venus OS, so those modules are stubbed in ``sys.modules`` before
the driver is loaded, and ``settings`` is executed against a generated
config.ini; ``driver_harness`` does all of that once for every suite. The driver
file name contains dashes, so it is loaded by path with ``importlib``.
"""

import math
import unittest
from unittest import mock

import driver_harness

SETTINGS = driver_harness.settings
aggbat = driver_harness.driver

NAN = float("nan")


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

HEARTBEAT_S = 900


class GateTestCase(unittest.TestCase):
    """Common fixture: a gate over a fake service, with an injected clock."""

    def setUp(self):
        self.svc = driver_harness.RecordingDbusService()
        self.clock = FakeClock()
        clock_patcher = mock.patch.object(aggbat, "tt", self.clock)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)
        heartbeat_patcher = mock.patch.object(aggbat, "PUBLISH_HEARTBEAT_S", HEARTBEAT_S)
        heartbeat_patcher.start()
        self.addCleanup(heartbeat_patcher.stop)
        self.gate = aggbat._GatedDbusService(self.svc)

    def register(self, path, initial=None):
        """Register a path the way the driver's add_path() calls do."""
        self.svc.add_path(path, initial)

    def write(self, *pairs):
        """Write ``(path, value)`` pairs inside one ``with`` block."""
        for path, _ in pairs:
            if path not in self.svc.values:
                self.register(path)
        with self.gate as bus:
            for path, value in pairs:
                bus[path] = value

    def write_each(self, path, values):
        """Write each value in its own ``with`` block, like the update loop."""
        if path not in self.svc.values:
            self.register(path)
        for value in values:
            with self.gate as bus:
                bus[path] = value

    @property
    def written(self):
        return self.svc.written

    def written_for(self, path):
        return [value for written_path, value in self.svc.written if written_path == path]


class TestUnchangedValuesAreNotWritten(GateTestCase):

    def test_first_write_reaches_the_service(self):
        self.write_each("/Dc/0/Voltage", [52.0])
        self.assertEqual(self.written, [("/Dc/0/Voltage", 52.0)])

    def test_same_value_twice_is_written_once(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.0])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])

    def test_same_value_twice_in_one_context_is_written_once(self):
        self.write(("/Dc/0/Voltage", 52.0), ("/Dc/0/Voltage", 52.0))
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])

    def test_repeated_writes_of_an_unchanged_value_are_written_once(self):
        self.write_each("/Soc", [77.0] * 50)
        self.assertEqual(self.written_for("/Soc"), [77.0])

    def test_unchanged_values_are_dropped_on_ungated_paths_too(self):
        for path in UNGATED_PATHS:
            with self.subTest(path=path):
                self.svc.written = []
                self.write_each(path, [12.0, 12.0, 12.0])
                self.assertEqual(self.written_for(path), [12.0])

    def test_int_and_float_of_equal_value_are_not_rewritten(self):
        self.write_each("/Dc/0/Power", [5, 5.0])
        self.assertEqual(self.written_for("/Dc/0/Power"), [5])

    def test_paths_are_evaluated_independently(self):
        self.write(("/Dc/0/Voltage", 52.0), ("/Dc/0/Current", 52.0))
        self.write(("/Dc/0/Voltage", 52.0), ("/Dc/0/Current", 52.0))
        self.assertEqual(self.written, [("/Dc/0/Voltage", 52.0), ("/Dc/0/Current", 52.0)])

    def test_registration_is_not_a_write(self):
        self.register("/Soc", 77.0)
        self.assertEqual(self.written, [])

    def test_value_equal_to_the_registered_initial_value_is_not_written(self):
        # The first comparison is against the add_path() initial value, which is
        # the real published value, so no redundant first write happens.
        self.register("/Soc", 77.0)
        self.write_each("/Soc", [77.0])
        self.assertEqual(self.written_for("/Soc"), [])


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestThresholdGating(GateTestCase):

    def test_change_below_threshold_is_suppressed(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.005])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])

    def test_change_exactly_at_threshold_is_written(self):
        # threshold 5 W, exactly 5 W of change (representable, no float slack)
        self.write_each("/Dc/0/Power", [100.0, 105.0])
        self.assertEqual(self.written_for("/Dc/0/Power"), [100.0, 105.0])

    def test_change_above_threshold_is_written(self):
        self.write_each("/Dc/0/Current", [10.0, 11.0])
        self.assertEqual(self.written_for("/Dc/0/Current"), [10.0, 11.0])

    def test_negative_change_below_threshold_is_suppressed(self):
        self.write_each("/Dc/0/Power", [100.0, 96.5])
        self.assertEqual(self.written_for("/Dc/0/Power"), [100.0])

    def test_negative_change_above_threshold_is_written(self):
        self.write_each("/Dc/0/Power", [100.0, 90.0])
        self.assertEqual(self.written_for("/Dc/0/Power"), [100.0, 90.0])

    def test_flicker_around_a_stable_value_is_fully_suppressed(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.004, 52.0, 51.996, 52.0, 52.004])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])

    def test_threshold_is_applied_against_the_registered_initial_value(self):
        self.register("/Dc/0/Voltage", 52.0)
        self.write_each("/Dc/0/Voltage", [52.005])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [])
        self.write_each("/Dc/0/Voltage", [52.02])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.02])

    def test_threshold_of_zero_writes_every_change(self):
        with mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, {"/Dc/0/Voltage": 0}):
            self.write_each("/Dc/0/Voltage", [52.0, 52.000001, 52.000002])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0, 52.000001, 52.000002])

    def test_threshold_of_zero_still_drops_identical_repeats(self):
        with mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, {"/Dc/0/Voltage": 0}):
            self.write_each("/Dc/0/Voltage", [52.0, 52.0, 52.5, 52.5])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0, 52.5])


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestComparedAgainstThePublishedValue(GateTestCase):
    """Slow drift must eventually be written: the comparison base is the value
    currently published, which only moves when a write actually goes through."""

    def test_accumulated_sub_threshold_steps_eventually_write(self):
        # threshold 0.01, steps of 0.004: writes on the third step.
        self.write_each("/Dc/0/Voltage", [52.0 + 0.004 * i for i in range(4)])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0, 52.0 + 0.004 * 3])

    def test_long_upward_ramp_writes_every_third_step(self):
        values = [52.0 + 0.004 * i for i in range(250)]
        self.write_each("/Dc/0/Voltage", values)
        written = self.written_for("/Dc/0/Voltage")
        # 1 seed + one write for every 3 steps of 0.004 (0.012 >= 0.01)
        self.assertEqual(len(written), 1 + 249 // 3)
        self.assertEqual(written[-1], values[-1])
        for previous, current in zip(written, written[1:]):
            self.assertGreaterEqual(abs(current - previous), TEST_THRESHOLDS["/Dc/0/Voltage"])

    def test_long_downward_ramp_writes(self):
        values = [80.0 - 0.04 * i for i in range(100)]
        self.write_each("/Dc/0/Current", values)
        written = self.written_for("/Dc/0/Current")
        self.assertGreater(len(written), 1)
        # The value on the bus never lags the truth by more than the threshold.
        self.assertLess(abs(written[-1] - values[-1]), TEST_THRESHOLDS["/Dc/0/Current"])

    def test_drift_is_not_measured_against_the_previous_attempt(self):
        # Every consecutive step is sub-threshold (0.0625 < 0.1), yet the total
        # drift is large; comparing against the last attempt would write nothing
        # after the seed. 0.0625 is exactly representable, so the accumulated
        # steps compare against the threshold without float slack.
        self.write_each("/Soc", [50.0 + 0.0625 * i for i in range(33)])
        written = self.written_for("/Soc")
        self.assertEqual(len(written), 1 + 32 // 2)
        self.assertEqual(written[-1], 52.0)

    def test_written_value_is_the_new_value_not_the_delta(self):
        self.write_each("/Dc/0/Power", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        self.assertEqual(self.written_for("/Dc/0/Power"), [100.0, 105.0])


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestForeignWrites(GateTestCase):
    """Regression tests for the divergence a shadow cache of "last published"
    values caused: the driver's paths are writeable, so another process can
    write them over D-Bus. The gate compares against the live published value,
    so the driver reasserts its own value on the next cycle."""

    def test_driver_reasserts_its_value_after_a_foreign_write(self):
        self.write_each("/Soc", [77.0])
        self.svc.foreign_write("/Soc", 12.0)
        self.svc.written = []

        # The driver writes its unchanged value on the next update cycle.
        self.write_each("/Soc", [77.0])

        self.assertEqual(self.written_for("/Soc"), [77.0])
        self.assertEqual(self.svc.values["/Soc"], 77.0)

    def test_driver_reasserts_its_value_on_an_ungated_path(self):
        self.write_each("/Info/MaxChargeVoltage", [55.2])
        self.svc.foreign_write("/Info/MaxChargeVoltage", 48.0)
        self.svc.written = []
        self.write_each("/Info/MaxChargeVoltage", [55.2])
        self.assertEqual(self.written_for("/Info/MaxChargeVoltage"), [55.2])

    def test_foreign_write_is_corrected_on_the_very_next_cycle(self):
        self.write_each("/Alarms/HighCellVoltage", [0])
        self.svc.foreign_write("/Alarms/HighCellVoltage", 2)
        self.write_each("/Alarms/HighCellVoltage", [0, 0, 0])
        # Corrected once, then quiet again.
        self.assertEqual(self.written_for("/Alarms/HighCellVoltage"), [0, 0])

    def test_foreign_write_within_the_threshold_is_corrected_on_the_heartbeat(self):
        # A foreign value closer than the threshold is left alone until the
        # heartbeat cycle bypasses thresholds. Divergence is bounded by the
        # threshold and by PUBLISH_HEARTBEAT_S, never unbounded in time.
        self.write_each("/Soc", [77.0])
        self.svc.foreign_write("/Soc", 77.05)
        self.svc.written = []

        self.write_each("/Soc", [77.0])
        self.assertEqual(self.written_for("/Soc"), [])

        self.clock.advance(HEARTBEAT_S)
        self.write_each("/Soc", [77.0])
        self.assertEqual(self.written_for("/Soc"), [77.0])


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestUngatedPaths(GateTestCase):

    def test_control_paths_are_written_on_any_change(self):
        for path in ("/Info/MaxChargeVoltage", "/Info/MaxChargeCurrent", "/Info/MaxDischargeCurrent"):
            with self.subTest(path=path):
                self.svc.written = []
                self.write_each(path, [55.2, 55.200001, 55.3])
                self.assertEqual(self.written_for(path), [55.2, 55.200001, 55.3])

    def test_alarm_paths_are_written_on_any_change(self):
        self.write_each("/Alarms/HighCellVoltage", [0, 1, 0, 2])
        self.assertEqual(self.written_for("/Alarms/HighCellVoltage"), [0, 1, 0, 2])

    def test_unknown_path_is_never_thresholded(self):
        self.write_each("/Voltages/Cell1", [3.2, 3.200001])
        self.assertEqual(self.written_for("/Voltages/Cell1"), [3.2, 3.200001])

    def test_control_paths_are_absent_from_the_threshold_map(self):
        for path in UNGATED_PATHS:
            with self.subTest(path=path):
                self.assertNotIn(path, aggbat.PUBLISH_GATE_THRESHOLDS)


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestNonNumericValues(GateTestCase):

    def test_repeated_none_is_written_once(self):
        self.register("/Dc/0/Voltage", 52.0)
        self.write_each("/Dc/0/Voltage", [None, None, None])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [None])

    def test_none_matching_the_published_value_is_not_written(self):
        self.write_each("/Dc/0/Voltage", [None])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [])

    def test_none_to_number_is_written(self):
        self.write_each("/Dc/0/Voltage", [None, 52.0])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])

    def test_number_to_none_is_written(self):
        self.write_each("/Dc/0/Voltage", [52.0, None])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0, None])

    def test_first_numeric_value_after_none_is_not_thresholded(self):
        self.write_each("/Dc/0/Voltage", [52.0, None, 52.001])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0, None, 52.001])

    def test_strings_are_deduped_but_never_thresholded(self):
        self.write_each("/Dc/0/Voltage", ["52.0", "52.0", "52.000001"])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), ["52.0", "52.000001"])

    def test_string_on_an_ungated_path_is_deduped(self):
        self.write_each("/ProductName", ["aggregate", "aggregate", "aggregate v2"])
        self.assertEqual(self.written_for("/ProductName"), ["aggregate", "aggregate v2"])

    def test_number_to_string_is_written(self):
        self.write_each("/Dc/0/Voltage", [52.0, "52.0"])
        written = self.written_for("/Dc/0/Voltage")
        self.assertEqual(len(written), 2)
        self.assertEqual(written[1], "52.0")


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestNaN(GateTestCase):
    """NaN is not equal to itself and every comparison with it is False, so an
    unchanged NaN would otherwise be written on every single cycle."""

    def assertWrittenIsAllNaN(self, path, count):
        written = self.written_for(path)
        self.assertEqual(len(written), count)
        for value in written:
            self.assertTrue(math.isnan(value), "%r is not NaN" % (value,))

    def test_nan_following_nan_is_not_written(self):
        # A computed NaN is a new float object every cycle, so identity does not
        # save us here; the value comparison has to.
        for path in ("/Dc/0/Voltage", "/Info/MaxChargeVoltage"):
            with self.subTest(path=path):
                self.svc.written = []
                self.write_each(path, [float("nan") for _ in range(4)])
                self.assertWrittenIsAllNaN(path, 1)

    def test_the_same_nan_object_repeated_is_not_written(self):
        self.write_each("/Soc", [NAN, NAN, NAN])
        self.assertWrittenIsAllNaN("/Soc", 1)

    def test_first_nan_is_written(self):
        self.write_each("/Dc/0/Voltage", [52.0, NAN])
        written = self.written_for("/Dc/0/Voltage")
        self.assertEqual(written[0], 52.0)
        self.assertTrue(math.isnan(written[1]))
        self.assertEqual(len(written), 2)

    def test_real_value_after_nan_is_written(self):
        self.write_each("/Dc/0/Voltage", [NAN, 52.0])
        written = self.written_for("/Dc/0/Voltage")
        self.assertTrue(math.isnan(written[0]))
        self.assertEqual(written[1], 52.0)

    def test_a_run_of_nan_between_real_values_is_written_once_each_way(self):
        self.write_each("/Soc", [77.0, NAN, NAN, NAN, 78.0])
        written = self.written_for("/Soc")
        self.assertEqual(len(written), 3)
        self.assertEqual(written[0], 77.0)
        self.assertTrue(math.isnan(written[1]))
        self.assertEqual(written[2], 78.0)

    def test_nan_is_not_written_again_on_a_heartbeat_cycle(self):
        self.write_each("/Soc", [NAN])
        self.clock.advance(HEARTBEAT_S)
        self.write_each("/Soc", [NAN])
        self.assertWrittenIsAllNaN("/Soc", 1)


@mock.patch.dict(aggbat.PUBLISH_GATE_THRESHOLDS, TEST_THRESHOLDS, clear=True)
class TestHeartbeat(GateTestCase):
    """Every PUBLISH_HEARTBEAT_S one cycle bypasses the thresholds, so a value
    that drifted less than its threshold is brought up to date."""

    def test_sub_threshold_drift_is_written_on_the_heartbeat_cycle(self):
        self.write_each("/Dc/0/Voltage", [52.0, 52.005])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])
        self.clock.advance(HEARTBEAT_S)
        self.write_each("/Dc/0/Voltage", [52.005])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0, 52.005])

    def test_unchanged_value_is_not_rewritten_on_the_heartbeat(self):
        # velib drops writes of an unchanged value anyway, so a heartbeat cannot
        # turn an identical value into a D-Bus signal.
        self.write_each("/Dc/0/Voltage", [52.0])
        self.clock.advance(HEARTBEAT_S)
        self.write_each("/Dc/0/Voltage", [52.0])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])

    def test_no_bypass_before_the_heartbeat_elapses(self):
        self.write_each("/Dc/0/Voltage", [52.0])
        self.clock.advance(HEARTBEAT_S - 0.1)
        self.write_each("/Dc/0/Voltage", [52.005])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [52.0])

    def test_heartbeat_bypasses_thresholds_for_the_whole_cycle(self):
        self.write(("/Dc/0/Voltage", 52.0), ("/Soc", 77.0), ("/Dc/0/Power", 100.0))
        self.svc.written = []
        self.clock.advance(HEARTBEAT_S)
        self.write(("/Dc/0/Voltage", 52.001), ("/Soc", 77.01), ("/Dc/0/Power", 100.1))
        self.assertEqual(
            self.written,
            [("/Dc/0/Voltage", 52.001), ("/Soc", 77.01), ("/Dc/0/Power", 100.1)],
        )

    def test_thresholds_apply_again_after_the_heartbeat_cycle(self):
        self.write_each("/Dc/0/Voltage", [52.0])
        self.clock.advance(HEARTBEAT_S)
        self.write_each("/Dc/0/Voltage", [52.001])
        self.svc.written = []
        self.write_each("/Dc/0/Voltage", [52.002])
        self.assertEqual(self.written_for("/Dc/0/Voltage"), [])

    def test_heartbeat_is_rearmed_after_firing(self):
        self.write_each("/Soc", [77.0])
        self.clock.advance(HEARTBEAT_S)
        self.write_each("/Soc", [77.01])
        self.clock.advance(100)
        self.write_each("/Soc", [77.02])
        self.assertEqual(self.written_for("/Soc"), [77.0, 77.01])
        self.clock.advance(HEARTBEAT_S - 100)
        self.write_each("/Soc", [77.02])
        self.assertEqual(self.written_for("/Soc"), [77.0, 77.01, 77.02])

    def test_heartbeat_is_decided_at_context_entry(self):
        self.register("/Soc")
        with self.gate as bus:
            bus["/Soc"] = 77.0
            self.clock.advance(5 * HEARTBEAT_S)
            bus["/Soc"] = 77.01
        self.assertEqual(self.written_for("/Soc"), [77.0])

    def test_a_long_stall_produces_a_single_heartbeat_cycle(self):
        self.write_each("/Soc", [77.0])
        self.clock.advance(10 * HEARTBEAT_S)
        self.write_each("/Soc", [77.01, 77.02])
        self.assertEqual(self.written_for("/Soc"), [77.0, 77.01])


class TestServiceProxy(GateTestCase):

    def test_direct_setitem_passes_through(self):
        self.register("/CustomName")
        self.gate["/CustomName"] = "AggregateBatteries"
        self.assertEqual(self.written_for("/CustomName"), ["AggregateBatteries"])

    def test_direct_setitem_is_not_gated(self):
        self.register("/Soc")
        self.gate["/Soc"] = 77.0
        self.gate["/Soc"] = 77.001
        self.assertEqual(self.written_for("/Soc"), [77.0, 77.001])

    def test_direct_setitem_is_visible_to_the_next_gated_write(self):
        self.register("/Soc")
        self.gate["/Soc"] = 77.0
        self.svc.written = []
        self.write_each("/Soc", [77.0])
        self.assertEqual(self.written_for("/Soc"), [])

    def test_getitem_reads_through_to_the_service(self):
        self.register("/Soc")
        self.gate["/Soc"] = 77.0
        self.assertEqual(self.gate["/Soc"], 77.0)
        with self.gate as bus:
            self.assertEqual(bus["/Soc"], 77.0)

    def test_unknown_attributes_are_delegated(self):
        self.assertEqual(self.gate.register(), "registered")
        self.assertTrue(self.svc.registered)

    def test_add_path_is_delegated(self):
        self.gate.add_path("/Soc", 77.0)
        self.assertEqual(self.svc.values["/Soc"], 77.0)
        self.assertEqual(self.written, [])

    def test_context_manager_delegates_enter_and_exit(self):
        with self.gate:
            pass
        self.assertEqual(self.svc.enter_count, 1)
        self.assertEqual(self.svc.exit_count, 1)

    def test_exception_inside_the_context_still_exits_the_service(self):
        self.register("/Soc")
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
