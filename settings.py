# ######################################
# ######## Hardware settings ###########
# ######################################

# Nr. of physical batteries to be aggregated. Smart shunt for battery current is not needed and not supported.
NR_OF_BATTERIES = 2
NR_OF_CELLS_PER_BATTERY = 24

# Nr. of MPPTs
NR_OF_MPPTS = 1

# If DC loads with Smart Shunt present, can be used for total current measurement.
DC_LOADS = False

# False: Current subtracted, True: Current added
INVERT_SMARTSHUNT = False

# ######################################
# ########### DBus settings ############
# ######################################

# Key world to identify services of physical Serial Batteries (and SmartShunt if available). You don't need to change it.
BATTERY_SERVICE_NAME = "com.victronenergy.battery"

# Path of Battery Product Name. You don't need to change it.
BATTERY_PRODUCT_NAME_PATH = "/ProductName"

# Key world to identify the batteries (to exclude SmartShunt). If the BATTERY_PRODUCT_NAME_PATH, e.g. SerialBattery(Jkbms),
# contains this key word, the device will be identified and included into the battery list. 
BATTERY_PRODUCT_NAME = "SerialBattery"

# The name stored in the here selected BATTERY_INSTANCE_NAME_PATH will be taken as the name of the battery in the list.
# Each battery instance should have an unique name. If not, a number will be added. You can choose: "/CustomName"
# (set up in the serial battery driver and is lost on restart of the serial battery driver) or "/Serial"
# (set up in the BMS and therefore not volatile).
BATTERY_INSTANCE_NAME_PATH = "/Serial"

# Key world to identify service of Multis/Quattros (or cluster of them).  You don't need to change it.
MULTI_KEY_WORD = "com.victronenergy.vebus"

# Key world to identify services of solar chargers. You don't need to change it.
MPPT_KEY_WORD = "com.victronenergy.solarcharger"

# Key world to identify services of SmartShunt, if you use it for current into DC loads. You don't need to change it.
SMARTSHUNT_NAME_KEY_WORD = "SmartShunt"

# Trials to identify of all batteries before exit and restart.
SEARCH_TRIALS = 10

# Trials to get consistent data of all batteries before exit and restart.
READ_TRIALS = 10

# ######################################
# ############# Options ################
# ######################################

# If True, the battery current measurement by Multis/Quattros and MPPTs is taken instead of BMS.
# Necessary for JK BMS due to poor current measurement precision.
# The Victron current measurement is very precise, therefore SmartShunt is not needed and not supported.
CURRENT_FROM_VICTRON = True

# Use multiple SmartShunts and control which ones
# - False or an empty list is the original default behavior of using the last SmartShunt instance
# - True uses all available SmartShunts
# - a list of numbers allows using only certain SmartShunts, the numbers are in order of SmartShunt occurence as listed in dbus-spy or log file
MULTIPLE_SMARTSHUNTS = False

# Threshold below which to use sum of currents from SmartShunts as battery current
# if SMARTSHUNT_CURRENT_THRESHOLD is <= 0 then the SmartShunt current aggregrate is always used
SMARTSHUNT_CURRENT_THRESHOLD = -1

# If True, the program's own charge counter is used instead of the BMS counters.
# Necessary for JK BMS due to poor current measurement precision
# and not implemented 100% and 0% reset except of case of MOSFET disconnection.
OWN_SOC = True

# Allow zeroing program's own charge counter at MIN_CELL_VOLTAGE. At full battery it is always set to 100%.
ZERO_SOC = False

# When the battery charge changes more than CHARGE_SAVE_PRECISION, the "charge" file is updated.
# It is a trade-off between resolution and file access frequency. The value is relative.
# The "charge" file is read on start of this program.
CHARGE_SAVE_PRECISION = 0.0025

# ######################################
# #### Charge/Discharge parameters #####
# ######################################

