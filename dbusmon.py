#!/usr/bin/env python3

import os
import sys
import logging

# add ext folder to sys.path
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext", "velib_python"))

# optionally from victron
# sys.path.insert(1, "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")

from dbusmonitor import DbusMonitor, SCAN_CALL_TIMEOUT  # noqa: E402
from dbus.mainloop.glib import DBusGMainLoop  # noqa: E402

# from gi.repository import GLib  # not accessed


BUSITEM_INTERFACE = "com.victronenergy.BusItem"


class FollowingDbusMonitor(DbusMonitor):
    """A DbusMonitor that listens to BusItem signals per service, never from every sender.

    velib's constructor subscribes to PropertiesChanged and ItemsChanged with no
    sender, so dbus-daemon delivers every BusItem signal on the bus to this
    process and the handlers drop all but a few. On a Cerbo that is about ten
    wake-ups a second for nothing. Here those two receivers are replaced by one
    pair per service, registered under the service's well-known name: the
    daemon delivers a signal only if its sender owns that name at the time, and
    dbus-python follows the owner client-side, so the match survives an owner
    change. The pair is registered before the service is scanned, so nothing
    that changes after its GetItems is missed, and removed when it leaves the bus.

    Until follow_only() is called, every service the monitor scans is followed,
    so the device search reads a cache as live as before. After it, only the
    named services are. A read of any other one returns the default, as if the
    service were absent, rather than a value that has stopped updating: the
    driver's read guards handle a missing value, a stale one goes unnoticed.
    """

    def __init__(self, *args, **kwargs):
        self._followed = None
        """None: every service the monitor scans; otherwise the set to keep following"""

        self._receivers = {}
        """service name -> its (PropertiesChanged, ItemsChanged) receivers"""

        self._warned_unfollowed = set()
        super().__init__(*args, **kwargs)

    def _scan_dbus(self):
        # The base constructor subscribed from every sender just before calling this.
        self.dbusConn.remove_signal_receiver(self.handler_value_changes, "PropertiesChanged", BUSITEM_INTERFACE)
        self.dbusConn.remove_signal_receiver(self.handler_item_changes, "ItemsChanged", BUSITEM_INTERFACE, None, "/")
        super()._scan_dbus()

    def _is_followed(self, serviceName):
        return self._followed is None or serviceName in self._followed

    def _subscribe(self, serviceName):
        if serviceName in self._receivers:
            return
        self._receivers[serviceName] = (
            self.dbusConn.add_signal_receiver(
                self.handler_value_changes,
                dbus_interface=BUSITEM_INTERFACE,
                signal_name="PropertiesChanged",
                bus_name=serviceName,
                path_keyword="path",
                sender_keyword="senderId",
            ),
            self.dbusConn.add_signal_receiver(
                self.handler_item_changes,
                dbus_interface=BUSITEM_INTERFACE,
                signal_name="ItemsChanged",
                bus_name=serviceName,
                path="/",
                sender_keyword="senderId",
            ),
        )

    def _unsubscribe(self, serviceName):
        for receiver in self._receivers.pop(serviceName, ()):
            receiver.remove()

    def scan_dbus_service_inner(self, serviceName, *args, **kwargs):
        # Inside velib's try in scan_dbus_service: if subscribing fails, the scan
        # fails and the service stays out of the cache, which reads as missing.
        if self._is_followed(serviceName):
            self._subscribe(serviceName)
        return super().scan_dbus_service_inner(serviceName, *args, **kwargs)

    def _process_name_owner_changed(self, name, oldowner, newowner):
        if newowner == "":
            self._unsubscribe(name)
        super()._process_name_owner_changed(name, oldowner, newowner)

    def follow_only(self, serviceNames):
        """Keep following only ``serviceNames``; stop listening to every other service.

        Cheap when the set is unchanged, so it can be called on every update. Never
        raises: a service it cannot start following is treated as absent, and
        retried on the next call.
        """
        wanted = {str(name) for name in serviceNames if self.service_wanted(str(name))}
        if wanted == self._followed:
            return
        self._followed = set(wanted)
        for name in list(self._receivers):
            if name not in wanted:
                self._unsubscribe(name)
        for name in sorted(wanted):
            if name in self.servicesByName and name not in self._receivers:
                # not listened to until now, so its cached values may be stale
                try:
                    self._subscribe(name)
                    values = self.dbusConn.call_blocking(name, "/", BUSITEM_INTERFACE, "GetItems", "", [], timeout=SCAN_CALL_TIMEOUT)
                    self.handler_item_changes(values, self.servicesByName[name].id)
                except Exception:
                    logging.exception("dbusmonitor: could not start following %s, treating it as absent" % name)
                    self._unsubscribe(name)
                    self._followed.discard(name)
        logging.info("dbusmonitor: following only %s" % ", ".join(sorted(self._followed)))

    def get_value(self, serviceName, objectPath, default_value=None):
        if not self._is_followed(serviceName):
            if serviceName not in self._warned_unfollowed:
                self._warned_unfollowed.add(serviceName)
                logging.warning("dbusmonitor: %s is read but not followed, treating it as absent" % serviceName)
            return default_value
        return super().get_value(serviceName, objectPath, default_value)


