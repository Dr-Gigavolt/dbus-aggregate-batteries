# -*- coding: utf-8 -*-
"""Unit tests for the "Dbus publish gate" options in settings.py.

settings.py reads ``config.default.ini`` and then ``config.ini`` from its own
directory, validates the parsed values and calls ``sys.exit(1)`` after listing
everything it collected in ``errors_in_config``. These tests copy settings.py
and config.default.ini into a throwaway directory next to a generated
config.ini, so the real parsing and validation run without touching the
repository's own config.ini.
"""

import configparser
import logging
import shutil
import unittest

import driver_harness


THRESHOLD_OPTIONS = (
    "PUBLISH_GATE_VOLTAGE",
    "PUBLISH_GATE_CURRENT",
    "PUBLISH_GATE_POWER",
    "PUBLISH_GATE_TEMPERATURE",
    "PUBLISH_GATE_SOC",
    "PUBLISH_GATE_TIME_TO_GO",
    "PUBLISH_GATE_CONSUMED_AMPHOURS",
)


class SettingsTestCase(unittest.TestCase):

    def setUp(self):
        # settings.py logs its findings at ERROR level; keep the test output clean.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def make_dir(self, overrides=None):
        directory = driver_harness.make_config_dir(overrides)
        self.addCleanup(shutil.rmtree, directory, True)
        return directory

    def load(self, overrides=None):
        """Load settings with the given config.ini overrides, expecting success."""
        module = driver_harness.load_settings(self.make_dir(overrides))
        self.assertEqual(module.errors_in_config, [])
        return module

    def load_expecting_exit(self, overrides):
        """Load settings expecting sys.exit(1); return the collected errors."""
        module = driver_harness.new_settings_module(self.make_dir(overrides))
        with self.assertRaises(SystemExit) as raised:
            driver_harness.exec_settings(module)
        self.assertEqual(raised.exception.code, 1)
        return module.errors_in_config

    def assertErrorMentions(self, errors, needle):
        self.assertTrue(
            any(needle in error for error in errors),
            "no error containing %r in %r" % (needle, errors),
        )


class TestDefaults(SettingsTestCase):

    def setUp(self):
        super(TestDefaults, self).setUp()
        self.defaults = configparser.ConfigParser()
        self.defaults.read(driver_harness.CONFIG_DEFAULT_PATH)

    def test_thresholds_default_to_the_shipped_config(self):
        module = self.load()
        for option in THRESHOLD_OPTIONS:
            with self.subTest(option=option):
                self.assertEqual(getattr(module, option), float(self.defaults["DEFAULT"][option]))

    def test_heartbeat_defaults_to_the_shipped_config(self):
        module = self.load()
        self.assertEqual(module.PUBLISH_HEARTBEAT, int(self.defaults["DEFAULT"]["PUBLISH_HEARTBEAT"]))

    def test_shipped_defaults_are_all_valid(self):
        module = self.load()
        for option in THRESHOLD_OPTIONS:
            with self.subTest(option=option):
                self.assertGreaterEqual(getattr(module, option), 0)
        self.assertGreater(module.PUBLISH_HEARTBEAT, 0)

    def test_thresholds_are_floats_and_heartbeat_is_an_int(self):
        module = self.load()
        for option in THRESHOLD_OPTIONS:
            with self.subTest(option=option):
                self.assertIsInstance(getattr(module, option), float)
        self.assertIsInstance(module.PUBLISH_HEARTBEAT, int)


