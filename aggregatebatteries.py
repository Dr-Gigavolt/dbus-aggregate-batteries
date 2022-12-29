#!/usr/bin/env python3

"""
Service to aggregate multiple serial batteries https://github.com/Louisvdw/dbus-serialbattery
to one virtual battery.

Python location on Venus:
/usr/bin/python3.8
/usr/lib/python3.8/site-packages/

References:
https://dbus.freedesktop.org/doc/dbus-python/tutorial.html
https://github.com/victronenergy/venus/wiki/dbus
https://github.com/victronenergy/velib_python
"""

from gi.repository import GLib
import logging
import sys
import os
import dbus
from settings import *
import time as tt
from datetime import datetime as dt

sys.path.append('/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService, VeDbusItemImport

BULK = 0
ABSORPTION = 1
FLOAT = 2

class DbusAggBatService(object):
    
    def __init__(self, servicename='com.victronenergy.battery.aggregate'):
        self._batteries = []
        self._scanTrials = 0
        self._readTrials = 0
        self._chargeState = BULK
        self._absorptionFinished = False
        self._absorptionPauseFinished = True
        self._absorptionStartTime = 0
        self._absorptionStopTime = 0
        self._MaxChargeVoltage_old = 0
        self._MaxChargeCurrent_old = 0
        self._MaxDischargeCurrent_old = 0
        self._dbusservice = VeDbusService(servicename)
        self._dbusConn = dbus.SessionBus()  if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
        
         
        # Create the mandatory objects
        self._dbusservice.add_mandatory_paths(processname = __file__, processversion = '0.0', connection = 'Virtual',
			deviceinstance = 0, productid = 0, productname = 'AggregateBatteries', firmwareversion = '0.0', 
            hardwareversion = '0.0', connected = 1)

        # Create DC paths        
        self._dbusservice.add_path('/Dc/0/Voltage', None, writeable=True, gettextcallback=lambda a, x: "{:.1f}V".format(x))
        self._dbusservice.add_path('/Dc/0/Current', None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
        self._dbusservice.add_path('/Dc/0/Power', None, writeable=True, gettextcallback=lambda a, x: "{:.2f}kW".format(x/1000))
        
        # Create capacity paths
        self._dbusservice.add_path('/Soc', None, writeable=True)
        self._dbusservice.add_path('/Capacity', None, writeable=True, gettextcallback=lambda a, x: "{:.0f}Ah".format(x))
        self._dbusservice.add_path('/InstalledCapacity', None, gettextcallback=lambda a, x: "{:.0f}Ah".format(x))
        self._dbusservice.add_path('/ConsumedAmphours', None, gettextcallback=lambda a, x: "{:.0f}Ah".format(x))
        
        # Create temperature paths
        self._dbusservice.add_path('/Dc/0/Temperature', None, writeable=True)       
        self._dbusservice.add_path('/System/MinCellTemperature', None, writeable=True)
        #self._dbusservice.add_path('/System/MinTemperatureCellId', None, writeable=True)
        self._dbusservice.add_path('/System/MaxCellTemperature', None, writeable=True)
        #self._dbusservice.add_path('/System/MaxTemperatureCellId', None, writeable=True)       
        
        # Create extras paths
        self._dbusservice.add_path('/System/MinCellVoltage', None, writeable=True)
        self._dbusservice.add_path('/System/MinVoltageCellId', None, writeable=True)
        self._dbusservice.add_path('/System/MaxCellVoltage', None, writeable=True)
        self._dbusservice.add_path('/System/MaxVoltageCellId', None, writeable=True)
        self._dbusservice.add_path('/System/NrOfCellsPerBattery', None, writeable=True)
        self._dbusservice.add_path('/System/NrOfModulesOnline', None, writeable=True)
        self._dbusservice.add_path('/System/NrOfModulesOffline', None, writeable=True)
        self._dbusservice.add_path('/System/NrOfModulesBlockingCharge', None, writeable=True)
        self._dbusservice.add_path('/System/NrOfModulesBlockingDischarge', None, writeable=True)         
        
        # Create alarm paths
        self._dbusservice.add_path('/Alarms/LowVoltage', None, writeable=True)
        self._dbusservice.add_path('/Alarms/HighVoltage', None, writeable=True)
        self._dbusservice.add_path('/Alarms/LowCellVoltage', None, writeable=True)
        #self._dbusservice.add_path('/Alarms/HighCellVoltage', None, writeable=True)
        self._dbusservice.add_path('/Alarms/LowSoc', None, writeable=True)
        self._dbusservice.add_path('/Alarms/HighChargeCurrent', None, writeable=True)
        self._dbusservice.add_path('/Alarms/HighDischargeCurrent', None, writeable=True)
        self._dbusservice.add_path('/Alarms/CellImbalance', None, writeable=True)
        self._dbusservice.add_path('/Alarms/InternalFailure', None, writeable=True)
        self._dbusservice.add_path('/Alarms/HighChargeTemperature', None, writeable=True)
        self._dbusservice.add_path('/Alarms/LowChargeTemperature', None, writeable=True)
        self._dbusservice.add_path('/Alarms/HighTemperature', None, writeable=True)
        self._dbusservice.add_path('/Alarms/LowTemperature', None, writeable=True)
        
        # Create control paths
        self._dbusservice.add_path('/Info/MaxChargeCurrent', None, writeable=True, gettextcallback=lambda a, x: "{:.0f}A".format(x))
        self._dbusservice.add_path('/Info/MaxDischargeCurrent', None, writeable=True, gettextcallback=lambda a, x: "{:.0f}A".format(x))
        self._dbusservice.add_path('/Info/MaxChargeVoltage', None, writeable=True, gettextcallback=lambda a, x: "{:.1f}V".format(x))
        
        self._now = tt.time()
         
        GLib.timeout_add(1000, self._scan)  # search connected batteries
    
    
    ###########################
    # search physical batteries
    ###########################
    
    def _scan(self):
        self._batteries = []
        batteriesCount = 0
        logging.info('%s: Scan of batteries: Trial Nr. %d' % (dt.now(),(self._scanTrials + 1)))
        for service in self._dbusConn.list_names():
            if SERVICE_KEY_WORD in service:
                if PRODUCT_NAME_KEY_WORD in (VeDbusItemImport(self._dbusConn, service, '/ProductName').get_value()):
                    self._batteries.append(service)
                    batteriesCount += 1 
        logging.info('%s: %d batteries found.' % (dt.now(), batteriesCount))
        if batteriesCount == NR_OF_BATTERIES:
            GLib.timeout_add(1000, self._update)
            return False    # all OK, stop calling this function
        elif self._scanTrials < SCAN_TRIALS:
            self._scanTrials += 1
            return True     # next trial
        else:
            logging.error('%s: ERROR: Required number of batteries not found. Exiting.' % dt.now())
            sys.exit()
    
    #############################
    # exception safe max and min
    #############################
        
    def _max(self, x):
        try:
            return max(x)
        except:
            return None
       
    def _min(self, x):
        try:
            return min(x)
        except:
            return None

    #########################################    
    # aggregate values of physical batteries
    # calculate charging parameters 
    # update Dbus
    #########################################
    
    def _update(self):  
        
        # DC
        Voltage = 0
        Current = 0
        Power = 0
        
        # Capacity
        Soc = 0
        Capacity = 0
        InstalledCapacity = 0
        ConsumedAmphours = 0        
        
        # Temperature
        Temperature = 0
        MaxCellTemperature = []   # list, maxima of all physical batteries
        MinCellTemperature = []   # list, minima of all physical batteries
        
        # Extras
        MaxCellVoltage = {}   # dictionary {'ID' : MaxCellVoltage, ... } for all physical batteries
        MinCellVoltage = {}   # dictionary {'ID' : MinCellVoltage, ... } for all physical batteries        
        NrOfCellsPerBattery = []     # list, NRofCells of all physical batteries (shall be the same)
        NrOfModulesOnline = 0
        NrOfModulesOffline = 0
        NrOfModulesBlockingCharge = 0
        NrOfModulesBlockingDischarge = 0
        
        # Alarms
        LowVoltage_alarm = []       # lists to find maxima
        HighVoltage_alarm = []
        LowCellVoltage_alarm = []
        #HighCellVoltage_alarm = []
        LowSoc_alarm = []
        HighChargeCurrent_alarm = []
        HighDischargeCurrent_alarm = []
        CellImbalance_alarm = []
        InternalFailure_alarm = []
        HighChargeTemperature_alarm = []
        LowChargeTemperature_alarm = []
        HighTemperature_alarm = []
        LowTemperature_alarm = []

        try:
            for i in range(NR_OF_BATTERIES):
          
                # DC
                Voltage += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Voltage').get_value()                # sum for average voltage
                Current += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Current').get_value()                # sum of currents
                Power += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Power').get_value()                    # sum of powers
                
                # Capacity
                Soc += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Soc').get_value()                             # sum for average Soc
                Capacity += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Capacity').get_value()                   # sum of Ah capacities
                InstalledCapacity += VeDbusItemImport(self._dbusConn, self._batteries[i], '/InstalledCapacity').get_value() # sum of installed Ah capacities
                ConsumedAmphours += VeDbusItemImport(self._dbusConn, self._batteries[i], '/ConsumedAmphours').get_value()   # sum of consumed Ah capacities
                
                # Temperature
                Temperature += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Temperature').get_value()                   # sum for average temperature
                MaxCellTemperature.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MaxCellTemperature').get_value()) # append list of max. cell temperatures
                MinCellTemperature.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MinCellTemperature').get_value()) # append list of min. cell temperatures

                # Cell min/max voltage
                MaxCellVoltage['B%d_%s' % (i, VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MaxVoltageCellId').get_value())]\
                = VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MaxCellVoltage').get_value()                                        # append dictionary by the cell ID and its max. voltage
                MinCellVoltage['B%d_%s' % (i, VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MinVoltageCellId').get_value())]\
                = VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MinCellVoltage').get_value()                                        # append dictionary by the cell ID and its max. voltage
                    
                # Battery state
                NrOfCellsPerBattery.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/NrOfCellsPerBattery').get_value())                  # append list of nr. of cells                 
                NrOfModulesOnline += VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/NrOfModulesOnline').get_value()                         # sum of modules online
                NrOfModulesOffline += VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/NrOfModulesOffline').get_value()                       # sum of modules offline
                NrOfModulesBlockingCharge += VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/NrOfModulesBlockingCharge').get_value()         # sum of modules blocking charge
                NrOfModulesBlockingDischarge += VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/NrOfModulesBlockingDischarge').get_value()   # sum of modules blocking discharge
                
                # Alarms
                LowVoltage_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/LowVoltage').get_value())
                HighVoltage_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/HighVoltage').get_value())
                LowCellVoltage_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/LowCellVoltage').get_value())
                #HighCellVoltage_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/HighCellVoltage').get_value())  # not implemented in Venus
                LowSoc_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/LowSoc').get_value())
                HighChargeCurrent_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/HighChargeCurrent').get_value())
                HighDischargeCurrent_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/HighDischargeCurrent').get_value())
                CellImbalance_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/CellImbalance').get_value())
                InternalFailure_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/InternalFailure_alarm').get_value())
                HighChargeTemperature_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/HighChargeTemperature').get_value())
                LowChargeTemperature_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/LowChargeTemperature').get_value())
                HighTemperature_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/HighTemperature').get_value())
                LowTemperature_alarm.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/Alarms/LowTemperature').get_value())
               
        except:
            self._readTrials += 1
            logging.error('%s: ERROR: DBus Value Error. Read trial nr. %d' % (dt.now(), self._readTrials))
            if (self._readTrials > READ_TRIALS):
                logging.error('DBus read failed. Exiting.')
                sys.exit()
            else:
                return True         # next call allowed
        
        self._readTrials = 0
        
        # averaging
        Voltage = Voltage / NR_OF_BATTERIES
        Soc = Soc / NR_OF_BATTERIES
        Temperature = Temperature / NR_OF_BATTERIES
        
        # find max and min cell voltage (have ID)
        MaxVoltageCellId = max(MaxCellVoltage, key = MaxCellVoltage.get)
        MaxCellVoltage = MaxCellVoltage[MaxVoltageCellId]
        MinVoltageCellId = min(MinCellVoltage, key = MinCellVoltage.get)
        MinCellVoltage = MinCellVoltage[MinVoltageCellId]
        
        # find max and min cell temperature (have no ID)
        MaxCellTemp = self._max(MaxCellTemperature)
        MinCellTemp = self._min(MinCellTemperature)
        
        NrOfCellsPerBattery = NrOfCellsPerBattery[0]     #some check if all equal ???
        
        # find max in alarms
        LowVoltage_alarm = self._max(LowVoltage_alarm)
        HighVoltage_alarm = self._max(HighVoltage_alarm)
        LowCellVoltage_alarm = self._max(LowCellVoltage_alarm)
        #HighCellVoltage_alarm = self._max(HighCellVoltage_alarm)
        LowSoc_alarm = self._max(LowSoc_alarm)
        HighChargeCurrent_alarm = self._max(HighChargeCurrent_alarm)
        HighDischargeCurrent_alarm = self._max(HighDischargeCurrent_alarm)
        CellImbalance_alarm = self._max(CellImbalance_alarm)
        InternalFailure_alarm = self._max(InternalFailure_alarm)
        HighChargeTemperature_alarm = self._max(HighChargeTemperature_alarm)
        LowChargeTemperature_alarm = self._max(LowChargeTemperature_alarm)
        HighTemperature_alarm = self._max(HighTemperature_alarm)
        LowTemperature_alarm = self._max(LowTemperature_alarm)
        
        # manage charge voltage
        if self._chargeState == BULK:     
            MaxChargeVoltage = ABSORPTION_VOLTAGE * NrOfCellsPerBattery    
            if (MaxCellVoltage >= MAX_CELL_VOLTAGE) or (Voltage >= ABSORPTION_VOLTAGE * NrOfCellsPerBattery):                    
                if self._absorptionPauseFinished:
                    self._chargeState = ABSORPTION
                    self._absorptionStartTime = tt.time()
                    logging.info('%s: Starting absorption after bulk' % dt.now())
                else:
                    self._chargeState = FLOAT
                    logging.info('%s: Starting float after bulk' % dt.now())
                
        if self._chargeState == ABSORPTION:                     # not elif, if ABSORPTION set above, cann be as next processed here 
            if (MaxCellVoltage >= MAX_CELL_VOLTAGE):
                    MaxChargeVoltage = Voltage            # clamp the voltage to the current value if one cell goes too high
                    logging.info('%s: Max. cell voltage reached. Absorption voltage limited to %.2fV' % (dt.now(), Voltage))
            else:
                MaxChargeVoltage = (ABSORPTION_VOLTAGE * NrOfCellsPerBattery)
            if (Voltage < RE_BULK_VOLTAGE * NrOfCellsPerBattery):
                self._chargeState = BULK
            elif (tt.time() - self._absorptionStartTime) >= ABSORBTION_TIME_M * 60:
                self._absorptionFinished = True
                self._chargeState = FLOAT
                self._absorptionStopTime = tt.time()
                logging.info('%s: Starting float after absorption' % dt.now())
        
        if self._chargeState == FLOAT:                          # not elif, if FLOAT set above, cann be as next processed here 
            if (MaxCellVoltage >= MAX_CELL_VOLTAGE) and (FLOAT_VOLTAGE * NrOfCellsPerBattery > Voltage):
                    MaxChargeVoltage = Voltage    # clamp the voltage to the current value if one cell goes too high
                    logging.info('%s: Max. cell voltage reached. Nominal float voltage is too high. Absorption voltage limited to %.2fV' % (dt.now(), Voltage))
            else:
                MaxChargeVoltage = (FLOAT_VOLTAGE * NrOfCellsPerBattery)
                
        if (not self._absorptionPauseFinished) and ((tt.time() - absorptionStopTime) >= ABSORBTION_RESTART_H * 3600):
            self._absorptionPauseFinished = True
            logging.info('%s: Absorption pause finished.' % dt.now())

        
        # manage charge current
        if (MaxCellVoltage >= CV2):                             # CV2 > CV1
            MaxChargeCurrent = MAX_CHARGE_CURRENT_ABOVE_CV2
        
        elif (MaxCellVoltage >= CV1):
            MaxChargeCurrent = MAX_CHARGE_CURRENT_ABOVE_CV1    
        
        else:
            MaxChargeCurrent = MAX_CHARGE_CURRENT
        
        if (Voltage <= DISCHARGE_VOLTAGE * NrOfCellsPerBattery) or (MinCellVoltage <= MIN_CELL_VOLTAGE):
            MaxDischargeCurrent = 0
        else:
            MaxDischargeCurrent = MAX_DISCHARGE_CURRENT
        
        # write message if the max charging voltage or max. charging or discharging current changes
        if (MaxChargeVoltage != self._MaxChargeVoltage_old):
            logging.info('%s: Max. charging voltage: %.1fV'  % (dt.now(), MaxChargeVoltage))
            self._MaxChargeVoltage_old = MaxChargeVoltage           
        
        if (MaxChargeCurrent != self._MaxChargeCurrent_old):
            logging.info('%s: Max. charging current: %.1fA'  % (dt.now(), MaxChargeCurrent))
            self._MaxChargeCurrent_old = MaxChargeCurrent

        if (MaxDischargeCurrent != self._MaxDischargeCurrent_old):
            logging.info('%s: Max. dircharging current: %.1fA'  % (dt.now(), MaxDischargeCurrent))
            self._MaxDischargeCurrent_old = MaxDischargeCurrent        
               
        
        # send DC
        self._dbusservice['/Dc/0/Voltage'] = round(Voltage, 1)
        self._dbusservice['/Dc/0/Current'] = round(Current, 1)
        self._dbusservice['/Dc/0/Power'] = round(Power, 0)
        
        # send capacity
        self._dbusservice['/Soc'] = Soc
        self._dbusservice['/Capacity'] = Capacity
        self._dbusservice['/InstalledCapacity'] = InstalledCapacity
        self._dbusservice['/ConsumedAmphours'] = ConsumedAmphours
        
        # send temperature
        self._dbusservice['/Dc/0/Temperature'] = Temperature
        self._dbusservice['/System/MaxCellTemperature'] = MaxCellTemp
        self._dbusservice['/System/MinCellTemperature'] = MinCellTemp
        
        # send cell min/max voltage
        self._dbusservice['/System/MaxCellVoltage'] = MaxCellVoltage
        self._dbusservice['/System/MaxVoltageCellId'] = MaxVoltageCellId
        self._dbusservice['/System/MinCellVoltage'] = MinCellVoltage
        self._dbusservice['/System/MinVoltageCellId'] = MinVoltageCellId
        
        # send battery state
        self._dbusservice['/System/NrOfCellsPerBattery'] = NrOfCellsPerBattery
        self._dbusservice['/System/NrOfModulesOnline'] = NrOfModulesOnline
        self._dbusservice['/System/NrOfModulesOffline'] = NrOfModulesOffline
        self._dbusservice['/System/NrOfModulesBlockingCharge'] = NrOfModulesBlockingCharge
        self._dbusservice['/System/NrOfModulesBlockingDischarge'] = NrOfModulesBlockingDischarge
        
        # send alarms
        self._dbusservice['/Alarms/LowVoltage'] = LowVoltage_alarm
        self._dbusservice['/Alarms/HighVoltage'] = HighVoltage_alarm
        self._dbusservice['/Alarms/LowCellVoltage'] = LowCellVoltage_alarm
        #self._dbusservice['/Alarms/HighCellVoltage'] = HighCellVoltage_alarm   # not implemended in Venus
        self._dbusservice['/Alarms/LowSoc'] = LowSoc_alarm
        self._dbusservice['/Alarms/HighChargeCurrent'] = HighChargeCurrent_alarm
        self._dbusservice['/Alarms/HighDischargeCurrent'] = HighDischargeCurrent_alarm
        self._dbusservice['/Alarms/CellImbalance'] = CellImbalance_alarm
        self._dbusservice['/Alarms/InternalFailure'] = InternalFailure_alarm
        self._dbusservice['/Alarms/HighChargeTemperature'] = HighChargeTemperature_alarm
        self._dbusservice['/Alarms/LowChargeTemperature'] = LowChargeTemperature_alarm
        self._dbusservice['/Alarms/HighTemperature'] = HighChargeTemperature_alarm
        self._dbusservice['/Alarms/LowTemperature'] = LowChargeTemperature_alarm
        
        # send charge/discharge control
        self._dbusservice['/Info/MaxChargeCurrent'] = MaxChargeCurrent
        self._dbusservice['/Info/MaxDischargeCurrent'] = MaxDischargeCurrent
        self._dbusservice['/Info/MaxChargeVoltage'] = MaxChargeVoltage

        return True



def main():
    logging.basicConfig(filename = 'aggregatebatteries.log', level=logging.INFO)

    from dbus.mainloop.glib import DBusGMainLoop
    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    battery_output = DbusAggBatService()

    logging.info('%s: Connected to dbus, and switching over to GLib.MainLoop() (= event based)' % dt.now())
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
