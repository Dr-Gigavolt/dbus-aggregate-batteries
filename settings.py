# -*- coding: utf-8 -*-
# Standard library importsimport bisect
import configparser
import logging
import sys
from pathlib import Path
from time import sleep
from typing import List, Any, Callable


PATH_CONFIG_DEFAULT: str = "config.default.ini"
PATH_CONFIG_USER: str = "config.ini"

config = configparser.ConfigParser()
path = Path(__file__).parents[0]
default_config_file_path = str(path.joinpath(PATH_CONFIG_DEFAULT).absolute())
custom_config_file_path = str(path.joinpath(PATH_CONFIG_USER).absolute())
try:
    config.read([default_config_file_path, custom_config_file_path])

    # Ensure the [DEFAULT] section exists and is uppercase
    if "DEFAULT" not in config:
        logging.error(f'The custom config file "{custom_config_file_path}" is missing the [DEFAULT] section.')
        logging.error("Make sure the first line of the file is exactly (case-sensitive): [DEFAULT]")
        sleep(60)
        sys.exit(1)

except configparser.MissingSectionHeaderError as error_message:
    logging.error(f'Error reading "{custom_config_file_path}"')
    logging.error("Make sure the first line is exactly: [DEFAULT]")
    logging.error(f"{error_message}\n")
    sleep(60)
    sys.exit(1)

