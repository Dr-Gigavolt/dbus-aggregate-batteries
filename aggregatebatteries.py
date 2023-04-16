#!/usr/bin/env python3

"""
Service to aggregate multiple serial batteries https://github.com/Louisvdw/dbus-serialbattery
to one virtual battery.

Python location on Venus:
/usr/bin/python3.CHARGE_VOLTAGE * NrOfCellsPerBatteryCHARGE_VOLTAGE * NrOfCellsPerBattery
/usr/lib/python3.8/site-packages/

References:
https://dbus.freedesktop.org/doc/dbus-python/tutorial.html
https://github.com/victronenergy/venus/wiki/dbus
https://github.com/victronenergy/velib_python
"""

VERSION = '2.3'

from gi.repository import GLib
import logging
import sys
import os
import dbus
from settings import *
from functions import *
from datetime import datetime as dt         # for UTC time stamps for logging
import time as tt                           # for charge measurement
from dbusmon import DbusMon
from threading import Thread

sys.path.append('/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService

class DbusAggBatService(object):
    
    def __init__(self, servicename='com.victronenergy.battery.aggregate'):
        self._fn = Functions()
        self._batteries = []
        self._multi = None
        self._mppts = []
        self._smartShunt = None
        self._searchTrials = 0
        self._readTrials = 0
        self._MaxChargeVoltage_old = 0
        self._MaxChargeCurrent_old = 0
        self._MaxDischargeCurrent_old = 0
        self._dbusservice = VeDbusService(servicename)
        self._dbusConn = dbus.SessionBus()  if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else dbus.SystemBus()
        self._timeOld = tt.time() 
        
        # read initial charge from text file
        try:
            self._charge_file = open('/data/dbus-aggregate-batteries/charge', 'r')      # read
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
        self._dbusservice.add_path('/Voltages/Sum', None, writeable=True, gettextcallback=lambda a, x: "{:.3f}V".format(x))
        self._dbusservice.add_path('/Voltages/Diff', None, writeable=True, gettextcallback=lambda a, x: "{:.3f}V".format(x)) # do do
        
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
        self._dbusservice.add_path('/Info/MaxChargeVoltage', None, writeable=True, gettextcallback=lambda a, x: "{:.3f}V".format(x))
        self._dbusservice.add_path('/Io/AllowToCharge', None, writeable=True)
        self._dbusservice.add_path('/Io/AllowToDischarge', None, writeable=True)

        x = Thread(target = self._startMonitor)
        x.start()   
    
        GLib.timeout_add(5000, self._find_batteries)  # search connected batteries

    ##############################################################################################################
    ##############################################################################################################
    ### Starting battery dbus monitor in external thread (otherwise collision with AggregateBatteries service) ###
    ##############################################################################################################
    ##############################################################################################################
    
    def _startMonitor(self):
        logging.info('%s: Starting battery monitor.' % dt.now())
        self._dbusMon = DbusMon()

    #####################################################################
    #####################################################################
    ### search physical batteries and optional SmartShunt on DC loads ###
    #####################################################################
    #####################################################################
    
    def _find_batteries(self):
        self._batteries = []
        batteriesCount = 0
        productName = ''
        logging.info('%s: Searching batteries: Trial Nr. %d' % (dt.now(),(self._searchTrials + 1)))
        
        try:                                                            # if Dbus monitor not running yet, new trial instead of exception
            for service in self._dbusConn.list_names():
                if BATTERY_KEY_WORD in service:
                    productName = self._dbusMon.dbusmon.get_value(service, '/ProductName')
                    if BATTERY_NAME_KEY_WORD in productName:    
                        self._batteries.append(service)
                        logging.info('%s: %s found.' % (dt.now(),(self._dbusMon.dbusmon.get_value(service, '/ProductName'))))
                        batteriesCount += 1
                    elif SMARTSHUNT_NAME_KEY_WORD in productName:           # if SmartShunt found, can be used for DC load current
                        self._smartShunt = service
                    
        except Exception:
            pass
        logging.info('%s: %d batteries found.' % (dt.now(), batteriesCount))
        
        if batteriesCount == NR_OF_BATTERIES:
            if CURRENT_FROM_VICTRON:
                self._searchTrials = 0
                GLib.timeout_add(1000, self._find_multis)               # if current from Victron stuff search multi/quattro on DBus
            else:
                self._timeOld = tt.time()
                GLib.timeout_add(1000, self._update)                    # if current from BMS start the _update loop
            return False                                                # all OK, stop calling this function
        elif self._searchTrials < SEARCH_TRIALS:
            self._searchTrials += 1
            return True                                                 # next trial
        else:
            logging.error('%s: Required number of batteries not found. Exiting.' % dt.now())
            sys.exit()
    
    ##########################################################################
    ##########################################################################
    ### search Multis or Quattros (if selected for DC current measurement) ###
    ##########################################################################
    ##########################################################################
    
    def _find_multis(self):
        logging.info('%s: Searching Multi/Quatro VEbus: Trial Nr. %d' % (dt.now(),(self._searchTrials + 1)))
        try:
            for service in self._dbusConn.list_names():
                if MULTI_KEY_WORD in service:
                    self._multi = service
                    logging.info('%s: %s found.' % (dt.now(),(self._dbusMon.dbusmon.get_value(service, '/ProductName'))))
        except Exception:
            pass
            
        if (self._multi != None):        
            if (NR_OF_MPPTS > 0):
                GLib.timeout_add(1000, self._find_mppts)                # search MPPTs on DBus if present
            else:
                self._timeOld = tt.time()
                GLib.timeout_add(1000, self._update)                    # if no MPPTs start the _update loop
            return False                                                # all OK, stop calling this function
        elif self._searchTrials < SEARCH_TRIALS:
            self._searchTrials += 1
            return True                                                 # next trial
        else:
            logging.error('%s: Multi/Quattro not found. Exiting.' % dt.now())
            sys.exit()    
            
    #############################################################
    #############################################################
    ### search MPPTs (if selected for DC current measurement) ###
    #############################################################
    #############################################################
    
    def _find_mppts(self):
        self._mppts = []
        mpptsCount = 0
        logging.info('%s: Searching MPPTs: Trial Nr. %d' % (dt.now(),(self._searchTrials + 1)))
        try:
            for service in self._dbusConn.list_names():
                if MPPT_KEY_WORD in service:
                    self._mppts.append(service)
                    logging.info('%s: %s found.' % (dt.now(),(self._dbusMon.dbusmon.get_value(service, '/ProductName'))))
                    mpptsCount += 1
        except Exception:
            pass
            
        logging.info('%s: %d MPPT(s) found.' % (dt.now(), mpptsCount))
        if mpptsCount == NR_OF_MPPTS:
            self._timeOld = tt.time()
            GLib.timeout_add(1000, self._update)
            return False                                                    # all OK, stop calling this function
        elif self._searchTrials < SEARCH_TRIALS:
            self._searchTrials += 1
            return True                                                     # next trial
        else:
            logging.error('%s: Required number of MPPTs not found. Exiting.' % dt.now())
            sys.exit()

    ##################################################################################
    ##################################################################################     
    #### aggregate values of physical batteries, perform calculations, update Dbus ###
    ################################################################################## 
    ################################################################################## 
    
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
        MaxCellTemperature = []         # list, maxima of all physical batteries
        MinCellTemperature = []         # list, minima of all physical batteries
        
        # Extras
        MaxCellVoltage = {}             # dictionary {'ID' : MaxCellVoltage, ... } for all physical batteries
        MinCellVoltage = {}             # dictionary {'ID' : MinCellVoltage, ... } for all physical batteries        
        NrOfCellsPerBattery = []        # list, NRofCells of all physical batteries (shall be the same)
        NrOfModulesOnline = 0
        NrOfModulesOffline = 0
        NrOfModulesBlockingCharge = 0
        NrOfModulesBlockingDischarge = 0
        VoltagesSum = []                # battery voltages from sum of cells
        
        # Alarms
        LowVoltage_alarm = []           # lists to find maxima
        HighVoltage_alarm = []
        LowCellVoltage_alarm = []
        #HighCellVoltage_alarm = []     # not available in JK BMS
        LowSoc_alarm = []
        HighChargeCurrent_alarm = []
        HighDischargeCurrent_alarm = []
        CellImbalance_alarm = []
        InternalFailure_alarm = []
        HighChargeTemperature_alarm = []
        LowChargeTemperature_alarm = []
        HighTemperature_alarm = []
        LowTemperature_alarm = []
        BatteryName = ''
        cellVoltages = {}
        chargeVoltageReduced = []
        
        # Charge/discharge parameters
        MaxChargeCurrent = []           # the minimum of MaxChargeCurrent * NR_OF_BATTERIES to be transmitted
        MaxDischargeCurrent = []        # the minimum of MaxDischargeCurrent * NR_OF_BATTERIES to be transmitted
        MaxChargeVoltage = []           # if some cells are above MAX_CELL_VOLTAGE, store here the sum of differences for each battery
        AllowToCharge = []			    # minimum of all to be transmitted
        AllowToDischarge = []		    # minimum of all to be transmitted

        ####################################################
        # Get DBus values from all SerialBattery instances #
        ####################################################
        
        #logging.info('%s: Starting read SerialBatteries' % dt.now())
        try:
            for i in range(NR_OF_BATTERIES):
                # Custom name, if exists
                try:
                    BatteryName = self._dbusMon.dbusmon.get_value(self._batteries[i], BATTERY_NAME_PATH)
                except Exception:
                    BatteryName = 'Battery%d' % (i + 1)    
                
                # DC                                               
                Voltage += self._dbusMon.dbusmon.get_value(self._batteries[i], '/Dc/0/Voltage')                                                      # sum for average voltage                                      
                Current += self._dbusMon.dbusmon.get_value(self._batteries[i], '/Dc/0/Current')                                                  # sum of currents                                              
                Power += self._dbusMon.dbusmon.get_value(self._batteries[i], '/Dc/0/Power')                                                      # sum of powers
                
                # Capacity                                               
                InstalledCapacity += self._dbusMon.dbusmon.get_value(self._batteries[i], '/InstalledCapacity')                                       # sum of installed Ah capacities
                if not OWN_SOC:                                                                                                                      # only if needed
                    ConsumedAmphours += self._dbusMon.dbusmon.get_value(self._batteries[i], '/ConsumedAmphours')                                     # sum of consumed Ah capacities
                    Capacity += self._dbusMon.dbusmon.get_value(self._batteries[i], '/Capacity')                                                     # sum of Ah capacities
                    Soc += self._dbusMon.dbusmon.get_value(self._batteries[i], '/Soc') * self._dbusMon.dbusmon.get_value(self._batteries[i], '/Capacity') # weight sum for average Soc
                
                # Temperature
                Temperature += self._dbusMon.dbusmon.get_value(self._batteries[i], '/Dc/0/Temperature')                                              # sum for average temperature
                MaxCellTemperature.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/MaxCellTemperature'))                         # append list of max. cell temperatures
                MinCellTemperature.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/MinCellTemperature'))                         # append list of min. cell temperatures

                # Cell voltages
                MaxCellVoltage['%s_%s' % (BatteryName, self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/MaxVoltageCellId'))]\
                = self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/MaxCellVoltage')                                                      # append dictionary by the cell ID and its max. voltage
                MinCellVoltage['%s_%s' % (BatteryName, self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/MinVoltageCellId'))]\
                = self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/MinCellVoltage')                                                      # append dictionary by the cell ID and its max. voltage
                VoltagesSum.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Voltages/Sum'))                                             
                
                    
                # Battery state
                NrOfCellsPerBattery.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/NrOfCellsPerBattery'))                       # append list of nr. of cells, to do: put outside of _update()                 
                NrOfModulesOnline += self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/NrOfModulesOnline')                                # sum of modules online
                NrOfModulesOffline += self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/NrOfModulesOffline')                              # sum of modules offline
                NrOfModulesBlockingCharge += self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/NrOfModulesBlockingCharge')                # sum of modules blocking charge
                NrOfModulesBlockingDischarge += self._dbusMon.dbusmon.get_value(self._batteries[i], '/System/NrOfModulesBlockingDischarge')          # sum of modules blocking discharge
                
                for j in range (NrOfCellsPerBattery[i]):                                                                                             # make dictionary of all cell voltages        
                    cellVoltages['%s_Cell%d' % (BatteryName, j+1)] = self._dbusMon.dbusmon.get_value(self._batteries[i], '/Voltages/Cell%d' % (j+1))                        
                    # to do: send to Dbus
                
                # Alarms
                LowVoltage_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/LowVoltage'))
                HighVoltage_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/HighVoltage'))
                LowCellVoltage_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/LowCellVoltage'))
                #HighCellVoltage_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/HighCellVoltage'))                        # not implemented in Venus
                LowSoc_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/LowSoc'))
                HighChargeCurrent_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/HighChargeCurrent'))
                HighDischargeCurrent_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/HighDischargeCurrent'))
                CellImbalance_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/CellImbalance'))
                InternalFailure_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/InternalFailure_alarm'))
                HighChargeTemperature_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/HighChargeTemperature'))
                LowChargeTemperature_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/LowChargeTemperature'))
                HighTemperature_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/HighTemperature'))
                LowTemperature_alarm.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Alarms/LowTemperature'))
                
                if OWN_CHARGE_PARAMETERS:    # calculate reduction of charge voltage as sum of overvoltages of all cells
                    cellOvervoltage = 0
                    for j in range (NrOfCellsPerBattery[i]):
                        cellVoltage = self._dbusMon.dbusmon.get_value(self._batteries[i], '/Voltages/Cell%d' % (j+1))
                        if (cellVoltage > MAX_CELL_VOLTAGE):
                            cellOvervoltage += (cellVoltage - MAX_CELL_VOLTAGE)   
                    chargeVoltageReduced.append(VoltagesSum[i] - cellOvervoltage) 
                
                else:    # Aggregate charge/discharge parameters
                    MaxChargeCurrent.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Info/MaxChargeCurrent'))                # list of max. charge currents to find minimum
                    MaxDischargeCurrent.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Info/MaxDischargeCurrent'))          # list of max. discharge currents  to find minimum
                    MaxChargeVoltage.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Info/MaxChargeVoltage'))                # list of max. charge voltages  to find minimum
                    
                AllowToCharge.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Io/AllowToCharge'))					          # list of AllowToCharge to find minimum
                AllowToDischarge.append(self._dbusMon.dbusmon.get_value(self._batteries[i], '/Io/AllowToDischarge'))                      # list of AllowToDischarge to find minimum  
        
            # find max and min cell voltage (have ID)
            # placed in try-except structure for the case if some values are of None. The _max() and _min() don't work with dictionaries
            MaxVoltageCellId = max(MaxCellVoltage, key = MaxCellVoltage.get)
            MaxCellVoltage = MaxCellVoltage[MaxVoltageCellId]
            MinVoltageCellId = min(MinCellVoltage, key = MinCellVoltage.get)
            MinCellVoltage = MinCellVoltage[MinVoltageCellId]
        
        except Exception as err:
            self._readTrials += 1
            logging.error('%s: Error: %s. Read trial nr. %d' % (dt.now(), err, self._readTrials))
            if (self._readTrials > READ_TRIALS):
                logging.error('%s: DBus read failed. Exiting.'  % dt.now())
                sys.exit()
            else:
                return True         # next call allowed
        
        self._readTrials = 0        # must be reset after try-except
        
        #####################################################
        # Process collected values (except of dictionaries) #
        #####################################################
        
        # averaging
        Voltage = Voltage / NR_OF_BATTERIES
        Temperature = Temperature / NR_OF_BATTERIES
        VoltagesSum = sum(VoltagesSum) / NR_OF_BATTERIES
        
        if not OWN_SOC:                                                             # only if needed
            Soc = Soc / (NR_OF_BATTERIES * Capacity)
        
        # find max and min cell temperature (have no ID)
        MaxCellTemp = self._fn._max(MaxCellTemperature)
        MinCellTemp = self._fn._min(MinCellTemperature)
        
        if self._fn._max(NrOfCellsPerBattery) == self._fn._min(NrOfCellsPerBattery):        # Nr. of cells must be equal; to do: put outside of _update()
            NrOfCellsPerBattery = NrOfCellsPerBattery[0]
        else:
            logging.error('%s: Number of cells of batteries is not equal. Exiting.'  % dt.now())
            sys.exit()
        
        # find max in alarms
        LowVoltage_alarm = self._fn._max(LowVoltage_alarm)
        HighVoltage_alarm = self._fn._max(HighVoltage_alarm)
        LowCellVoltage_alarm = self._fn._max(LowCellVoltage_alarm)
        #HighCellVoltage_alarm = self._fn._max(HighCellVoltage_alarm)                   # not implemented in JK BMS
        LowSoc_alarm = self._fn._max(LowSoc_alarm)
        HighChargeCurrent_alarm = self._fn._max(HighChargeCurrent_alarm)
        HighDischargeCurrent_alarm = self._fn._max(HighDischargeCurrent_alarm)
        CellImbalance_alarm = self._fn._max(CellImbalance_alarm)
        InternalFailure_alarm = self._fn._max(InternalFailure_alarm)
        HighChargeTemperature_alarm = self._fn._max(HighChargeTemperature_alarm)
        LowChargeTemperature_alarm = self._fn._max(LowChargeTemperature_alarm)
        HighTemperature_alarm = self._fn._max(HighTemperature_alarm)
        LowTemperature_alarm = self._fn._max(LowTemperature_alarm)
        
        # find max. charge voltage (if needed)
        if not OWN_CHARGE_PARAMETERS:
            MaxChargeVoltage = self._fn._min(MaxChargeVoltage)
            MaxChargeCurrent = self._fn._min(MaxChargeCurrent) * NR_OF_BATTERIES
            MaxDischargeCurrent = self._fn._min(MaxDischargeCurrent) * NR_OF_BATTERIES
        
        AllowToCharge = self._fn._min(AllowToCharge)
        AllowToDischarge = self._fn._min(AllowToDischarge)
        
        ####################################
        # Measure current by Victron stuff #
        ####################################
        
        if CURRENT_FROM_VICTRON:
            try:
                Current_VE = self._dbusMon.dbusmon.get_value(self._multi, '/Dc/0/Current')                          # get DC current of multi/quattro (or system of them)
                for i in range(NR_OF_MPPTS):
                    Current_VE += self._dbusMon.dbusmon.get_value(self._mppts[i], '/Dc/0/Current')                  # add DC current of all MPPTs (if present)          
                
                if DC_LOADS:
                    if INVERT_SMARTSHUNT:
                        Current_VE += self._dbusMon.dbusmon.get_value(self._smartShunt, '/Dc/0/Current')            # SmartShunt is monitored as a battery
                    else:
                        Current_VE -= self._dbusMon.dbusmon.get_value(self._smartShunt, '/Dc/0/Current')
                                                                                                       
                if Current_VE is not None:
                    Current = Current_VE                                                                            # BMS current overwritten only if no exception raised
                    Power = Voltage * Current_VE                                                                    # calculate own power (not read from BMS)
                else:
                    logging.error('%s: Victron current is None. Using BMS current and power instead.' % dt.now())   # the BMS values are not overwritten    
            
            except Exception:
                logging.error('%s: Victron current read error. Using BMS current and power instead.' % dt.now())    # the BMS values are not overwritten       
        
        ####################################################################################################
        # Calculate own charge/discharge parameters (overwrite the values received from the SerialBattery) #
        ####################################################################################################
        
        if OWN_CHARGE_PARAMETERS:                                                           
            
            # manage charge voltage       
            ChargeVoltageBattery = CHARGE_VOLTAGE * NrOfCellsPerBattery
            if (Voltage >= ChargeVoltageBattery):
                self._ownCharge = InstalledCapacity                                                                     # reset Coulumb counter to 100%
            if MaxCellVoltage >= MAX_CELL_VOLTAGE:                         
                MaxChargeVoltage = min((min(chargeVoltageReduced)-VOLTAGE_SET_PRECISION), ChargeVoltageBattery)         # avoid exceeding MAX_CELL_VOLTAGE, take the charger innacuracy into account
                self._ownCharge = InstalledCapacity                                                                     # reset Coulumb counter to 100%
            else:     
                MaxChargeVoltage = ChargeVoltageBattery
                
            if (Voltage <= DISCHARGE_VOLTAGE * NrOfCellsPerBattery) or (MinCellVoltage <= MIN_CELL_VOLTAGE):
                self._ownCharge = 0                                                         # reset Coulumb counter to 0%     
                 
       
            # manage charge current
            if NrOfModulesBlockingCharge > 0:
                MaxChargeCurrent = 0
            else:
                MaxChargeCurrent = MAX_CHARGE_CURRENT * self._fn._interpolate(CELL_FULL_LIMITING_VOLTAGE, CELL_FULL_LIMITED_CURRENT, MaxCellVoltage)

            # manage discharge current
            if NrOfModulesBlockingDischarge > 0:
                MaxDischargeCurrent = 0
            else:
                MaxDischargeCurrent = MAX_DISCHARGE_CURRENT * self._fn._interpolate(CELL_EMPTY_LIMITING_VOLTAGE, CELL_EMPTY_LIMITED_CURRENT, MinCellVoltage)
        
        # write message if the max charging voltage or max. charging or discharging current changes
        if abs(MaxChargeVoltage - self._MaxChargeVoltage_old) >= LOG_VOLTAGE_CHANGE:
            logging.info('%s: Max. charging voltage: %.1fV; Max. cell voltage: %.3fV'  % (dt.now(), MaxChargeVoltage, MaxCellVoltage))
            self._MaxChargeVoltage_old = MaxChargeVoltage           
        
        if abs(MaxChargeCurrent - self._MaxChargeCurrent_old) >= LOG_CURRENT_CHANGE:
            logging.info('%s: Max. charging current: %.1fA; Max. cell voltage: %.3fV'  % (dt.now(), MaxChargeCurrent, MaxCellVoltage))
            self._MaxChargeCurrent_old = MaxChargeCurrent

        if abs(MaxDischargeCurrent - self._MaxDischargeCurrent_old) >= LOG_CURRENT_CHANGE:
            logging.info('%s: Max. dircharging current: %.1fA; Min. cell voltage: %.3fV'  % (dt.now(), MaxDischargeCurrent, MinCellVoltage))
            self._MaxDischargeCurrent_old = MaxDischargeCurrent        
               
        ###########################################################
        # own Coulomb counter (runs even the BMS values are used) #
        ###########################################################
        
        deltaTime = tt.time() - self._timeOld         
        self._timeOld = tt.time()
        self._ownCharge += Current * deltaTime / 3600
        self._ownCharge = max(self._ownCharge, 0) 
        self._ownCharge = min(self._ownCharge, InstalledCapacity)
        ownSoc = 100* self._ownCharge / InstalledCapacity
        
        # store the charge into text file if changed significantly (avoid frequent file access)
        if abs(self._ownCharge - self._ownCharge_old) >= (CHARGE_SAVE_PRECISION * InstalledCapacity):
            self._charge_file = open('/data/dbus-aggregate-batteries/charge', 'w')
            self._charge_file.write('%.3f' % self._ownCharge)
            self._charge_file.close()
            self._ownCharge_old = self._ownCharge
   
        # overwrite BMS charge values
        if OWN_SOC:
            Capacity = self._ownCharge
            Soc = ownSoc
            ConsumedAmphours = InstalledCapacity - self._ownCharge
        
        #######################
        # Send values to DBus #
        #######################

        with self._dbusservice as bus:

            # send DC
            bus['/Dc/0/Voltage'] = round(Voltage, 2)
            bus['/Dc/0/Current'] = round(Current, 1)
            bus['/Dc/0/Power'] = round(Power, 0)
        
            # send charge
            bus['/Soc'] = Soc
            bus['/Capacity'] = Capacity
            bus['/InstalledCapacity'] = InstalledCapacity
            bus['/ConsumedAmphours'] = ConsumedAmphours
        
            # send temperature
            bus['/Dc/0/Temperature'] = Temperature
            bus['/System/MaxCellTemperature'] = MaxCellTemp
            bus['/System/MinCellTemperature'] = MinCellTemp
        
            # send cell voltages
            bus['/System/MaxCellVoltage'] = MaxCellVoltage
            bus['/System/MaxVoltageCellId'] = MaxVoltageCellId
            bus['/System/MinCellVoltage'] = MinCellVoltage
            bus['/System/MinVoltageCellId'] = MinVoltageCellId
            bus['/Voltages/Sum']= VoltagesSum
            bus['/Voltages/Diff']= MaxCellVoltage - MinCellVoltage
            
            # to do: move the battery names detection outside of _update() function to execute only once
            # and create paths dynamically: '/Voltages/%s_Cell%d' % (BatteryName, cellID)
            #    bus['/Voltages/%s' % cellName] = cellVoltages[cellName]
        
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
            
            # this does not control the charger, is only displayed in GUI
            bus['/Io/AllowToCharge'] = AllowToCharge
            bus['/Io/AllowToDischarge'] = AllowToDischarge
            
            

        return True
        
        
#################
#################  
### Main loop ###
#################
#################

def main():

    if LOGGING == 1:    # print to console
        logging.basicConfig(level=logging.INFO)        
    elif LOGGING == 2:  # print to file   
        logging.basicConfig(filename = '/data/dbus-aggregate-batteries/aggregatebatteries.log', level=logging.INFO)
    
    logging.info('%s: Starting AggregateBatteries.' % dt.now())
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    aggbat = DbusAggBatService()
    logging.info('%s: Connected to DBus, and switching over to GLib.MainLoop()' % dt.now())
    mainloop = GLib.MainLoop()
    mainloop.run()

if __name__ == "__main__":
    main()

