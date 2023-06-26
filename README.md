<<<<<<< Updated upstream
Version 3.0 is being tested and will be published soon. The following features will be added:

- reduced CVL (to extend the battery life time) with full charge once per given period of time (to balance and reset SoC counter) ... an alternative instead of doing it every day by bulk-absorption-float
- automatic deactivation of DC-coupled feed in (to enable CCL) in case of dynamic SoC reduction due to voltage peaking of one ore multiple cells
- automatic deactivation of DC-coupled feed in case of blocking charge or discharge by BMS
- sending of cell voltages to Dbus (made by Marvo2011)


Version 2.4
=======
Version 3.0
>>>>>>> Stashed changes

This is a service for Victron Venus OS to collect the data from multiple parallel-connected batteries using https://github.com/Louisvdw/dbus-serialbattery driver, merge them and publish as a single virtual battery to Dbus. 
It could serve at least as a temporary solution for https://github.com/Louisvdw/dbus-serialbattery/issues/8

Attention: This is my first experience with the Victron system. I offer it "as it is" for persons with sufficient knowledge and experience and under exclusion of any kind of liability. You should review and understand the code before using it. 

My hardware:
- 3x MultiPlus-II 48/5000/70-50
- 1x SmartSolar MPPT VE.Can 250/100
- 1x Fronius Symo 15.0-3-M
- 2x LTO batteries with JK BMS 2A24S20P

Please report the bugs and propose improvements. Many thanks to all who already participated. According previous experience I prefer if you attach a piece of code instead of creating a merge request. And please understand, that I'm not able to include all proposals, this would make the program too complex and difficult to maintain.

Installation:
- create /data/dbus-aggregate-batteries directory
- copy the stuff into it
- set chmod 744 for ./service/run and ./restart
- set the parameters in ./settings.py (please read comments to understand the function and adjust the parameters)
- write initial charge guess (in A.h) into ./charge
- add command ln -s /data/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries into /data/rc.local 

The service starts automatically after start/restart of the Venus OS. After modifying of files restart it by executing:

sh restart - it kills the service which starts automatically again
sh restart_dbus-serial-battery - the same for all instances of the battery driver
sh restart_all - the same for both, battery driver and AggregateBatteries
(please adapt the last two according your version of SerialBattery)

For debugging (to see the error messages in the console) it is reasonable to rename: ./service/run and start by: python3 aggregatebatteries.py

Logging file: aggregatebatteries.log

If you wish to mount the code into /opt/victronenergy/ follow these instructions:
https://github.com/Dr-Gigavolt/dbus-aggregate-batteries/issues/24

Function:

On starts, the program searches for DBus services:
- all Serial Batteries
- SmartShunt for DC load (option)
- Multiplus or Quattro (or cluster of them) for DC current measurement
- all solar chargers (SmartSolar, BlueSolar, MPPT RS) for DC current measurement

The Victron devices can be used for battery current measurement by setting CURRENT_FROM_VICTRON = True. This is useful if the BMS current measurement is inaccurate (e.g. JK BMS).
Precise current measurement is necessary for precise Coulomb counter which can be activated by OWN_SOC = True. The Coulomb (A.h) value is saved to the text file "charge" after each increment or decrement of CHARGE_SAVE_PRECISION (relative value).

The data from DBus are collected, processed and the results are sent back to DBus once per second. 	
dbusmonitor defined in dbusmon.py is used instead of VeDbusItemImport which was very resources hungry (since V2.0). I strongly recommend to everyone modifying the code to keep this technique.

If you wish to combine the charger control parameters (CVL, CCL, DCL) provided by all instances of SerialBattery, please set OWN_CHARGE_PARAMETERS = False.

If OWN_CHARGE_PARAMETERS = True, the charging and discharging is controlled by the AggregateBatteries.

In contrary to SerialBattery driver, I don't use the Bulk-Absorption-Float lead-acid-like algorithm. The LTO cells used by me are very robust and don't suffer at full charge voltage for longer period of time. Of course you shouldn't keep them above 2.5V, even max. voltage according datasheet is 2.8V. In case of constant voltage charging they are full at about 2.45V. But the most of you use LFP cells, therefore I added another approach into version 3.0. For LFP you can try something around 3.5V for balancing and something below for regular charge, but I don't know exactly, have no experience with LFP. Of course, the feature can be used with LTO as well.

The feature is activated by BALANCING_CVL_ENABLED = True. The cells are charged up to CHARGE_VOLTAGE normally. After BALANCING_REPETITION days of normal charging CVL increases to BALANCING_VOLTAGE. The last day of balancing is stored in the "last balancing" text file. If during this process the cell unbalance falls under CELL_DIFF_MAX, the BALANCING_VOLTAGE is kept as long as the solar power is available. Then, when the cells are discharged from BALANCING_VOLTAGE down to CHARGE_VOLTAGE by own consumption, the process finishes. This algorithm avoids 100% charge during the most of the days in order to prolong the battery life. In contrary, the Bulk-Absorption-Float charges the battery to 100% every day, keeps the voltage for couple of minutes and then discharges the excessive charge into the grid. If you prefer it, just set OWN_CHARGE_PARAMETERS = False and use the calculation of the SerialBattery.

In the future I would add a list defining CHARGE_VOLTAGE for each month of the year. And if some of you prefers to discharge the cells voltage down to the CHARGE_VOLTAGE immediatelly after balancing finished into the grid, let me know. For better understanding whether it is useful or not please find and share some papers about LFP aging under constant voltage. Up to now I found such a document for LTO only (https://www.global.toshiba/content/dam/toshiba/ww/products-solutions/battery/scib/pdf/ToshibaRechargeableBattery-en.pdf or http://futuregrqd.cluster027.hosting.ovh.net/Download/Datasheet/Toshiba_LTO_2.4V_20Ah.pdf), see "Float characteristic".    

If the battery is not balanced properly or the target voltage is set too high, one or more cell's voltages start to peak. To avoid emergency disconnecting of the battery by BMS, the dynamic CVL reduction is activated if at least one cell exceeds the MAX_CELL_VOLTAGE. To avoid instabilities of charger, the DC-coupled PV feed in (if initially enabled) will be disabled in order to enable the CCL. The CCL does not work if the DC-coupled PV feed-in is enabled, see: https://www.victronenergy.com.au/media/pg/Energy_Storage_System/en/configuration.html, chapter 4.3.4. When all cell voltages fall below MAX_CELL_VOLTAGE and the cell difference falls below CELL_DIFF_MAX, the DC-coupled PV feed in is enabled again (if was enabled before). 

The charge or discharge current is set to zero if at least one BMS is blocking charge or discharge respectively. If charge is blocked, the DC-coupled PV feed-in (if initially enabled), will be disabled, see the reason above.