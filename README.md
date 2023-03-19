This is a service for Victron Venus OS to collect the data from multiple parallel-connected batteries using https://github.com/Louisvdw/dbus-serialbattery driver, merge them and publish as a single virtual battery to Dbus. 
It could serve at least as a temporary solution for https://github.com/Louisvdw/dbus-serialbattery/issues/8
I recommend to use with this commit of dbus-serialbattery: https://github.com/Louisvdw/dbus-serialbattery/tree/3685d15a5d1ba801867bbdb98f57fd805ea2c24a/etc/dbus-serialbattery 

Attention: This is my first experience with the Victron system and this software is not tested properly yet. I offer it "as it is" for persons with sufficient knowledge and experience and under exclusion of any kind of liability. You should review and understand the code before using it. 

My hardware:
- 3x MultiPlus-II 48/5000/70-50
- 1x SmartSolar MPPT VE.Can 250/100
- 1x Fronius Symo 15.0-3-M
- 2x LTO batteries with JK BMS 2A24S20P

Please report the bugs and propose improvements.

Installation:
- create /data/dbus-aggregate-batteries directory
- copy the stuff into it
- set chmod 744 for ./service/run and ./restart
- set the parameters in ./settings.py (see the file and the info below)
- write initial charge guess (in A.h) into ./charge
- add command ln -s /data/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries into /data/rc.local 

The service starts automatically after start/restart of the Venus OS. After changing of aggregatebatteries.py, dbusmon.py or settings.py restart it by executing:

sh restart - it kills the service which starts automatically again
sh restart_dbus-serial-battery - the same for all instances of the battery driver
sh restart_all - the same for both, battery driver and AggregateBatteries

For debugging (to see the error messages in the console) it is reasonable to rename: ./service/run and start by: python3 aggregatebatteries.py

Function:

on start, search for:
- all batteries: services containing BATTERY_KEY_WORD in their names and BATTERY_NAME_KEY_WORD (to differentiate between battery and SmartShunt) in their product names
- if a SmartShunt is found, is remembered and can be taken into account as DC load in case of own DC current measurement
- service (only one) containing MULTI_KEY_WORD in its name - Multi or Quattro or cluster of them for DC current measurement
- all services containing MPPT_KEY_WORD - SmartSolars and BlueSolars for DC current measurement. MPPT RS not tested.	
every second:
- data of all batteries are collected
- data are merged, e.g. average voltage, sum of currents, average of SoC, cells with absolute minimum and maximum voltage etc., see the code for details
- own Coulumb counter is updated
- own charge/discharge parameters (max. charge voltage and max. charge and discharge current) are calculated
- if CURRENT_FROM_VICTRON = True: DC current measurement from Multis/Quattros and MPPTs is used instead of BMS current measurement (reasonable e.g. in case of JK BMS with poor accuracy)
- if DC_LOADS = True: SmartShunt enabled to measure DC consumption. Set INVERT_SMARTSHUNT = True to change its polarity
- OWN_SOC = True: Own Coulumb counter is used instead of the one in BMS
- OWN_CHARGE_PARAMETERS = True: Calculate own max. charge voltage and max. charge and discharge currents. Othervise merged values from SerialBattery instances are transmitted.	
- new data are published on Dbus as a single virtual battery

dbusmonitor defined in dbusmon.py is used instead of VeDbusItemImport which was very ressource hungry (since V2.0)	
	
Calculation of own charge/discharge parameters:
	
- The max. charge voltage is either set to (CHARGE_VOLTAGE * Nr. of cells) or is limited in order not to exceed the MAX_CELL_VOLTAGE. This avoids emergency disconnecting the battery by its BMS. The limited charge voltage is calculated by subtracting the sum of all cell overvoltages (above MAX_CELL_VOLTAGE) and a margin VOLTAGE_SET_PRECISION from the sum of all cell voltages. This is done for all batteries and the minimum is taken.    	
- The MaxChargeCurrent and MaxDischargeCurrent are linear interpolated between given points in lists (see settings.py for details).

The charge or discharge current is set to zero if at least one BMS is blocking charge or discharge respectively. Here is a trouble with the commit #393 of SerialBattery - the blocking charge/discharge is set always by the SerialBattery driver, even if everything in config is set false - the state of the BMS-es is not forwarded any more. To avoid it (if you wish to use OWN_CHARGE_PARAMETERS = True) the setting of SerialBattery must be more liberal then the setting of AggregateBatteries.

Logging file:
./service/aggregatebatteries.log	

