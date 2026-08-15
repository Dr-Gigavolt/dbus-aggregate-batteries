"""Tests for the reactive-update scheduling in dbus-aggregate-batteries.py.

The real DbusAggBatService.__init__ connects to D-Bus, so it is never called
here: the object is created with object.__new__ and only the attributes the
methods under test actually read are set (_reactive_ready, _updating) plus a
recording stand-in for _update, which as an instance attribute shadows the
heavyweight class method.  GLib is swapped for a stub that records scheduling
calls, so the queued idle callback runs only when a test decides to run it.
"""

import unittest

import driver_stubs


class _RecordingUpdate:
    """Callable stand-in for DbusAggBatService._update that counts its calls."""

    def __init__(self, raises=None, side_effect=None):
        self.calls = 0
        self.raises = raises
        self.side_effect = side_effect

    def __call__(self):
        self.calls += 1
        if self.side_effect is not None:
            self.side_effect()
        if self.raises is not None:
            raise self.raises
        return True


class _DbusString:
    """Mimics dbus.String: not a str subclass, but str() yields the service name."""

    def __init__(self, value):
        self._value = value

    def __str__(self):
        return self._value


NON_BATTERY_SERVICES = [
    "com.victronenergy.vebus.ttyO1",
    "com.victronenergy.solarcharger.ttyUSB0",
    "com.victronenergy.temperature.ttyUSB1",
    "com.victronenergy.system",
    "com.victronenergy.settings",
    "com.victronenergy.dcload.ttyUSB2",
    "com.victronenergy.multi.ttyUSB3",
]


class ReactiveSchedulingTestCase(unittest.TestCase):
    def setUp(self):
        self.driver = driver_stubs.load_driver()
        self.glib = driver_stubs.FakeGLib()
        self._original_glib = self.driver.GLib
        self.driver.GLib = self.glib
        self.addCleanup(self._restore_glib)

    def _restore_glib(self):
        self.driver.GLib = self._original_glib

    def _make_service(self, reactive_ready=True, update=None):
        service = object.__new__(self.driver.DbusAggBatService)
        service._reactive_ready = reactive_ready
        service._updating = False
        service._update = update if update is not None else _RecordingUpdate()
        return service

    @staticmethod
    def _change(service, path="/Dc/0/Voltage", value=52.1):
        """Argument tuple as DbusMonitor delivers it: service, path, options, changes, deviceInstance."""
        return (service, path, {}, {"Value": value, "Text": str(value)}, 512)

    # ── service filtering ────────────────────────────────────────────────

    def test_battery_change_schedules_an_update(self):
        service = self._make_service()
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        self.assertEqual(len(self.glib.idle_calls), 1)
        self.assertTrue(service._updating)

    def test_scheduled_callback_is_update_reactive(self):
        service = self._make_service()
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        callback, args = self.glib.idle_calls[0]
        self.assertEqual(args, ())
        self.assertEqual(callback.__func__, self.driver.DbusAggBatService._update_reactive)
        self.assertIs(callback.__self__, service)

    def test_changes_from_other_services_are_ignored(self):
        for name in NON_BATTERY_SERVICES:
            with self.subTest(service=name):
                service = self._make_service()
                service._on_input_changed(*self._change(name, path="/Dc/0/Current", value=-3.2))
                self.assertEqual(self.glib.idle_calls, [])
                self.assertFalse(service._updating)
                self.assertEqual(service._update.calls, 0)

    def test_service_name_is_stringified_before_the_prefix_check(self):
        service = self._make_service()
        service._on_input_changed(*self._change(_DbusString("com.victronenergy.battery.ttyUSB0")))
        self.assertEqual(len(self.glib.idle_calls), 1)

        other = self._make_service()
        other._on_input_changed(*self._change(_DbusString("com.victronenergy.vebus.ttyO1")))
        self.assertEqual(len(self.glib.idle_calls), 1)

    # ── arming ───────────────────────────────────────────────────────────

    def test_nothing_is_scheduled_before_the_battery_search_completes(self):
        for name in ["com.victronenergy.battery.ttyUSB0"] + NON_BATTERY_SERVICES:
            with self.subTest(service=name):
                service = self._make_service(reactive_ready=False)
                service._on_input_changed(*self._change(name))
                self.assertEqual(self.glib.idle_calls, [])
                self.assertFalse(service._updating)

    def test_arming_after_a_dropped_change_allows_the_next_one(self):
        service = self._make_service(reactive_ready=False)
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        self.assertEqual(self.glib.idle_calls, [])

        service._reactive_ready = True
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        self.assertEqual(len(self.glib.idle_calls), 1)

    # ── coalescing ───────────────────────────────────────────────────────

    def test_burst_of_changes_produces_exactly_one_update(self):
        service = self._make_service()
        paths = ["/Dc/0/Voltage", "/Dc/0/Current", "/Dc/0/Power", "/Soc", "/System/MinCellVoltage", "/System/MaxCellVoltage"]
        for path in paths:
            service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0", path=path))

        self.assertEqual(len(self.glib.idle_calls), 1, "a burst must be coalesced into a single queued update")
        self.glib.run_pending_idle()
        self.assertEqual(service._update.calls, 1)

    def test_a_change_after_the_update_ran_schedules_a_new_one(self):
        service = self._make_service()
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        self.glib.run_pending_idle()
        self.assertFalse(service._updating)

        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB1", path="/Soc", value=71.0))
        self.assertEqual(len(self.glib.idle_calls), 1)
        self.glib.run_pending_idle()
        self.assertEqual(service._update.calls, 2)

    def test_changes_arriving_while_update_runs_are_served_by_that_run(self):
        service = self._make_service()

        def change_during_update():
            service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0", path="/Soc", value=80.0))

        service._update = _RecordingUpdate(side_effect=change_during_update)
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        self.glib.run_pending_idle()

        self.assertEqual(service._update.calls, 1)
        self.assertEqual(self.glib.idle_calls, [], "a change seen during the update must not queue a second one")

    # ── one-shot semantics and the finally-guard ─────────────────────────

    def test_update_reactive_returns_false_so_the_idle_source_is_removed(self):
        service = self._make_service()
        self.assertIs(service._update_reactive(), False)

    def test_updating_guard_is_cleared_when_update_raises(self):
        service = self._make_service(update=_RecordingUpdate(raises=RuntimeError("boom")))
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        with self.assertRaises(RuntimeError):
            self.glib.run_pending_idle()
        self.assertFalse(service._updating, "the finally block must clear _updating even on failure")

    def test_reactive_updates_recover_after_a_failed_update(self):
        failing = _RecordingUpdate(raises=RuntimeError("boom"))
        service = self._make_service(update=failing)
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        with self.assertRaises(RuntimeError):
            self.glib.run_pending_idle()

        healthy = _RecordingUpdate()
        service._update = healthy
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        self.assertEqual(len(self.glib.idle_calls), 1, "one exception must not wedge reactive updates")
        self.glib.run_pending_idle()
        self.assertEqual(healthy.calls, 1)

    def test_reactive_floor_is_a_positive_slow_floor(self):
        self.assertIsInstance(self.driver.DbusAggBatService.REACTIVE_FLOOR_S, int)
        self.assertGreater(self.driver.DbusAggBatService.REACTIVE_FLOOR_S, 1)


if __name__ == "__main__":
    unittest.main()
