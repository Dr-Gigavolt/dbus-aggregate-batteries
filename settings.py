# Version 3.0

#######################################
########## Hardware settings ##########
#######################################

NR_OF_BATTERIES = 2                                     # Nr. of physical batteries to be aggregated
NR_OF_CELLS_PER_BATTERY = 22
NR_OF_MPPTS = 1                                         # Nr. of MPPTs
DC_LOADS = False                                        # If DC loads with Smart Shunt present, can be used for total current measurement
INVERT_SMARTSHUNT = False                               # False: Current subtracted, True: Current added 

#######################################
############ DBus settings ############
#######################################

BATTERY_SERVICE_NAME = 'com.victronenergy.battery'      # Key world to identify services of physical Serial Batteries (and SmartShunt if available)                
BATTERY_PRODUCT_NAME_PATH = '/ProductName'              # Path of Battery Product Name
BATTERY_PRODUCT_NAME = 'SerialBattery'                  # Key world to identify the batteries (to exclude SmartShunt)
BATTERY_INSTANCE_NAME_PATH = '/CustomName'              # if CustomName doesn't exist, set '/ProductName'
MULTI_KEY_WORD = 'com.victronenergy.vebus'              # Key world to identify service of Multis/Quattros (or cluster of them)
MPPT_KEY_WORD = 'com.victronenergy.solarcharger'        # Key world to identify services of solar chargers
SMARTSHUNT_NAME_KEY_WORD = 'SmartShunt'                 # Key world to identify services of SmartShunt

SEARCH_TRIALS = 10                                      # Trials to identify of all batteries before exit and restart
READ_TRIALS = 10                                        # Trials to get consistent data of all batteries before exit and restart

#######################################
############ DBus settings ############
#######################################

CURRENT_FROM_VICTRON = True                             # If True, the current measurement by Multis/Quattros and MPPTs is taken instead of BMS
OWN_SOC = True                                          # If True, the self calculated charge indicators are taken instead of BMS
CHARGE_SAVE_PRECISION = 0.0025                          # Trade-off between save precision and file access frequency

#######################################
##### Charge/Discharge parameters #####
#######################################

# Please note: Victron EES disables CCL if DC-coupled PV feed-in is active

OWN_CHARGE_PARAMETERS = True                            # Calculate own charge/discharge control parameters (True) from following settings
                                                        # or use them from battery driver (False)
CHARGE_VOLTAGE = 2.3                                    # Constant voltage charge = this value * nr. of cells
BALANCING_VOLTAGE = 2.45                                # This voltage per cell will be set periodically and kept until balancing below CELL_DIFF_MAX and next charge cycle
BALANCING_REPETITION = 10                               # in days                      

MAX_CELL_VOLTAGE = 2.5                                  # If reached by 1-st cell, the CVL is dynamically limited. DC-coupled PV feed-in will be disabled to enable the CCL. 
DISCHARGE_VOLTAGE = 2.0                                 # If reached, discharge current set to zero
MIN_CELL_VOLTAGE = 1.9                                  # If reached, discharge current set to zero
CELL_DIFF_MAX = 0.025                                   # If lower: re-enable DC-coupled PV feed in (if was enabled before); go back from BALANCING_VOLTAGE to CHARGE_VOLTAGE

MAX_CHARGE_CURRENT = 300                                # Max. charge current at normal conditions
MAX_DISCHARGE_CURRENT = 200                             # Max. discharge current at normal conditions

# settings limiting charge and discharge current if at least one cell gets full or empty
# the lists may have any length, but the same length for voltage and current
# linear interpolation is used for values between
CELL_FULL_LIMITING_VOLTAGE = [CHARGE_VOLTAGE, BALANCING_VOLTAGE, MAX_CELL_VOLTAGE]           # [min, .... ,max]
CELL_FULL_LIMITED_CURRENT =  [1, 0.05, 0]
CELL_EMPTY_LIMITING_VOLTAGE = [DISCHARGE_VOLTAGE - 0.1, DISCHARGE_VOLTAGE, MIN_CELL_VOLTAGE]    # [min, .... ,max]
CELL_EMPTY_LIMITED_CURRENT =  [0, 0.05, 1]

#######################################
####### Logging and reporting #########
#######################################

SEND_CELL_VOLTAGES = 0                                 # 0: Disable Cell Info in dbus, 1: Format: /Cell/BatteryName_Cell<ID>
LOGGING = 2                                            # 0: no logging, 1: print to console, 2: print to file
LOG_PERIOD = 600                                       # in seconds; if 0, periodic logging is disabled