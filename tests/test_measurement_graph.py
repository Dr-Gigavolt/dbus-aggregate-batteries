#!/usr/bin/env python3

"""
Unit tests for the measurement-graph declaration published by the aggregate
battery service.

Two D-Bus paths are under test:

* ``/Measurement/Kind`` - the constant string ``derived``, telling summing
  consumers that this service re-publishes values rolled up from other
  services and must not be counted alongside them.
* ``/Measurement/TracksServices`` - created empty and filled once the battery
  search completes, with the discovered battery service names joined by commas
  in sorted order and without spaces. Consumers parse this string, so the exact
  format is part of the contract.

The battery search can finish at three different places, and each of them has
to publish the constituent list, otherwise a system that took that route would
be left advertising an empty declaration:

* ``_find_batteries``  - current comes from the BMSes, no Victron devices are
  searched at all.
* ``_find_multis``     - a MultiPlus/Quattro is used but no MPPTs are configured.
* ``_find_mppts``      - MPPTs are configured and the expected number was found.

``dbus``, ``vedbus`` and ``gi``/``GLib`` are not importable off the Venus device,
and ``settings`` exits the interpreter when no ``config.ini`` is present, so
``driver_harness`` stubs them once for every suite and loads the dash-named
driver by path. The device search reads a lot of settings and these tests vary
them, so each test asks the harness for a fresh in-memory settings namespace
instead of mutating a module-global one.

The service object is never built through ``__init__`` (that one opens a real
bus). Tests use ``driver_harness.new_service()``, which is ``object.__new__``
plus only the attributes the methods under test actually read.
"""

import ast
import logging
import unittest

import driver_harness

driver = driver_harness.driver

KIND_PATH = "/Measurement/Kind"
TRACKS_PATH = "/Measurement/TracksServices"


def setUpModule():
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def make_service(batteries=None, bus_names=(), monitor_values=None):
    """Build a DbusAggBatService without running its D-Bus touching __init__."""
    return driver_harness.new_service(
        _dbusservice=driver_harness.RecordingDbusService(),
        _dbusConn=driver_harness.FakeBus(bus_names),
        # a path nobody scripted answers None here, the way a real monitor does
        _dbusMon=driver_harness.FakeDbusMon(monitor_values or {}, default=None),
        _batteries_dict=dict(batteries or {}),
        _smartShunt_list=[],
        _mppts_list=[],
        _num_battery_shunts=0,
        _multi=None,
        _searchTrials=1,
        _timeOld=0.0,
        _ownCharge=0.5,
        _updating=False,
    )


def battery_monitor_values(services_by_name, product_name="SerialBattery(Jkbms)", cells=16):
    """Monitor answers that make ``_find_batteries`` accept every given service."""
    values = {}
    for name, service in services_by_name.items():
        values[(service, "/ProductName")] = product_name
        values[(service, "/CustomName")] = name
        values[(service, "/System/NrOfCellsPerBattery")] = cells
    return values


# ---------------------------------------------------------------------------
# Source-level assertions about the declaration itself
# ---------------------------------------------------------------------------


def _parse_driver():
    with open(driver_harness.DRIVER_PATH, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=driver_harness.DRIVER_PATH)


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return _NON_LITERAL


_NON_LITERAL = object()


def measurement_add_path_calls():
    """Every ``add_path`` call for a ``/Measurement/...`` path, as (path, value, kwargs)."""
    calls = []
    for node in ast.walk(_parse_driver()):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_path" or not node.args:
            continue
        path = _literal(node.args[0])
        if not isinstance(path, str) or not path.startswith("/Measurement/"):
            continue
        value = _literal(node.args[1]) if len(node.args) > 1 else _NON_LITERAL
        kwargs = {keyword.arg: _literal(keyword.value) for keyword in node.keywords}
        calls.append((path, value, kwargs))
    return calls


def _subscript_key(subscript):
    node = subscript.slice
    if isinstance(node, ast.Constant):
        return node.value
    # Python 3.8 wraps the subscript key in an ast.Index node
    inner = getattr(node, "value", None)
    if isinstance(inner, ast.Constant):
        return inner.value
    return None


