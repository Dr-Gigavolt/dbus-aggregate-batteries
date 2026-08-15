#!/usr/bin/env python3

"""
Unit tests for a constituent that is registered and serving DC values while its
BMS has not answered yet, so that its per-cell and charge parameter paths read
as None.

This is the second shape of the fault this branch is about, and it was captured
on a production Cerbo GX: after both battery drivers restarted, one battery came
back running on its fallback shunt, which has DC values but cannot see cells.
For 19 s it reported None for /System/Max|MinCellVoltage, /System/Max|MinCell-
Temperature and its charge parameters. One cycle into that window the driver
died with

    TypeError('must be real number, not NoneType')

That message is what "%.1f" % None raises, and the periodic log line formats the
CVL, CCL and DCL exactly that way. The None got there through Functions._min(),
which answers None for a list containing one instead of raising - so the same
None had already been published to /Info/MaxChargeVoltage, i.e. an invalid CVL
had reached DVCC one line before the crash.

An exception escaping _update() is worse than it looks: GLib drops the source of
a callback that raised, so the aggregation stops for good while the service
keeps its last values on the bus.

The real driver is exercised; see driver_harness for how it is loaded and wired
off-device.
"""

import unittest
from unittest import mock

from driver_harness import NR_OF_CELLS, Battery, DriverTestCase, FakeDbusMon, driver

# paths a battery running on its fallback shunt cannot answer
CELL_PATHS = (
    "/System/MaxCellVoltage",
    "/System/MinCellVoltage",
    "/System/MaxCellTemperature",
    "/System/MinCellTemperature",
)
CELL_ID_PATHS = (
    "/System/MaxVoltageCellId",
    "/System/MinVoltageCellId",
    "/System/MaxTemperatureCellId",
    "/System/MinTemperatureCellId",
)
CHARGE_PARAMETER_PATHS = (
    "/Info/MaxChargeVoltage",
    "/Info/MaxChargeCurrent",
    "/Info/MaxDischargeCurrent",
    "/Info/ChargeMode",
)


class PartialConstituentTestCase(DriverTestCase):
    """Battery A with everything, battery B with DC values and nothing per-cell."""

    def setUp(self):
        super().setUp()
        self.healthy = Battery(
            "BatteryA",
            voltage=52.0,
            current=10.0,
            power=520.0,
            temperature=20.0,
            max_cell_voltage=3.48,
            max_voltage_cell_id=7,
            min_cell_voltage=3.21,
            min_voltage_cell_id=11,
            max_cell_temperature=24.0,
            min_cell_temperature=19.0,
        )
        self.degraded = Battery("BatteryB", voltage=54.0, current=5.0, power=270.0, temperature=24.0)

    def make_bank(self, missing_paths, **overrides):
        """A service whose second battery answers None for ``missing_paths``."""
        service = self.make_service([self.healthy, self.degraded], **overrides)
        values = {}
        for battery in (self.healthy, self.degraded):
            values.update(battery.values())
        for path in missing_paths:
            values[(self.degraded.service, path)] = None
        service._dbusMon = FakeDbusMon(values)
        return service

    def assertNoValueIsNone(self, service):
        """No path may be published as None: that is an invalid value on D-Bus."""
        none_writes = [path for path, value in service._dbusservice.written if value is None]
        self.assertEqual([], none_writes, "None reached D-Bus on %r" % none_writes)


