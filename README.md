## Attention - troubles with new Venus OS (probably since 3.60)

I deleted releases after July 7-th 2025 because there were issues with new installation stcripts. I apologize I have no time to care about it and hope in help of other contributors. If you have upgraded Victron OS to v.3.6x and have incompatibility issues with installation path /data (otherwise don't touch running system) please:

- copy the dbus-aggregate-batteries directory into /data/app manually
- in dbus-aggregate-batteries/aggregatebatteries.py change all absolute paths /data to /data/apps
- in dbus-aggregate-batteries/service/run change path /data to /data/apps
- remove the old symbolic link /service/dbus-aggregate-batteries
- create new symbolic link: ln -s /data/apps/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries
- if you need shell scripts, change paths there to /data/apps as well. In this case correct the path to reinstall-local.sh in /data/rc.local. If you don't need them, you can delete them as well as the entry in rc.local. I recommend to keep and correct at least restart.sh and restart_dbus-serial-battery.sh, they are useful for debugging.

Other and perhaps the most simple temporary solution to make your system running is the release 3.5.20250707 with Venus OS 3.5x (I still run 3.55)

Thanks for your understanding.

-----------------------------------------------------------------------------------------------------------------------------------------------------

Attention: This is my first experience with the Victron system. I offer it "as it is" for persons with sufficient knowledge and experience and under exclusion of any kind of liability. You should review and understand the code before using it. Please read carefully the explanation of all parameters in `config.ini`. I extended the description after some users misunderstood it. Please execute command dbus-spy on your Venus OS and review all paths transmitted by Serial Battery instances.

### My hardware
- 3x MultiPlus-II 48/5000/70-50
- 1x SmartSolar MPPT VE.Can 250/100
- 1x Fronius Symo 15.0-3-M
- 2x LTO batteries 24S x 5P with JK BMS 2A24S20P

Please report the bugs and propose improvements. Many thanks to all who already participated. According previous experience I prefer if you attach a piece of code instead of creating a merge request. And please understand, that I'm not able to include all proposals, this would make the program too complex and difficult to maintain.

#### Many thanks to Mr-Manuel for adding install scripts and improving logging

## Installation
- Execute these commands to download the driver from the internet and install it:
  ```bash
  wget -O /tmp/install.sh https://raw.githubusercontent.com/Dr-Gigavolt/dbus-aggregate-batteries/main/install.sh

  bash /tmp/install.sh
  ```

Else copy the files or clone the repository as and execute `enable.sh`.

- Set the parameters in `./config.ini`
- Read the comments in `./config.default.ini` to understand the functions and adjust the parameters, if needed
- Write initial charge guess (in Ah) into `./storedvalue_charge`, if `OWN_SOC` is enabled

The service starts automatically after start/restart of the Venus OS.

After modifying files restart it by executing:
```bash
/data/apps/dbus-aggregate-batteries/restart.sh
```

Restart dbus-serialbattery, if needed:
```bash
/data/apps/dbus-aggregate-batteries/restart_dbus-serial-battery.sh
```

If you restart the [dbus-serialbattery](https://github.com/mr-manuel/venus-os_dbus-serialbattery), wait until all instances are visible, assign CustomNames and restart the Aggregate Batteries driver.

For debugging and to see the error messages in the console, stop the service with `svc -d /service/dbus-aggregate-batteries` and start the software manually by executing `python3 /data/apps/dbus-aggregate-batteries/dbus-aggregate-batteries.py`.
After debugging start the service again with `svc -u /service/dbus-aggregate-batteries`.

To check the logs run `/data/apps/dbus-aggregate-batteries/get-logs.sh` and exit again with `CTRL + C`.

If you wish to mount the code into `/opt/victronenergy/` follow these instructions:
https://github.com/Dr-Gigavolt/dbus-aggregate-batteries/issues/24

## Function

On start, the program searches for DBus services:
- all Serial Batteries. Smart Shunts as battery current monitor are neither supported nor needed, you can activate precise current measurement by Victron devices if the precision of your BMS is not sufficient.
- one Smart Shunt for DC load (option)
- Multiplus or Quattro (or cluster of them) for DC current measurement
- all solar chargers (SmartSolar, BlueSolar, MPPT RS) for DC current measurement

The data from DBus are collected, processed and the results are sent back to DBus once per second.
Dbus monitor defined in dbusmon.py is used instead of VeDbusItemImport which was very resource hungry (since V2.0). I strongly recommend to everyone modifying the code to keep this technique.

If you wish to combine the charger control parameters (`CVL - Charge Voltage Limit`, `CCL - Charge Current Limit`, `DCL - Discharge Current Limit`) provided by all instances of dbus-serialbattery, please set `OWN_CHARGE_PARAMETERS = False`.

If `OWN_CHARGE_PARAMETERS = True`, the charging and discharging is controlled by the AggregateBatteries.
In combination with `OWN_CHARGE_PARAMETERS = False` you need to set up the charge counter resetting values `MAX_CELL_VOLTAGE_SOC_FULL` and `MIN_CELL_VOLTAGE_SOC_EMPTY`

In contrast to dbus-serialbattery driver, I don't use the Bulk-Absorption-Float lead-acid-like algorithm. The LTO cells used by me are very robust and don't suffer at full charge voltage for longer periods of time. Of course you shouldn't keep them above `2.5V`, although max. voltage according to datasheet is `2.8V`. In case of constant voltage charging they are full at about `2.45V ... 2.5V`. But most of you use LFP cells, therefore I use another approach. For LFP you have to set up the cell voltages according to your experience or literature.

If the nominal charge voltage in `CHARGE_VOLTAGE_LIST` is set below the `BALANCING_VOLTAGE` (regular charging below 100% SoC), every `BALANCING_REPETITION` days full charge and balancing with `BALANCING_VOLTAGE` occurs. If not successful at given day (`BALANCING_VOLTAGE` not reached or cell voltage difference remains above `CELL_DIFF_MAX`), the next trial is done on the following day. The `BALANCING_VOLTAGE` is kept as long as the solar power is available. Then, when the cells are discharged from `BALANCING_VOLTAGE` down to `CHARGE_VOLTAGE` by own consumption, the process finishes. This algorithm avoids 100% charge during most of the days in order to prolong the battery life. In contrast, the Bulk-Absorption-Float charges the battery to 100% every day, keeps the voltage for a couple of minutes and then discharges the excessive charge into the grid. If you prefer it, just set `OWN_CHARGE_PARAMETERS = False` and use the calculation of the dbus-serialbattery.

You can select the program's own SoC counter by setting `OWN_SOC = True`. Otherwise weighted (by battery capacity) average of the BMS SoC counters is calculated. The stored charge is multiplied by parameter `BATTERY_EFFICIENCY` in order to consider losses and enhance the precision of the own SoC counter.

For better understanding whether the discharge to "Float" is useful or not please find and share some papers about LFP aging under constant voltage. Up to now I found such a document for LTO only (https://www.global.toshiba/content/dam/toshiba/ww/products-solutions/battery/scib/pdf/ToshibaRechargeableBattery-en.pdf or http://futuregrqd.cluster027.hosting.ovh.net/Download/Datasheet/Toshiba_LTO_2.4V_20Ah.pdf), see "Float characteristic".

If the battery is not balanced properly or the target voltage is set too high, one or more cell's voltages start to peak. To avoid emergency disconnecting of the battery by BMS, the dynamic CVL reduction is activated if at least one cell exceeds the `MAX_CELL_VOLTAGE`. To avoid instabilities of charger, the DC-coupled PV feed-in (if initially enabled) will be disabled in order to enable the `CCL`. The `CCL` does not work if the DC-coupled PV feed-in is enabled, see: https://www.victronenergy.com.au/media/pg/Energy_Storage_System/en/configuration.html, chapter 4.3.4. When all cell voltages fall below `MAX_CELL_VOLTAGE` and the cell difference falls below `CELL_DIFF_MAX`, the DC-coupled PV feed-in is enabled again (if was enabled by user before).

The charge or discharge current is set to zero if at least one BMS is blocking charge or discharge respectively. If charge is blocked, the DC-coupled PV feed-in (if initially enabled), will be disabled, see the reason above.
