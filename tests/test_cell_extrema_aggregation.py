#!/usr/bin/env python3

"""
Unit tests for the cell voltage / cell temperature extrema aggregation inside
``DbusAggBatService._update()``.

The real driver is exercised; see driver_harness for how it is loaded and wired
off-device. Nothing here re-implements the aggregation logic: every assertion
is about what the driver itself computed and published.
"""

import logging
import unittest
from unittest import mock

from driver_harness import Battery, DriverTestCase, FakeDbusMon, driver

# the injected clock lives with the tolerance tests, which is where it is
# explained; both suites are flat modules in tests/, as is driver_harness itself
from test_missing_data_tolerance import FakeClock


class PartialCellVoltageDataTest(DriverTestCase):
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

        voltage_warnings = [message for message in captured.output if "cell voltage missing" in message]
        # both halves are missing, so the battery is announced once, not twice
        self.assertEqual(1, len(voltage_warnings))
        self.assertIn("'%s'" % self.silent.name, voltage_warnings[0])
        self.assertIn("Max. and Min.", voltage_warnings[0])
        self.assertIn("excluded from aggregation this cycle", voltage_warnings[0])
        # the healthy battery must never be named as skipped
        self.assertNotIn(self.reporting.name, voltage_warnings[0])


class PartialCellTemperatureDataTest(DriverTestCase):
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

        temperature_warnings = [message for message in captured.output if "cell temperature missing" in message]
        self.assertEqual(1, len(temperature_warnings))
        self.assertIn("'%s'" % self.silent.name, temperature_warnings[0])
        self.assertIn("Max. and Min.", temperature_warnings[0])
        self.assertIn("excluded from aggregation this cycle", temperature_warnings[0])


class EveryBatterySkippedTest(DriverTestCase):
    """No battery reports extrema: nothing is aggregated, so nothing is published.

    Run with MISSING_DATA_TOLERANCE = 0, so that the exception reaches the read
    failure handler on the first cycle. By default the driver first waits the
    constituents out for MISSING_DATA_TOLERANCE seconds, publishing nothing
    either way; that window is the subject of test_missing_data_tolerance.py.
    """

    def _all_silent_voltage_service(self, **overrides):
        overrides.setdefault("MISSING_DATA_TOLERANCE", 0)
        batteries = [
            Battery("BatteryA", max_cell_voltage=None, min_cell_voltage=None),
            Battery("BatteryB", max_cell_voltage=None, min_cell_voltage=None),
        ]
        return self.make_service(batteries, **overrides)

    def _all_silent_temperature_service(self, **overrides):
        overrides.setdefault("MISSING_DATA_TOLERANCE", 0)
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


class AllBatteriesReportingTest(DriverTestCase):
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


class AsymmetricExtremaTest(DriverTestCase):
    """A battery that reports a max but no min must not yield a mismatched pair."""

    def test_single_battery_with_max_but_no_min_voltage_is_a_read_failure(self):
        battery = Battery("Solo", max_cell_voltage=3.44, max_voltage_cell_id=1, min_cell_voltage=None, min_voltage_cell_id=2)
        # again with the waiting switched off, see EveryBatterySkippedTest
        service = self.make_service([battery], MISSING_DATA_TOLERANCE=0)

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
        # again with the waiting switched off, see EveryBatterySkippedTest
        service = self.make_service([battery], MISSING_DATA_TOLERANCE=0)

        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self.assertTrue(any("No battery reported cell temperatures" in message for message in captured.output))
        published = service._dbusservice.published
        self.assertNotIn("/System/MaxCellTemperature", published)
        self.assertNotIn("/System/MinCellTemperature", published)
        self.assertEqual(2, service._readTrials)

    def test_min_only_missing_is_announced(self):
        """
        A battery dropped from only half of the aggregation is still named.

        The aggregate is arithmetically defensible (a true bank max and the best
        known min), but the battery is out of the min aggregation, so the skip
        must be as loud as any other. The message says which half went missing.
        """
        partial = Battery("Partial", max_cell_voltage=3.60, max_voltage_cell_id=1, min_cell_voltage=None, min_voltage_cell_id=2)
        healthy = Battery("Healthy", max_cell_voltage=3.40, max_voltage_cell_id=5, min_cell_voltage=3.25, min_voltage_cell_id=6)
        service = self.make_service([partial, healthy])

        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        warnings = [message for message in captured.output if "cell voltage missing" in message]
        self.assertEqual(1, len(warnings))
        self.assertIn("'Partial'", warnings[0])
        self.assertIn("Min. cell voltage missing", warnings[0])
        # only the min. went missing, so the max. must not be blamed as well
        self.assertNotIn("Max.", warnings[0])
        self.assertNotIn("Healthy", warnings[0])

        published = service._dbusservice.published
        self.assertEqual("Partial: 1", published["/System/MaxVoltageCellId"])
        self.assertEqual("Healthy: 6", published["/System/MinVoltageCellId"])

    def test_max_only_missing_is_announced(self):
        """The mirror image: a battery reporting a min but no max is named too."""
        partial = Battery("Partial", max_cell_temperature=None, max_temperature_cell_id=1, min_cell_temperature=12.0, min_temperature_cell_id=2)
        healthy = Battery("Healthy", max_cell_temperature=26.0, max_temperature_cell_id=5, min_cell_temperature=21.0, min_temperature_cell_id=6)
        service = self.make_service([partial, healthy])

        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        warnings = [message for message in captured.output if "cell temperature missing" in message]
        self.assertEqual(1, len(warnings))
        self.assertIn("'Partial'", warnings[0])
        self.assertIn("Max. cell temperature missing", warnings[0])
        self.assertNotIn("Min.", warnings[0])

        published = service._dbusservice.published
        self.assertEqual("Healthy: 5", published["/System/MaxTemperatureCellId"])
        self.assertEqual("Partial: 2", published["/System/MinTemperatureCellId"])

    def test_a_battery_missing_both_halves_is_warned_about_once(self):
        """The common case (a battery serving nothing) must not warn twice per dimension."""
        silent = Battery(
            "Silent",
            max_cell_voltage=None,
            min_cell_voltage=None,
            max_cell_temperature=None,
            min_cell_temperature=None,
        )
        healthy = Battery("Healthy")
        service = self.make_service([silent, healthy])

        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        warnings = [record.getMessage() for record in captured.records if record.levelno >= logging.WARNING]
        # exactly two warnings in total: one per dimension, not one per dictionary
        self.assertEqual(2, len(warnings), "expected one warning per dimension, got %r" % warnings)
        self.assertEqual(1, len([message for message in warnings if "cell voltage" in message]))
        self.assertEqual(1, len([message for message in warnings if "cell temperature" in message]))
        for message in warnings:
            self.assertIn("Max. and Min.", message)
            self.assertIn("'Silent'", message)