# Please note: Victron ESS disables CCL (Charge Curent Limit) if DC-coupled PV feed-in is active.
# This program disables the DC-coupled PV feed-in when necessary to protect batteries
# (dynamic CVL - Charge Volgage Limit is activated) and re-enables again in safe condition.

# If True, the charge/discharge control parameters (CVL - Charge Voltage Limit, CCL - Charge Current Limit,
# DCL - Discharge Current Limit) are calculated by this program.
# If False, the parameters from Serial Battery instances are taken and aggregated.
OWN_CHARGE_PARAMETERS = True

# This voltage per cell will be set periodically, once BALANCING_REPETITION days and kept until balancing
# goal is reached (cell voltage difference <= CELL_DIFF_MAX) and the next charge cycle begins.
# In case of heavy disbalance this condition can last several days.
BALANCING_VOLTAGE = 2.5
BALANCING_REPETITION = 10

# Set up how full the battery has to be charged in given month. Set lower values in summer
# to prolong battery life and higher values in winter to have more energy available.
CHARGE_VOLTAGE_LIST = [
    2.5,  # January
    2.45,  # February
    2.45,  # March
    2.40,  # April
    2.35,  # May
    2.30,  # June
    2.30,  # July
    2.35,  # August
    2.40,  # September
    2.45,  # October
    2.45,  # November
    2.5,  # December
]

# This is a cell-full protection feature. If MAX_CELL_VOLTAGE is reached by at least one cell,
# the CVL is dynamically limited to avoid over-charging and triggering the BMS disconnection.
# DC-coupled PV feed-in will be disabled to enable the CCL.
MAX_CELL_VOLTAGE = 2.55

# This is a cell-empty protection feature. If reached, discharge current is set to zero
MIN_CELL_VOLTAGE = 1.9

# Allows discharge again above MIN_CELL_VOLTAGE + MIN_CELL_HYSTERESIS
MIN_CELL_HYSTERESIS = 0.3

# Cell balancing (with BALANCING_VOLTAGE) goal in volts. When reached, the charging voltage limit per cell is reduced
# from BALANCING_VOLTAGE down to CHARGE_VOLTAGE from the CHARGE_VOLTAGE_LIST. If due to heavy disbalance the dynamic CVL
#  was activated and DC-coupled PV feed-in was de-activated, these measures are finished when the balancing goal is reached.
CELL_DIFF_MAX = 0.025

# Charge fed into batteries is multiplied by efficiency in order to consider losses and enhance SoC counter precision.
BATTERY_EFFICIENCY = 0.985

# Max. total charge current at normal conditions
MAX_CHARGE_CURRENT = 200

# Max. total discharge current at normal conditions
MAX_DISCHARGE_CURRENT = 200

# Settings limiting charge current when at least one cell is getting full or empty. The lists may have any length,
# but the length must be same for voltage and current. Linear interpolation is used for values between. 
# The charge current limitation of empty cell reduces inverter power in case when the battery has to be charged from grid.

CELL_CHARGE_LIMITING_VOLTAGE = [MIN_CELL_VOLTAGE, MIN_CELL_VOLTAGE + 0.05, BALANCING_VOLTAGE - 0.1, BALANCING_VOLTAGE, MAX_CELL_VOLTAGE]  # [min, ... ,max]; low voltage: limiting current from grid
CELL_CHARGE_LIMITED_CURRENT = [0.2, 1, 1, 0.1, 0] # [min, ... ,max]

# Settings limiting discharge current if at least one cell is getting empty. The lists may have any length,
# but the same length for voltage and current. Linear interpolation is used for values between.
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

# 0: Disable Cell Info on dbus, 1: Format: /Cell/BatteryName_Cell<ID>
SEND_CELL_VOLTAGES = 0

# 0: no logging, 1: print to console, 2: print to file
LOGGING = 2

# Logging period in seconds. If 0, periodic logging is disabled.
LOG_PERIOD = 300