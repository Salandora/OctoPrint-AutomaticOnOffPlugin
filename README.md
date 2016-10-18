# Automatic On/Off Plugin

This plugin relies on other API-Plugins which implement the methods to e.g. switch GPIOs, talk to a micro controller, do what ever is necessary to swith on the relay

---

Plugin to control a Relai card.

Will add a toggle button for a 12V power supply to the navigation bar

## Setup

Install via the bundled [Plugin Manager](https://github.com/foosel/OctoPrint/wiki/Plugin:-Plugin-Manager)
or manually using this URL:

    https://github.com/Salandora/OctoPrint-AutomaticOnOffPlugin/archive/master.zip

## Actual API Plugins

  Raspberry Pi: https://github.com/Salandora/OctoPrint-RaspberryPiApi
                This one is especially for the Raspberry.

  Generic Command: https://github.com/Salandora/OctoPrint-CommandApi
		   This one is a generic one, you'll need to provide it with some terminal command e.g. gpio mode ... or a shell script
