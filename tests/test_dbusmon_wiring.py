"""Tests that DbusMon hands the reactive callback through to DbusMonitor.

DbusMonitor is replaced by a recording stub (see driver_harness), so constructing
DbusMon touches no D-Bus at all and the constructor arguments can be inspected.
The dbusmon module itself is the real one: it is what is under test here.
"""

import unittest

import driver_harness


class DbusMonWiringTestCase(unittest.TestCase):
    def setUp(self):
        self.dbusmon = driver_harness.load_dbusmon()

    def test_callback_is_passed_as_value_changed_callback(self):
        def callback(service, path, options, changes, device_instance):  # pragma: no cover - never invoked
            return None

        monitor = self.dbusmon.DbusMon(value_changed_callback=callback).dbusmon
        self.assertIs(monitor.kwargs["valueChangedCallback"], callback)

    def test_aggregate_service_is_still_ignored(self):
        monitor = self.dbusmon.DbusMon(value_changed_callback=lambda *args: None).dbusmon
        self.assertEqual(monitor.kwargs["ignoreServices"], ["com.victronenergy.battery.aggregate"])

    def test_ignored_service_is_the_name_the_driver_publishes_under(self):
        """ignoreServices is the primary defence against our own publishes feeding back; it must name the right service."""
        driver = driver_harness.driver
        monitor = self.dbusmon.DbusMon().dbusmon
        self.assertIn(driver.AGGREGATE_SERVICE_NAME, monitor.kwargs["ignoreServices"])

    def test_callback_defaults_to_none(self):
        monitor = self.dbusmon.DbusMon().dbusmon
        self.assertIsNone(monitor.kwargs["valueChangedCallback"])

    def test_monitor_list_is_passed_positionally_and_covers_batteries(self):
        monitor = self.dbusmon.DbusMon().dbusmon
        self.assertIn("com.victronenergy.battery", monitor.monitorlist)
        self.assertIn("/Dc/0/Voltage", monitor.monitorlist["com.victronenergy.battery"])

    def test_driver_registers_its_reactive_callback_with_dbusmon(self):
        """_startMonitor must wire _on_input_changed through DbusMon into DbusMonitor."""
        driver = driver_harness.driver
        service = driver_harness.new_service()
        service._startMonitor()

        callback = driver_harness.RecordingDbusMonitor.last_instance.kwargs["valueChangedCallback"]
        self.assertEqual(callback.__func__, driver.DbusAggBatService._on_input_changed)
        self.assertIs(callback.__self__, service)


if __name__ == "__main__":
    unittest.main()
