# Version 2.3

NR_OF_BATTERIES = 2                                     # Nr. of physical batteries to be aggregated
NR_OF_MPPTS = 1                                         # Nr. of MPPTs

BATTERY_KEY_WORD = 'com.victronenergy.battery.tty'      # Key world to identify services of physical Serial Batteries
BATTERY_NAME_KEY_WORD = 'SerialBattery'                 # Key world to identify the name of batteries (to exclude SmartShunt)
BATTERY_NAME_PATH = '/CustomName'                       # What defines the battery name
#BATTERY_NAME_PATH = '/HardwareVersion'

MULTI_KEY_WORD = 'com.victronenergy.vebus.tty'          # Key world to identify service of Multis/Quattros (or cluster of them)
MPPT_KEY_WORD = 'com.victronenergy.solarcharger.tty'    # Key world to identify services of solar chargers (RS not tested, only SmartSolar)
SMARTSHUNT_NAME_KEY_WORD = 'SmartShunt'                 # Key world to identify services of SmartShunt (not tested)
                                                        # specify more precisely if more SmartShunts are in systems

SEARCH_TRIALS = 10                                      # Trials to identify of all batteries before exit and restart
READ_TRIALS = 10                                        # Trials to get consistent data of all batteries before exit and restart

CURRENT_FROM_VICTRON = True                             # If True, the current measurement by Multis/Quattros and MPPTs is taken instead of BMS
DC_LOADS = False                                        # If DC loads with Smart Shunt present, can be used for total current measurement 
INVERT_SMARTSHUNT = False                               # False: Current subtracted, True: Current added
OWN_SOC = True                                          # If True, the self calculated charge indicators are taken instead of BMS
CHARGE_SAVE_PRECISION = 0.0025                          # Trade-off between save precision and file access frequency

OWN_CHARGE_PARAMETERS = True                            # Calculate own charge/discharge control parameters (True) from following settings
                                                        # or use them from battery driver (False)
CHARGE_VOLTAGE = 2.5                                    # Constant voltage charge = this value * nr. of cells
MAX_CELL_VOLTAGE = 2.53                                 # If reached by 1-st cell, the charger voltage is clamped to the measured value
DISCHARGE_VOLTAGE = 2.0                                 # If reached, discharge current set to zero
MIN_CELL_VOLTAGE = 1.9                                  # If reached, discharge current set to zero
VOLTAGE_SET_PRECISION = 0.06                            # To be subtracted from the calculated max. charge voltage if MAX_CELL_VOLTAGE is exceeded

MAX_CHARGE_CURRENT = 300                                # Max. charge current at normal conditions
MAX_DISCHARGE_CURRENT = 200                             # Max. discharge current at normal conditions

# settings limiting charge and discharge current if at least one cell gets full or empty
# the lists may have any length, but the same length for voltage and current
# linear interpolation is used for values between
CELL_FULL_LIMITING_VOLTAGE = [CHARGE_VOLTAGE - 0.1, CHARGE_VOLTAGE, MAX_CELL_VOLTAGE]           # [min, .... ,max]
CELL_FULL_LIMITED_CURRENT =  [1, 0.05, 0]
CELL_EMPTY_LIMITING_VOLTAGE = [DISCHARGE_VOLTAGE - 0.1, DISCHARGE_VOLTAGE, MIN_CELL_VOLTAGE]    # [min, .... ,max]
CELL_EMPTY_LIMITED_CURRENT =  [0, 0.05, 1]

LOGGING = 2                                             # 0: no logging, 1: print to console, 2: print to file
LOG_VOLTAGE_CHANGE = 0.1                                # change of max. charge voltage to be logged
LOG_CURRENT_CHANGE = 5                                  # change of max. charge/discharge current to be logged