class MissingChargeParametersTest(PartialConstituentTestCase):
    """The shape that crashed in production: no per-cell data and no charge parameters."""

    def make_bank(self, missing_paths=CELL_PATHS + CELL_ID_PATHS + CHARGE_PARAMETER_PATHS, **overrides):
        return super().make_bank(missing_paths, **overrides)

    def test_no_exception_escapes_the_update(self):
        # LOG_PERIOD > 0 with the timestamp at 0 is the state right after a
        # start: the periodic log line runs on the very first cycle, which is
        # where the TypeError was raised in production
        service = self.make_bank(LOG_PERIOD=300)
        service._logLastPrintTimeStamp = 0

        with self.assertLogs(level="WARNING"):
            self.assertTrue(service._update(), "the update must survive and ask to be called again")

    def test_nothing_is_published(self):
        service = self.make_bank()

        with self.assertLogs(level="WARNING"):
            service._update()

        self.assertEqual([], service._dbusservice.written)

    def test_no_invalid_cvl_reaches_dvcc(self):
        """The min. over a list containing None is None, and that must not be published."""
        service = self.make_bank()

        with self.assertLogs(level="WARNING"):
            service._update()

        for path in ("/Info/MaxChargeVoltage", "/Info/MaxChargeCurrent", "/Info/MaxDischargeCurrent"):
            self.assertNotIn(path, service._dbusservice.published)
        self.assertNoValueIsNone(service)

    def test_the_missing_charge_parameters_are_named(self):
        service = self.make_bank()

        with self.assertLogs(level="WARNING") as captured:
            service._update()

        announcements = [message for message in captured.output if "Missing charge parameter" in message]
        self.assertEqual(1, len(announcements), "expected one announcement, got %r" % announcements)
        self.assertIn(self.degraded.name, announcements[0])
        self.assertIn("MaxChargeVoltage=None", announcements[0])

    def test_a_single_missing_charge_voltage_is_enough(self):
        """The incident's narrowest shape, reproduced exactly.

        With only /Info/MaxChargeVoltage absent, the old code published None to
        /Info/MaxChargeVoltage - D-Bus takes that as "invalid", so the publish
        itself does not complain - and then raised TypeError("must be real
        number, not NoneType") formatting the same None into the CVL log line.
        """
        service = self.make_bank(("/Info/MaxChargeVoltage",), LOG_PERIOD=300)
        service._logLastPrintTimeStamp = 0

        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        self.assertNotIn("/Info/MaxChargeVoltage", service._dbusservice.published)
        self.assertEqual([], service._dbusservice.written)
        self.assertTrue(any("MaxChargeVoltage=None" in message for message in captured.output))

    def test_it_is_a_tolerated_gap_not_a_read_failure(self):
        service = self.make_bank()

        with self.assertLogs(level="WARNING"):
            service._update()

        self.assertEqual(1, service._readTrials)

    def test_publishing_resumes_when_the_bms_answers(self):
        """The production window lasted 19 s; the bank must simply pick up again."""
        service = self.make_bank()
        with self.assertLogs(level="WARNING"):
            service._update()

        values = {}
        for battery in (self.healthy, self.degraded):
            values.update(battery.values())
        service._dbusMon = FakeDbusMon(values)

        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        self.assertTrue(any("complete again" in message for message in captured.output))
        self.assertEqual(53.0, service._dbusservice.published["/Dc/0/Voltage"])
        self.assertNoValueIsNone(service)


