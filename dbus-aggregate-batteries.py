#!/usr/bin/env python3

"""
Service to aggregate multiple serial batteries https://github.com/mr-manuel/venus-os_dbus-serialbattery
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
import platform
import dbus
import re
import settings
from functions import Functions

# for UTC time stamps for logging
from datetime import datetime as dt

# for charge measurement
import time as tt
from dbusmon import DbusMon
from threading import Thread

# add ext folder to sys.path
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext"))

# optionally from victron
# sys.path.insert(1, "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")

from vedbus import VeDbusService, VeDbusItemImport  # noqa: E402

VERSION = "4.0.20260217-beta"


def get_bus():
    """Return the shared system bus connection (singleton provided by dbus-python)."""
    return dbus.SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else dbus.SystemBus()


class DbusAggBatService(object):

    def __init__(self, servicename="com.victronenergy.battery.aggregate"):
        self._fn = Functions()
        self._batteries_dict = {}
        """ dictionary with battery name as key and dbus service as value """

        self._multi = None
        """ dbus service of MultiPlus/Quattro, if found """

        self._mppts_list = []
        """ list of dbus services of MPPTs, if found """

        # store list of SmartShunts as specified in settings.py
        self._smartShunt_list = []
        """ list of dbus services of SmartShunts, if found """

        # Initialize tread as None
        self._dbusMon = None

        # the number of SmartShunts at the beginning of _smartShunt_list that are in the
        # battery service (dc_load are listed behind)
        self._num_battery_shunts = 0
        self._settings = None
        self._searchTrials = 1
        self._readTrials = 1
        self._MaxChargeVoltage_old = 0
        self._MaxChargeCurrent_old = 0
        self._MaxDischargeCurrent_old = 0
        # Keep track of MultiPlus/Quattro connection status
        # so connect/disconnect notice is output only once
        # - prevents log overflowing when MultiPlus/Quattro is
        #   switched off for longer periods of time (i.e. in mobile applications)
        self._multi_connected = True
        # implementing hysteresis for allowing discharge
        self._fullyDischarged = False
        self._dbusConn = get_bus()
        logging.info("Initializing VeDbusService...")
        self._dbusservice = VeDbusService(servicename, self._dbusConn, register=False)
        logging.info("VeDbusService initialized")
        self._timeOld = tt.time()
        # written when dynamic CVL limit activated
        self._DCfeedActive = False
        # Set True when starting dynamic CVL reduction. Set False when balancing is finished.
        self._dynCVLactivated = False
        # 0: inactive; 1: goal reached, waiting for discharging under nominal voltage; 2: nominal voltage reached
        self._balancing = 0
        # Day in year
        self._lastBalancing = 0
        # set if the CVL needs to be reduced due to peaking
        self._dynamicCVL = False
        # last timestamp then the log was printed
        self._logLastPrintTimeStamp = 0

        self.SETTINGS_PATH_SHORT = "Devices/aggregatebatteries/CustomName"  # without /Settings/ prefix for AddSetting
        self.SETTINGS_PATH = "/Settings/" + self.SETTINGS_PATH_SHORT  # with /Settings/ prefix for VeDbusItemImport

        # read initial charge from text file
        try:
            self._charge_file = open("/data/apps/dbus-aggregate-batteries/storedvalue_charge", "r")  # read
            self._ownCharge = float(self._charge_file.readline().strip())
            self._charge_file.close()
            self._ownCharge_old = self._ownCharge
            logging.info("Initial Ah read from file: %.0fAh" % (self._ownCharge))
        except Exception:
            logging.error("Charge file read error. Exiting...")
            tt.sleep(settings.TIME_BEFORE_RESTART)
            sys.exit(1)

        # read the day of the last balancing from text file
        if settings.OWN_CHARGE_PARAMETERS:
            try:
                self._lastBalancing_file = open(
                    "/data/apps/dbus-aggregate-batteries/storedvalue_last_balancing",
                    "r",
                )
                self._lastBalancing = int(self._lastBalancing_file.readline().strip())
                self._lastBalancing_file.close()
                # in days
                time_unbalanced = int((dt.now()).strftime("%j")) - self._lastBalancing
                if time_unbalanced < 0:
                    # year change
                    time_unbalanced += 365
                logging.info("Last balancing done at the %d. day of the year" % (self._lastBalancing))
                logging.info("Batteries balanced %d days ago." % time_unbalanced)
            except Exception:
                logging.error("Last balancing file read error. Exiting...")
                tt.sleep(settings.TIME_BEFORE_RESTART)
                sys.exit(1)

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path("/Mgmt/ProcessVersion", "Python " + platform.python_version())
        self._dbusservice.add_path("/Mgmt/Connection", "Virtual")

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", 99)
        # this product ID was randomly selected - please exchange, if interference with another component
        self._dbusservice.add_path("/ProductId", 0xBA44)
        self._dbusservice.add_path("/ProductName", "AggregateBatteries")
        self._dbusservice.add_path("/CustomName", "AggregateBatteries", writeable=True, onchangecallback=self._callback_changed_custom_name)
        self._dbusservice.add_path("/FirmwareVersion", VERSION)
        self._dbusservice.add_path("/HardwareVersion", VERSION)
        self._dbusservice.add_path("/Connected", 1)

        # Create DC paths
        self._dbusservice.add_path(
            "/Dc/0/Voltage",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.2f}V".format(x),
        )
        self._dbusservice.add_path(
            "/Dc/0/Current",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.2f}A".format(x),
        )
        self._dbusservice.add_path(
            "/Dc/0/Power",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.0f}W".format(x),
        )

        # Create capacity paths
        self._dbusservice.add_path("/Soc", None, writeable=True)
        self._dbusservice.add_path(
            "/Capacity",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.0f}Ah".format(x),
        )
        self._dbusservice.add_path(
            "/InstalledCapacity",
            None,
            gettextcallback=lambda a, x: "{:.0f}Ah".format(x),
        )
        self._dbusservice.add_path("/ConsumedAmphours", None, gettextcallback=lambda a, x: "{:.0f}Ah".format(x))

        # Create temperature paths
        self._dbusservice.add_path("/Dc/0/Temperature", None, writeable=True)
        self._dbusservice.add_path("/System/MinCellTemperature", None, writeable=True)
        self._dbusservice.add_path("/System/MaxCellTemperature", None, writeable=True)

        # Create extras paths
        self._dbusservice.add_path(
            "/System/MinCellVoltage",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.3f}V".format(x),
        )
        self._dbusservice.add_path("/System/MinVoltageCellId", None, writeable=True)
        self._dbusservice.add_path(
            "/System/MaxCellVoltage",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.3f}V".format(x),
        )
        self._dbusservice.add_path("/System/MaxVoltageCellId", None, writeable=True)
        self._dbusservice.add_path("/System/NrOfCellsPerBattery", None, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesOnline", None, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesOffline", None, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesBlockingCharge", None, writeable=True)
        self._dbusservice.add_path("/System/NrOfModulesBlockingDischarge", None, writeable=True)
        self._dbusservice.add_path(
            "/Voltages/Sum",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.3f}V".format(x),
        )
        self._dbusservice.add_path(
            "/Voltages/Diff",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.3f}V".format(x),
        )
        self._dbusservice.add_path("/TimeToGo", None, writeable=True)

        # Create alarm paths
        self._dbusservice.add_path("/Alarms/LowVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighCellVoltage", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowSoc", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighChargeCurrent", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighDischargeCurrent", None, writeable=True)
        self._dbusservice.add_path("/Alarms/CellImbalance", None, writeable=True)
        self._dbusservice.add_path("/Alarms/InternalFailure", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighChargeTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowChargeTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/HighTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/LowTemperature", None, writeable=True)
        self._dbusservice.add_path("/Alarms/BmsCable", None, writeable=True)

        # Create control paths
        self._dbusservice.add_path(
            "/Info/MaxChargeCurrent",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.1f}A".format(x),
        )
        self._dbusservice.add_path(
            "/Info/MaxDischargeCurrent",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.1f}A".format(x),
        )
        self._dbusservice.add_path(
            "/Info/MaxChargeVoltage",
            None,
            writeable=True,
            gettextcallback=lambda a, x: "{:.2f}V".format(x),
        )
        self._dbusservice.add_path("/Io/AllowToCharge", None, writeable=True)
        self._dbusservice.add_path("/Io/AllowToDischarge", None, writeable=True)
        self._dbusservice.add_path("/Io/AllowToBalance", None, writeable=True)

        x = Thread(target=self._startMonitor)
        x.start()

        # wait that Dbus monitor is running else there is no data
        while self._dbusMon is None:
            tt.sleep(1)

        # search com.victronenergy.settings
        GLib.timeout_add_seconds(settings.UPDATE_INTERVAL_FIND_DEVICES, self._find_settings)

        # register VeDbusService after all paths where added and all data is available
        logging.info("Registering VeDbusService...")
        self._dbusservice.register()

    # #############################################################################################################
    # #############################################################################################################
    # ## Starting battery dbus monitor in external thread (otherwise collision with AggregateBatteries service) ###
    # #############################################################################################################
    # #############################################################################################################

    def _startMonitor(self):
        logging.info("Starting dbusmonitor...")
        self._dbusMon = DbusMon()
        logging.info("dbusmonitor started")

    # ####################################################################
    # ####################################################################
    # ## search Settings, to maintain CCL during dynamic CVL reduction ###
    # https://www.victronenergy.com/upload/documents/Cerbo_GX/140558-CCGX__Venus_GX__Cerbo_GX__Cerbo-S_GX_Manual-pdf-en.pdf, P72  # noqa: E501
    # ####################################################################
    # ####################################################################

    def _find_settings(self) -> bool:
        logging.info("Searching Settings: Trial Nr. %d" % self._searchTrials)
        try:
            for service in self._dbusConn.list_names():
                if "com.victronenergy.settings" in service:
                    self._settings = service
                    logging.info("|- com.victronenergy.settings found")
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logging.debug(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

            pass

        if self._settings is not None:
            self._searchTrials = 1

            # try to read saved CustomName from settings and apply it if exists
            try:
                setting_item = VeDbusItemImport(self._dbusConn, self._settings, self.SETTINGS_PATH, createsignal=False)
                if setting_item.exists:
                    custom_name = setting_item.get_value()
                    if custom_name is not None and custom_name != "AggregateBatteries":
                        self._dbusservice["/CustomName"] = custom_name
                        logging.info(f'   |- Custom name restored from settings: "{custom_name}"')
            except Exception:
                (
                    exception_type,
                    exception_object,
                    exception_traceback,
                ) = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logging.debug(f"Could not read CustomName from settings: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

            # search batteries on DBus if present
            GLib.timeout_add_seconds(settings.UPDATE_INTERVAL_FIND_DEVICES, self._find_batteries)
            # all OK, stop calling this function
            return False
        elif self._searchTrials < settings.SEARCH_TRIALS:
            self._searchTrials += 1
            # next trial
            return True
        else:
            logging.error("com.victronenergy.settings not found. Exiting...")
            tt.sleep(settings.TIME_BEFORE_RESTART)
            sys.exit(1)

    # #####################################################################
    # #####################################################################
    # ## search physical batteries and optional SmartShunts on DC loads ###
    # #####################################################################
    # #####################################################################

    def _find_batteries(self) -> bool:
        self._batteries_dict = {}

        # SmartShunt list - will be populated so battery category SmartShunts are at the beginning of the list
        self._smartShunt_list = []

        # no SmartShunts in the battery category have been found yet
        self._num_battery_shunts = 0
        batteriesCount = 0

        # the following two variables are used when self._ownCharge (read from
        # the charge file), is negative
        # to accumulate the SoC of the aggregated batteries from their BMSes
        Soc = 0

        # to accumulate the overall capacity of the aggregated batteries from their BMSes
        InstalledCapacity = 0

        ##################################################
        # Logic to interpret the USE_SMARTSHUNTS setting #
        ##################################################
        use_smartshunts = False

        # list to keep track of which SmartShunts have been included to not match the same shunt twice and
        # to make sure the correct number is matched
        included_smartshunts = []

        # need to find >= 0 NR_OF_SMARTSHUNTS
        NR_OF_SMARTSHUNTS = 0

        if isinstance(settings.USE_SMARTSHUNTS, bool):
            # True: use all available SmartShunts, False: don't use any SmartShunt
            use_smartshunts = settings.USE_SMARTSHUNTS
        elif isinstance(settings.USE_SMARTSHUNTS, (list, tuple)):
            # empty list -> don't use any SmartShunt
            use_smartshunts = len(settings.USE_SMARTSHUNTS) > 0

            if use_smartshunts:
                # NR_SMARTSHUNTS is the number of SmartShunts specified by the user
                NR_SMARTSHUNTS = len(settings.USE_SMARTSHUNTS)

            # initially, no SmartShunt has been found yet
            included_smartshunts = [False] * NR_SMARTSHUNTS

        productName = ""

        # keep track of SmartShunt (user-defined) name as specified by SMARTSHUNT_INSTANCE_NAME_PATH
        shuntName = ""
        logging.info("Searching batteries: Trial Nr. %d" % self._searchTrials)

        # if Dbus monitor not running yet, new trial instead of exception
        try:
            service_names = [str(name) for name in self._dbusConn.list_names() if "com.victronenergy" in str(name)]
            for service in sorted(service_names):
                logging.info("|- Dbusmonitor sees: %s" % (service))
                # Current device is in Victron "battery" service
                battery_service = settings.BATTERY_SERVICE_NAME in service
                # Current device is in Victron "dcload" service (i.e. a SmartShunt set to DC metering)
                dcload_service = settings.DCLOAD_SERVICE_NAME in service
                if battery_service or dcload_service:
                    productName = self._dbusMon.dbusmon.get_value(service, settings.BATTERY_PRODUCT_NAME_PATH)
                    shuntName = self._dbusMon.dbusmon.get_value(service, settings.SMARTSHUNT_INSTANCE_NAME_PATH)
                if battery_service:
                    if (productName is not None) and (settings.BATTERY_PRODUCT_NAME in productName):
                        logging.info('   |- Correct battery product name "%s" found' % productName)

                        # Custom name, if exists
                        try:
                            BatteryName = self._dbusMon.dbusmon.get_value(service, settings.BATTERY_INSTANCE_NAME_PATH)
                        except Exception:
                            (
                                exception_type,
                                exception_object,
                                exception_traceback,
                            ) = sys.exc_info()
                            file = exception_traceback.tb_frame.f_code.co_filename
                            line = exception_traceback.tb_lineno
                            logging.debug(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

                            BatteryName = "Battery%d" % (batteriesCount + 1)

                        # Check if all batteries have custom names
                        if BatteryName in self._batteries_dict:
                            BatteryName = "%s%d" % (BatteryName, batteriesCount + 1)

                        self._batteries_dict[BatteryName] = service
                        logging.info("   |- Battery name: %s" % BatteryName)
                        logging.info("   |- Custom name:  %s" % self._dbusMon.dbusmon.get_value(service, "/CustomName"))
                        logging.info("   |- Product name: %s" % self._dbusMon.dbusmon.get_value(service, "/ProductName"))

                        batteriesCount += 1

                        # accumulate battery capacities and Soc if not read from charge file
                        if self._ownCharge < 0:
                            battery_capacity = self._dbusMon.dbusmon.get_value(service, "/InstalledCapacity")
                            battery_soc = self._dbusMon.dbusmon.get_value(service, "/Soc") * battery_capacity
                            InstalledCapacity += battery_capacity
                            Soc += battery_soc
                            logging.info("      |- SoC: %f / %f Ah" % (battery_soc / 100.0, battery_capacity))

                        # Create voltage paths with battery names
                        if settings.SEND_CELL_VOLTAGES == 1:
                            for cellId in range(1, (settings.NR_OF_CELLS_PER_BATTERY) + 1):
                                self._dbusservice.add_path(
                                    "/Voltages/%s_Cell%d"
                                    % (
                                        re.sub("[^A-Za-z0-9_]+", "", BatteryName),
                                        cellId,
                                    ),
                                    None,
                                    writeable=True,
                                    gettextcallback=lambda a, x: "{:.3f}V".format(x),
                                )

                        # Check if Nr. of cells is equal
                        if self._dbusMon.dbusmon.get_value(service, "/System/NrOfCellsPerBattery") != settings.NR_OF_CELLS_PER_BATTERY:
                            logging.error("     |- Number of battery cells does not match config:")
                            logging.error(
                                "        |- Cells found in battery:         %d" % (self._dbusMon.dbusmon.get_value(service, "/System/NrOfCellsPerBattery"))
                            )
                            logging.error("        |- Cells specified in config file: %d" % (settings.NR_OF_CELLS_PER_BATTERY))
                            logging.error("Exiting...")
                            tt.sleep(settings.TIME_BEFORE_RESTART)
                            sys.exit(1)

                        # end of section

                ##########################################################
                # Find SmartShunts in either Battery or DC Load services #
                ##########################################################
                if battery_service or dcload_service:
                    # if SmartShunt found, can be used for battery monitoring or DC load current
                    # depending on how it is set
                    if (productName is not None) and (settings.SMARTSHUNT_NAME_KEYWORD in productName):
                        shunt_vrm_id = self._dbusMon.dbusmon.get_value(service, "/DeviceInstance")
                        logging.info('   |- Correct SmartShunt product name "%s" found' % productName)

                        # user specified to use SmartShunts
                        if use_smartshunts:
                            # if USE_SMARTSHUNTS is set to `True` and not a list, the conditional below won't
                            # run and every SmartShunt is included
                            include_shunt = True

                            # user-specified list of SmartShunts
                            if isinstance(settings.USE_SMARTSHUNTS, (list, tuple)):
                                # go over user-list and see if we can match current shunt
                                for shunt_id in range(0, len(settings.USE_SMARTSHUNTS)):
                                    # already included, move along
                                    if included_smartshunts[shunt_id]:
                                        continue

                                    # match by VRM Id
                                    if isinstance(settings.USE_SMARTSHUNTS[shunt_id], int):
                                        include_shunt = settings.USE_SMARTSHUNTS[shunt_id] == shunt_vrm_id

                                    # match by shuntName (as specified in the SMARTSHUNT_INSTANCE_NAME_PATH field)
                                    elif isinstance(settings.USE_SMARTSHUNTS[shunt_id], str):
                                        include_shunt = settings.USE_SMARTSHUNTS[shunt_id] == shuntName

                                    # Bail out with an error if list entry is neither string integer nor string
                                    else:
                                        logging.error(
                                            '   |- Bad element #%d in "%s" in USE_SMARTSHUNTS list. Entries need to be '
                                            + " VRM instancmbers or Name strings. Exiting...",
                                            shunt_id + 1,
                                            settings.USE_SMARTSHUNTS[shunt_id],
                                        )
                                        tt.sleep(settings.TIME_BEFORE_RESTART)
                                        sys.exit(1)

                                    # if a shunt has been matched as one the user defined and we haven't included it
                                    # yet, we can get out of this loop
                                    if include_shunt:
                                        break

                            # SmartShunt is added to list
                            if include_shunt:
                                # battery SmartShunts are inserted at the end of the battery part of the list
                                if battery_service:
                                    self._smartShunt_list.insert(self._num_battery_shunts, service)
                                    self._num_battery_shunts += 1
                                # dcload SmartShunts get added to the end of the list
                                # (which is the end of the dcload part of the list)
                                else:
                                    self._smartShunt_list.append(service)
                                logging.info(
                                    "   |- %s [%d] added, named as: %s."
                                    % (
                                        productName,
                                        shunt_vrm_id,
                                        shuntName,
                                    )
                                )
                # end of SmartShunt detection (AT, 2025)

        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logging.debug(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

            pass

        # when SmartShunts have been found, add their overall number in addition to
        # the number of batteries aggregated to the log output
        if len(self._smartShunt_list) > 0:
            logging.info(
                "%d batteries and %d SmartShunts found"
                % (
                    batteriesCount,
                    len(self._smartShunt_list),
                )
            )
        else:
            logging.info("> %d batteries found." % (batteriesCount))

        # make sure the correct number of batteries and SmartShunts has been found
        if (batteriesCount == settings.NR_OF_BATTERIES) and (len(self._smartShunt_list) >= NR_OF_SMARTSHUNTS):
            if self._ownCharge < 0:
                self._ownCharge = Soc / 100.0
                Soc /= InstalledCapacity
            if settings.CURRENT_FROM_VICTRON:
                self._searchTrials = 1
                # if current from Victron stuff search multi/quattro on DBus
                GLib.timeout_add_seconds(settings.UPDATE_INTERVAL_FIND_DEVICES, self._find_multis)
            else:
                self._timeOld = tt.time()
                # if current from BMS start the _update loop
                GLib.timeout_add_seconds(settings.UPDATE_INTERVAL_DATA, self._update)

            # all OK, stop calling this function
            return False
        # if the correct number has not been found yet, repeat until SEARCH_TRIALS is reached
        elif self._searchTrials < settings.SEARCH_TRIALS:
            self._searchTrials += 1
            # next trial
            return True
        # bail out if correct number of batteries and SmartShunts can not be found after SEARCH_TRIALS tries
        else:
            if NR_OF_SMARTSHUNTS > 0:
                logging.error(
                    "Required nr of batteries (%d) or SmartShunts (%d) not found. Exiting...",
                    settings.NR_OF_BATTERIES,
                    NR_OF_SMARTSHUNTS,
                )
            else:
                logging.info(self._batteries_dict)
                logging.error("Required number of batteries not found. Exiting...")
            tt.sleep(settings.TIME_BEFORE_RESTART)
            sys.exit(1)

    # #########################################################################
    # #########################################################################
    # ## search Multis or Quattros (if selected for DC current measurement) ###
    # #########################################################################
    # #########################################################################

    def _find_multis(self):
        # only search for MultiPlus/Quattro devices if that is specified, possible use-cases:
        # - no MultiPlus/Quattro device installed (examples: a pure DC system, a different inverter/charger is used)
        # - current detection of MultiPlus/Quattro is not wanted (i.e. SmartShunts are used instead)
        # may still want to aggregate their batteries when using no inverter/no Victron inverter/charger)
        if len(settings.MULTI_KEYWORD) > 0:
            logging.info("Searching MultiPlus/Quattro VEbus: Trial Nr. %d" % self._searchTrials)
            try:
                for service in self._dbusConn.list_names():
                    if settings.MULTI_KEYWORD in service:
                        self._multi = service
                        logging.info("|- %s found." % ((self._dbusMon.dbusmon.get_value(service, "/ProductName")),))
            except Exception:
                (
                    exception_type,
                    exception_object,
                    exception_traceback,
                ) = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logging.debug(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

                pass

            logging.info("> 1 MultiPlus/Quattro found.")
            if self._multi is None:
                if self._searchTrials < settings.SEARCH_TRIALS:
                    self._searchTrials += 1
                    # next trial
                    return True
                else:
                    logging.error("Multi/Quattro not found. Exiting...")
                    tt.sleep(settings.TIME_BEFORE_RESTART)
                    sys.exit(1)

        if settings.NR_OF_MPPTS > 0:
            self._searchTrials = 1
            # search MPPTs on DBus if present
            GLib.timeout_add_seconds(settings.UPDATE_INTERVAL_FIND_DEVICES, self._find_mppts)
        else:
            self._timeOld = tt.time()
            # if no MPPTs start the _update loop
            GLib.timeout_add_seconds(settings.UPDATE_INTERVAL_DATA, self._update)

        # all OK, stop calling this function
        return False

    # ############################################################
    # ############################################################
    # ## search MPPTs (if selected for DC current measurement) ###
    # ############################################################
    # ############################################################

    def _find_mppts(self):
        self._mppts_list = []
        mpptsCount = 0
        logging.info("Searching MPPT(s): Trial Nr. %d" % self._searchTrials)
        try:
            for service in self._dbusConn.list_names():
                if settings.MPPT_KEYWORD in service:
                    self._mppts_list.append(service)
                    logging.info("|- %s found." % ((self._dbusMon.dbusmon.get_value(service, "/ProductName")),))
                    mpptsCount += 1
        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logging.debug(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

            pass

        logging.info("> %d MPPT(s) found." % (mpptsCount))
        if mpptsCount == settings.NR_OF_MPPTS:
            self._timeOld = tt.time()
            GLib.timeout_add_seconds(settings.UPDATE_INTERVAL_DATA, self._update)
            # all OK, stop calling this function
            return False
        elif self._searchTrials < settings.SEARCH_TRIALS:
            self._searchTrials += 1
            # next trial
            return True
        else:
            logging.error("Required number of MPPTs not found. Exiting...")
            tt.sleep(settings.TIME_BEFORE_RESTART)
            sys.exit(1)

    def _callback_changed_custom_name(self, path, value):
        """
        Save the custom name to the dbus service com.victronenergy.settings/Settings/Devices/aggregatebatteries/CustomName

        :param path: The dbus path being changed
        :param value: The new custom name value
        :return: The value if successful, None if failed
        """

        try:
            # First check if the setting path exists in the settings service
            setting_exists = False
            try:
                # Try to get the value to check if it exists
                test_item = VeDbusItemImport(self._dbusConn, self._settings, self.SETTINGS_PATH, createsignal=False)
                setting_exists = test_item.exists
            except Exception:
                setting_exists = False

            # If setting doesn't exist, create it using AddSetting D-Bus method
            if not setting_exists:
                logging.info(f"Setting {self.SETTINGS_PATH} doesn't exist, creating it...")
                try:
                    settings_obj = self._dbusConn.get_object(self._settings, "/Settings")
                    settings_iface = dbus.Interface(settings_obj, "com.victronenergy.Settings")
                    # AddSetting(group, name, default_value, type, min, max)
                    # type 's' = string, empty string for group means root /Settings/
                    settings_iface.AddSetting("", self.SETTINGS_PATH_SHORT, value, "s", "", "")
                    logging.info(f"Successfully created setting {self.SETTINGS_PATH}")
                except dbus.exceptions.DBusException as e:
                    logging.warning(f"Failed to create setting via AddSetting: {e}")
                    # Setting might already exist, continue to try setting it

            # Now set the value using VeDbusItemImport directly (bypasses dbusmonitor)
            setting_item = VeDbusItemImport(self._dbusConn, self._settings, self.SETTINGS_PATH, createsignal=False)
            result = setting_item.set_value(value)

            if result == 0:
                logging.info(f'CustomName successfully changed to "{value}"')
                return value
            else:
                logging.warning(f'CustomName change to "{value}" failed with result: {result}')
                return False

        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            logging.warning(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            return False

    # #################################################################################
    # #################################################################################
    # ### aggregate values of physical batteries, perform calculations, update Dbus ###
    # #################################################################################
    # #################################################################################

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
        TimeToGo = 0

        # Temperature
        Temperature = 0
        # list, maxima of all physical batteries
        MaxCellTemp_list = []
        # list, minima of all physical batteries
        MinCellTemp_list = []

        # Extras
        cellVoltages_dict = {}
        # dictionary {'ID' : MaxCellVoltage, ... } for all physical batteries
        MaxCellVoltage_dict = {}
        # dictionary {'ID' : MinCellVoltage, ... } for all physical batteries
        MinCellVoltage_dict = {}
        NrOfModulesOnline = 0
        NrOfModulesOffline = 0
        NrOfModulesBlockingCharge = 0
        NrOfModulesBlockingDischarge = 0
        # battery voltages from sum of cells
        VoltagesSum_dict = {}
        chargeVoltageReduced_list = []

        # Alarms
        # lists to find maxima
        LowVoltage_alarm_list = []
        HighVoltage_alarm_list = []
        LowCellVoltage_alarm_list = []
        HighCellVoltage_alarm_list = []
        LowSoc_alarm_list = []
        HighChargeCurrent_alarm_list = []
        HighDischargeCurrent_alarm_list = []
        CellImbalance_alarm_list = []
        InternalFailure_alarm_list = []
        HighChargeTemperature_alarm_list = []
        LowChargeTemperature_alarm_list = []
        HighTemperature_alarm_list = []
        LowTemperature_alarm_list = []
        BmsCable_alarm_list = []

        # Charge/discharge parameters

        # the minimum of MaxChargeCurrent * NR_OF_BATTERIES to be transmitted
        MaxChargeCurrent_list = []
        # the minimum of MaxDischargeCurrent * NR_OF_BATTERIES to be transmitted
        MaxDischargeCurrent_list = []
        # if some cells are above MAX_CELL_VOLTAGE, store here the sum of differences for each battery
        MaxChargeVoltage_list = []
        # minimum of all to be transmitted
        AllowToCharge_list = []
        # minimum of all to be transmitted
        AllowToDischarge_list = []
        # minimum of all to be transmitted
        AllowToBalance_list = []
        # Bulk, Absorption, Float, Keep always max voltage
        ChargeMode_list = []

        ####################################################
        # Get DBus values from all SerialBattery instances #
        ####################################################

        try:
            for i in self._batteries_dict:

                # DC
                # to detect error
                step = "Read V, I, P"
                Voltage += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Dc/0/Voltage")
                Current += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Dc/0/Current")
                Power += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Dc/0/Power")

                # Capacity
                step = "Read and calculate capacity, SoC, Time to go"
                InstalledCapacity += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/InstalledCapacity")

                if not settings.OWN_SOC:
                    ConsumedAmphours += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/ConsumedAmphours")
                    Capacity += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Capacity")
                    Soc += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Soc") * self._dbusMon.dbusmon.get_value(
                        self._batteries_dict[i], "/InstalledCapacity"
                    )
                    ttg = self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/TimeToGo")
                    if (ttg is not None) and (TimeToGo is not None):
                        TimeToGo += ttg * self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/InstalledCapacity")
                    else:
                        TimeToGo = None

                # Temperature
                step = "Read temperatures"
                Temperature += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Dc/0/Temperature")
                MaxCellTemp_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/MaxCellTemperature"))
                MinCellTemp_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/MinCellTemperature"))

                # Cell voltages
                # cell ID : its voltage
                step = "Read max. and min cell voltages and voltage sum"
                MaxCellVoltage_dict[
                    "%s: %s"
                    % (
                        self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/CustomName"),
                        self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/MaxVoltageCellId"),
                    )
                ] = self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/MaxCellVoltage")
                MinCellVoltage_dict[
                    "%s: %s"
                    % (
                        self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/CustomName"),
                        self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/MinVoltageCellId"),
                    )
                ] = self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/MinCellVoltage")

                # here an exception is raised and new read trial initiated if None is on Dbus
                volt_sum_get = self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Voltages/Sum")
                if volt_sum_get is not None:
                    VoltagesSum_dict[i] = volt_sum_get
                else:
                    raise TypeError(
                        f"Battery {i} returns None value of /Voltages/Sum. Please check, if the setting "
                        + "'BATTERY_CELL_DATA_FORMAT=1' in dbus-serialbattery config"
                    )

                # Battery state
                step = "Read battery state"
                NrOfModulesOnline += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/NrOfModulesOnline")
                NrOfModulesOffline += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/NrOfModulesOffline")
                NrOfModulesBlockingCharge += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/NrOfModulesBlockingCharge")
                # sum of modules blocking discharge
                NrOfModulesBlockingDischarge += self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/System/NrOfModulesBlockingDischarge")

                step = "Read cell voltages"
                for j in range(settings.NR_OF_CELLS_PER_BATTERY):
                    cellVoltages_dict["%s_Cell%d" % (i, j + 1)] = self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Voltages/Cell%d" % (j + 1))

                # Alarms
                step = "Read alarms"
                LowVoltage_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/LowVoltage"))
                HighVoltage_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/HighVoltage"))
                LowCellVoltage_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/LowCellVoltage"))
                HighCellVoltage_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/HighCellVoltage"))
                LowSoc_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/LowSoc"))
                HighChargeCurrent_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/HighChargeCurrent"))
                HighDischargeCurrent_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/HighDischargeCurrent"))
                CellImbalance_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/CellImbalance"))
                InternalFailure_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/InternalFailure_alarm"))
                HighChargeTemperature_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/HighChargeTemperature"))
                LowChargeTemperature_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/LowChargeTemperature"))
                HighTemperature_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/HighTemperature"))
                LowTemperature_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/LowTemperature"))
                BmsCable_alarm_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Alarms/BmsCable"))

                # calculate reduction of charge voltage as sum of overvoltages of all cells
                if settings.OWN_CHARGE_PARAMETERS:
                    step = "Calculate CVL reduction"
                    cellOvervoltage = 0
                    for j in range(settings.NR_OF_CELLS_PER_BATTERY):
                        cellVoltage = self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Voltages/Cell%d" % (j + 1))
                        if cellVoltage > settings.MAX_CELL_VOLTAGE:
                            cellOvervoltage += cellVoltage - settings.MAX_CELL_VOLTAGE
                    chargeVoltageReduced_list.append(VoltagesSum_dict[i] - cellOvervoltage)

                # Aggregate charge/discharge parameters
                else:
                    step = "Read charge parameters"
                    # list of max. charge currents to find minimum
                    MaxChargeCurrent_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Info/MaxChargeCurrent"))
                    # list of max. discharge currents  to find minimum
                    MaxDischargeCurrent_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Info/MaxDischargeCurrent"))
                    # list of max. charge voltages  to find minimum
                    MaxChargeVoltage_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Info/MaxChargeVoltage"))
                    # list of charge modes of batteries (Bulk, Absorption, Float, Keep always max voltage)
                    ChargeMode_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Info/ChargeMode"))

                step = "Read Allow to"
                # list of AllowToCharge to find minimum
                AllowToCharge_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Io/AllowToCharge"))
                # list of AllowToDischarge to find minimum
                AllowToDischarge_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Io/AllowToDischarge"))
                # list of AllowToBalance to find minimum
                AllowToBalance_list.append(self._dbusMon.dbusmon.get_value(self._batteries_dict[i], "/Io/AllowToBalance"))

            step = "Find max. and min. cell voltage of all batteries"
            # placed in try-except structure for the case if some values are of None.
            # The _max() and _min() don't work with dictionaries
            MaxVoltageCellId = max(MaxCellVoltage_dict, key=MaxCellVoltage_dict.get)
            MaxCellVoltage = MaxCellVoltage_dict[MaxVoltageCellId]
            MinVoltageCellId = min(MinCellVoltage_dict, key=MinCellVoltage_dict.get)
            MinCellVoltage = MinCellVoltage_dict[MinVoltageCellId]

        except Exception:
            (
                exception_type,
                exception_object,
                exception_traceback,
            ) = sys.exc_info()
            file = exception_traceback.tb_frame.f_code.co_filename
            line = exception_traceback.tb_lineno
            locals_at_error = exception_traceback.tb_frame.f_locals
            logging.error(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")
            logging.error(f"Local variables at error: {locals_at_error}")
            logging.error("Occured during step %s, Battery %s." % (step, i))
            logging.error("Read trial nr. %d" % self._readTrials)
            self._readTrials += 1
            if self._readTrials > settings.READ_TRIALS:
                logging.error("DBus read failed. Exiting...")
                tt.sleep(settings.TIME_BEFORE_RESTART)
                sys.exit(1)
            else:
                # next call allowed
                return True

        #####################################################
        # Process collected values (except of dictionaries) #
        #####################################################

        # averaging
        Voltage = Voltage / settings.NR_OF_BATTERIES
        Temperature = Temperature / settings.NR_OF_BATTERIES
        VoltagesSum = sum(VoltagesSum_dict.values()) / settings.NR_OF_BATTERIES

        # find max and min cell temperature (have no ID)
        MaxCellTemp = self._fn._max(MaxCellTemp_list)
        MinCellTemp = self._fn._min(MinCellTemp_list)

        # find max in alarms
        LowVoltage_alarm = self._fn._max(LowVoltage_alarm_list)
        HighVoltage_alarm = self._fn._max(HighVoltage_alarm_list)
        LowCellVoltage_alarm = self._fn._max(LowCellVoltage_alarm_list)
        HighCellVoltage_alarm = self._fn._max(HighCellVoltage_alarm_list)
        LowSoc_alarm = self._fn._max(LowSoc_alarm_list)
        HighChargeCurrent_alarm = self._fn._max(HighChargeCurrent_alarm_list)
        HighDischargeCurrent_alarm = self._fn._max(HighDischargeCurrent_alarm_list)
        CellImbalance_alarm = self._fn._max(CellImbalance_alarm_list)
        InternalFailure_alarm = self._fn._max(InternalFailure_alarm_list)
        HighChargeTemperature_alarm = self._fn._max(HighChargeTemperature_alarm_list)
        LowChargeTemperature_alarm = self._fn._max(LowChargeTemperature_alarm_list)
        HighTemperature_alarm = self._fn._max(HighTemperature_alarm_list)
        LowTemperature_alarm = self._fn._max(LowTemperature_alarm_list)
        BmsCable_alarm = self._fn._max(BmsCable_alarm_list)

        # find max. charge voltage (if needed)
        if not settings.OWN_CHARGE_PARAMETERS:
            if settings.KEEP_MAX_CVL and any("Float" in item for item in ChargeMode_list):
                MaxChargeVoltage = self._fn._max(MaxChargeVoltage_list)

            else:
                MaxChargeVoltage = self._fn._min(MaxChargeVoltage_list)

            MaxChargeCurrent = self._fn._min(MaxChargeCurrent_list) * settings.NR_OF_BATTERIES

            MaxDischargeCurrent = self._fn._min(MaxDischargeCurrent_list) * settings.NR_OF_BATTERIES

        AllowToCharge = self._fn._min(AllowToCharge_list)
        AllowToDischarge = self._fn._min(AllowToDischarge_list)
        AllowToBalance = self._fn._min(AllowToBalance_list)

        ####################################
        # Measure current by Victron stuff #
        ####################################

        if settings.CURRENT_FROM_VICTRON:
            success = True
            # variable to accumulate currents measured by Victron stuff (i.e. MultiPlus/Quattro, SmartShunts, MPPTs)
            Current_VE = 0
            try:
                # Read MultiPlus/Quattro data only when one is used and has been found
                # MultiPlus/Quattro `Connected` value will go to 0 if it exists but is switch off (VE-BUS remains connected)
                # by the user (either via Digital Multi Control, Cerbo, VRM, or the device itself)
                if self._multi is not None:
                    Multi_Connected = self._dbusMon.dbusmon.get_value(self._multi, "/Connected")
                    # Read current only when MultiPlus/Quattro is connected
                    if Multi_Connected > 0:
                        # get DC current of multiPlus/quattro (or system of them)
                        Current_VE = self._dbusMon.dbusmon.get_value(self._multi, "/Dc/0/Current")
                        # Output to log that MultiPlus/Quattro is connected again
                        if not self._multi_connected:
                            logging.info("MultiPlus/Quattro is connected")
                        self._multi_connected = True  # keep track of state to notice if state changes at next round
                    else:
                        # Output to log when MultiPlus/Quattro state changed from connected (at last read) to not connected
                        if self._multi_connected:
                            logging.info("MultiPlus/Quattro is not connected")
                        self._multi_connected = False  # keep track of state to notice if state changes at next round

                for i in range(settings.NR_OF_MPPTS):
                    # add DC current of all MPPTs (if present)
                    Current_VE += self._dbusMon.dbusmon.get_value(self._mppts_list[i], "/Dc/0/Current")

            except Exception:
                (
                    exception_type,
                    exception_object,
                    exception_traceback,
                ) = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logging.debug(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

                success = False

            Current_SHUNTS = 0
            try:
                # go over all SmartShunts
                for i in range(len(self._smartShunt_list)):
                    shunt_current = self._dbusMon.dbusmon.get_value(self._smartShunt_list[i], "/Dc/0/Current")
                    if shunt_current is None:
                        raise ValueError(f"SmartShunt {self._smartShunt_list[i]} returns None as current")

                    # SmartShunt is monitored as a battery
                    if i < self._num_battery_shunts:
                        Current_SHUNTS += shunt_current
                    # SmartShunt is in DC metering mode
                    else:
                        Current_SHUNTS -= shunt_current

            except Exception as err:
                (
                    exception_type,
                    exception_object,
                    exception_traceback,
                ) = sys.exc_info()
                file = exception_traceback.tb_frame.f_code.co_filename
                line = exception_traceback.tb_lineno
                logging.debug(f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}")

                logging.error("Error during SmartShunt polling: %s" % (err))
                if settings.IGNORE_SMARTSHUNT_ABSENCE:
                    success = False
                    pass
                else:
                    self._readTrials += 1
                    if self._readTrials > settings.READ_TRIALS:
                        tt.sleep(settings.TIME_BEFORE_RESTART)
                        sys.exit(1)
                    else:
                        # next call allowed
                        return True

            if success:
                if settings.INVERT_SMARTSHUNTS:
                    Current_VE -= Current_SHUNTS
                else:
                    Current_VE += Current_SHUNTS
                # BMS current overwritten only if no exception raised
                Current = Current_VE
                # calculate own power (not read from BMS)
                Power = Voltage * Current_VE
            else:
                # the BMS values are not overwritten
                logging.error("Victron current reading error. Using BMS current and power instead")

        # must be reset after try-except of all reads
        self._readTrials = 1

        ####################################################################################################
        # Calculate own charge/discharge parameters (overwrite the values received from the SerialBattery) #
        ####################################################################################################

        if settings.OWN_CHARGE_PARAMETERS:
            CVL_NORMAL = settings.NR_OF_CELLS_PER_BATTERY * settings.CHARGE_VOLTAGE_LIST[int((dt.now()).strftime("%m")) - 1]
            CVL_BALANCING = settings.NR_OF_CELLS_PER_BATTERY * settings.BALANCING_VOLTAGE
            ChargeVoltageBattery = CVL_NORMAL

            # in days
            time_unbalanced = int((dt.now()).strftime("%j")) - self._lastBalancing
            if time_unbalanced < 0:
                # year change
                time_unbalanced += 365

            # if the normal charging voltage is lower then 100% SoC
            # manage balancing voltage
            if CVL_BALANCING > CVL_NORMAL:
                if (self._balancing == 0) and (time_unbalanced >= settings.BALANCING_REPETITION):
                    # activate increased CVL for balancing
                    self._balancing = 1
                    logging.info("CVL increase for balancing activated")

                if self._balancing == 1:
                    ChargeVoltageBattery = CVL_BALANCING
                    if (Voltage >= CVL_BALANCING) and ((MaxCellVoltage - MinCellVoltage) < settings.CELL_DIFF_MAX):
                        self._balancing = 2
                        logging.info("Balancing goal reached")

                if self._balancing >= 2:
                    # keep balancing voltage at balancing day until decrease of solar powers and
                    ChargeVoltageBattery = CVL_BALANCING
                    # the charge above "normal" is consumed
                    if Voltage <= CVL_NORMAL:
                        self._balancing = 0
                        self._lastBalancing = int((dt.now()).strftime("%j"))
                        self._lastBalancing_file = open(
                            "/data/apps/dbus-aggregate-batteries/storedvalue_last_balancing",
                            "w",
                        )
                        self._lastBalancing_file.write("%s" % self._lastBalancing)
                        self._lastBalancing_file.close()
                        logging.info("CVL increase for balancing de-activated")

                if self._balancing == 0:
                    ChargeVoltageBattery = CVL_NORMAL

            # if normal charging voltage is 100% SoC and balancing is finished
            elif (time_unbalanced > 0) and (Voltage >= CVL_BALANCING) and ((MaxCellVoltage - MinCellVoltage) < settings.CELL_DIFF_MAX):
                logging.info("Balancing goal reached with full charging set as normal. Updating storedvalue_last_balancing file")
                self._lastBalancing = int((dt.now()).strftime("%j"))
                self._lastBalancing_file = open(
                    "/data/apps/dbus-aggregate-batteries/storedvalue_last_balancing",
                    "w",
                )
                self._lastBalancing_file.write("%s" % self._lastBalancing)
                self._lastBalancing_file.close()

            if Voltage >= CVL_BALANCING:
                # reset Coulumb counter to 100%
                self._ownCharge = InstalledCapacity

            # manage dynamic CVL reduction
            if MaxCellVoltage >= settings.MAX_CELL_VOLTAGE:
                if not self._dynamicCVL:
                    self._dynamicCVL = True
                    logging.info(f"Dynamic CVL reduction started due to max. cell voltage: {MaxVoltageCellId} {MaxCellVoltage:.3f}V")
                    # avoid periodic readout
                    if not self._dynCVLactivated:
                        self._dynCVLactivated = True
                        # check if DC-feed enabled
                        self._DCfeedActive = self._dbusMon.dbusmon.get_value(
                            "com.victronenergy.settings",
                            "/Settings/CGwacs/OvervoltageFeedIn",
                        )

                        # disable DC-coupled PV feed-in
                        self._dbusMon.dbusmon.set_value(
                            "com.victronenergy.settings",
                            "/Settings/CGwacs/OvervoltageFeedIn",
                            0,
                        )

                        if self._DCfeedActive == 0:
                            logging.info("DC-coupled PV feed-in was not active")
                        else:
                            logging.info("DC-coupled PV feed-in de-activated")

                # avoid exceeding MAX_CELL_VOLTAGE
                MaxChargeVoltage = min((min(chargeVoltageReduced_list)), ChargeVoltageBattery)

            else:
                MaxChargeVoltage = ChargeVoltageBattery

                if self._dynamicCVL:
                    self._dynamicCVL = False
                    logging.info("Dynamic CVL reduction finished")
                    if (MaxCellVoltage - MinCellVoltage) < settings.CELL_DIFF_MAX:

                        # re-enable DC-feed if it was enabled before
                        self._dbusMon.dbusmon.set_value(
                            "com.victronenergy.settings",
                            "/Settings/CGwacs/OvervoltageFeedIn",
                            self._DCfeedActive,
                        )
                        if self._DCfeedActive:
                            logging.info("DC-coupled PV feed-in re-activated after succeeded " + "balancing")
                        else:
                            logging.info("DC-coupled PV feed-in was not active before and was " + "not activated")

                        # reset to prevent permanent logging and activation of  /Settings/CGwacs/OvervoltageFeedIn
                        self._DCfeedActive = False
                        self._dynCVLactivated = False

            if (MinCellVoltage <= settings.MIN_CELL_VOLTAGE) and settings.ZERO_SOC:
                # reset Coulumb counter to 0%
                self._ownCharge = 0

            # manage charge current
            if NrOfModulesBlockingCharge > 0:
                MaxChargeCurrent = 0
            else:
                MaxChargeCurrent = settings.MAX_CHARGE_CURRENT * self._fn._interpolate(
                    settings.CELL_CHARGE_LIMITING_VOLTAGE,
                    settings.CELL_CHARGE_LIMITED_CURRENT,
                    MaxCellVoltage,
                )

            # manage discharge current
            if MinCellVoltage <= settings.MIN_CELL_VOLTAGE:
                self._fullyDischarged = True
            elif MinCellVoltage > settings.MIN_CELL_VOLTAGE + settings.MIN_CELL_HYSTERESIS:
                self._fullyDischarged = False

            if (NrOfModulesBlockingDischarge > 0) or (self._fullyDischarged):
                MaxDischargeCurrent = 0
            else:
                MaxDischargeCurrent = settings.MAX_DISCHARGE_CURRENT * self._fn._interpolate(
                    settings.CELL_DISCHARGE_LIMITING_VOLTAGE,
                    settings.CELL_DISCHARGE_LIMITED_CURRENT,
                    MinCellVoltage,
                )

        # SoC resetting if OWN_SOC = True and OWN_CHARGE_PARAMETERS = False
        else:
            if settings.OWN_SOC:
                # reset Coulumb counter to 100%
                if MaxCellVoltage >= settings.MAX_CELL_VOLTAGE_SOC_FULL:
                    self._ownCharge = InstalledCapacity
                if (MinCellVoltage <= settings.MIN_CELL_VOLTAGE_SOC_EMPTY) and settings.ZERO_SOC:
                    # reset Coulumb counter to 0%
                    self._ownCharge = 0

        ###########################################################
        # own Coulomb counter (runs even the BMS values are used) #
        ###########################################################

        deltaTime = tt.time() - self._timeOld
        self._timeOld = tt.time()
        if Current > 0:
            # charging (with efficiency)
            self._ownCharge += Current * (deltaTime / 3600) * settings.BATTERY_EFFICIENCY
        else:
            # discharging
            self._ownCharge += Current * (deltaTime / 3600)
        self._ownCharge = max(self._ownCharge, 0)
        self._ownCharge = min(self._ownCharge, InstalledCapacity)

        # store the charge into text file if changed significantly (avoid frequent file access)
        if abs(self._ownCharge - self._ownCharge_old) >= (settings.CHARGE_SAVE_PRECISION * InstalledCapacity):
            self._charge_file = open("/data/apps/dbus-aggregate-batteries/storedvalue_charge", "w")
            self._charge_file.write("%.3f" % self._ownCharge)
            self._charge_file.close()
            self._ownCharge_old = self._ownCharge

        # overwrite BMS charge values
        if settings.OWN_SOC:
            Capacity = self._ownCharge
            Soc = 100 * self._ownCharge / InstalledCapacity
            ConsumedAmphours = InstalledCapacity - self._ownCharge
            if (self._dbusMon.dbusmon.get_value("com.victronenergy.system", "/SystemState/LowSoc") == 0) and (Current < 0):
                TimeToGo = -3600 * self._ownCharge / Current
            else:
                TimeToGo = None
        else:
            # weighted sum
            Soc = Soc / InstalledCapacity
            if TimeToGo is not None:
                # weighted sum
                TimeToGo = TimeToGo / InstalledCapacity

        #######################
        # Send values to DBus #
        #######################

        with self._dbusservice as bus:

            # send DC
            bus["/Dc/0/Voltage"] = Voltage
            # bus["/Dc/0/Voltage"] = round(Voltage, 2)
            bus["/Dc/0/Current"] = Current
            # bus["/Dc/0/Current"] = round(Current, 1)
            bus["/Dc/0/Power"] = Power
            # bus["/Dc/0/Power"] = round(Power, 0)

            # send charge
            bus["/Soc"] = Soc
            bus["/TimeToGo"] = TimeToGo
            bus["/Capacity"] = Capacity
            bus["/InstalledCapacity"] = InstalledCapacity
            bus["/ConsumedAmphours"] = ConsumedAmphours

            # send temperature
            bus["/Dc/0/Temperature"] = Temperature
            bus["/System/MaxCellTemperature"] = MaxCellTemp
            bus["/System/MinCellTemperature"] = MinCellTemp

            # send cell voltages
            bus["/System/MaxCellVoltage"] = MaxCellVoltage
            bus["/System/MaxVoltageCellId"] = MaxVoltageCellId
            bus["/System/MinCellVoltage"] = MinCellVoltage
            bus["/System/MinVoltageCellId"] = MinVoltageCellId
            bus["/Voltages/Sum"] = VoltagesSum
            bus["/Voltages/Diff"] = round(MaxCellVoltage - MinCellVoltage, 3)

            if settings.SEND_CELL_VOLTAGES == 1:
                for cellId, currentCell in enumerate(cellVoltages_dict):
                    bus["/Voltages/%s" % (re.sub("[^A-Za-z0-9_]+", "", currentCell))] = cellVoltages_dict[currentCell]

            # send battery state
            bus["/System/NrOfCellsPerBattery"] = settings.NR_OF_CELLS_PER_BATTERY
            bus["/System/NrOfModulesOnline"] = NrOfModulesOnline
            bus["/System/NrOfModulesOffline"] = NrOfModulesOffline
            bus["/System/NrOfModulesBlockingCharge"] = NrOfModulesBlockingCharge
            bus["/System/NrOfModulesBlockingDischarge"] = NrOfModulesBlockingDischarge

            # send alarms
            bus["/Alarms/LowVoltage"] = LowVoltage_alarm
            bus["/Alarms/HighVoltage"] = HighVoltage_alarm
            bus["/Alarms/LowCellVoltage"] = LowCellVoltage_alarm
            bus["/Alarms/HighCellVoltage"] = HighCellVoltage_alarm
            bus["/Alarms/LowSoc"] = LowSoc_alarm
            bus["/Alarms/HighChargeCurrent"] = HighChargeCurrent_alarm
            bus["/Alarms/HighDischargeCurrent"] = HighDischargeCurrent_alarm
            bus["/Alarms/CellImbalance"] = CellImbalance_alarm
            bus["/Alarms/InternalFailure"] = InternalFailure_alarm
            bus["/Alarms/HighChargeTemperature"] = HighChargeTemperature_alarm
            bus["/Alarms/LowChargeTemperature"] = LowChargeTemperature_alarm
            bus["/Alarms/HighTemperature"] = HighTemperature_alarm
            bus["/Alarms/LowTemperature"] = LowTemperature_alarm
            bus["/Alarms/BmsCable"] = BmsCable_alarm

            # send charge/discharge control
            bus["/Info/MaxChargeCurrent"] = MaxChargeCurrent
            bus["/Info/MaxDischargeCurrent"] = MaxDischargeCurrent
            bus["/Info/MaxChargeVoltage"] = MaxChargeVoltage

            """
            # Not working, Serial Battery disapears regardles BLOCK_ON_DISCONNECT is True or False
            if BmsCable_alarm == 0:
                bus["/Info/MaxChargeCurrent"] = MaxChargeCurrent
                bus["/Info/MaxDischargeCurrent"] = MaxDischargeCurrent
                bus["/Info/MaxChargeVoltage"] = MaxChargeVoltage
            # if BMS connection lost
            else:
                bus["/Info/MaxChargeCurrent"] = 0
                bus["/Info/MaxDischargeCurrent"] = 0
                bus["/Info/MaxChargeVoltage"] = NR_OF_CELLS_PER_BATTERY * min(CHARGE_VOLTAGE_LIST)
                logging.error("BMS connection lost.")
            """

            # this does not control the charger, is only displayed in GUI
            bus["/Io/AllowToCharge"] = AllowToCharge
            bus["/Io/AllowToDischarge"] = AllowToDischarge
            bus["/Io/AllowToBalance"] = AllowToBalance

        # ##########################################################
        # ################ Periodic logging ########################
        # ##########################################################

        if settings.LOG_PERIOD > 0 and int(tt.time()) - self._logLastPrintTimeStamp >= settings.LOG_PERIOD:
            self._logLastPrintTimeStamp = int(tt.time())
            logging.info(f"Repetitive logging (every {settings.LOG_PERIOD}s)")
            logging.info("|- CVL: %.1fV, CCL: %.0fA, DCL: %.0fA" % (MaxChargeVoltage, MaxChargeCurrent, MaxDischargeCurrent))
            logging.info("|- Bat. voltage: %.1fV, Bat. current: %.0fA, SoC: %.1f%%, Balancing state: %d" % (Voltage, Current, Soc, self._balancing))
            logging.info(
                "|- Min. cell voltage: %s: %.3fV, Max. cell voltage: %s: %.3fV, difference: %.3fV"
                % (
                    MinVoltageCellId,
                    MinCellVoltage,
                    MaxVoltageCellId,
                    MaxCellVoltage,
                    MaxCellVoltage - MinCellVoltage,
                )
            )

        return True


# ################
# ################
# ## Main loop ###
# ################
# ################


def main():

    logging.basicConfig(level=settings.LOGGING)

    logging.info("")
    logging.info("*** Starting dbus-aggregate-batteries ***")

    # show Venus OS version and device type
    logging.info(
        "Venus OS " + Functions.get_venus_os_version() + " (" + Functions.get_venus_os_image_type() + ") running on " + Functions.get_venus_os_device_type()
    )

    # show the version of the driver
    logging.info(f"dbus-aggregate-batteries v{VERSION}")

    # print config errors and exit if there are any
    if settings.errors_in_config:
        logging.error("Errors in config file:")

        for error in settings.errors_in_config:
            logging.error(f"|- {error}")

        logging.error("")
        logging.error("Please fix the errors in the config file and restart the program.")
        tt.sleep(settings.TIME_BEFORE_RESTART)
        sys.exit(1)

    logging.info("========== Settings ==========")
    logging.info("|- NR_OF_BATTERIES: %d" % settings.NR_OF_BATTERIES)
    logging.info("|- NR_OF_CELLS_PER_BATTERY: %d" % settings.NR_OF_CELLS_PER_BATTERY)
    logging.info("|- UPDATE_INTERVAL_FIND_DEVICES: %d s" % settings.UPDATE_INTERVAL_FIND_DEVICES)
    logging.info("|- UPDATE_INTERVAL_DATA: %d s" % settings.UPDATE_INTERVAL_DATA)

    from dbus.mainloop.glib import DBusGMainLoop

    # Check if old value files exist, if yes rename them
    if os.path.isfile("/data/apps/dbus-aggregate-batteries/charge"):
        os.rename(
            "/data/apps/dbus-aggregate-batteries/charge",
            "/data/apps/dbus-aggregate-batteries/storedvalue_charge",
        )
        logging.info("Charge file renamed to storedvalue_charge")

    if os.path.isfile("/data/apps/dbus-aggregate-batteries/last_balancing"):
        os.rename(
            "/data/apps/dbus-aggregate-batteries/last_balancing",
            "/data/apps/dbus-aggregate-batteries/storedvalue_last_balancing",
        )
        logging.info("Bast_balancing file renamed to storedvalue_last_balancing")

    DBusGMainLoop(set_as_default=True)

    DbusAggBatService()

    logging.info("Connected to DBus, and switching over to GLib.MainLoop()")
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()
