# ######################################
# ######## Hardware settings ###########
# ######################################

# Nr. of physical batteries to be aggregated. Smart shunt for battery current is not needed and not supported.
NR_OF_BATTERIES = 2
NR_OF_CELLS_PER_BATTERY = 22
# Nr. of MPPTs
NR_OF_MPPTS = 1
# If DC loads with Smart Shunt present, can be used for total current measurement
DC_LOADS = False
# False: Current subtracted, True: Current added
INVERT_SMARTSHUNT = False

# ######################################
# ########### DBus settings ############
# ######################################

# Key world to identify services of physical Serial Batteries (and SmartShunt if available)
BATTERY_SERVICE_NAME = "com.victronenergy.battery"
# Path of Battery Product Name
BATTERY_PRODUCT_NAME_PATH = "/ProductName"
# Key world to identify the batteries (to exclude SmartShunt)
BATTERY_PRODUCT_NAME = "SerialBattery"
# if CustomName doesn't exist, set '/ProductName'
BATTERY_INSTANCE_NAME_PATH = "/CustomName"
# Key world to identify service of Multis/Quattros (or cluster of them)
MULTI_KEY_WORD = "com.victronenergy.vebus"
# Key world to identify services of solar chargers
MPPT_KEY_WORD = "com.victronenergy.solarcharger"
# Key world to identify services of SmartShunt
SMARTSHUNT_NAME_KEY_WORD = "SmartShunt"

# Trials to identify of all batteries before exit and restart
SEARCH_TRIALS = 10
# Trials to get consistent data of all batteries before exit and restart
READ_TRIALS = 10

# ######################################
# ############# Options ################
# ######################################

# If True, the current measurement by Multis/Quattros and MPPTs is taken instead of BMS.
CURRENT_FROM_VICTRON = True
# Necessary for JK BMS due to poor precision.

# If True, the self calculated charge indicators are taken instead of BMS
OWN_SOC = True
# Allow zeroing charge counter at MIN_CELL_VOLTAGE. At full battery it is always set to 100%.
ZERO_SOC = True
# Trade-off between save precision and file access frequency
CHARGE_SAVE_PRECISION = 0.0025

# ######################################
# #### Charge/Discharge parameters #####
# ######################################

# Please note: Victron ESS disables CCL if DC-coupled PV feed-in is active.
# This program disables the DC-coupled PV feed-in when necessary.

# Calculate own charge/discharge control parameters (True) from following settings
OWN_CHARGE_PARAMETERS = True
# or use them from battery driver (False)

# This voltage per cell will be set periodically and kept until balancing below CELL_DIFF_MAX and next charge cycle
BALANCING_VOLTAGE = 2.45
# in days
BALANCING_REPETITION = 10

# Set up how full the battery has to be charged in given month
CHARGE_VOLTAGE_LIST = [
    2.45,  # January
    2.45,  # February
    2.42,  # March
    2.40,  # April
    2.40,  # May
    2.35,  # June
    2.35,  # July
    2.35,  # August
    2.40,  # September
    2.42,  # October
    2.45,  # November
    2.45,  # December
]

# If reached by 1-st cell, the CVL is dynamically limited. DC-coupled PV feed-in will be disabled to enable the CCL.
MAX_CELL_VOLTAGE = 2.5
# If reached, discharge current set to zero
MIN_CELL_VOLTAGE = 1.9
# Allow discharge above MIN_CELL_VOLTAGE + MIN_CELL_HYSTERESIS
MIN_CELL_HYSTERESIS = 0.1
# If lower: re-enable DC-coupled PV feed in (if was disabled by dynamic CVL reduction and was enabled before);
# go back from BALANCING_VOLTAGE to CHARGE_VOLTAGE
CELL_DIFF_MAX = 0.015
# Ah fed into batteries are multiplied by efficiency
BATTERY_EFFICIENCY = 0.98

# Max. charge current at normal conditions
MAX_CHARGE_CURRENT = 300
# Max. discharge current at normal conditions
MAX_DISCHARGE_CURRENT = 200

# settings limiting charge and discharge current if at least one cell gets full or empty
# the lists may have any length, but the same length for voltage and current
# linear interpolation is used for values between

CELL_CHARGE_LIMITING_VOLTAGE = [
    MIN_CELL_VOLTAGE,
    MIN_CELL_VOLTAGE + 0.05,
    BALANCING_VOLTAGE - 0.1,
    BALANCING_VOLTAGE,
    MAX_CELL_VOLTAGE,
]  # [min, ... ,max]; low voltage: limiting current from grid
CELL_CHARGE_LIMITED_CURRENT = [0.2, 1, 1, 0.05, 0]
# [min, ... ,max]
CELL_DISCHARGE_LIMITING_VOLTAGE = [
    MIN_CELL_VOLTAGE,
    MIN_CELL_VOLTAGE + 0.1,
    MIN_CELL_VOLTAGE + 0.2,
]
CELL_DISCHARGE_LIMITED_CURRENT = [0, 0.05, 1]

# #######################################
# ## if OWN_CHARGE_PARAMETERS = False ###
# #######################################

# If "False", the transmitted CVL is always the minimum of all batteries
# If "True", the transmitted CVL is the maximum of all batteries until all are in "float",
# than the minimum of all is taken. Attention: By using this function you rely on the functionality
# and correct settings of the SerialBattery driver. Set "True" only if you know exactly
# what you are doing. If not sure, keep it at "False".

KEEP_MAX_CVL = False

# ######################################
# ###### Logging and reporting #########
# ######################################

# 0: Disable Cell Info in dbus, 1: Format: /Cell/BatteryName_Cell<ID>
SEND_CELL_VOLTAGES = 0
# 0: no logging, 1: print to console, 2: print to file
LOGGING = 2
# in seconds; if 0, periodic logging is disabled
LOG_PERIOD = 900
