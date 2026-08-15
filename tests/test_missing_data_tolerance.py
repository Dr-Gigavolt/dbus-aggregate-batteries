#!/usr/bin/env python3

"""
Unit tests for riding out a constituent that is not serving data.

A battery driver that restarts takes its D-Bus service off the bus, and the
monitor then answers None for its paths instead of raising. On a production
Cerbo GX that lasted roughly 50 s, during which the aggregate exhausted
READ_TRIALS, exited, and restarted into a battery search that could not find the
battery either. A neighbouring driver restarting is a normal event, not a fault
of the aggregation.

Riding it out is bounded on purpose. A restart landing on another that is still
initialising was measured at 125 s to 134 s of absence, and that is deliberately
outside the shipped window: an absence far longer than a restart is a problem of
its own, and the escalation path below - named battery, measured gap, exceeded
tolerance, handover - is a better answer than silence.

What the driver does instead is bounded by MISSING_DATA_TOLERANCE seconds of
wall clock time, and while it lasts it publishes *nothing*: Current and Power
are sums over the bank and Voltage and Temperature are divided by
NR_OF_BATTERIES, so an aggregate over the remaining batteries would under-report
or skew the bank. Consumers keep seeing the last complete aggregate, which is a
better answer for DVCC than a fresh partial one. Only when the window is
exceeded does the old read failure path take over, unchanged.

Time is injected: the driver's ``tt`` module is replaced by a clock the test
advances by hand, so nothing here sleeps.

The real driver is exercised; see driver_harness for how it is loaded and wired
off-device.
"""

import shutil
import unittest
from unittest import mock

import driver_harness
from driver_harness import Battery, DriverTestCase, FakeDbusMon, driver

# the window the behaviour tests configure. Deliberately not the shipped default:
# these tests are about what happens at the edges of the window, whatever it is
# set to, and the default is asserted on its own in MissingDataToleranceConfigTest
TOLERANCE = 60


class FakeClock:
    """Stands in for the driver's ``time`` module: a clock the test moves itself."""

    def __init__(self, now=1_000_000.0):
        self.now = now
        self.slept = []
        """seconds passed to every tt.sleep() call, in order"""

    def time(self):
        return self.now

    def sleep(self, seconds):
        # the driver only sleeps before exiting; record it instead of waiting
        self.slept.append(seconds)

    def advance(self, seconds):
        self.now += seconds
        return self.now


def serve(service, present, absent=()):
    """Rewire the monitor: ``present`` answer their scripted values, ``absent`` answer None.

    A service that has left the bus is not simply missing from the monitor's
    answers - DbusMonitor returns None for every path of a vanished service,
    which is exactly what the driver has to cope with.
    """
    values = {}
    for battery in present:
        values.update(battery.values())
    for battery in absent:
        values.update({key: None for key in battery.values()})
    service._dbusMon = FakeDbusMon(values)