def measurement_subscript_writes():
    """Every ``self._dbusservice["/Measurement/..."] = ...`` assignment target path."""
    written = []
    for node in ast.walk(_parse_driver()):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            key = _subscript_key(target)
            if isinstance(key, str) and key.startswith("/Measurement/"):
                written.append(key)
    return written


class MeasurementDeclarationTests(unittest.TestCase):
    """The two /Measurement paths must be declared once, with the right literals."""

    def test_kind_is_declared_as_the_string_derived(self):
        kind_calls = [call for call in measurement_add_path_calls() if call[0] == KIND_PATH]
        self.assertEqual(len(kind_calls), 1, "%s must be declared exactly once" % KIND_PATH)
        _, value, _ = kind_calls[0]
        self.assertIsInstance(value, str, "consumers read %s as a string" % KIND_PATH)
        self.assertEqual(value, "derived")

    def test_tracks_services_is_declared_as_a_writeable_empty_string(self):
        tracks_calls = [call for call in measurement_add_path_calls() if call[0] == TRACKS_PATH]
        self.assertEqual(len(tracks_calls), 1, "%s must be declared exactly once" % TRACKS_PATH)
        _, value, kwargs = tracks_calls[0]
        self.assertIsInstance(value, str)
        self.assertEqual(value, "", "%s starts empty and is filled after the search" % TRACKS_PATH)
        self.assertTrue(kwargs.get("writeable"), "%s is written after creation" % TRACKS_PATH)

    def test_only_kind_and_tracks_services_are_declared(self):
        declared = sorted(call[0] for call in measurement_add_path_calls())
        self.assertEqual(declared, [KIND_PATH, TRACKS_PATH])

    def test_the_direct_only_keys_are_not_published(self):
        """A derived service must not claim to measure a physical device.

        /Measurement/PhysicalDevice, /PeerServices and /LineAuthority are
        published by services with Kind "direct" — they identify the physical
        thing being measured, the other services watching it, and which of them
        is authoritative for the line. None of that is meaningful for a service
        that computes its values from other services, and a consumer resolving
        the graph would be misled by it.
        """
        declared = {call[0] for call in measurement_add_path_calls()}
        for path in ("/Measurement/PhysicalDevice", "/Measurement/PeerServices", "/Measurement/LineAuthority"):
            with self.subTest(path=path):
                self.assertNotIn(path, declared)

    def test_kind_is_never_reassigned_after_declaration(self):
        self.assertNotIn(KIND_PATH, measurement_subscript_writes(), "%s is a constant declaration" % KIND_PATH)

    def test_tracks_services_is_the_only_measurement_path_written_at_runtime(self):
        self.assertEqual(set(measurement_subscript_writes()), {TRACKS_PATH})


# ---------------------------------------------------------------------------
# The three completion paths
# ---------------------------------------------------------------------------


