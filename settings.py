NR_OF_BATTERIES = 2                                     # Nr. of physical batteries to be aggregated
SERVICE_KEY_WORD = 'com.victronenergy.battery.ttyUSB'   # Key world to identify services of physical Serial Batteries
PRODUCT_NAME_KEY_WORD = 'SerialBattery'                 # Key world to identify the product name (to exclude SmartShunt)
SCAN_TRIALS = 10                                        # Trials to identify of all batteries before exit
READ_TRIALS = 20                                        # Trials to get consistent data of all batteries before exit

ABSORPTION_VOLTAGE = 2.5                                # Absorption voltage = this value * nr. of cells
ABSORBTION_TIME_M = 30                                  # in minutes
ABSORBTION_RESTART_H = 6                                # time in hours to allow absorption again                            
FLOAT_VOLTAGE = 2.45                                    # Float voltage = this value * nr. of cells                 
RE_BULK_VOLTAGE = 2.4
MAX_CELL_VOLTAGE = 2.7                                  # If reached by 1-st cell, the charger voltage is clamped to the measured value
DISCHARGE_VOLTAGE = 2                                   # If reached, discharge current set to zero
MIN_CELL_VOLTAGE = 1.9

MAX_CHARGE_CURRENT = 200                                # Max. charge current at normal conditions
MAX_DISCHARGE_CURRENT = 200                             # Max. discharge current at normal conditions

MAX_CHARGE_CURRENT_ABOVE_CV1 = 50                       # Reduction of charge current if the max. cell voltage reaches CV1
CV1 = 2.5
MAX_CHARGE_CURRENT_ABOVE_CV2 = 10                       # Reduction of charge current if the max. cell voltage reaches CV2
CV2 = 2.6