# Map config logging levels to logging module levels
LOGGING_LEVELS = {
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

# Check if the LOGGING option is valid
if "LOGGING" not in config["DEFAULT"] or config["DEFAULT"]["LOGGING"].upper() not in LOGGING_LEVELS:
    logging.warning('Invalid "LOGGING" option "%s" in config file. Using default level "INFO".' % config["DEFAULT"].get("LOGGING"))
    LOGGING = logging.INFO
else:
    LOGGING = LOGGING_LEVELS.get(config["DEFAULT"].get("LOGGING").upper())

# Set logging level from config file
logging.basicConfig(level=LOGGING)

# List to store config errors
# This is needed else the errors are not instantly visible
errors_in_config = []

# Check if there are any options in the custom config file that are not in the default config file
default_config = configparser.ConfigParser()
custom_config = configparser.ConfigParser()
# Ensure that option names are treated as case-sensitive
default_config.optionxform = str
custom_config.optionxform = str
# Read the default and custom config files
default_config.read(default_config_file_path)
custom_config.read(custom_config_file_path)

for section in custom_config.sections() + ["DEFAULT"]:
    if section not in default_config.sections() + ["DEFAULT"]:
        errors_in_config.append(f'Section "{section}" in config.ini is not valid.')
    else:
        for option in custom_config[section]:
            if option not in default_config[section]:
                errors_in_config.append(f'Option "{option}" in config.ini is not valid.')

# Free up memory
del default_config, custom_config, section

# Check if option variable was set and if yes, free it
if "option" in locals():
    del option


# --------- Helper Functions ---------
def get_bool_from_config(group: str, option: str) -> bool:
    """
    Get a boolean value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Boolean value
    """
    return config[group].get(option, "False").lower() == "true"


def get_float_from_config(group: str, option: str, default_value: float = 0) -> float:
    """
    Get a float value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Float value
    """
    value = config[group].get(option, default_value)
    if value == "":
        return default_value
    try:
        return float(value)
    except ValueError:
        errors_in_config.append(f"Invalid value '{value}' for option '{option}' in group '{group}'.")
        return default_value


def get_int_from_config(group: str, option: str, default_value: int = 0) -> int:
    """
    Get an integer value from the config file.

    :param group: Group in the config file
    :param option: Option in the config file
    :return: Integer value
    """
    value = config[group].get(option, default_value)
    if value == "":
        return default_value
    try:
        return int(value)
    except ValueError:
        errors_in_config.append(f"Invalid value '{value}' for option '{option}' in group '{group}'.")
        return default_value


def get_list_from_config(group: str, option: str, mapper: Callable[[Any], Any] = lambda v: v) -> List[Any]:
    """
    Get a string with comma-separated values from the config file and return a list of values.

    :param group: Group in the config file
    :param option: Option in the config file
    :param mapper: Function to map the values to the correct type
    :return: List of values
    """
    try:
        lines = config[group].get(option).splitlines()
        cleaned = []
        for line in lines:
            # Remove comments (anything after ';')
            line = line.split(";", 1)[0]
            # Remove whitespace
            line = line.strip()
            # Skip empty lines
            if line:
                # Remove trailing commas
                cleaned += line.rstrip(",").split(",")
        return [mapper(item.strip()) for item in cleaned if item.strip()]
    except KeyError:
        logging.error(f"Missing config option '{option}' in group '{group}'")
        errors_in_config.append(f"Missing config option '{option}' in group '{group}'")
        return []
    except ValueError:
        errors_in_config.append(f"Invalid value '{mapper}' for option '{option}' in group '{group}'.")
        return []


def check_config_issue(condition: bool, message: str):
    """
    Check a condition and append a message to the errors_in_config list if the condition is True.

    :param condition: The condition to check
    :param message: The message to append if the condition is True
    """
    if condition:
        errors_in_config.append(f"{message}")


# SAVE CONFIG VALUES to constants

# ----- Needed hardware settings -----
NR_OF_BATTERIES: int = get_int_from_config("DEFAULT", "NR_OF_BATTERIES")
if NR_OF_BATTERIES < 2:
    errors_in_config.append("NR_OF_BATTERIES must be at least 2. Currently set to %d." % NR_OF_BATTERIES)

NR_OF_CELLS_PER_BATTERY: int = get_int_from_config("DEFAULT", "NR_OF_CELLS_PER_BATTERY")
if NR_OF_CELLS_PER_BATTERY < 2:
    errors_in_config.append("NR_OF_CELLS_PER_BATTERY must be at least 2. Currently set to %d." % NR_OF_CELLS_PER_BATTERY)

NR_OF_MPPTS: int = get_int_from_config("DEFAULT", "NR_OF_MPPTS")


# ----- DBus settings -----
BATTERY_SERVICE_NAME: str = config["DEFAULT"]["BATTERY_SERVICE_NAME"]
DCLOAD_SERVICE_NAME: str = config["DEFAULT"]["DCLOAD_SERVICE_NAME"]
BATTERY_PRODUCT_NAME_PATH: str = config["DEFAULT"]["BATTERY_PRODUCT_NAME_PATH"]
BATTERY_PRODUCT_NAME: str = config["DEFAULT"]["BATTERY_PRODUCT_NAME"]
BATTERY_INSTANCE_NAME_PATH: str = config["DEFAULT"]["BATTERY_INSTANCE_NAME_PATH"]
MULTI_KEYWORD: str = config["DEFAULT"]["MULTI_KEYWORD"]
MPPT_KEYWORD: str = config["DEFAULT"]["MPPT_KEYWORD"]
SMARTSHUNT_NAME_KEYWORD: str = config["DEFAULT"]["SMARTSHUNT_NAME_KEYWORD"]
SMARTSHUNT_INSTANCE_NAME_PATH: str = config["DEFAULT"]["SMARTSHUNT_INSTANCE_NAME_PATH"]
SEARCH_TRIALS: int = get_int_from_config("DEFAULT", "SEARCH_TRIALS")
READ_TRIALS: int = get_int_from_config("DEFAULT", "READ_TRIALS")
UPDATE_INTERVAL_FIND_DEVICES: int = get_int_from_config("DEFAULT", "UPDATE_INTERVAL_FIND_DEVICES")
UPDATE_INTERVAL_DATA: int = get_int_from_config("DEFAULT", "UPDATE_INTERVAL_DATA")
TIME_BEFORE_RESTART: int = get_int_from_config("DEFAULT", "TIME_BEFORE_RESTART")


# ----- Options -----
CURRENT_FROM_VICTRON: bool = get_bool_from_config("DEFAULT", "CURRENT_FROM_VICTRON")
USE_SMARTSHUNTS: bool = get_bool_from_config("DEFAULT", "USE_SMARTSHUNTS")
INVERT_SMARTSHUNTS: bool = get_bool_from_config("DEFAULT", "INVERT_SMARTSHUNTS")
IGNORE_SMARTSHUNT_ABSENCE: bool = get_bool_from_config("DEFAULT", "IGNORE_SMARTSHUNT_ABSENCE")
OWN_SOC: bool = get_bool_from_config("DEFAULT", "OWN_SOC")
ZERO_SOC: bool = get_bool_from_config("DEFAULT", "ZERO_SOC")
MAX_CELL_VOLTAGE_SOC_FULL: float = get_float_from_config("DEFAULT", "MAX_CELL_VOLTAGE_SOC_FULL")
MIN_CELL_VOLTAGE_SOC_EMPTY: float = get_float_from_config("DEFAULT", "MIN_CELL_VOLTAGE_SOC_EMPTY")
CHARGE_SAVE_PRECISION: float = get_float_from_config("DEFAULT", "CHARGE_SAVE_PRECISION")


# ----- Charge/Discharge parameters -----
OWN_CHARGE_PARAMETERS: bool = get_bool_from_config("DEFAULT", "OWN_CHARGE_PARAMETERS")
BALANCING_VOLTAGE: float = get_float_from_config("DEFAULT", "BALANCING_VOLTAGE")
BALANCING_REPETITION: int = get_int_from_config("DEFAULT", "BALANCING_REPETITION")
CHARGE_VOLTAGE_LIST: List[float] = get_list_from_config("DEFAULT", "CHARGE_VOLTAGE_LIST", float)
MAX_CELL_VOLTAGE: float = get_float_from_config("DEFAULT", "MAX_CELL_VOLTAGE")
MIN_CELL_VOLTAGE: float = get_float_from_config("DEFAULT", "MIN_CELL_VOLTAGE")
MIN_CELL_HYSTERESIS: float = get_float_from_config("DEFAULT", "MIN_CELL_HYSTERESIS")
CELL_DIFF_MAX: float = get_float_from_config("DEFAULT", "CELL_DIFF_MAX")
BATTERY_EFFICIENCY: float = get_float_from_config("DEFAULT", "BATTERY_EFFICIENCY")
MAX_CHARGE_CURRENT: int = get_int_from_config("DEFAULT", "MAX_CHARGE_CURRENT")
MAX_DISCHARGE_CURRENT: int = get_int_from_config("DEFAULT", "MAX_DISCHARGE_CURRENT")

CELL_CHARGE_LIMITING_VOLTAGE: List[float] = get_list_from_config("DEFAULT", "CELL_CHARGE_LIMITING_VOLTAGE", float)
CELL_CHARGE_LIMITED_CURRENT: List[float] = get_list_from_config("DEFAULT", "CELL_CHARGE_LIMITED_CURRENT", float)
if not CELL_CHARGE_LIMITING_VOLTAGE or len(CELL_CHARGE_LIMITING_VOLTAGE) < 2 or len(CELL_CHARGE_LIMITING_VOLTAGE) != len(CELL_CHARGE_LIMITED_CURRENT):
    if not len(CELL_CHARGE_LIMITING_VOLTAGE) == 0:
        errors_in_config.append("CELL_CHARGE_LIMITING_VOLTAGE is not set or has less than 2 values. Using default values.")
    CELL_CHARGE_LIMITING_VOLTAGE = [
        MIN_CELL_VOLTAGE,
        MIN_CELL_VOLTAGE + 0.05,
        BALANCING_VOLTAGE - 0.1,
        BALANCING_VOLTAGE,
        MAX_CELL_VOLTAGE,
    ]
if not CELL_CHARGE_LIMITED_CURRENT or len(CELL_CHARGE_LIMITED_CURRENT) < 2 or len(CELL_CHARGE_LIMITING_VOLTAGE) != len(CELL_CHARGE_LIMITED_CURRENT):
    if not len(CELL_CHARGE_LIMITED_CURRENT) == 0:
        errors_in_config.append("CELL_CHARGE_LIMITED_CURRENT is not set or has less than 2 values. Using default values.")
    CELL_CHARGE_LIMITED_CURRENT = [0.2, 1, 1, 0.1, 0]

CELL_DISCHARGE_LIMITING_VOLTAGE: List[float] = get_list_from_config("DEFAULT", "CELL_DISCHARGE_LIMITING_VOLTAGE", float)
CELL_DISCHARGE_LIMITED_CURRENT: List[float] = get_list_from_config("DEFAULT", "CELL_DISCHARGE_LIMITED_CURRENT", float)
if (
    not CELL_DISCHARGE_LIMITING_VOLTAGE
    or len(CELL_DISCHARGE_LIMITING_VOLTAGE) < 2
    or len(CELL_DISCHARGE_LIMITING_VOLTAGE) != len(CELL_DISCHARGE_LIMITED_CURRENT)
):
    if not len(CELL_DISCHARGE_LIMITING_VOLTAGE) == 0:
        errors_in_config.append("CELL_DISCHARGE_LIMITING_VOLTAGE is not set or has less than 2 values. Using default values.")
    CELL_DISCHARGE_LIMITING_VOLTAGE = [
        MIN_CELL_VOLTAGE,
        MIN_CELL_VOLTAGE + 0.1,
        MIN_CELL_VOLTAGE + 0.2,
    ]
if not CELL_DISCHARGE_LIMITED_CURRENT or len(CELL_DISCHARGE_LIMITED_CURRENT) < 2 or len(CELL_DISCHARGE_LIMITING_VOLTAGE) != len(CELL_DISCHARGE_LIMITED_CURRENT):
    if not len(CELL_DISCHARGE_LIMITED_CURRENT) == 0:
        errors_in_config.append("CELL_DISCHARGE_LIMITED_CURRENT is not set or has less than 2 values. Using default values.")
    CELL_DISCHARGE_LIMITED_CURRENT = [0, 0.05, 1]


# --------- if OWN_CHARGE_PARAMETERS = False ---------
KEEP_MAX_CVL: bool = get_bool_from_config("DEFAULT", "KEEP_MAX_CVL")
AGGREGATE_CHARGE_MODE: bool = get_bool_from_config("DEFAULT", "AGGREGATE_CHARGE_MODE")
SEND_CELL_VOLTAGES: int = get_int_from_config("DEFAULT", "SEND_CELL_VOLTAGES")
LOG_PERIOD: int = get_int_from_config("DEFAULT", "LOG_PERIOD")


# print errors and exit if there are any
if errors_in_config:
    logging.error("Errors in config file:")

    for error in errors_in_config:
        logging.error(f"|- {error}")

    logging.error("")
    logging.error("Please fix the errors in the config file and restart the program.")
    sleep(60)
    sys.exit(1)
