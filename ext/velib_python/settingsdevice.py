import dbus
import logging
import time
from functools import partial

# Local imports
from vedbus import VeDbusItemImport
from ve_utils import unwrap_dbus_value, wrap_dbus_value

## Indexes for the setting dictonary.
PATH = 0
VALUE = 1
MINIMUM = 2
MAXIMUM = 3
SILENT = 4

VE_INTERFACE = "com.victronenergy.BusItem"

## VeDbusSettingItem class, our own proxy that's lighter than what dbus-python has
class VeDbusSettingItem(object):
	def __new__(cls, bus, serviceName, path, *args, **kwargs):
		o = object.__new__(cls)

		# This is called once, when the first VeDbusSettingItem is created
		if "_tracked" not in VeDbusSettingItem.__dict__:
			VeDbusSettingItem._tracked = {}

			# Track changes on service
			bus.add_signal_receiver(VeDbusSettingItem._setting_changed_handler,
				"PropertiesChanged", dbus_interface=VE_INTERFACE,
				bus_name=serviceName, path_keyword='path')
			bus.add_signal_receiver(VeDbusSettingItem._items_changed_handler,
				"ItemsChanged", dbus_interface=VE_INTERFACE,
				bus_name=serviceName, path="/")

		return o

	@staticmethod
	def _setting_changed_handler(change, path=None):
		try:
			o = VeDbusSettingItem._tracked[path]
		except KeyError:
			pass # Not our setting
		else:
			o._value = unwrap_dbus_value(change['Value'])
			try:
				t = change['Text']
			except KeyError:
				t = str(o._value)

			o._callback(o._servicename, o._path, {
				'Value': o._value, 'Text': t})

	@staticmethod
	def _items_changed_handler(items):
		if not isinstance(items, dict):
			return
		for path, changes in items.items():
			try:
				o = self._tracked[path]
				v = changes['Value']
			except KeyError:
				continue # Not our setting, or no value

			try:
				t = changes['Text']
			except KeyError:
				t = str(unwrap_dbus_value(v))

			o._value = unwrap_dbus_value(v)
			o._callback(o._servicename, o._path, { 'Value': o._value, 'Text': t})

	def __init__(self, bus, servicename, path, callback, initial_value=None):
		self._bus = bus
		self._servicename = servicename
		self._path = path
		self._callback = callback
		self._value = initial_value
		self._tracked[path] = self

	def __del__(self):
		try:
			del self._tracked[self._path]
		except (AttributeError, KeyError):
			pass

	def get_value(self):
		return self._value

	def set_value(self, v):
		return self._bus.call_blocking(self._servicename, self._path,
				dbus_interface=VE_INTERFACE, method='SetValue', signature="v",
				args=[wrap_dbus_value(v)])

	def set_default(self):
		return self._bus.call_blocking(self._servicename, self._path,
				dbus_interface=VE_INTERFACE, method='SetDefault', signature="",
				args=[])