class MissingDataTestCase(DriverTestCase):
    """A two battery bank whose second battery can be taken off the bus at will."""

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        patcher = mock.patch.object(driver, "tt", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.healthy = Battery("BatteryA", voltage=52.0, current=10.0, power=520.0, temperature=20.0)
        self.vanishing = Battery("BatteryB", voltage=54.0, current=5.0, power=270.0, temperature=24.0)

    def make_bank(self, **overrides):
        overrides.setdefault("MISSING_DATA_TOLERANCE", TOLERANCE)
        return self.make_service([self.healthy, self.vanishing], **overrides)

    def first_complete_cycle(self, service):
        """One successful update, so that there is something published to protect."""
        self.assertTrue(service._update())
        self.assertNotEqual([], service._dbusservice.written)

    def vanish(self, service):
        serve(service, [self.healthy], [self.vanishing])

    def restore(self, service):
        serve(service, [self.healthy, self.vanishing])


class ToleratedGapTest(MissingDataTestCase):
    """While a constituent is absent, the service publishes nothing at all."""

    def test_nothing_is_written_during_the_gap(self):
        service = self.make_bank()
        self.first_complete_cycle(service)
        writes_before = list(service._dbusservice.written)

        self.vanish(service)
        with self.assertLogs(level="WARNING"):
            for _ in range(10):
                self.clock.advance(1)
                self.assertTrue(service._update(), "the update must ask to be called again")

        self.assertEqual(
            writes_before,
            service._dbusservice.written,
            "not a single value may reach the service while a constituent is missing",
        )

    def test_consumers_keep_seeing_the_last_complete_aggregate(self):
        service = self.make_bank()
        self.first_complete_cycle(service)
        published_before = dict(service._dbusservice.published)
        # 53 V, the average of the two batteries, not the 52 V of the survivor
        self.assertEqual(53.0, published_before["/Dc/0/Voltage"])
        self.assertEqual(15.0, published_before["/Dc/0/Current"])

        # the surviving battery even moves while the other one is away: still no
        # partial aggregate, however tempting a fresh number looks
        self.healthy.voltage = 50.0
        self.healthy.current = 30.0
        self.vanish(service)
        with self.assertLogs(level="WARNING"):
            self.clock.advance(1)
            service._update()

        self.assertEqual(published_before, service._dbusservice.published)

    def test_no_read_trial_is_consumed(self):
        service = self.make_bank()
        self.first_complete_cycle(service)

        self.vanish(service)
        with self.assertLogs(level="WARNING"):
            for _ in range(20):
                self.clock.advance(1)
                service._update()

        self.assertEqual(1, service._readTrials, "a driver restarting next door is not a read failure of ours")

    def test_the_gap_is_announced_naming_the_battery_and_the_value(self):
        service = self.make_bank()
        self.vanish(service)

        with self.assertLogs(level="WARNING") as captured:
            service._update()

        announcements = [message for message in captured.output if "Battery data missing" in message]
        self.assertEqual(1, len(announcements), "expected exactly one announcement, got %r" % announcements)
        self.assertIn(self.vanishing.name, announcements[0])
        self.assertIn("Voltage=None", announcements[0])
        self.assertIn("Publishing nothing", announcements[0])
        self.assertIn(str(TOLERANCE), announcements[0])

    def test_repeated_lines_are_rate_limited(self):
        """A minute long gap must not produce a line per update cycle."""
        service = self.make_bank()
        self.vanish(service)

        with self.assertLogs(level="WARNING") as captured:
            for _ in range(TOLERANCE):
                service._update()
                self.clock.advance(1)

        lines = [message for message in captured.output if "Battery data" in message]
        self.assertLessEqual(len(lines), 1 + TOLERANCE // driver.MISSING_DATA_LOG_PERIOD)
        # but the state is repeated, so an operator reading the log sees it persist
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(self.vanishing.name in message for message in lines))

    def test_zero_tolerance_does_not_wait_at_all(self):
        """The escape hatch back to the behaviour from before this option existed."""
        service = self.make_bank(MISSING_DATA_TOLERANCE=0)
        self.vanish(service)

        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self.assertEqual(2, service._readTrials)
        self.assertFalse(any("Battery data missing" in message for message in captured.output))


class RecoveryTest(MissingDataTestCase):
    """When the constituent comes back, publishing resumes and the log says so."""

    def test_recovery_within_the_window_resumes_publishing(self):
        service = self.make_bank()
        self.first_complete_cycle(service)

        self.vanish(service)
        with self.assertLogs(level="WARNING"):
            for _ in range(30):
                self.clock.advance(1)
                service._update()

        self.restore(service)
        self.clock.advance(1)
        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        recovery = [message for message in captured.output if "complete again" in message]
        self.assertEqual(1, len(recovery), "expected exactly one recovery line, got %r" % recovery)
        # the gap opened on the first cycle that found the battery gone
        self.assertIn("30 s", recovery[0])
        self.assertEqual(53.0, service._dbusservice.published["/Dc/0/Voltage"])
        self.assertIsNone(service._missingDataSince)

    def test_a_second_gap_is_announced_again(self):
        """Recovery closes the window, so the next gap is a new one, not a continuation."""
        service = self.make_bank()

        for _ in range(2):
            self.vanish(service)
            with self.assertLogs(level="WARNING") as captured:
                self.clock.advance(1)
                service._update()
            self.assertTrue(any("Battery data missing" in message for message in captured.output))

            self.restore(service)
            with self.assertLogs(level="WARNING"):
                self.clock.advance(1)
                service._update()

        self.assertEqual(1, service._readTrials)


class WindowExceededTest(MissingDataTestCase):
    """Past MISSING_DATA_TOLERANCE the old read failure path takes over unchanged."""

    def _run_past_the_window(self, service):
        self.vanish(service)
        with self.assertLogs(level="WARNING"):
            service._update()
        self.clock.advance(TOLERANCE + 1)

    def test_the_handover_is_logged_and_counts_a_read_trial(self):
        service = self.make_bank()
        self._run_past_the_window(service)

        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        handover = [message for message in captured.output if "more than MISSING_DATA_TOLERANCE" in message]
        self.assertEqual(1, len(handover))
        self.assertIn("61 s", handover[0])
        self.assertEqual(2, service._readTrials, "from here on the read trials count as they always did")
        self.assertEqual([], service._dbusservice.written, "still nothing published")

    def test_the_handover_is_logged_once_not_per_cycle(self):
        service = self.make_bank(READ_TRIALS=100)
        self._run_past_the_window(service)

        with self.assertLogs(level="ERROR") as captured:
            for _ in range(10):
                self.clock.advance(1)
                service._update()

        handover = [message for message in captured.output if "more than MISSING_DATA_TOLERANCE" in message]
        self.assertEqual(1, len(handover), "expected the handover to be announced once, got %r" % handover)
        self.assertEqual(11, service._readTrials)

    def test_read_trials_still_end_in_a_restart(self):
        service = self.make_bank(READ_TRIALS=1)
        self._run_past_the_window(service)

        with self.assertLogs(level="ERROR") as captured:
            with self.assertRaises(SystemExit) as raised:
                service._update()

        self.assertEqual(1, raised.exception.code)
        self.assertEqual([driver.settings.TIME_BEFORE_RESTART], self.clock.slept)
        self.assertTrue(any("DBus read failed" in message for message in captured.output))

    def test_data_returning_after_the_window_still_recovers(self):
        """Expiry is not a point of no return: only READ_TRIALS ends the process."""
        service = self.make_bank(READ_TRIALS=100)
        self._run_past_the_window(service)
        with self.assertLogs(level="ERROR"):
            service._update()

        self.restore(service)
        self.clock.advance(1)
        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        self.assertTrue(any("complete again" in message for message in captured.output))
        self.assertEqual(1, service._readTrials)
        self.assertEqual(53.0, service._dbusservice.published["/Dc/0/Voltage"])


class OtherExceptionsTest(MissingDataTestCase):
    """Every other read error keeps the READ_TRIALS semantics exactly."""

    def _break_capacity(self, service):
        """A None that is not one of the guarded values: it raises a plain TypeError."""
        values = {}
        for battery in (self.healthy, self.vanishing):
            values.update(battery.values())
        values[(self.vanishing.service, "/InstalledCapacity")] = None
        service._dbusMon = FakeDbusMon(values)

    def test_a_plain_read_error_counts_one_trial_per_cycle(self):
        service = self.make_bank()
        self._break_capacity(service)

        with self.assertLogs(level="ERROR") as captured:
            for trial in range(1, 6):
                self.clock.advance(1)
                self.assertTrue(service._update())
                self.assertEqual(trial + 1, service._readTrials)

        self.assertTrue(any("TypeError" in message for message in captured.output))
        self.assertIsNone(service._missingDataSince, "this is not a missing data gap and must not open one")
        self.assertEqual([], service._dbusservice.written)

    def test_a_plain_read_error_still_exits_after_read_trials(self):
        service = self.make_bank(READ_TRIALS=1)
        self._break_capacity(service)

        with self.assertLogs(level="ERROR"):
            with self.assertRaises(SystemExit) as raised:
                service._update()

        self.assertEqual(1, raised.exception.code)
        self.assertEqual([driver.settings.TIME_BEFORE_RESTART], self.clock.slept)

    def test_a_plain_read_error_is_not_waited_out(self):
        """Its budget is trials, not seconds: time passing does not extend it."""
        service = self.make_bank(READ_TRIALS=2)
        self._break_capacity(service)

        with self.assertLogs(level="ERROR"):
            self.assertTrue(service._update())
            # ten windows worth of time buys nothing here
            self.clock.advance(TOLERANCE * 10)
            with self.assertRaises(SystemExit):
                service._update()


class ChargeIntegrationAcrossGapTest(MissingDataTestCase):
    """The Coulomb counter must account for the tolerated gap exactly once."""

    def make_bank(self, **overrides):
        # a bank that is charging at a known, constant current, with the
        # efficiency factor out of the way
        self.healthy.current = 5.0
        self.vanishing.current = 5.0
        overrides.setdefault("BATTERY_EFFICIENCY", 1.0)
        return super().make_bank(**overrides)

    def test_the_gap_is_integrated_once_when_the_data_returns(self):
        service = self.make_bank()
        self.clock.advance(10)
        self.first_complete_cycle(service)
        charge_after_first_cycle = service._ownCharge

        self.vanish(service)
        with self.assertLogs(level="WARNING"):
            for _ in range(30):
                self.clock.advance(1)
                service._update()

        self.assertEqual(charge_after_first_cycle, service._ownCharge, "a cycle that published nothing must not integrate")

        self.restore(service)
        self.clock.advance(1)
        with self.assertLogs(level="WARNING"):
            service._update()

        # 10 A of bank current for the 31 s that passed since the last complete
        # cycle: the gap is neither lost nor counted twice
        self.assertAlmostEqual(charge_after_first_cycle + 10.0 * 31 / 3600, service._ownCharge, places=9)

    def test_time_old_is_not_advanced_by_a_skipped_cycle(self):
        service = self.make_bank()
        self.first_complete_cycle(service)
        time_old = service._timeOld

        self.vanish(service)
        with self.assertLogs(level="WARNING"):
            for _ in range(5):
                self.clock.advance(1)
                service._update()

        self.assertEqual(time_old, service._timeOld)

    def test_a_complete_cycle_samples_the_clock_once(self):
        service = self.make_bank()
        self.first_complete_cycle(service)
        self.assertEqual(self.clock.now, service._timeOld)


class LogValueTest(unittest.TestCase):
    """The periodic log line must never be the thing that takes the driver down."""

    def test_a_number_is_formatted_as_before(self):
        self.assertEqual("52.4", driver._log_value(52.35))
        self.assertEqual("52", driver._log_value(52.35, "%.0f"))
        self.assertEqual("3.333", driver._log_value(10 / 3, "%.3f"))

    def test_none_does_not_raise(self):
        self.assertEqual("n/a", driver._log_value(None))
        self.assertEqual("n/a", driver._log_value(None, "%.3f"))


class MissingDataToleranceConfigTest(unittest.TestCase):
    """The ini option: its default, an override and the values that are rejected."""

    def _settings_for(self, overrides=None, include_user_config=True):
        directory = driver_harness.make_config_dir(overrides, include_user_config=include_user_config)
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return driver_harness.new_settings_module(directory)

    def test_default_covers_a_single_driver_restart_with_margin(self):
        module = self._settings_for()
        driver_harness.exec_settings(module)
        self.assertEqual(120, module.MISSING_DATA_TOLERANCE)
        # a clean single driver restart measured roughly 50 s on a Cerbo GX, and
        # the window is worth having only if it clears that comfortably
        self.assertGreater(module.MISSING_DATA_TOLERANCE, 2 * 50)
        self.assertEqual([], module.errors_in_config)

    def test_default_does_not_cover_a_compound_restart(self):
        """Deliberate: two minutes of absence is escalated, not sat out.

        A restart landing on one still initialising measured 125 s to 134 s. A
        default that swallowed it would also swallow a battery that is broken or
        has been removed, in silence, for that long.
        """
        module = self._settings_for()
        driver_harness.exec_settings(module)
        self.assertLess(module.MISSING_DATA_TOLERANCE, 125)

    def test_the_shipped_default_is_used_without_a_user_config(self):
        module = self._settings_for(include_user_config=False)
        with self.assertRaises(SystemExit):
            # the shipped NR_OF_BATTERIES placeholder is invalid on purpose
            driver_harness.exec_settings(module)
        self.assertEqual(120, module.MISSING_DATA_TOLERANCE)

    def test_it_can_be_overridden(self):
        module = self._settings_for({"MISSING_DATA_TOLERANCE": "120"})
        driver_harness.exec_settings(module)
        self.assertEqual(120, module.MISSING_DATA_TOLERANCE)
        self.assertEqual([], module.errors_in_config)

    def test_zero_is_accepted_as_the_escape_hatch(self):
        module = self._settings_for({"MISSING_DATA_TOLERANCE": "0"})
        driver_harness.exec_settings(module)
        self.assertEqual(0, module.MISSING_DATA_TOLERANCE)
        self.assertEqual([], module.errors_in_config)

    def test_a_negative_value_is_rejected(self):
        module = self._settings_for({"MISSING_DATA_TOLERANCE": "-1"})
        with self.assertRaises(SystemExit):
            driver_harness.exec_settings(module)
        self.assertIn(
            "MISSING_DATA_TOLERANCE must be 0 or greater.",
            module.errors_in_config,
        )

    def test_a_non_numeric_value_is_rejected(self):
        module = self._settings_for({"MISSING_DATA_TOLERANCE": "a minute"})
        with self.assertRaises(SystemExit):
            driver_harness.exec_settings(module)
        self.assertTrue(
            any("MISSING_DATA_TOLERANCE" in error for error in module.errors_in_config),
            "expected the invalid value to be reported, got %r" % module.errors_in_config,
        )


if __name__ == "__main__":
    unittest.main()