class TestUserOverrides(SettingsTestCase):

    def test_user_config_overrides_a_threshold(self):
        module = self.load({"PUBLISH_GATE_VOLTAGE": "0.5"})
        self.assertEqual(module.PUBLISH_GATE_VOLTAGE, 0.5)

    def test_user_config_overrides_every_threshold(self):
        overrides = {option: "1.25" for option in THRESHOLD_OPTIONS}
        module = self.load(overrides)
        for option in THRESHOLD_OPTIONS:
            with self.subTest(option=option):
                self.assertEqual(getattr(module, option), 1.25)

    def test_user_config_overrides_the_heartbeat(self):
        module = self.load({"PUBLISH_HEARTBEAT": "60"})
        self.assertEqual(module.PUBLISH_HEARTBEAT, 60)

    def test_overriding_one_option_leaves_the_others_at_their_default(self):
        module = self.load({"PUBLISH_GATE_POWER": "42"})
        self.assertEqual(module.PUBLISH_GATE_POWER, 42.0)
        self.assertEqual(module.PUBLISH_GATE_VOLTAGE, 0.01)
        self.assertEqual(module.PUBLISH_HEARTBEAT, 900)

    def test_integer_threshold_is_read_as_float(self):
        module = self.load({"PUBLISH_GATE_CURRENT": "2"})
        self.assertEqual(module.PUBLISH_GATE_CURRENT, 2.0)
        self.assertIsInstance(module.PUBLISH_GATE_CURRENT, float)

    def test_zero_thresholds_are_accepted(self):
        overrides = {option: "0" for option in THRESHOLD_OPTIONS}
        module = self.load(overrides)
        for option in THRESHOLD_OPTIONS:
            with self.subTest(option=option):
                self.assertEqual(getattr(module, option), 0.0)

    def test_empty_threshold_falls_back_to_zero(self):
        module = self.load({"PUBLISH_GATE_SOC": ""})
        self.assertEqual(module.PUBLISH_GATE_SOC, 0)


class TestInvalidValues(SettingsTestCase):

    def test_negative_threshold_is_rejected(self):
        for option in THRESHOLD_OPTIONS:
            with self.subTest(option=option):
                errors = self.load_expecting_exit({option: "-0.1"})
                self.assertErrorMentions(errors, "%s must be 0 or greater." % option)

    def test_non_numeric_threshold_is_rejected(self):
        errors = self.load_expecting_exit({"PUBLISH_GATE_POWER": "five"})
        self.assertErrorMentions(errors, "Invalid value 'five' for option 'PUBLISH_GATE_POWER'")

    def test_non_numeric_heartbeat_is_rejected(self):
        errors = self.load_expecting_exit({"PUBLISH_HEARTBEAT": "later"})
        self.assertErrorMentions(errors, "Invalid value 'later' for option 'PUBLISH_HEARTBEAT'")

    def test_fractional_heartbeat_is_rejected(self):
        errors = self.load_expecting_exit({"PUBLISH_HEARTBEAT": "900.5"})
        self.assertErrorMentions(errors, "Invalid value '900.5' for option 'PUBLISH_HEARTBEAT'")

    def test_zero_heartbeat_is_rejected(self):
        errors = self.load_expecting_exit({"PUBLISH_HEARTBEAT": "0"})
        self.assertErrorMentions(errors, "PUBLISH_HEARTBEAT must be greater than 0.")

    def test_negative_heartbeat_is_rejected(self):
        errors = self.load_expecting_exit({"PUBLISH_HEARTBEAT": "-1"})
        self.assertErrorMentions(errors, "PUBLISH_HEARTBEAT must be greater than 0.")

    def test_empty_heartbeat_is_rejected(self):
        # An empty value falls back to 0, which the "> 0" check then rejects.
        errors = self.load_expecting_exit({"PUBLISH_HEARTBEAT": ""})
        self.assertErrorMentions(errors, "PUBLISH_HEARTBEAT must be greater than 0.")

    def test_every_bad_value_is_reported_at_once(self):
        errors = self.load_expecting_exit(
            {
                "PUBLISH_GATE_VOLTAGE": "-1",
                "PUBLISH_GATE_CURRENT": "-1",
                "PUBLISH_HEARTBEAT": "0",
            }
        )
        self.assertErrorMentions(errors, "PUBLISH_GATE_VOLTAGE must be 0 or greater.")
        self.assertErrorMentions(errors, "PUBLISH_GATE_CURRENT must be 0 or greater.")
        self.assertErrorMentions(errors, "PUBLISH_HEARTBEAT must be greater than 0.")

    def test_unknown_publish_gate_option_is_rejected(self):
        errors = self.load_expecting_exit({"PUBLISH_GATE_VOLTAGE_TYPO": "0.1"})
        self.assertErrorMentions(errors, 'Option "PUBLISH_GATE_VOLTAGE_TYPO" in config.ini is not valid.')


if __name__ == "__main__":
    unittest.main()