## The Settings Device class.
# Used by python programs, such as the vrm-logger, to read and write settings they
# need to store on disk. And since these settings might be changed from a different
# source, such as the GUI, the program can pass an eventCallback that will be called
# as soon as some setting is changed.
#
# The settings are stored in flash via the com.victronenergy.settings service on dbus.
# See https://github.com/victronenergy/localsettings for more info.
#
# If there are settings in de supportSettings list which are not yet on the dbus, 
# and therefore not yet in the xml file, they will be added through the dbus-addSetting
# interface of com.victronenergy.settings.
class SettingsDevice(object):
	## The constructor processes the tree of dbus-items.
	# @param bus the system-dbus object
	# @param name the dbus-service-name of the settings dbus service, 'com.victronenergy.settings'
	# @param supportedSettings dictionary with all setting-names, and their defaultvalue, min, max and whether
	# the setting is silent. The 'silent' entry is optional. If set to true, no changes in the setting will
	# be logged by localsettings.
	# @param eventCallback function that will be called on changes on any of these settings
	# @param timeout Maximum interval to wait for localsettings. An exception is thrown at the end of the
	# interval if the localsettings D-Bus service has not appeared yet.
	def __init__(self, bus, supportedSettings, eventCallback, name='com.victronenergy.settings', timeout=0):
		logging.debug("===== Settings device init starting... =====")
		self._bus = bus
		self._dbus_name = name
		self._eventCallback = eventCallback
		self._values = {} # stored the values, used to pass the old value along on a setting change
		self._settings = {}

		count = 0
		while True:
			if 'com.victronenergy.settings' in self._bus.list_names():
				break
			if count == timeout:
				raise Exception("The settings service com.victronenergy.settings does not exist!")
			count += 1
			logging.info('waiting for settings')
			time.sleep(1)

		# Add the items.
		self.addSettings(supportedSettings)

		logging.debug("===== Settings device init finished =====")

	def addSettings(self, settings):
		# We need a lookup table to map the path back to the setting name/alias
		lookup = {options[PATH]: setting for setting, options in settings.items()}
		li = [{
			"path": options[PATH],
			"default": options[VALUE],
			"min": options[MINIMUM],
			"max": options[MAXIMUM],
			"silent": len(options) > SILENT and options[SILENT]
		} for setting, options in settings.items()]
		result = self._bus.call_blocking(self._dbus_name, '/',
			'com.victronenergy.Settings', 'AddSettings',
			'aa{sv}', [li])

		for r in result:
			if (error := r["error"]) == 0:
				setting = lookup[r['path']]
				busitem = VeDbusSettingItem(self._bus, self._dbus_name,
					r["path"],
					callback=partial(self.handleChangedSetting, setting),
					initial_value=unwrap_dbus_value(r['value']))
				self._settings[setting] = busitem
				self._values[setting] = busitem.get_value()
			else:
				logging.error(f"Failed to add setting {r['path']}, error {error}")


	def addSetting(self, path, value, _min, _max, silent=False, callback=None):
		busitem = VeDbusItemImport(self._bus, self._dbus_name, path, callback)
		if busitem.exists and (value, _min, _max, silent) == busitem._proxy.GetAttributes():
			logging.debug("Setting %s found" % path)
		else:
			logging.info("Setting %s does not exist yet or must be adjusted" % path)

			# Prepare to add the setting. Most dbus types extend the python
			# type so it is only necessary to additionally test for Int64.
			if isinstance(value, (int, dbus.Int64)):
				itemType = 'i'
			elif isinstance(value, float):
				itemType = 'f'
			else:
				itemType = 's'

			# Add the setting
			# TODO, make an object that inherits VeDbusItemImport, and complete the D-Bus settingsitem interface
			settings_item = VeDbusItemImport(self._bus, self._dbus_name, '/Settings', createsignal=False)
			setting_path = path.replace('/Settings/', '', 1)
			if silent:
				settings_item._proxy.AddSilentSetting('', setting_path, value, itemType, _min, _max)
			else:
				settings_item._proxy.AddSetting('', setting_path, value, itemType, _min, _max)

			busitem = VeDbusItemImport(self._bus, self._dbus_name, path, callback)

		return busitem

	def handleChangedSetting(self, setting, servicename, path, changes):
		oldvalue = self._values[setting] if setting in self._values else None
		self._values[setting] = changes['Value']

		if self._eventCallback is None:
			return

		self._eventCallback(setting, oldvalue, changes['Value'])

	def setDefault(self, path):
		item = VeDbusItemImport(self._bus, self._dbus_name, path, createsignal=False)
		item.set_default()

	def __getitem__(self, setting):
		return self._settings[setting].get_value()

	def __setitem__(self, setting, newvalue):
		result = self._settings[setting].set_value(newvalue)
		if result != 0:
			# Trying to make some false change to our own settings? How dumb!
			assert False
