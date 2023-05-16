#!/usr/bin/env python3
# Version 2.3

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
            
            '/Io/AllowToCharge': dummy,
            '/Io/AllowToDischarge': dummy,
            '/Io/AllowToBalance': dummy,
            
            '/Voltages/Cell1': dummy,
            '/Voltages/Cell2': dummy,
            '/Voltages/Cell3': dummy,
            '/Voltages/Cell4': dummy,
            '/Voltages/Cell5': dummy,
            '/Voltages/Cell6': dummy,
            '/Voltages/Cell7': dummy,
            '/Voltages/Cell8': dummy,
            '/Voltages/Cell9': dummy,
            '/Voltages/Cell10': dummy,
            '/Voltages/Cell11': dummy,
            '/Voltages/Cell12': dummy,
            '/Voltages/Cell13': dummy,
            '/Voltages/Cell14': dummy,
            '/Voltages/Cell15': dummy,
            '/Voltages/Cell16': dummy,
            '/Voltages/Cell17': dummy,
            '/Voltages/Cell18': dummy,
            '/Voltages/Cell19': dummy,
            '/Voltages/Cell20': dummy,
            '/Voltages/Cell21': dummy,
            '/Voltages/Cell22': dummy,
            '/Voltages/Cell23': dummy,
            '/Voltages/Cell24': dummy,
            '/Voltages/Cell25': dummy,
            '/Voltages/Cell26': dummy,
            '/Voltages/Cell27': dummy,
            '/Voltages/Cell28': dummy,
            '/Voltages/Cell29': dummy,
            '/Voltages/Cell30': dummy,
            '/Voltages/Cell31': dummy,
            '/Voltages/Cell32': dummy,
            '/Voltages/Diff': dummy,
            '/Voltages/Sum': dummy,
            
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