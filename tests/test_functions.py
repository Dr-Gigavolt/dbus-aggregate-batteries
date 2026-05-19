import unittest

from functions import Functions


class FunctionsTests(unittest.TestCase):
    def setUp(self):
        self.functions = Functions()

    def test_median_ignores_none_values(self):
        self.assertAlmostEqual(self.functions._median([3.4, None, 3.6, 3.5]), 3.5)

    def test_reaches_configured_pack_voltage_before_balancing_voltage(self):
        self.assertTrue(
            self.functions._full_charge_reached(
                pack_voltage=63.0,
                balancing_voltage=67.2,
                own_soc_full_voltage=63.0,
            )
        )

    def test_reaches_configured_median_cell_voltage_before_balancing_voltage(self):
        self.assertTrue(
            self.functions._full_charge_reached(
                pack_voltage=62.9,
                balancing_voltage=67.2,
                own_soc_full_voltage=63.0,
                cell_voltages=[3.45, 3.50, 3.54],
                own_soc_full_cell_median_voltage=3.5,
            )
        )

    def test_reaches_existing_balancing_voltage_without_extra_thresholds(self):
        self.assertTrue(
            self.functions._full_charge_reached(
                pack_voltage=67.2,
                balancing_voltage=67.2,
            )
        )

    def test_does_not_mark_full_below_all_thresholds(self):
        self.assertFalse(
            self.functions._full_charge_reached(
                pack_voltage=62.9,
                balancing_voltage=67.2,
                own_soc_full_voltage=63.0,
                cell_voltages=[3.45, 3.47, 3.49, 3.49],
                own_soc_full_cell_median_voltage=3.5,
            )
        )


if __name__ == "__main__":
    unittest.main()
