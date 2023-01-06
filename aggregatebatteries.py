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

VERSION = '1.0'

from gi.repository import GLib
import logging
import sys
import os
import dbus
from settings import *
from datetime import datetime as dt         # for UTC time stamps for logging
import time as tt                           # for charge measurement

sys.path.append('/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService, VeDbusItemImport

class DbusAggBatService(object):
    
    def __init__(self, servicename='com.victronenergy.battery.aggregate'):
        self._batteries = []
        self._multi = None
        self._mppts = []
        self._scanTrials = 0
        self._readTrials = 0
        self._MaxChargeVoltage_old = 0
        self._MaxChargeCurrent_old = 0
        self._MaxDischargeCurrent_old = 0
        self._dbusservice = VeDbusService(servicename)
        self._dbusConn = dbus.SessionBus()  if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
        self._timeOld = tt.time() 
        
        # read initial charge from text file
        try:
            self._charge_file = open('charge', 'r')      # read
            self._ownCharge = float(self._charge_file.readline().strip())
            self._charge_file.close()
            self._ownCharge_old = self._ownCharge
            logging.info('%s: Initial Ah read from file: %.0fAh' % (dt.now(), self._ownCharge))
        except Exception:
            logging.error('%s: Charge file read error. Exiting.' % dt.now())
            sys.exit()  
 
        # Create the mandatory objects
        self._dbusservice.add_mandatory_paths(processname = __file__, processversion = '0.0', connection = 'Virtual',
			deviceinstance = 0, productid = 0, productname = 'AggregateBatteries', firmwareversion = VERSION, 
            hardwareversion = '0.0', connected = 1)

        # Create DC paths        
        self._dbusservice.add_path('/Dc/0/Voltage', None, writeable=True, gettextcallback=lambda a, x: "{:.2f}V".format(x))
        self._dbusservice.add_path('/Dc/0/Current', None, writeable=True, gettextcallback=lambda a, x: "{:.1f}A".format(x))
        self._dbusservice.add_path('/Dc/0/Power', None, writeable=True, gettextcallback=lambda a, x: "{:.0f}W".format(x))
        
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
         
        GLib.timeout_add(1000, self._find_batteries)  # search connected batteries
    
    
    ###########################
    # search physical batteries
    ###########################
    
    def _find_batteries(self):
        self._batteries = []
        batteriesCount = 0
        logging.info('%s: Scan of batteries: Trial Nr. %d' % (dt.now(),(self._scanTrials + 1)))
        for service in self._dbusConn.list_names():
            if BATTERY_KEY_WORD in service:
                try:  
                    if BATTERY_NAME_KEY_WORD in (VeDbusItemImport(self._dbusConn, service, '/ProductName').get_value()):    # if data not ready (None) pass without increment, don't stop
                        self._batteries.append(service)
                        batteriesCount += 1
                        #logging.info('%s: %d batteries found.' % (dt.now(), batteriesCount))
                except Exception:
                    logging.error('%s: Exception when reading battery product name.' % dt.now())
                    pass
        logging.info('%s: %d batteries found.' % (dt.now(), batteriesCount))
        if batteriesCount == NR_OF_BATTERIES:
            if CURRENT_FROM_VICTRON:
                self._scanTrials = 0
                GLib.timeout_add(1000, self._find_multis)               # if current from Victron stuff search multi/quattro on DBus
            else:
                self._timeOld = tt.time()
                GLib.timeout_add(1000, self._update)                    # if current from BMS start the _update loop
            return False    # all OK, stop calling this function
        elif self._scanTrials < SCAN_TRIALS:
            self._scanTrials += 1
            return True     # next trial
        else:
            logging.error('%s: Required number of batteries not found. Exiting.' % dt.now())
            sys.exit()
    
    ########################################################
    # search Multis (if selected for DC current measurement)
    ########################################################
    
    def _find_multis(self):
        logging.info('%s: Searching Multi/Quatro VEbus: Trial Nr. %d' % (dt.now(),(self._scanTrials + 1)))
        for service in self._dbusConn.list_names():
            if MULTI_KEY_WORD in service:
                self._multi = service
                logging.info('%s: %s found.' % (dt.now(),(VeDbusItemImport(self._dbusConn, service, '/ProductName').get_value())))
        if (self._multi != None):        
            if (NR_OF_MPPTS > 0):
                GLib.timeout_add(1000, self._find_mppts)                # search MPPTs on DBus if present
            else:
                self._timeOld = tt.time()
                GLib.timeout_add(1000, self._update)                    # if no MPPTs start the _update loop
            return False    # all OK, stop calling this function
        elif self._scanTrials < SCAN_TRIALS:
            self._scanTrials += 1
            return True     # next trial
        else:
            logging.error('%s: Multi/Quattro not found. Exiting.' % dt.now())
            sys.exit()    
            
    #######################################################
    # search MPPTs (if selected for DC current measurement)
    #######################################################
    
    def _find_mppts(self):
        self._mppts = []
        mpptsCount = 0
        logging.info('%s: Searching of MPPTs: Trial Nr. %d' % (dt.now(),(self._scanTrials + 1)))
        for service in self._dbusConn.list_names():
            if MPPT_KEY_WORD in service:
                self._mppts.append(service)
                mpptsCount += 1
        logging.info('%s: %d MPPTs found.' % (dt.now(), mpptsCount))
        if mpptsCount == NR_OF_MPPTS:
            self._timeOld = tt.time()
            GLib.timeout_add(1000, self._update)
            return False    # all OK, stop calling this function
        elif self._scanTrials < SCAN_TRIALS:
            self._scanTrials += 1
            return True     # next trial
        else:
            logging.error('%s: Required number of MPPTss not found. Exiting.' % dt.now())
            sys.exit()
    
    #############################
    # exception safe max and min
    #############################
        
    def _max(self, x):
        try:
            return max(x)
        except Exception:
            return None
       
    def _min(self, x):
        try:
            return min(x)
        except Exception:
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
        MaxCellTemperature = []     # list, maxima of all physical batteries
        MinCellTemperature = []     # list, minima of all physical batteries
        
        # Extras
        MaxCellVoltage = {}         # dictionary {'ID' : MaxCellVoltage, ... } for all physical batteries
        MinCellVoltage = {}         # dictionary {'ID' : MinCellVoltage, ... } for all physical batteries        
        NrOfCellsPerBattery = []    # list, NRofCells of all physical batteries (shall be the same)
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
                Voltage += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Voltage').get_value()                                        # sum for average voltage
                Current += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Current').get_value()                                        # sum of currents
                Power += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Power').get_value()                                            # sum of powers
                
                # Capacity
                Soc += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Soc').get_value()                                                     # sum for average Soc
                Capacity += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Capacity').get_value()                                           # sum of Ah capacities
                InstalledCapacity += VeDbusItemImport(self._dbusConn, self._batteries[i], '/InstalledCapacity').get_value()                         # sum of installed Ah capacities
                ConsumedAmphours += VeDbusItemImport(self._dbusConn, self._batteries[i], '/ConsumedAmphours').get_value()                           # sum of consumed Ah capacities
                
                # Temperature
                Temperature += VeDbusItemImport(self._dbusConn, self._batteries[i], '/Dc/0/Temperature').get_value()                                # sum for average temperature
                MaxCellTemperature.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MaxCellTemperature').get_value())           # append list of max. cell temperatures
                MinCellTemperature.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MinCellTemperature').get_value())           # append list of min. cell temperatures

                # Cell min/max voltage
                MaxCellVoltage['B%d_%s' % (i, VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MaxVoltageCellId').get_value())]\
                = VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MaxCellVoltage').get_value()                                        # append dictionary by the cell ID and its max. voltage
                MinCellVoltage['B%d_%s' % (i, VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MinVoltageCellId').get_value())]\
                = VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/MinCellVoltage').get_value()                                        # append dictionary by the cell ID and its max. voltage
                    
                # Battery state
                NrOfCellsPerBattery.append(VeDbusItemImport(self._dbusConn, self._batteries[i], '/System/NrOfCellsPerBattery').get_value())                # append list of nr. of cells                 
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
               
        except Exception:
            self._readTrials += 1
            logging.error('%s: DBus Value Error. Read trial nr. %d' % (dt.now(), self._readTrials))
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
        
        NrOfCellsPerBattery = NrOfCellsPerBattery[0]                                # add here some check if all equal ???
        
        # find max in alarms
        LowVoltage_alarm = self._max(LowVoltage_alarm)
        HighVoltage_alarm = self._max(HighVoltage_alarm)
        LowCellVoltage_alarm = self._max(LowCellVoltage_alarm)
        #HighCellVoltage_alarm = self._max(HighCellVoltage_alarm)                   # not implemented in JK BMS
        LowSoc_alarm = self._max(LowSoc_alarm)
        HighChargeCurrent_alarm = self._max(HighChargeCurrent_alarm)
        HighDischargeCurrent_alarm = self._max(HighDischargeCurrent_alarm)
        CellImbalance_alarm = self._max(CellImbalance_alarm)
        InternalFailure_alarm = self._max(InternalFailure_alarm)
        HighChargeTemperature_alarm = self._max(HighChargeTemperature_alarm)
        LowChargeTemperature_alarm = self._max(LowChargeTemperature_alarm)
        HighTemperature_alarm = self._max(HighTemperature_alarm)
        LowTemperature_alarm = self._max(LowTemperature_alarm)
        
        if CURRENT_FROM_VICTRON:
            try:
                Current = VeDbusItemImport(self._dbusConn, self._multi, '/Dc/0/Current').get_value()                    # get DC current of multi/quattro (or system of them)
                for i in range(NR_OF_MPPTS):
                    Current += VeDbusItemImport(self._dbusConn, self._mppts[i], '/Dc/0/Current').get_value()            # add DC current of all MPPTs (if present)          
                    Power = Voltage * Current                                                                           # calculate own power (not read from BMS)
            except Exception:
                logging.error('%s: Victron current read error. Using BMS current and power instead.' % dt.now())        # the BMS values are not overwritten
                pass        
        
        # manage charge voltage       
        if MaxCellVoltage >= MAX_CELL_VOLTAGE:
            MaxChargeVoltage = Voltage - (MaxCellVoltage - MAX_CELL_VOLTAGE)         # clamp the voltage to the current value if one cell goes too high
            self._ownCharge = InstalledCapacity
        else:     
            MaxChargeVoltage = CHARGE_VOLTAGE * NrOfCellsPerBattery
       
        # manage charge current
        if (MaxCellVoltage >= MAX_CELL_VOLTAGE) or (NrOfModulesBlockingCharge > 0):                         
            MaxChargeCurrent = 0
        
        elif (MaxCellVoltage >= CV2):                               # CV2 > CV1               
            MaxChargeCurrent = MAX_CHARGE_CURRENT_ABOVE_CV2
        
        elif (MaxCellVoltage >= CV1):
            MaxChargeCurrent = MAX_CHARGE_CURRENT_ABOVE_CV1    
        
        else:
            MaxChargeCurrent = MAX_CHARGE_CURRENT
        
        if (Voltage <= DISCHARGE_VOLTAGE * NrOfCellsPerBattery) or (MinCellVoltage <= MIN_CELL_VOLTAGE) or (NrOfModulesBlockingDischarge > 0):
            MaxDischargeCurrent = 0
            self._ownCharge = 0
        else:
            MaxDischargeCurrent = MAX_DISCHARGE_CURRENT
        
        # write message if the max charging voltage or max. charging or discharging current changes
        if abs(MaxChargeVoltage - self._MaxChargeVoltage_old) >= 0.1:
            logging.info('%s: Max. charging voltage: %.1fV'  % (dt.now(), MaxChargeVoltage))
            self._MaxChargeVoltage_old = MaxChargeVoltage           
        
        if (MaxChargeCurrent != self._MaxChargeCurrent_old):
            logging.info('%s: Max. charging current: %.1fA'  % (dt.now(), MaxChargeCurrent))
            self._MaxChargeCurrent_old = MaxChargeCurrent

        if (MaxDischargeCurrent != self._MaxDischargeCurrent_old):
            logging.info('%s: Max. dircharging current: %.1fA'  % (dt.now(), MaxDischargeCurrent))
            self._MaxDischargeCurrent_old = MaxDischargeCurrent        
               
        # own Coulomb counter
        deltaTime = tt.time() - self._timeOld         
        self._timeOld = tt.time()
        self._ownCharge += Current * deltaTime / 3600
        self._ownCharge = max(self._ownCharge, 0) 
        self._ownCharge = min(self._ownCharge, InstalledCapacity)
        ownSoc = 100* self._ownCharge / InstalledCapacity
        
        # store the charge into text file if changed significantly (avoid frequent file access)
        if abs(self._ownCharge - self._ownCharge_old) >= (CHARGE_SAVE_PRECISION * InstalledCapacity):
            self._charge_file = open('charge', 'w')
            self._charge_file.write('%.3f' % self._ownCharge)
            self._charge_file.close()
            self._ownCharge_old = self._ownCharge
            #logging.info('%s: Saving own charge on exit' % dt.now())
   
        # overwrite BMS charge values
        if OWN_SOC:
            Capacity = self._ownCharge
            Soc = ownSoc
            ConsumedAmphours = InstalledCapacity - self._ownCharge
        
        #logging.info('%s: Sendind data' % dt.now())
        with self._dbusservice as bus:
        
            # send DC
            bus['/Dc/0/Voltage'] = round(Voltage, 1)
            bus['/Dc/0/Current'] = round(Current, 1)
            bus['/Dc/0/Power'] = round(Power, 0)
        
            # send capacity
            bus['/Soc'] = Soc
            bus['/Capacity'] = Capacity
            bus['/InstalledCapacity'] = InstalledCapacity
            bus['/ConsumedAmphours'] = ConsumedAmphours
        
            # send temperature
            bus['/Dc/0/Temperature'] = Temperature
            bus['/System/MaxCellTemperature'] = MaxCellTemp
            bus['/System/MinCellTemperature'] = MinCellTemp
        
            # send cell min/max voltage
            bus['/System/MaxCellVoltage'] = MaxCellVoltage
            bus['/System/MaxVoltageCellId'] = MaxVoltageCellId
            bus['/System/MinCellVoltage'] = MinCellVoltage
            bus['/System/MinVoltageCellId'] = MinVoltageCellId
        
            # send battery state
            bus['/System/NrOfCellsPerBattery'] = NrOfCellsPerBattery
            bus['/System/NrOfModulesOnline'] = NrOfModulesOnline
            bus['/System/NrOfModulesOffline'] = NrOfModulesOffline
            bus['/System/NrOfModulesBlockingCharge'] = NrOfModulesBlockingCharge
            bus['/System/NrOfModulesBlockingDischarge'] = NrOfModulesBlockingDischarge
        
            # send alarms
            bus['/Alarms/LowVoltage'] = LowVoltage_alarm
            bus['/Alarms/HighVoltage'] = HighVoltage_alarm
            bus['/Alarms/LowCellVoltage'] = LowCellVoltage_alarm
            #bus['/Alarms/HighCellVoltage'] = HighCellVoltage_alarm   # not implemended in Venus
            bus['/Alarms/LowSoc'] = LowSoc_alarm
            bus['/Alarms/HighChargeCurrent'] = HighChargeCurrent_alarm
            bus['/Alarms/HighDischargeCurrent'] = HighDischargeCurrent_alarm
            bus['/Alarms/CellImbalance'] = CellImbalance_alarm
            bus['/Alarms/InternalFailure'] = InternalFailure_alarm
            bus['/Alarms/HighChargeTemperature'] = HighChargeTemperature_alarm
            bus['/Alarms/LowChargeTemperature'] = LowChargeTemperature_alarm
            bus['/Alarms/HighTemperature'] = HighChargeTemperature_alarm
            bus['/Alarms/LowTemperature'] = LowChargeTemperature_alarm
        
            # send charge/discharge control
            bus['/Info/MaxChargeCurrent'] = MaxChargeCurrent
            bus['/Info/MaxDischargeCurrent'] = MaxDischargeCurrent
            bus['/Info/MaxChargeVoltage'] = MaxChargeVoltage

        return True
    
def main():
    logging.basicConfig(filename = 'aggregatebatteries.log', level=logging.INFO)

    from dbus.mainloop.glib import DBusGMainLoop
    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)
    DbusAggBatService()
    logging.info('%s: Connected to dbus, and switching over to GLib.MainLoop() (= event based)' % dt.now())
    mainloop = GLib.MainLoop()
    mainloop.run()

if __name__ == "__main__":
    main()

