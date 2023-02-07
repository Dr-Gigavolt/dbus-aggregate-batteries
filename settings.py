# Version 2.0

NR_OF_BATTERIES = 2                                     # Nr. of physical batteries to be aggregated
NR_OF_MPPTS = 1                                         # Nr. of MPPTs

BATTERY_KEY_WORD = 'com.victronenergy.battery.tty'      # Key world to identify services of physical Serial Batteries
BATTERY_NAME_KEY_WORD = 'SerialBattery'                 # Key world to identify the name of batteries (to exclude SmartShunt)
MULTI_KEY_WORD = 'com.victronenergy.vebus.tty'          # Key world to identify service of Multis/Quattros (or cluster of them)
MPPT_KEY_WORD = 'com.victronenergy.solarcharger.tty'    # Key world to identify services of solar chargers (RS not tested, only SmartSolar)
SMARTSHUNT_NAME_KEY_WORD = 'SmartShunt'                 # Key world to identify services of SmartShunt (not tested) 

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
MAX_VOLTAGE_DIFF = 0.01                                 # Max precision for MPPTs are 10mV (used for dynamic reducing MaxChargeVoltage) CHARGE_VOLTAGE must set to 'dynamic'
MAX_CELL_VOLTAGE = 2.53                                 # If reached by 1-st cell, the charger voltage is clamped to the measured value
DISCHARGE_VOLTAGE = 2.0                                 # If reached, discharge current set to zero
MIN_CELL_VOLTAGE = 1.9                                  # If reached, discharge current set to zero

MAX_CHARGE_CURRENT = 200                                # Max. charge current at normal conditions
MAX_DISCHARGE_CURRENT = 200                             # Max. discharge current at normal conditions

MAX_CHARGE_CURRENT_ABOVE_CV1 = 50                       # Reduction of charge current if the max. cell voltage reaches CV1
CV1 = 2.45
MAX_CHARGE_CURRENT_ABOVE_CV2 = 10                       # Reduction of charge current if the max. cell voltage reaches CV2
CV2 = 2.5

LOGGING = 2                                             # 0: no logging, 1: print to console, 2: print to file
