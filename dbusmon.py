#!/usr/bin/env python3
# Version 2.0

import sys
sys.path.append('/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from dbusmonitor import DbusMonitor
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import logging

class DbusMon:
    def __init__(self):
        dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
        self.monitorlist = {'com.victronenergy.battery': {
			'/Connected': dummy,
			'/ProductName': dummy,
            '/CustomName': dummy,
			'/Mgmt/Connection': dummy,
            '/DeviceInstance': dummy,
            
			'/Dc/0/Voltage': dummy,
			'/Dc/0/Current': dummy,
            '/Dc/0/Power': dummy,
            
            '/InstalledCapacity': dummy,
            '/ConsumedAmphours': dummy,
            '/Capacity': dummy,
            '/Soc': dummy,

			'/Dc/0/Temperature': dummy,
            '/System/MaxCellTemperature': dummy,
            '/System/MinCellTemperature': dummy,
            
            '/System/MaxVoltageCellId': dummy,
            '/System/MaxCellVoltage': dummy,
            '/System/MinVoltageCellId': dummy,
            '/System/MinCellVoltage': dummy,
            
            '/System/NrOfCellsPerBattery': dummy,
            '/System/NrOfModulesOnline': dummy,
            '/System/NrOfModulesOffline': dummy,
            '/System/NrOfModulesBlockingCharge': dummy,
            '/System/NrOfModulesBlockingDischarge': dummy,
            
            '/Alarms/LowVoltage': dummy,
            '/Alarms/HighVoltage': dummy,
            '/Alarms/LowCellVoltage': dummy,
            '/Alarms/HighCellVoltage': dummy,
            '/Alarms/LowSoc': dummy,
            '/Alarms/HighChargeCurrent': dummy,
            '/Alarms/HighDischargeCurrent': dummy,
            '/Alarms/CellImbalance': dummy,
            '/Alarms/InternalFailure_alarm': dummy,
            '/Alarms/HighChargeTemperature': dummy,
            '/Alarms/LowChargeTemperature': dummy,
            '/Alarms/HighTemperature': dummy,
            '/Alarms/LowTemperature': dummy,
            
			'/Info/MaxChargeCurrent': dummy,
            '/Info/MaxDischargeCurrent': dummy,
			'/Info/MaxChargeVoltage': dummy},
            
            'com.victronenergy.vebus': {
            '/Dc/0/Current': dummy,
            '/ProductName': dummy},
            
            'com.victronenergy.solarcharger': {
            '/Dc/0/Current': dummy,
            '/ProductName': dummy}
            }
        
        self.dbusmon = DbusMonitor(self.monitorlist)    

    def print_values(self, service):
        for path in self.monitorlist['com.victronenergy.battery']:
            logging.info('%s: %s' % (path, self.dbusmon.get_value(service, path)))
        logging.info('\n')
        return True
        

################        
# test program #
################

def main():
    logging.basicConfig(level=logging.INFO)
    DBusGMainLoop(set_as_default=True)
    batterymonitor = BatteryMonitor()
    
    #GLib.timeout_add(1000, batterymonitor.print_values, 'com.victronenergy.battery.ttyUSB2')
    batterymonitor.print_values('com.victronenergy.vebus.ttyUSB0')
    batterymonitor.print_values('com.victronenergy.solarcharger.ttyUSB1')
    
    # Start and run the mainloop
    logging.info("Battery monitor: Starting mainloop.\n")
    mainloop = GLib.MainLoop()
    mainloop.run()

if __name__ == "__main__":
	main()