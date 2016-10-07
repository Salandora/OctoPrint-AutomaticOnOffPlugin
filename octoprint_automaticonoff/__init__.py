###############################
##
##
## Based on foosel OctoPrint-PbPiLink Plugin
## https://github.com/foosel/OctoPrint-PbPiLink
##
##
###############################


# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import threading
from octoprint.events import Events

from octoprint_automaticonoff.api import SwitchOnOffApiPlugin

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

	EVENTS_NOCLIENTS = (Events.CLIENT_OPENED, Events.CLIENT_CLOSED, Events.PRINT_DONE)
	EVENTS_DISCONNECT = (Events.DISCONNECTED,)

	def __init__(self):
		self._connection_data = None
		self._clients = 0
		self._client_poweroff_timer = None

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
                    disconnect=True
                )
            ),
            noclients_countdown=5,
            api = ""
		)

	def initialize(self):
		if self._settings.get_boolean(["power", "on", "connect"]):
			original_connect = self._printer.connect
			def wrapped_connect(*args, **kwargs):
				self._poweron(connect=False)
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
		from flask import jsonify

		return jsonify(**self._status())

	def get_api_commands(self):
		return dict(
			power_on=[],
			power_off=[],
			list_apis=[]
		)

	def on_api_command(self, command, data):
		from flask import jsonify

		if command == "power_on":
			self._poweron()

		elif command == "power_off":
			self._poweroff()
			
		elif command == "list_apis":
			return jsonify(**dict(apis=self.get_apiplugins()))

		return jsonify(**self._status())

	def _status(self):
		return dict(power=self._get_power())

	##~~ EventHandlerPlugin

	def on_event(self, event, payload):
		if not event in self.__class__.EVENTS_NOCLIENTS and not event in self.__class__.EVENTS_DISCONNECT:
			return

		if event in self.__class__.EVENTS_NOCLIENTS:
			if event == Events.CLIENT_OPENED:
				if self._clients == 0 and self._settings.get_boolean(["power", "on", "clients"]):
					self._poweron()
				self._clients += 1

			elif event == Events.CLIENT_CLOSED:
				self._clients -= 1

			if self._clients <= 0:
				self._clients = 0
				self._client_poweroff_timer = threading.Timer(self._settings.get_float(["noclients_countdown"]) * 60, self._noclients_poweroff)
				self._client_poweroff_timer.start()
			elif self._client_poweroff_timer is not None:
				self._client_poweroff_timer.cancel()
				self._client_poweroff_timer = None

		elif event in self.__class__.EVENTS_DISCONNECT:
			if self._settings.get_boolean(["power", "off", "disconnect"]):
				self._poweroff(disconnect=False)

	##~~ Helpers

	def _poweron(self, connect=True):
		self._set_power(True)
		if connect and self._connection_data is not None:
			state, port, baudrate, printer_profile = self._connection_data
			if state != "Operational":
				return
			self._printer.connect(port=port, baudrate=baudrate, printer_profile=printer_profile)

	def _poweroff(self, disconnect=True):
		self._connection_data = self._printer.get_current_connection()
		if disconnect:
			self._printer.disconnect()
			
		self._set_power(False)

	def _noclients_poweroff(self):
		if self._printer.is_printing():
			return

		if not self._settings.get_boolean(["power", "off", "noclients"]):
			return

		self._logger.info("Powering off after not seeing any clients after {}minute/s".format(self._settings.get_float(["noclients_countdown"])))
		self._poweroff()

	def _set_power(self, enable):
		api = self.get_api()
		if api is None:
			return
		
		if enable:
			self._logger.info("Enabling power supply")
		else:
			self._logger.info("Disabling power supply")
			
		api.set_power(enable)	
	
	def _get_power(self):
		api = self.get_api()
		if api is None:
			return State.UNKNOWN
		
		return api.get_power()

__plugin_name__ = "Automatic On/Off Plugin"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = AutomaticOnOffPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}