class ExtremaWarningThrottleTest(DriverTestCase):
    """A constituent stays cell blind for a while, and the log must survive it.

    Being excluded from an extrema aggregation is not a gap: the other batteries
    have cell data, so the aggregate is computed and published every cycle. But
    a battery running on its fallback shunt has no per-cell data until its BMS
    answers - 19 s of it on the system this was measured on, which used to be 96
    warning lines - and with reactive updates the number of cycles inside that
    window is set by how chatty the other batteries are. The announcement and the
    recovery must always be logged; only the repeats are throttled.
    """

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        patcher = mock.patch.object(driver, "tt", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.healthy = Battery("Reporting")
        self.blind = Battery("Blind")

    def serve(self, service, batteries):
        """Re-read the (mutated) batteries, the way the next cycle would."""
        values = {}
        for battery in batteries:
            values.update(battery.values())
        service._dbusMon = FakeDbusMon(values)

    def blind_to_cell_voltages(self, battery):
        battery.max_cell_voltage = None
        battery.min_cell_voltage = None

    def blind_to_cell_temperatures(self, battery):
        battery.max_cell_temperature = None
        battery.min_cell_temperature = None

    def counts(self, captured):
        """(announcements, throttled repeats, recoveries) in the captured log."""
        lines = [record.getMessage() for record in captured.records]
        return (
            len([message for message in lines if "missing from" in message and "still missing" not in message]),
            len([message for message in lines if "still missing from" in message]),
            len([message for message in lines if "complete again" in message]),
        )

    def run_cycles(self, service, count):
        for _ in range(count):
            self.assertTrue(service._update())
            self.clock.advance(1)

    def test_a_long_cell_blind_window_costs_a_bounded_number_of_lines(self):
        self.blind_to_cell_voltages(self.blind)
        self.blind_to_cell_temperatures(self.blind)
        service = self.make_service([self.healthy, self.blind])

        with self.assertLogs(level="WARNING") as captured:
            # a minute of it: without the throttle this was two lines per cycle
            self.run_cycles(service, 60)

            self.blind.max_cell_voltage = 3.35
            self.blind.min_cell_voltage = 3.30
            self.blind.max_cell_temperature = 25.0
            self.blind.min_cell_temperature = 20.0
            self.serve(service, [self.healthy, self.blind])
            self.assertTrue(service._update())

        announcements, repeats, recoveries = self.counts(captured)
        # one announcement and one recovery per dimension, and a repeat every
        # MISSING_DATA_LOG_PERIOD seconds in between: 14 lines, not 120
        self.assertEqual(2, announcements)
        self.assertEqual(2 * (60 // driver.MISSING_DATA_LOG_PERIOD - 1), repeats)
        self.assertEqual(2, recoveries)
        self.assertEqual(14, len(captured.records))

    def test_the_window_is_announced_and_closed_naming_the_battery(self):
        self.blind_to_cell_voltages(self.blind)
        service = self.make_service([self.healthy, self.blind])

        with self.assertLogs(level="WARNING") as captured:
            self.run_cycles(service, 30)
            self.blind.max_cell_voltage = 3.35
            self.blind.min_cell_voltage = 3.30
            self.serve(service, [self.healthy, self.blind])
            service._update()

        lines = [record.getMessage() for record in captured.records]
        self.assertIn("Max. and Min. cell voltage missing from 'Blind' — excluded from aggregation this cycle", lines[0])
        recovery = [message for message in lines if "complete again" in message]
        self.assertEqual(1, len(recovery))
        self.assertIn("'Blind'", recovery[0])
        self.assertIn("Cell voltage", recovery[0])
        self.assertIn("30 s", recovery[0])
        self.assertNotIn("Reporting", " ".join(lines), "the battery that reports must never be named")

    def test_repeats_carry_how_long_it_has_lasted(self):
        self.blind_to_cell_voltages(self.blind)
        service = self.make_service([self.healthy, self.blind])

        with self.assertLogs(level="WARNING") as captured:
            self.run_cycles(service, 25)

        repeats = [record.getMessage() for record in captured.records if "still missing from" in record.getMessage()]
        self.assertEqual(2, len(repeats))
        self.assertIn("after 10 s", repeats[0])
        self.assertIn("after 20 s", repeats[1])

    def test_a_second_battery_going_blind_is_announced_at_once(self):
        """One open window must not swallow the next battery dropping out."""
        self.blind_to_cell_voltages(self.blind)
        late = Battery("Late")
        service = self.make_service([self.healthy, self.blind, late])

        with self.assertLogs(level="WARNING") as captured:
            self.run_cycles(service, 5)
            # well inside the throttle window of the first battery
            self.blind_to_cell_voltages(late)
            self.serve(service, [self.healthy, self.blind, late])
            service._update()

        lines = [record.getMessage() for record in captured.records]
        self.assertEqual(2, len(lines), "expected exactly the two announcements, got %r" % lines)
        self.assertIn("'Blind'", lines[0])
        self.assertIn("'Late'", lines[1])

    def test_each_battery_recovers_on_its_own(self):
        self.blind_to_cell_voltages(self.blind)
        late = Battery("Late", max_cell_voltage=None, min_cell_voltage=None)
        service = self.make_service([self.healthy, self.blind, late])

        with self.assertLogs(level="WARNING") as captured:
            self.run_cycles(service, 3)
            late.max_cell_voltage = 3.35
            late.min_cell_voltage = 3.30
            self.serve(service, [self.healthy, self.blind, late])
            self.run_cycles(service, 1)

        recovery = [record.getMessage() for record in captured.records if "complete again" in record.getMessage()]
        self.assertEqual(1, len(recovery))
        self.assertIn("'Late'", recovery[0])
        # the other battery is still out, and still not repeating itself
        self.assertEqual((2, 0, 1), self.counts(captured))

    def test_a_new_window_after_a_recovery_is_announced_again(self):
        self.blind_to_cell_voltages(self.blind)
        service = self.make_service([self.healthy, self.blind])

        with self.assertLogs(level="WARNING") as captured:
            self.run_cycles(service, 2)
            self.blind.max_cell_voltage = 3.35
            self.blind.min_cell_voltage = 3.30
            self.serve(service, [self.healthy, self.blind])
            self.run_cycles(service, 1)
            self.blind_to_cell_voltages(self.blind)
            self.serve(service, [self.healthy, self.blind])
            self.run_cycles(service, 1)

        self.assertEqual((2, 0, 1), self.counts(captured))

    def test_losing_the_second_half_of_the_pair_is_announced(self):
        """A half missing is throttled; the other half going too is news again."""
        self.blind.min_cell_voltage = None
        service = self.make_service([self.healthy, self.blind])

        with self.assertLogs(level="WARNING") as captured:
            self.run_cycles(service, 3)
            self.blind.max_cell_voltage = None
            self.serve(service, [self.healthy, self.blind])
            self.run_cycles(service, 3)

        lines = [record.getMessage() for record in captured.records]
        self.assertEqual(2, len(lines))
        self.assertIn("Min. cell voltage missing", lines[0])
        self.assertIn("Max. and Min. cell voltage missing", lines[1])

    def test_the_aggregation_itself_is_unaffected_by_the_throttle(self):
        """Throttling the log must not change a single published value."""
        self.blind_to_cell_voltages(self.blind)
        reporting = Battery("Reporting", max_cell_voltage=3.48, max_voltage_cell_id=7, min_cell_voltage=3.21, min_voltage_cell_id=11)
        service = self.make_service([reporting, self.blind])

        with self.assertLogs(level="WARNING"):
            self.run_cycles(service, 30)

        published = service._dbusservice.published
        self.assertEqual(3.48, published["/System/MaxCellVoltage"])
        self.assertEqual("Reporting: 7", published["/System/MaxVoltageCellId"])
        self.assertEqual(3.21, published["/System/MinCellVoltage"])
        self.assertEqual(1, service._readTrials)


if __name__ == "__main__":
    unittest.main()
