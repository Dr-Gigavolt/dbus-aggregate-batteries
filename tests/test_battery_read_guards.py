#!/usr/bin/env python3

"""
Unit tests for the mandatory DC value guards in the battery read loop of
``DbusAggBatService._update()`` (non-CAN path).

A battery can be present on the bus but still serving None for /Dc/0/Voltage,
/Dc/0/Current, /Dc/0/Power or /Dc/0/Temperature. Before the guards this
produced a bare ``TypeError: unsupported operand type(s) for +=: 'int' and
'NoneType'`` that named neither the battery nor the value.

The guards deliberately do NOT skip the constituent the way the cell extrema
aggregation does: Current and Power are sums across batteries and Voltage and
Temperature are divided by NR_OF_BATTERIES afterwards, so dropping a battery
would publish a wrong bank number. The read trial / retry / restart path is
therefore unchanged; these tests pin down that the failure is now diagnosable
and that no partial accumulation happens before it.

The real driver is exercised; see driver_harness for how it is loaded and wired
off-device.
"""

import re
import unittest
from unittest import mock

from driver_harness import Battery, DriverTestCase

MANDATORY_MESSAGE = "Missing mandatory D-Bus value while reading battery"


def _locals_at_error(captured):
    """The 'Local variables at error' line the read-failure handler logs."""
    matching = [message for message in captured.output if "Local variables at error" in message]
    assert len(matching) == 1, "expected exactly one locals dump, got %d" % len(matching)
    return matching[0]


class MandatoryDcValueGuardTest(DriverTestCase):
    """A None V, I, P or temperature must name the battery and the values."""

    def _run_expecting_failure(self, batteries):
        service = self.make_service(batteries)
        with self.assertLogs(level="ERROR") as captured:
            # the existing read-failure handler swallows the exception, counts
            # the trial and asks to be called again
            self.assertTrue(service._update())
        return service, captured

    def _assert_message(self, captured, battery_name, expected_fragment):
        # the handler logs the exception itself and then a dump of the frame
        # locals (which repeats the exception); only the former is asserted on
        messages = [message for message in captured.output if MANDATORY_MESSAGE in message and "Exception occurred" in message]
        self.assertEqual(1, len(messages), "expected exactly one mandatory-value failure, got %r" % messages)
        self.assertIn(battery_name, messages[0])
        self.assertIn(expected_fragment, messages[0])
        self.assertIn("ValueError", messages[0], "must be the explicit ValueError, not a bare TypeError")
        self.assertNotIn("TypeError", messages[0])

    def test_none_voltage_names_the_battery_and_the_values(self):
        healthy = Battery("BatteryA")
        broken = Battery("BatteryB", voltage=None, current=12.0, power=624.0)
        service, captured = self._run_expecting_failure([healthy, broken])

        self._assert_message(captured, "BatteryB", "Voltage=None, Current=12.0, Power=624.0")
        self.assertEqual(2, service._readTrials, "the read trial must still be counted")
        self.assertEqual({}, service._dbusservice.published, "no aggregate may be published from a failed read")

    def test_none_current_names_the_battery_and_the_values(self):
        healthy = Battery("BatteryA")
        broken = Battery("BatteryB", voltage=52.0, current=None, power=624.0)
        service, captured = self._run_expecting_failure([healthy, broken])

        self._assert_message(captured, "BatteryB", "Voltage=52.0, Current=None, Power=624.0")
        self.assertEqual(2, service._readTrials)
        self.assertEqual({}, service._dbusservice.published)

    def test_none_power_names_the_battery_and_the_values(self):
        healthy = Battery("BatteryA")
        broken = Battery("BatteryB", voltage=52.0, current=12.0, power=None)
        service, captured = self._run_expecting_failure([healthy, broken])

        self._assert_message(captured, "BatteryB", "Voltage=52.0, Current=12.0, Power=None")
        self.assertEqual(2, service._readTrials)
        self.assertEqual({}, service._dbusservice.published)

    def test_none_temperature_names_the_battery_and_the_value(self):
        healthy = Battery("BatteryA")
        broken = Battery("BatteryB", temperature=None)
        service, captured = self._run_expecting_failure([healthy, broken])

        self._assert_message(captured, "BatteryB", "Temperature=None")
        self.assertEqual(2, service._readTrials)
        self.assertEqual({}, service._dbusservice.published)

    def test_all_three_missing_are_reported_together(self):
        """The message reports the whole triple, not just the first offender."""
        broken = Battery("Solo", voltage=None, current=None, power=None)
        _, captured = self._run_expecting_failure([broken])

        self._assert_message(captured, "Solo", "Voltage=None, Current=None, Power=None")

    def test_exhausted_read_trials_still_restart_the_driver(self):
        """The guard changes the message, not the retry/restart behaviour."""
        broken = Battery("Solo", voltage=None)
        service = self.make_service([broken], READ_TRIALS=1)
        service._readTrials = 1

        with mock.patch("time.sleep") as sleep:
            with self.assertLogs(level="ERROR") as captured:
                with self.assertRaises(SystemExit) as raised:
                    service._update()

        self.assertEqual(1, raised.exception.code)
        self.assertEqual(1, sleep.call_count)
        self.assertTrue(any(MANDATORY_MESSAGE in message for message in captured.output))


