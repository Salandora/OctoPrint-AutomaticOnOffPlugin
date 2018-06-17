###############################
##
##
## Based on foosel's OctoPrint-PbPiLink Plugin
## https://github.com/foosel/OctoPrint-PbPiLink
##
##
###############################


# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import threading
from flask import jsonify
from octoprint.events import Events

from octoprint_automaticonoff.api import SwitchOnOffApiPlugin
from time import sleep

class State(object):
	ON = "on",
	OFF = "off",
	UNKNOWN = "unknown"


class AutomaticOnOffPlugin(octoprint.plugin.TemplatePlugin,
							octoprint.plugin.SettingsPlugin,
							octoprint.plugin.StartupPlugin,
							octoprint.plugin.ShutdownPlugin,
							octoprint.plugin.SimpleApiPlugin,
							octoprint.plugin.AssetPlugin,
							octoprint.plugin.EventHandlerPlugin):

	EVENTS_PRINT = (Events.PRINT_STARTED, Events.PRINT_DONE)
	EVENTS_NOCLIENTS = (Events.CLIENT_OPENED, Events.CLIENT_CLOSED, Events.PRINT_DONE)
	EVENTS_DISCONNECT = (Events.DISCONNECTED)
	EVENTS_POWER = (Events.POWER_ON, Events.POWER_OFF)

	def __init__(self):
		self._connection_data = None
		self._clients = 0
		self._client_poweroff_timer = None

		self._idle_poweroff_timer = None

	##~~ Settings
	def get_settings_defaults(self):
		return dict(
			power = dict(
				on = dict(
					startup=True,
					clients=False,
					connect=True,
				),
				off = dict(
					shutdown=True,
					noclients=False,
					idle=False,
					disconnect=True,
					temperature=False,
				)
			),
			idle = dict(
				countdown=5,
				ignore_commands="M105"
			),
			temperature=40,
			autoconnect_delay = 5,
			noclients_countdown=5,
			reconnect_after_error=True,
			api = ""
		)

	def initialize(self):
		if self._settings.get_boolean(["power", "on", "connect"]):
			original_connect = self._printer.connect
			def wrapped_connect(*args, **kwargs):
				self._poweron(connect=False)
				if self._settings.get(["autoconnect_delay"]) > 0:
					self._logger.info("autoconnect_delay %d", self._settings.get(["autoconnect_delay"]))
					threading.Timer(self._settings.get(["autoconnect_delay"]), original_connect, args, kwargs).start()
				else:
					original_connect(*args, **kwargs)

			self._printer.connect = wrapped_connect

	##~~ Softwareupdate hook
	def get_update_information(self):
		return dict(
			automaticonoff=dict(
				displayName="Automatik On/Off Plugin",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="Salandora",
				repo="OctoPrint-AutomaticOnOffPlugin",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/Salandora/OctoPrint-AutomaticOnOffPlugin/archive/{target_version}.zip"
			)
		)

	##~~ Assets
	def get_assets(self):
		return dict(
			js=[
				"js/automaticonoff.js",
				"js/automaticonoff_settings.js"
			]
		)

	##~~ Startup

	def get_apiplugins(self):
		result = []

		for name, plugin in self._plugin_manager.plugins.items():
			if isinstance(plugin.implementation, SwitchOnOffApiPlugin):
				result.append(dict(identifier = name, name=plugin.name))

		return result

	def get_api(self):
		api = self._settings.get(["api"])
		if api is "":
			return None

		plugin_info = self._plugin_manager.get_plugin_info(api)
		if plugin_info is not None:
			return plugin_info.implementation

		return None

	def on_startup(self, host, port):
		# Maybe necessary for a late state
		# setup serial port if necessary
		#import fnmatch
		#additional_ports = self._settings.global_get(["serial", "additionalPorts"])
		#if not any(map(lambda x: fnmatch.fnmatch("/dev/ttyAMA0", x), additional_ports)):
		#	self._logger.info("Raspberry Pi Serial Port not yet in additional ports, adding it")
		#	additional_ports.append("/dev/ttyAMA*")
		#	self._settings.global_set(["serial", "additionalPorts"], additional_ports)
		#	self._settings.save()

		# power on if configured as such
		if self._settings.get_boolean(["power", "on", "startup"]):
			self._poweron()

	##~~ Shutdown
	def on_shutdown(self):
		if self._settings.get_boolean(["power", "off", "shutdown"]):
			self._poweroff(False)

		api = self.get_api()
		if api is None:
			return

		api.on_shutdown()

	##~~ SimpleAPI
	def is_api_adminonly(self):
		return True

	def on_api_get(self, request):
		return jsonify(**self._status())

	def get_api_commands(self):
		return dict(
			power_on=[],
			power_off=[],
			list_apis=[]
		)

	def on_api_command(self, command, data):
		if command == "power_on":
			self._poweron()

		elif command == "power_off":
			self._poweroff()

		elif command == "list_apis":
			return jsonify(**dict(apis=self.get_apiplugins()))

	def _status(self):
		return dict(power=self._get_power())

	##~~ EventHandlerPlugin
	def on_event(self, event, payload):
		if event not in self.EVENTS_NOCLIENTS and \
			event not in self.EVENTS_DISCONNECT and \
			event not in self.EVENTS_POWER and \
			event not in self.EVENTS_PRINT:
			return

		if event in self.EVENTS_PRINT:
			if event == Events.PRINT_STARTED:
				self._stop_timers()
			elif event == Events.PRINT_DONE:
				self._start_idle_timer()

		if event in self.EVENTS_NOCLIENTS:
			if event == Events.CLIENT_OPENED:
				if self._clients == 0 and self._settings.get_boolean(["power", "on", "clients"]):
					self._poweron()
				self._clients += 1
			elif event == Events.CLIENT_CLOSED:
				self._clients -= 1

			if self._clients <= 0:
				self._clients = 0
				self._start_client_timer()
			elif self._client_poweroff_timer is not None:
				self._stop_client_timer()

		elif event in self.EVENTS_DISCONNECT:
			self._stop_timers()
			if self._settings.get_boolean(["power", "off", "disconnect"]):
				self._poweroff(disconnect=False)

		elif event in self.EVENTS_POWER:
			if event == Events.POWER_ON:
				self._poweron()
			elif event == Events.POWER_OFF:
				self._poweroff()

	def _stop_idle_timer(self):
		if self._idle_poweroff_timer:
			self._idle_poweroff_timer.cancel()
			self._idle_poweroff_timer = None

	def _stop_client_timer(self):
		if self._client_poweroff_timer:
			self._client_poweroff_timer.cancel()
			self._client_poweroff_timer = None

	def _stop_timers(self):
		self._stop_idle_timer()
		self._stop_client_timer()

	def _start_idle_timer(self):
		if self._idle_poweroff_timer:
			self._stop_idle_timer()

		if self._settings.get_boolean(["power", "off", "idle"]):
			self._idle_poweroff_timer = threading.Timer(self._settings.get_float(["idle", "countdown"]) * 60, self._idle_poweroff)
			self._idle_poweroff_timer.start()

	def _start_client_timer(self):
		if self._client_poweroff_timer:
			self._stop_client_timer()

		if self._settings.get_boolean(["power", "off", "noclients"]):
			self._client_poweroff_timer = threading.Timer(self._settings.get_float(["noclients_countdown"]) * 60, self._noclients_poweroff)
			self._client_poweroff_timer.start()

	def on_sent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		ignore_commands = self._settings.get(["idle", "ignore_commands"])
		if self._printer.is_printing() or ignore_commands is None or ignore_commands.strip() is "":
			return

		ignore_commands = [x.strip() for x in ignore_commands.split(',')]
		if gcode is None or gcode in ignore_commands:
			return

		if self._settings.get_boolean(["power", "off", "idle"]):
			self._start_idle_timer()

	##~~ Helpers
	def _sendMessage(self, data=None):
		self._plugin_manager.send_plugin_message(self._identifier, data)

	def _poweron(self, connect=True):
		self._set_power(True)
		self._start_idle_timer()
		self._sendMessage(self._status())

		if connect and self._connection_data is not None:
			state, port, baudrate, printer_profile = self._connection_data
			if state != "Operational" and not (self._settings.get_boolean(["reconnect_after_error"]) and "Error" in state):
				return

			self._printer.connect(port=port, baudrate=baudrate, printer_profile=printer_profile)

	def _poweroff(self, disconnect=True):
		self._connection_data = self._printer.get_current_connection()
		if disconnect:
			self._printer.disconnect()

		self._set_power(False)
		self._sendMessage(self._status())
		self._stop_timers()

	def _wait_for_temperature(self):
		# Make a test every second
		while True:
			temperature = self._printer.get_current_temperatures()
			hottest = 0
			for values in temperature.values():
				hottest = values["actual"] if values["actual"] > hottest else hottest

			if hottest < self._settings.get_float(["temperature"]):
				break

			sleep(5)

	def _idle_poweroff(self):
		if not self._settings.get_boolean(["power", "off", "idle"]):
			return

		if self._settings.get_boolean(["power", "off", "temperature"]):
			self._wait_for_temperature()

		if self._printer.is_printing():
			self._logger.warning("Idle power off reached, but printer is printing.")
			self._stop_idle_timer()
			return

		self._logger.info("Powering off after idle state for {}minute/s".format(self._settings.get_float(["idle", "countdown"])))
		if self._settings.get_boolean(["power", "off", "temperature"]):
			self._logger.info("and temperature below {}C".format(self._settings.get_float(["temperature"])))

		self._poweroff()

	def _noclients_poweroff(self):
		if not self._settings.get_boolean(["power", "off", "noclients"]):
			return

		if self._settings.get_boolean(["power", "off", "temperature"]):
			self._wait_for_temperature()

		if self._printer.is_printing():
			self._logger.warning("No client power off reached, but printer is printing.")
			self._stop_client_timer()
			return

		self._logger.info("Powering off after not seeing any clients for {}minute/s".format(self._settings.get_float(["noclients_countdown"])))
		if self._settings.get_boolean(["power", "off", "temperature"]):
			self._logger.info("and temperature below {}C".format(self._settings.get_float(["temperature"])))

		self._poweroff()

	def _set_power(self, power):
		api = self.get_api()
		if api is None:
			return

		if power:
			self._logger.info("Enabling power supply")
		else:
			self._logger.info("Disabling power supply")

		api.set_power(power)

	def _get_power(self):
		api = self.get_api()
		if api is None:
			return State.UNKNOWN

		return api.get_power()

__plugin_name__ = "Automatic On/Off"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = AutomaticOnOffPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.comm.protocol.gcode.sent": __plugin_implementation__.on_sent
	}

