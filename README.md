## Version 3.4

Attention: This is my first experience with the Victron system. I offer it "as it is" for persons with sufficient knowledge and experience and under exclusion of any kind of liability. You should review and understand the code before using it. Please read carefully the explanation of all parameters in `settings.py`. None of them is universal, you have to adapt everything to your system.

### My hardware
- 3x MultiPlus-II 48/5000/70-50
- 1x SmartSolar MPPT VE.Can 250/100
- 1x Fronius Symo 15.0-3-M
- 2x LTO batteries 22S x 5P with JK BMS 2A24S20P

Please report the bugs and propose improvements. Many thanks to all who already participated. According previous experience I prefer if you attach a piece of code instead of creating a merge request. And please understand, that I'm not able to include all proposals, this would make the program too complex and difficult to maintain.

#### Many thanks to Mr-Manuel for adding install scripts and improve logging

## Installation
- execute this commands:
  ```bash
  wget -O /tmp/install.sh https://raw.githubusercontent.com/Dr-Gigavolt/dbus-aggregate-batteries/main/install.sh

  bash /tmp/install.sh
  ```

(or copy the files or clone the repository as before and execute reinstall-local.sh - the script sets the symlink and permissions, no need to do it manually)

- set the parameters in `./settings.py` (please read comments to understand the function and adjust the parameters)
- write initial charge guess (in Ah) into `./charge`

The service starts automatically after start/restart of the Venus OS. After modifying of files restart it by executing:


`/data/dbus-aggregate-batteries/restart.sh` - it kills the service which starts automatically again

`/data/dbus-aggregate-batteries/restart_dbus-serial-battery.sh` - kills all instances of Serial Battery, reinstalls files and starts again

If you restart the Serial Battery, wait until all instances are visible, assign CustomNames and restart the Aggregate Batteries

For debugging (to see the error messages in the console) it is reasonable to rename: ./service/run and start by: `python3 /data/dbus-aggregate-batteries/aggregatebatteries.py`

Logging file: `tail -F /var/log/dbus-aggregate-batteries/current` or use any text file editor.

If you wish to mount the code into `/opt/victronenergy/` follow these instructions:
https://github.com/Dr-Gigavolt/dbus-aggregate-batteries/issues/24

## Function

On starts, the program searches for DBus services:
- all Serial Batteries. Smart Shunts as battery monitor are neither supported nor needed, you can activate precise current measurement by Victron devices if the precision of your BMS is not sufficient.
- one Smart Shunt for DC load (option)
- Multiplus or Quattro (or cluster of them) for DC current measurement
- all solar chargers (SmartSolar, BlueSolar, MPPT RS) for DC current measurement

The data from DBus are collected, processed and the results are sent back to DBus once per second.
Dbus monitor defined in dbusmon.py is used instead of VeDbusItemImport which was very resources hungry (since V2.0). I strongly recommend to everyone modifying the code to keep this technique.

If you wish to combine the charger control parameters (`CVL`, `CCL`, `DCL`) provided by all instances of SerialBattery, please set `OWN_CHARGE_PARAMETERS = False`.
If `OWN_CHARGE_PARAMETERS = True`, the charging and discharging is controlled by the AggregateBatteries.

In contrary to SerialBattery driver, I don't use the Bulk-Absorption-Float lead-acid-like algorithm. The LTO cells used by me are very robust and don't suffer at full charge voltage for longer period of time. Of course you shouldn't keep them above `2.5V`, although max. voltage according datasheet is `2.8V`. In case of constant voltage charging they are full at about `2.45V`. But the most of you use LFP cells, therefore I added another approach since version 3.0. For LFP you have to set up the cell voltages according your experience or literature.

If the target charge voltage is set below the `BALANCING_VOLTAGE` (regular charging below 100% SoC), every `BALANCING_REPETITION` days full charge and balancing with `BALANCING_VOLTAGE` occurs. If not succesfull at given day (`BALANCING_VOLTAGE` not reached or cell voltage difference remains above `CELL_DIFF_MAX`), the next trial is done at the following day. The `BALANCING_VOLTAGE` is kept as long as the solar power is available. Then, when the cells are discharged from `BALANCING_VOLTAGE` down to `CHARGE_VOLTAGE` by own consumption, the process finishes. This algorithm avoids 100% charge during the most of the days in order to prolong the battery life. In contrary, the Bulk-Absorption-Float charges the battery to 100% every day, keeps the voltage for couple of minutes and then discharges the excessive charge into the grid. If you prefer it, just set `OWN_CHARGE_PARAMETERS = False` and use the calculation of the SerialBattery.

Changes in V3.1:
- parameter `BATTERY_EFFICIENCY`, it is multiplied by charge fed into battery in order to minimize accumulation of SoC error if the batteries are not fully charged for longer period of time.
- `CHARGE_VOLTAGE_LIST` containing a target cell voltage for each month.
- `KEEP_MAX_CVL` parameter added, see explanation in settings.py

For better understanding whether the discharge to "Float" it useful or not please find and share some papers about LFP aging under constant voltage. Up to now I found such a document for LTO only (https://www.global.toshiba/content/dam/toshiba/ww/products-solutions/battery/scib/pdf/ToshibaRechargeableBattery-en.pdf or http://futuregrqd.cluster027.hosting.ovh.net/Download/Datasheet/Toshiba_LTO_2.4V_20Ah.pdf), see "Float characteristic".

If the battery is not balanced properly or the target voltage is set too high, one or more cell's voltages start to peak. To avoid emergency disconnecting of the battery by BMS, the dynamic CVL reduction is activated if at least one cell exceeds the `MAX_CELL_VOLTAGE`. To avoid instabilities of charger, the DC-coupled PV feed in (if initially enabled) will be disabled in order to enable the `CCL`. The `CCL` does not work if the DC-coupled PV feed-in is enabled, see: https://www.victronenergy.com.au/media/pg/Energy_Storage_System/en/configuration.html, chapter 4.3.4. When all cell voltages fall below `MAX_CELL_VOLTAGE` and the cell difference falls below `CELL_DIFF_MAX`, the DC-coupled PV feed in is enabled again (if was enabled before).

The charge or discharge current is set to zero if at least one BMS is blocking charge or discharge respectively. If charge is blocked, the DC-coupled PV feed-in (if initially enabled), will be disabled, see the reason above.
