"""Tests for the reactive-update scheduling in dbus-aggregate-batteries.py.

The real DbusAggBatService.__init__ connects to D-Bus, so it is never called
here: the object is created with object.__new__ and only the attributes the
methods under test actually read are set (_reactive_ready, _updating) plus a
recording stand-in for _update, which as an instance attribute shadows the
heavyweight class method.  GLib is swapped for a stub that records scheduling
calls, so the queued idle callback runs only when a test decides to run it.
"""

import inspect
import logging
import os
import re
import unittest

import driver_harness


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


def _line_of(func, needle):
    """Absolute source line number of the first line of ``func`` that contains ``needle``."""
    lines, first = inspect.getsourcelines(func)
    for offset, text in enumerate(lines):
        if needle in text:
            return first + offset
    raise AssertionError(f"{needle!r} not found in {func.__name__}")


def _innermost_failure():
    """The statement that actually fails, mimicking the production TypeError from a deep D-Bus read."""
    raise TypeError("must be real number, not NoneType")


def _failing_recompute():
    """A frame between _update() and the raise, so the raising frame is nowhere near the handler's own."""
    _innermost_failure()


# The line the handler is expected to name.  It is several frames below the
# self._update() call site, which is what a handler reading sys.exc_info()[2]
# directly would report instead.
RAISING_LINE = _line_of(_innermost_failure, "raise TypeError")

# Tail of the logged message: "... in <file> line #<n>".
LOCATION_RE = re.compile(r" in (?P<file>.+) line #(?P<line>\d+)$")


NON_BATTERY_SERVICES = [
    "com.victronenergy.vebus.ttyO1",
    "com.victronenergy.solarcharger.ttyUSB0",
    "com.victronenergy.temperature.ttyUSB1",
    "com.victronenergy.system",
    "com.victronenergy.settings",
    "com.victronenergy.dcload.ttyUSB2",
    "com.victronenergy.multi.ttyUSB3",
    # no trailing dot: a service whose name merely begins with "battery" is not a battery
    "com.victronenergy.batterysomething",
    "com.victronenergy.batterymonitor.ttyUSB4",
]


class ReactiveSchedulingTestCase(unittest.TestCase):
    def setUp(self):
        self.driver = driver_harness.driver
        self.glib = driver_harness.patch_glib(self)

    def _make_service(self, reactive_ready=True, update=None):
        return driver_harness.new_service(
            _reactive_ready=reactive_ready,
            _updating=False,
            _update=update if update is not None else _RecordingUpdate(),
        )

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

    def test_our_own_service_never_schedules_an_update(self):
        """Called directly, as if dbusmon's ignoreServices had not filtered it: our own publishes must not feed back."""
        service = self._make_service()
        service._on_input_changed(*self._change(self.driver.AGGREGATE_SERVICE_NAME, path="/Dc/0/Voltage", value=52.4))
        self.assertEqual(self.glib.idle_calls, [])
        self.assertFalse(service._updating)
        self.assertEqual(service._update.calls, 0)

    def test_own_service_name_matches_the_default_service_name(self):
        """The skip-self guard is worthless if the constant drifts from the name the service registers under."""
        default = inspect.signature(self.driver.DbusAggBatService.__init__).parameters["servicename"].default
        self.assertEqual(default, self.driver.AGGREGATE_SERVICE_NAME)
        self.assertTrue(self.driver.AGGREGATE_SERVICE_NAME.startswith(self.driver.BATTERY_SERVICE_PREFIX))

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

    def test_failing_update_is_logged_instead_of_escaping_the_idle_callback(self):
        """The failure is logged, and the location names the statement that raised rather than the call site."""
        service = self._make_service(update=_RecordingUpdate(side_effect=_failing_recompute))
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))

        with self.assertLogs(level="ERROR") as captured:
            results = self.glib.run_pending_idle()

        self.assertEqual(results, [False], "the callback must stay one-shot even when the update failed")
        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn("TypeError('must be real number, not NoneType')", message)

        location = LOCATION_RE.search(message)
        self.assertIsNotNone(location, f"no '<file> line #<n>' location in the logged message: {message}")
        self.assertEqual(os.path.basename(location.group("file")), os.path.basename(__file__))
        self.assertEqual(int(location.group("line")), RAISING_LINE, "the logged line must be the raise, not a frame above it")
        self.assertNotIn(
            "dbus-aggregate-batteries.py",
            message,
            "the outermost frame is the self._update() call site, which is never where the failure is",
        )

    def test_logged_failure_carries_the_frames_between_the_callback_and_the_raise(self):
        """One line is scannable, but the chain is what says how the recompute reached the failing statement."""
        service = self._make_service(update=_RecordingUpdate(side_effect=_failing_recompute))
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))

        with self.assertLogs(level="ERROR") as captured:
            self.glib.run_pending_idle()

        record = captured.records[0]
        self.assertIsNotNone(record.exc_info, "the record must carry the exception, not only a formatted summary")
        formatted = logging.Formatter().format(record)
        for frame in ("_update_reactive", "_failing_recompute", "_innermost_failure"):
            with self.subTest(frame=frame):
                self.assertIn(frame, formatted)

    def test_updating_guard_is_cleared_when_update_raises(self):
        service = self._make_service(update=_RecordingUpdate(raises=RuntimeError("boom")))
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        with self.assertLogs(level="ERROR"):
            self.glib.run_pending_idle()
        self.assertFalse(service._updating, "the finally block must clear _updating even on failure")

    def test_system_exit_from_update_is_not_swallowed(self):
        """_update() exits the process when READ_TRIALS is exceeded; that must still propagate."""
        service = self._make_service(update=_RecordingUpdate(raises=SystemExit(1)))
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        with self.assertRaises(SystemExit):
            self.glib.run_pending_idle()
        self.assertFalse(service._updating)

    def test_reactive_updates_recover_after_a_failed_update(self):
        failing = _RecordingUpdate(raises=RuntimeError("boom"))
        service = self._make_service(update=failing)
        service._on_input_changed(*self._change("com.victronenergy.battery.ttyUSB0"))
        with self.assertLogs(level="ERROR"):
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