class CompletionPathTestCase(unittest.TestCase):
    """Shared fixture: fresh settings and a fresh GLib recorder per test."""

    # deliberately unsorted insertion order, and battery names whose sort order
    # is the reverse of the service-name sort order
    BATTERIES = {
        "Zulu": "com.victronenergy.battery.ttyUSB0",
        "Alpha": "com.victronenergy.battery.ttyUSB2",
        "Mike": "com.victronenergy.battery.ttyUSB1",
    }
    EXPECTED = "com.victronenergy.battery.ttyUSB0,com.victronenergy.battery.ttyUSB1,com.victronenergy.battery.ttyUSB2"

    def setUp(self):
        self.settings = driver_harness.use_stub_settings(self)
        self.glib = driver_harness.patch_glib(self)

    def published(self, service):
        """The value currently on TRACKS_PATH, failing loudly if it was never filled."""
        self.assertIn(TRACKS_PATH, service._dbusservice.values, "%s was never published" % TRACKS_PATH)
        value = service._dbusservice.values[TRACKS_PATH]
        self.assertNotEqual(value, "", "%s was left at its empty declaration value" % TRACKS_PATH)
        return value

    # -- the three ways the search can finish -------------------------------

    def run_batteries_only_path(self, batteries=None):
        """Finish in _find_batteries: current comes from the BMSes."""
        batteries = self.BATTERIES if batteries is None else batteries
        self.settings.CURRENT_FROM_VICTRON = False
        self.settings.NR_OF_BATTERIES = len(batteries)
        service = make_service(
            bus_names=sorted(batteries.values()),
            monitor_values=battery_monitor_values(batteries),
        )
        self.assertIs(service._find_batteries(), False, "the search must stop once it succeeded")
        return service

    def run_no_mppt_path(self, batteries=None):
        """Finish in _find_multis: a Multi is used and no MPPTs are configured."""
        batteries = self.BATTERIES if batteries is None else batteries
        self.settings.NR_OF_MPPTS = 0
        multi = "com.victronenergy.vebus.ttyO1"
        service = make_service(
            batteries=batteries,
            bus_names=[multi],
            monitor_values={(multi, "/ProductName"): "MultiPlus-II 48/5000"},
        )
        self.assertIs(service._find_multis(), False, "the search must stop once it succeeded")
        return service

    def run_mppt_path(self, batteries=None):
        """Finish in _find_mppts: the configured number of MPPTs was found."""
        batteries = self.BATTERIES if batteries is None else batteries
        mppts = ["com.victronenergy.solarcharger.ttyO2", "com.victronenergy.solarcharger.ttyO3"]
        self.settings.NR_OF_MPPTS = len(mppts)
        service = make_service(
            batteries=batteries,
            bus_names=mppts,
            monitor_values={(mppt, "/ProductName"): "SmartSolar MPPT" for mppt in mppts},
        )
        self.assertIs(service._find_mppts(), False, "the search must stop once it succeeded")
        return service

    def completion_paths(self):
        return (
            ("batteries only", self.run_batteries_only_path),
            ("no MPPT", self.run_no_mppt_path),
            ("MPPT", self.run_mppt_path),
        )


class TracksServicesPublishedOnEveryPathTests(CompletionPathTestCase):
    """None of the three completion routes may leave the declaration empty."""

    def test_batteries_only_path_publishes_the_constituents(self):
        service = self.run_batteries_only_path()
        self.assertEqual(self.published(service), self.EXPECTED)

    def test_no_mppt_path_publishes_the_constituents(self):
        service = self.run_no_mppt_path()
        self.assertEqual(self.published(service), self.EXPECTED)

    def test_mppt_path_publishes_the_constituents(self):
        service = self.run_mppt_path()
        self.assertEqual(self.published(service), self.EXPECTED)

    def test_every_path_writes_tracks_services_exactly_once(self):
        for label, run_path in self.completion_paths():
            with self.subTest(path=label):
                service = run_path()
                writes = service._dbusservice.writes_to(TRACKS_PATH)
                self.assertEqual(len(writes), 1, "%s path wrote %s %d times" % (label, TRACKS_PATH, len(writes)))
                self.assertEqual(writes[0], self.EXPECTED)

    def test_every_path_agrees_on_the_published_value(self):
        published = {label: self.published(run_path()) for label, run_path in self.completion_paths()}
        self.assertEqual(set(published.values()), {self.EXPECTED}, published)


class TracksServicesFormatTests(CompletionPathTestCase):
    """The string is parsed by consumers, so its shape is part of the contract."""

    def test_value_is_comma_separated_without_spaces(self):
        for label, run_path in self.completion_paths():
            with self.subTest(path=label):
                value = self.published(run_path())
                self.assertNotIn(" ", value, "consumers split on ',' only")
                self.assertEqual(value.split(","), sorted(self.BATTERIES.values()))

    def test_value_is_sorted_by_service_name_not_by_battery_name(self):
        # battery names sort Alpha < Mike < Zulu, which is the reverse of the
        # service-name order; sorting the wrong side of the dict would show up here
        value = self.published(self.run_no_mppt_path())
        self.assertEqual(value, self.EXPECTED)
        self.assertNotEqual(value, ",".join(self.BATTERIES[name] for name in sorted(self.BATTERIES)))

    def test_single_battery_value_has_no_separator(self):
        one = {"OnlyBattery": "com.victronenergy.battery.ttyUSB9"}
        for label, run_path in self.completion_paths():
            with self.subTest(path=label):
                value = self.published(run_path(batteries=one))
                self.assertEqual(value, "com.victronenergy.battery.ttyUSB9")

    def test_value_is_a_plain_string(self):
        value = self.published(self.run_mppt_path())
        self.assertIsInstance(value, str)