class MissingCellDataOnlyTest(PartialConstituentTestCase):
    """Charge parameters present, per-cell data absent: the bank still publishes."""

    def make_bank(self, missing_paths=CELL_PATHS + CELL_ID_PATHS, **overrides):
        return super().make_bank(missing_paths, **overrides)

    def test_the_aggregate_is_published_from_the_reporting_battery(self):
        service = self.make_bank(LOG_PERIOD=300)
        service._logLastPrintTimeStamp = 0

        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        published = service._dbusservice.published
        # the bank sums and averages cover both batteries
        self.assertEqual(53.0, published["/Dc/0/Voltage"])
        self.assertEqual(15.0, published["/Dc/0/Current"])
        # the extrema come from the only battery that can see its cells, loudly
        self.assertEqual(3.48, published["/System/MaxCellVoltage"])
        self.assertEqual("BatteryA: 7", published["/System/MaxVoltageCellId"])
        self.assertEqual(2, len([message for message in captured.output if "excluded from aggregation" in message]))

    def test_no_value_is_published_as_none(self):
        service = self.make_bank()

        with self.assertLogs(level="WARNING"):
            service._update()

        self.assertNoValueIsNone(service)

    def test_the_periodic_log_line_survives_it(self):
        service = self.make_bank(LOG_PERIOD=300)
        service._logLastPrintTimeStamp = 0

        with self.assertLogs(level="INFO") as captured:
            service._update()

        cvl_lines = [message for message in captured.output if "CVL:" in message]
        self.assertEqual(1, len(cvl_lines))
        self.assertNotIn("n/a", cvl_lines[0], "with the guards in place the values are all present")

    def test_missing_cell_voltages_are_published_as_invalid_for_that_battery_only(self):
        """SEND_CELL_VOLTAGES=1: the absent battery's own cells are invalid, the bank is not."""
        missing = CELL_PATHS + CELL_ID_PATHS + tuple("/Voltages/Cell%d" % cell for cell in range(1, NR_OF_CELLS + 1))
        service = self.make_bank(missing, SEND_CELL_VOLTAGES=1)

        with self.assertLogs(level="WARNING"):
            service._update()

        written = dict(service._dbusservice.written)
        for cell in range(1, NR_OF_CELLS + 1):
            path = "/Voltages/%s_Cell%d" % (self.degraded.name, cell)
            self.assertIn(path, written)
            self.assertIsNone(written[path], "an unknown cell voltage is invalid, not a made up number")
            self.assertEqual(3.3, written["/Voltages/%s_Cell%d" % (self.healthy.name, cell)])

        # and no bank level path is invalid because of it
        bank_nones = [path for path, value in service._dbusservice.written if value is None and "_Cell" not in path]
        self.assertEqual([], bank_nones)

    def test_a_missing_charge_mode_neither_raises_nor_decides_the_cvl(self):
        """KEEP_MAX_CVL inspects ChargeMode; a battery that does not publish it reads as None."""
        service = self.make_bank(CELL_PATHS + CELL_ID_PATHS + ("/Info/ChargeMode",), KEEP_MAX_CVL=True)

        with self.assertLogs(level="WARNING"):
            self.assertTrue(service._update())

        # no battery said "Float", so the minimum is used, as without KEEP_MAX_CVL
        self.assertEqual(55.2, service._dbusservice.published["/Info/MaxChargeVoltage"])


class MissingVoltagesSumTest(PartialConstituentTestCase):
    """/Voltages/Sum is a bank average too, so its absence is waited out as well."""

    def test_it_is_tolerated_and_publishes_nothing(self):
        service = self.make_bank(("/Voltages/Sum",))

        with self.assertLogs(level="WARNING") as captured:
            self.assertTrue(service._update())

        self.assertEqual([], service._dbusservice.written)
        self.assertEqual(1, service._readTrials)
        self.assertTrue(any("/Voltages/Sum" in message for message in captured.output))

    def test_a_permanent_absence_still_ends_in_the_read_failure_path(self):
        """The message points at a config error, so it must still reach the operator."""
        service = self.make_bank(("/Voltages/Sum",), MISSING_DATA_TOLERANCE=0, READ_TRIALS=1)

        with mock.patch("time.sleep"):
            with self.assertLogs(level="ERROR") as captured:
                with self.assertRaises(SystemExit):
                    service._update()

        self.assertTrue(any("BATTERY_CELL_DATA_FORMAT" in message for message in captured.output))


class MinAndMaxHelperTest(unittest.TestCase):
    """Why the guards are needed at all: the exception safe helpers swallow the None."""

    def test_min_over_a_list_with_none_is_none(self):
        functions = driver.Functions()
        self.assertIsNone(functions._min([55.2, None]))
        self.assertIsNone(functions._max([0, None]))
        # which is the value that used to be published and then formatted
        with self.assertRaises(TypeError) as raised:
            "%.1f" % functions._min([55.2, None])
        self.assertIn("must be real number", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