class NoPartialAccumulationTest(DriverTestCase):
    """The values are read into locals first, so nothing is summed before the raise."""

    def _assert_local_is_zero(self, captured, name):
        """Assert the driver's running total `name` was still 0 when it raised."""
        dump = _locals_at_error(captured)
        self.assertIsNotNone(
            re.search(r"'%s': 0[,}]" % name, dump),
            "expected %s to be untouched at the raise, locals were: %s" % (name, dump),
        )

    def test_voltage_and_current_are_not_accumulated_when_power_is_none(self):
        # a single battery, so any accumulation would have to come from this one
        broken = Battery("Solo", voltage=52.0, current=12.0, power=None)
        service = self.make_service([broken])

        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self._assert_local_is_zero(captured, "Voltage")
        self._assert_local_is_zero(captured, "Current")
        self._assert_local_is_zero(captured, "Power")

    def test_temperature_is_not_accumulated_when_it_is_none(self):
        broken = Battery("Solo", voltage=52.0, temperature=None)
        service = self.make_service([broken])

        with self.assertLogs(level="ERROR") as captured:
            self.assertTrue(service._update())

        self._assert_local_is_zero(captured, "Temperature")
        # and the check is not vacuous: V/I/P for this battery were accumulated
        # before the temperature read, so Voltage is no longer 0
        self.assertIsNone(re.search(r"'Voltage': 0[,}]", _locals_at_error(captured)))


class AllValuesPresentTest(DriverTestCase):
    """With every value present the aggregation is exactly what it was before."""

    def test_aggregate_is_published_unchanged(self):
        first = Battery("BatteryA", voltage=52.0, current=10.0, power=520.0, temperature=20.0)
        second = Battery("BatteryB", voltage=54.0, current=5.0, power=270.0, temperature=24.0)
        service = self.make_service([first, second])

        self.assertTrue(self.assertNothingWarned(service))

        published = service._dbusservice.published
        # Voltage and Temperature are averages over NR_OF_BATTERIES
        self.assertEqual(53.0, published["/Dc/0/Voltage"])
        self.assertEqual(22.0, published["/Dc/0/Temperature"])
        # Current and Power are sums
        self.assertEqual(15.0, published["/Dc/0/Current"])
        self.assertEqual(790.0, published["/Dc/0/Power"])
        self.assertEqual(1, service._readTrials, "a clean read must not count a trial")

    def test_zero_values_are_not_mistaken_for_missing(self):
        """0 A / 0 W are legitimate readings and must not trip the guard."""
        idle = Battery("BatteryA", voltage=52.0, current=0.0, power=0.0, temperature=0.0)
        other = Battery("BatteryB", voltage=52.0, current=0.0, power=0.0, temperature=0.0)
        service = self.make_service([idle, other])

        self.assertTrue(self.assertNothingWarned(service))

        published = service._dbusservice.published
        self.assertEqual(52.0, published["/Dc/0/Voltage"])
        self.assertEqual(0.0, published["/Dc/0/Current"])
        self.assertEqual(0.0, published["/Dc/0/Power"])
        self.assertEqual(0.0, published["/Dc/0/Temperature"])


if __name__ == "__main__":
    unittest.main()
