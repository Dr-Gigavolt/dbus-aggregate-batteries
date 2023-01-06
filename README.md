This is a service for Victron Venus OS to collect the data from multiple parallel-connected batteries using
https://github.com/Louisvdw/dbus-serialbattery driver, merge them and publish as a single virtual battery to Dbus.
 

It could serve at least as a temporary solution for https://github.com/Louisvdw/dbus-serialbattery/issues/8

I test the program only with JK BMS. I have no other hardware. As I found out that the current measurement of the JK BMS
has very pure accuracy (the AC component drawn from the battery is not properly filtered out) and therefore the SoC is
useless, I made in the version 0.1 optional current measurement by Victron chargers instead of BMS (for the case of pure accuracy)
and own Coulumb counter. Both features can be switched on and off in settings.py 

Attention: This is my first experience with the Victron system and this software is not tested properly yet.
I offer it "as it is" for persons with sufficient knowledge and experience and under exclusion of any kind of liability.
You should review and understand the code before using it. Please report the bugs and propose improvements.

Installation:
- create /data/dbus-aggregate-batteries directory
- copy the stuff into it
- set chmod 744 for ./service/run and ./restart
- set the parameters in ./settings.py (22 cells LTO batteries in my case)
- write initial charge guess (in A.h) into ./service/charge
- add command ln -s /data/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries into /data/rc.local


The service starts automatically after start/restart of the Venus OS. After changing of aggregatebatteries.py or
settings.py restart it by executing:

./restart - it kills the service which starts automatically again.

For debugging (to see the error messages in the console) it could be reasonable to rename: ./service/run 
and start by: python3 aggregatebatteries.py

Function:

on start, search for:
	- all services containing BATTERY_KEY_WORD in their names and BATTERY_NAME_KEY_WORD in their product names (double-check is necessary to
	  exclude SmartShunts, they are published as batteries)
	- service containing MULTI_KEY_WORD in its name - Multi or Quattro or cluster of them for DC current measurement
	- all services containing MPPT_KEY_WORD - SmartSolars and BlueSolars for DC current measurement. MPPT RS not tested.	
every second:
	- data of all batteries are collected
	- data are merged, e.g. average voltage, sum of currents, average of SoC, cells with absolute minimum and maximum voltage etc.,
	  see the code for details
	- own Coulumb counter is updated
	- if enabled, the DC current and charge-relevant variables from BMS are overwritten by current measured by Victron chargers and self
	  calculated charge and SoC.
	- charge/discharge limits (max. charge voltage and max. charge and discharge current) are calculated
	- new data are published on Dbus as a single virtual battery
	
The max. charge voltage is either set to (CHARGE_VOLTAGE * Nr. of cells) or is limited to the immediate battery voltage if the first cell reaches 
the MAX_CELL_VOLTAGE. This avoids emergency disconnecting the battery by its BMS.    
	
The MaxChargeCurrent is reduced from MAX_CHARGE_CURRENT to MAX_CHARGE_CURRENT_ABOVE_CV1 when the first cell reaches CV1 and further
reduced to MAX_CHARGE_CURRENT_ABOVE_CV2 when the first cell reaches CV2.

The MaxDischargeCurrent is reduced from MAX_DISCHARGE_CURRENT to zero if the battery voltage falls down to (DISCHARGE_VOLTAGE * Nr. of cells)
or the first cell falls down to MIN_CELL_VOLTAGE.

The charge or discharge current is set to zero if at least one BMS is blocking charge or discharge respectively.

Logging file:
./service/aggregatebatteries.log	

Known issue:
- the last data from dbus-serialbattery driver remain on Dbus if the connection is interrupted. Therefore my software cannot recognize it as well.
