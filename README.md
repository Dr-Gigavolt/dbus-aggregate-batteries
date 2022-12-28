This is a service for Victron Venus OS to collect the data from multiple parallel-connected batteries using
https://github.com/Louisvdw/dbus-serialbattery driver, merge them and publish as a single virtual battery to Dbus.

It could serve at least as a temporary solution for https://github.com/Louisvdw/dbus-serialbattery/issues/8

I test the program only with JK BMS. I have no other hardware.

Attention: This is my first experience with the Victron system and this software is not tested properly yet.
I offer it "as it is" for persons with sufficient knowledge and experience and under exclusion of any kind of liability.
You should review and understand the code before using it. Please report the bugs and propose improvements.

Installation:
- create /data/dbus-aggregate-batteries directory
- copy the stuff into it
- set chmod 744 for ./service/run and ./restart
- set the parameters in ./settings.py (22 cells LTO batteries in my case)
- add command ln -s /data/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries into /data/rc.local

The service starts automatically after start/restart of the Venus OS. Afrer changing of aggregatebatteries.py or
settings.py restart it by executing:

./restart - it kills the service which starts automatically again.

For debugging (to see the error messages in the console) it could be reasonable to rename: ./service/run 
and start by: python3 aggregatebatteries.py

Function:

on start:
	- all services containing SERVICE_KEY_WORD in their names are found
every second:
	- data of all batteries are collected
	- data are merged, e.g. average voltage, sum of currents, average of SoC, cells with absolute minimum and maximum voltage etc.,
	see the code for details
	- charge/discharge limits (max. charge voltage and max. charge and discharge current) are calculated
	- new data are published on Dbus as a single virtual battery
	
The charge state changes from BULK to ABSORPTION if either the absorption voltage (ABSORPTION_VOLTAGE * Nr. of cells) is reached
or the first cell reaches the MAX_CELL_VOLTAGE. In second case is the MaxChargeVoltage parameter set to the current battery
voltage. This avoids emergency disconnecting the battery by its BMS.

The MaxChargeVoltage parameter is reduced to (FLOAT_VOLTAGE * Nr. of cells) after ABSORBTION_TIME_M minutes. If the first cell 
reaches MAX_CELL_VOLTAGE the MaxChargeVoltage parameter set to the current battery voltage.

New absorption is allowed after ABSORBTION_RESTART_H hours.

If the battery voltage falls under (RE_BULK_VOLTAGE * Nr. of cells), the charge state is set to BULK again.    
	
The MaxChargeCurrent is reduced from MAX_CHARGE_CURRENT to MAX_CHARGE_CURRENT_ABOVE_CV1 when the first cell reaches CV1 and further
reduced to MAX_CHARGE_CURRENT_ABOVE_CV2 when the first cell reaches CV2.

The MaxDischargeCurrent is reduced from MAX_DISCHARGE_CURRENT to zero if the battery voltage falls down to (DISCHARGE_VOLTAGE * Nr. of cells)
or the first cell falls down to MIN_CELL_VOLTAGE.

Logging file:
./aggregatebatteries.log	

Known issues:
- the current measurement of JK BMS is very unprecise, I suppose it is interfered by the AC component drawn my Multis. Therefore the SoC is unprecise too with cumulative error. I will try to work with currents published by multis and MPPTs.
- the last data from dbus-serialbattery driver remain on Dbus if the connection is interrupted. Therefore my software cannot recognize it as well.
