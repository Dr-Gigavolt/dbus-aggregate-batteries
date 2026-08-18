import importlib.util
import sys
from functions import Functions
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock external dependencies before importing the module under test
# ---------------------------------------------------------------------------


class _MockBusConnection:
    """Stand-in for dbus.bus.BusConnection enabling class inheritance."""

    TYPE_SYSTEM = 0
    TYPE_SESSION = 1


_mock_dbus = MagicMock()
_mock_dbus.bus.BusConnection = _MockBusConnection

for _name, _mock in {
    "gi": MagicMock(),
    "gi.repository": MagicMock(),
    "dbus": _mock_dbus,
    "dbus.bus": _mock_dbus.bus,
    "settings": MagicMock(),
    "dbusmon": MagicMock(),
    "vedirect_shunt_monitor": MagicMock(),
    "vedbus": MagicMock(),
}.items():
    sys.modules[_name] = _mock

# ---------------------------------------------------------------------------
# Import the module under test (filename contains hyphens)
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location("dbus_aggregate_batteries", "dbus-aggregate-batteries.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

AggregatedChargeMode = _module.AggregatedChargeMode
DbusAggBatService = _module.DbusAggBatService

_ALL_MODES = list(AggregatedChargeMode)
_ALL_MODE_NAMES = [m.name for m in AggregatedChargeMode]

# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Lightweight DbusAggBatService that bypasses __init__."""
    svc = object.__new__(DbusAggBatService)
    svc._aggregated_charge_mode = AggregatedChargeMode.FLOAT
    svc._fn = Functions()
    return svc


# ===========================================================================


class TestUpdateAggregatedChargeMode:

    @pytest.mark.parametrize(
        "charge_modes, expected",
        [
            (["Bulk"], AggregatedChargeMode.BULK_OR_ABSORPTION),
            (["Bulk", "Absorption"], AggregatedChargeMode.BULK_OR_ABSORPTION),
            (["Absorption", "Bulk", "Absorption"], AggregatedChargeMode.BULK_OR_ABSORPTION),
            (["Float Transition"], AggregatedChargeMode.FLOAT_TRANSITION),
            (["Float", "Float Transition", "Float"], AggregatedChargeMode.FLOAT_TRANSITION),
            (["Float Transition", "Float Transition"], AggregatedChargeMode.FLOAT_TRANSITION),
            (["Float"], AggregatedChargeMode.FLOAT),
            (["Float", "Float"], AggregatedChargeMode.FLOAT),
        ],
        ids=[
            "single_bulk",
            "bulk_and_absorption",
            "three_non_float",
            "single_float_transition",
            "float_transition_among_floats",
            "all_float_transition",
            "single_float",
            "all_float",
        ],
    )
    @pytest.mark.parametrize("initial_mode", _ALL_MODES, ids=_ALL_MODE_NAMES)
    def test_deterministic_transitions(self, service, initial_mode, charge_modes, expected):
        service._aggregated_charge_mode = initial_mode
        service._update_aggregated_charge_mode(charge_modes)
        assert service._aggregated_charge_mode == expected

    @pytest.mark.parametrize(
        "charge_modes",
        [
            ["Bulk", "Float"],
            ["Float", "Absorption"],
            ["Bulk", "Float Transition"],
            ["Absorption", "Float Transition", "Bulk"],
            ["Bulk", "Float", "Float Transition"],
        ],
        ids=[
            "bulk_with_float",
            "float_with_absorption",
            "bulk_with_float_transition",
            "three_mixed_types",
            "all_category_types_mixed",
        ],
    )
    @pytest.mark.parametrize("initial_mode", _ALL_MODES, ids=_ALL_MODE_NAMES)
    def test_mixed_modes_leave_state_unchanged(self, service, initial_mode, charge_modes):
        service._aggregated_charge_mode = initial_mode
        service._update_aggregated_charge_mode(charge_modes)
        assert service._aggregated_charge_mode == initial_mode


class TestGetCvlWithAggregatedChargeMode:

    @pytest.mark.parametrize(
        "voltages, modes, expected",
        [
            ([56.0, 55.5], ["Bulk", "Absorption"], 55.5),
            ([56.0, 54.0], ["Bulk", "Float"], 56.0),
            ([55.0, 56.0, 54.0], ["Bulk", "Bulk", "Float"], 55.0),
        ],
        ids=[
            "all_bulk_returns_min",
            "float_voltage_ignored",
            "reduced_bulk_voltage_respected",
        ],
    )
    def test_bulk_or_absorption_mode(self, service, voltages, modes, expected):
        service._aggregated_charge_mode = AggregatedChargeMode.BULK_OR_ABSORPTION
        assert service._get_cvl_with_aggregated_charge_mode(voltages, modes) == expected

    @pytest.mark.parametrize(
        "voltages, modes, expected",
        [
            ([55.0, 55.5], ["Float Transition", "Float Transition"], 55.5),
            ([56.0, 57.0, 55.0], ["Float Transition", "Bulk", "Bulk"], 55.0),
            ([56.0, 54.0], ["Float Transition", "Float"], 56.0),
            ([55.0, 57.0, 55.2], ["Float Transition", "Float Transition", "Bulk"], 55.2),
        ],
        ids=[
            "max_of_transitions",
            "capped_by_bulk",
            "uncapped_when_no_bulk",
            "multiple_transitions_capped_by_bulk",
        ],
    )
    def test_float_transition_mode(self, service, voltages, modes, expected):
        service._aggregated_charge_mode = AggregatedChargeMode.FLOAT_TRANSITION
        assert service._get_cvl_with_aggregated_charge_mode(voltages, modes) == expected

    @pytest.mark.parametrize(
        "voltages, modes, expected",
        [
            ([54.0, 55.0], ["Float", "Float"], 54.0),
            ([56.0, 54.0], ["Bulk", "Float"], 54.0),
            ([56.0, 55.0, 54.0], ["Bulk", "Float Transition", "Float"], 54.0),
        ],
        ids=[
            "all_float_returns_min",
            "mixed_returns_global_min",
            "three_types_returns_global_min",
        ],
    )
    def test_float_mode(self, service, voltages, modes, expected):
        service._aggregated_charge_mode = AggregatedChargeMode.FLOAT
        assert service._get_cvl_with_aggregated_charge_mode(voltages, modes) == expected


class TestAggregatedChargeModeStatefulScenarios:
    """Multi-step tests verifying stateful CVL behavior."""

    def _step(self, service, charge_modes, voltages):
        """Simulate one update cycle: advance mode, then return the CVL."""
        service._update_aggregated_charge_mode(charge_modes)
        return service._get_cvl_with_aggregated_charge_mode(voltages, charge_modes)

    def test_waits_for_last_battery_to_leave_bulk_before_lowering_cvl(self, service):
        service._aggregated_charge_mode = AggregatedChargeMode.FLOAT

        # Both batteries start in Bulk
        cvl = self._step(service, ["Bulk", "Bulk"], [55.5, 56.0])
        assert service._aggregated_charge_mode == AggregatedChargeMode.BULK_OR_ABSORPTION
        assert cvl == 55.5

        # First battery reaches Float; aggregator stays in BULK_OR_ABSORPTION
        cvl = self._step(service, ["Float", "Bulk"], [54.0, 56.0])
        assert service._aggregated_charge_mode == AggregatedChargeMode.BULK_OR_ABSORPTION
        assert cvl == 56.0

        # Second battery enters Float Transition
        cvl = self._step(service, ["Float", "Float Transition"], [54.0, 55.5])
        assert service._aggregated_charge_mode == AggregatedChargeMode.FLOAT_TRANSITION
        assert cvl == 55.5

        # Both batteries in Float
        cvl = self._step(service, ["Float", "Float"], [54.0, 54.0])
        assert service._aggregated_charge_mode == AggregatedChargeMode.FLOAT
        assert cvl == 54.0

    def test_reduced_cvl_respected_during_cell_overvoltage_protection(self, service):
        """A battery in Bulk that lowers CVL to prevent cell overvoltage is
        respected even while another battery is in Float."""
        service._aggregated_charge_mode = AggregatedChargeMode.BULK_OR_ABSORPTION

        cvl = self._step(service, ["Bulk", "Bulk", "Float"], [55.0, 56.0, 54.0])

        assert cvl == 55.0

    def test_single_battery_bulk_from_float_keeps_float_until_all_request_bulk(self, service):
        """When all batteries are in Float and one switches to Bulk, the
        aggregator stays in Float so that dbus-serialbattery can finish
        balancing and SOC reset for every battery."""
        service._aggregated_charge_mode = AggregatedChargeMode.FLOAT

        # One battery switches to Bulk; aggregator stays in Float
        cvl = self._step(service, ["Float", "Bulk", "Float"], [54.0, 56.0, 54.0])
        assert service._aggregated_charge_mode == AggregatedChargeMode.FLOAT
        assert cvl == 54.0

        # Another battery switches to Bulk; aggregator stays in Float
        cvl = self._step(service, ["Float", "Bulk", "Bulk"], [54.0, 56.0, 56.0])
        assert service._aggregated_charge_mode == AggregatedChargeMode.FLOAT
        assert cvl == 54.0

        # All batteries leave Float - switches to BULK_OR_ABSORPTION
        cvl = self._step(service, ["Bulk", "Bulk", "Bulk"], [55.5, 56.0, 56.0])
        assert service._aggregated_charge_mode == AggregatedChargeMode.BULK_OR_ABSORPTION
        assert cvl == 55.5