class DbusMon:
    def __init__(self):
        dummy = {"code": None, "whenToLog": "configChange", "accessLevel": None}
        self.monitorlist = {
            "com.victronenergy.battery": {
                "/Connected": dummy,
                "/ProductName": dummy,
                "/CustomName": dummy,
                "/Serial": dummy,
                "/Mgmt/Connection": dummy,
                "/DeviceInstance": dummy,
                "/Dc/0/Voltage": dummy,
                "/Dc/0/Current": dummy,
                "/Dc/0/Power": dummy,
                "/InstalledCapacity": dummy,
                "/ConsumedAmphours": dummy,
                "/Capacity": dummy,
                "/Soc": dummy,
                "/Dc/0/Temperature": dummy,
                "/System/MaxTemperatureCellId": dummy,
                "/System/MaxCellTemperature": dummy,
                "/System/MinTemperatureCellId": dummy,
                "/System/MinCellTemperature": dummy,
                "/System/MaxVoltageCellId": dummy,
                "/System/MaxCellVoltage": dummy,
                "/System/MinVoltageCellId": dummy,
                "/System/MinCellVoltage": dummy,
                "/System/NrOfCellsPerBattery": dummy,
                "/System/NrOfModulesOnline": dummy,
                "/System/NrOfModulesOffline": dummy,
                "/System/NrOfModulesBlockingCharge": dummy,
                "/System/NrOfModulesBlockingDischarge": dummy,
                "/TimeToGo": dummy,
                "/Alarms/LowVoltage": dummy,
                "/Alarms/HighVoltage": dummy,
                "/Alarms/LowCellVoltage": dummy,
                "/Alarms/HighCellVoltage": dummy,
                "/Alarms/LowSoc": dummy,
                "/Alarms/HighChargeCurrent": dummy,
                "/Alarms/HighDischargeCurrent": dummy,
                "/Alarms/CellImbalance": dummy,
                "/Alarms/InternalFailure": dummy,
                "/Alarms/HighChargeTemperature": dummy,
                "/Alarms/LowChargeTemperature": dummy,
                "/Alarms/HighTemperature": dummy,
                "/Alarms/LowTemperature": dummy,
                "/Alarms/BmsCable": dummy,
                "/Io/AllowToCharge": dummy,
                "/Io/AllowToDischarge": dummy,
                "/Io/AllowToBalance": dummy,
                "/Voltages/Cell1": dummy,
                "/Voltages/Cell2": dummy,
                "/Voltages/Cell3": dummy,
                "/Voltages/Cell4": dummy,
                "/Voltages/Cell5": dummy,
                "/Voltages/Cell6": dummy,
                "/Voltages/Cell7": dummy,
                "/Voltages/Cell8": dummy,
                "/Voltages/Cell9": dummy,
                "/Voltages/Cell10": dummy,
                "/Voltages/Cell11": dummy,
                "/Voltages/Cell12": dummy,
                "/Voltages/Cell13": dummy,
                "/Voltages/Cell14": dummy,
                "/Voltages/Cell15": dummy,
                "/Voltages/Cell16": dummy,
                "/Voltages/Cell17": dummy,
                "/Voltages/Cell18": dummy,
                "/Voltages/Cell19": dummy,
                "/Voltages/Cell20": dummy,
                "/Voltages/Cell21": dummy,
                "/Voltages/Cell22": dummy,
                "/Voltages/Cell23": dummy,
                "/Voltages/Cell24": dummy,
                "/Voltages/Cell25": dummy,
                "/Voltages/Cell26": dummy,
                "/Voltages/Cell27": dummy,
                "/Voltages/Cell28": dummy,
                "/Voltages/Cell29": dummy,
                "/Voltages/Cell30": dummy,
                "/Voltages/Cell31": dummy,
                "/Voltages/Cell32": dummy,
                "/Voltages/Diff": dummy,
                "/Voltages/Sum": dummy,
                "/Info/MaxChargeCurrent": dummy,
                "/Info/MaxDischargeCurrent": dummy,
                "/Info/MaxChargeVoltage": dummy,
                "/Info/ChargeMode": dummy,
            },
            "com.victronenergy.dcload": {
                "/Connected": dummy,
                "/ProductName": dummy,
                "/CustomName": dummy,
                "/Serial": dummy,
                "/Mgmt/Connection": dummy,
                "/DeviceInstance": dummy,
                "/Dc/0/Voltage": dummy,
                "/Dc/0/Current": dummy,
                "/Dc/0/Power": dummy,
                "/Dc/0/Temperature": dummy,
                "/Alarms/HighVoltage": dummy,
                "/Alarms/HighStarterVoltage": dummy,
                "/Alarms/LowVoltage": dummy,
                "/Alarms/LowStarterVoltage": dummy,
                "/Alarms/HighTemperature": dummy,
                "/Alarms/LowTemperature": dummy,
            },
            "com.victronenergy.vebus": {
                "/Connected": dummy,
                "/Dc/0/Current": dummy,
                "/ProductName": dummy,
            },
            "com.victronenergy.solarcharger": {
                "/Dc/0/Current": dummy,
                "/ProductName": dummy,
            },
            "com.victronenergy.settings": {
                "/Settings/CGwacs/OvervoltageFeedIn": dummy,
            },
            "com.victronenergy.system": {
                "/SystemState/LowSoc": dummy,
                "/SystemState/BatteryLife": dummy,
            },
        }

        self.dbusmon = FollowingDbusMonitor(self.monitorlist, ignoreServices=["com.victronenergy.battery.aggregate"])

    def print_values(self, service, mon_list):
        for path in self.monitorlist[mon_list]:
            logging.info("%s: %s" % (path, self.dbusmon.get_value(service, path)))
        logging.info("\n")
        return True


################
# test program #
################


def main():
    logging.basicConfig(level=logging.INFO)
    DBusGMainLoop(set_as_default=True)
    dbusmon = DbusMon()

    # dbusmon.print_values('com.victronenergy.battery.ttyUSB2', 'com.victronenergy.battery')
    # dbusmon.print_values('com.victronenergy.vebus.ttyUSB0', 'com.victronenergy.vebus')
    # dbusmon.print_values('com.victronenergy.solarcharger.ttyUSB1', 'com.victronenergy.solarcharger')
    dbusmon.print_values("com.victronenergy.settings", "com.victronenergy.settings")
    dbusmon.dbusmon.set_value("com.victronenergy.settings", "/Settings/CGwacs/OvervoltageFeedIn", 0)

    # GLib.timeout_add(1000, dbusmon.print_values, 'com.victronenergy.battery.ttyUSB2')
    # Start and run the mainloop
    # logging.info("Battery monitor: Starting mainloop.\n")
    # mainloop = GLib.MainLoop()
    # mainloop.run()


if __name__ == "__main__":
    main()