class TracksServicesFollowsDiscoveryTests(CompletionPathTestCase):
    """The names come from the discovered batteries dict, never from a fixed list."""

    OTHER_BATTERIES = {
        "Delta": "com.victronenergy.battery.socketcan_can0",
        "Charlie": "com.victronenergy.battery.socketcan_can1",
    }
    OTHER_EXPECTED = "com.victronenergy.battery.socketcan_can0,com.victronenergy.battery.socketcan_can1"

    def test_a_different_batteries_dict_yields_a_different_value(self):
        for label, run_path in self.completion_paths():
            with self.subTest(path=label):
                value = self.published(run_path(batteries=self.OTHER_BATTERIES))
                self.assertEqual(value, self.OTHER_EXPECTED)
                self.assertNotEqual(value, self.EXPECTED)

    def test_batteries_only_path_publishes_what_the_bus_scan_discovered(self):
        service = self.run_batteries_only_path()
        self.assertEqual(
            self.published(service),
            ",".join(sorted(service._batteries_dict.values())),
        )
        self.assertEqual(sorted(service._batteries_dict.values()), sorted(self.BATTERIES.values()))

    def test_services_of_non_battery_devices_are_not_tracked(self):
        self.settings.CURRENT_FROM_VICTRON = False
        self.settings.NR_OF_BATTERIES = len(self.BATTERIES)
        monitor_values = battery_monitor_values(self.BATTERIES)
        decoy = "com.victronenergy.battery.ttyUSB7"
        monitor_values[(decoy, "/ProductName")] = "Some Other BMS"
        service = make_service(
            bus_names=sorted(list(self.BATTERIES.values()) + [decoy, "com.victronenergy.system"]),
            monitor_values=monitor_values,
        )
        self.assertIs(service._find_batteries(), False)
        self.assertEqual(self.published(service), self.EXPECTED)
        self.assertNotIn(decoy, self.published(service))


class TracksServicesNotPublishedBeforeCompletionTests(CompletionPathTestCase):
    """An unfinished search must not publish a partial constituent list."""

    def test_incomplete_battery_search_publishes_nothing(self):
        self.settings.CURRENT_FROM_VICTRON = False
        self.settings.NR_OF_BATTERIES = len(self.BATTERIES) + 1
        service = make_service(
            bus_names=sorted(self.BATTERIES.values()),
            monitor_values=battery_monitor_values(self.BATTERIES),
        )
        self.assertIs(service._find_batteries(), True, "the search must retry")
        self.assertEqual(service._dbusservice.writes_to(TRACKS_PATH), [])

    def test_multi_search_defers_publishing_to_the_mppt_search(self):
        self.settings.NR_OF_MPPTS = 2
        multi = "com.victronenergy.vebus.ttyO1"
        service = make_service(
            batteries=self.BATTERIES,
            bus_names=[multi],
            monitor_values={(multi, "/ProductName"): "MultiPlus-II 48/5000"},
        )
        self.assertIs(service._find_multis(), False)
        self.assertEqual(service._dbusservice.writes_to(TRACKS_PATH), [])

    def test_incomplete_mppt_search_publishes_nothing(self):
        self.settings.NR_OF_MPPTS = 2
        found = ["com.victronenergy.solarcharger.ttyO2"]
        service = make_service(
            batteries=self.BATTERIES,
            bus_names=found,
            monitor_values={(found[0], "/ProductName"): "SmartSolar MPPT"},
        )
        self.assertIs(service._find_mppts(), True, "the search must retry")
        self.assertEqual(service._dbusservice.writes_to(TRACKS_PATH), [])

    def test_battery_search_delegates_to_multi_search_without_publishing(self):
        self.settings.CURRENT_FROM_VICTRON = True
        self.settings.NR_OF_BATTERIES = len(self.BATTERIES)
        service = make_service(
            bus_names=sorted(self.BATTERIES.values()),
            monitor_values=battery_monitor_values(self.BATTERIES),
        )
        self.assertIs(service._find_batteries(), False)
        self.assertEqual(service._dbusservice.writes_to(TRACKS_PATH), [])
        self.assertIn(service._find_multis, self.glib.scheduled_callbacks)


if __name__ == "__main__":
    unittest.main()
