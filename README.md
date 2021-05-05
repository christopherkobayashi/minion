# minion 
A minimal, python-based home automation daemon.

## What?
This is a small python daemon that receives MQTT events and issues device commands.

## Why?
I wanted a small, non-GUI, deterministic way to control my TP-Link and Tasmota bulbs/switches  from my Zigbee wall switches.

Both HomeAssistant and Domoticz are overkill, and both suffer from "shiny syndrome".

## How?

Install the paho-mqtt, python-kasa (NOT "kasa"), and scheduler modules.  Edit the .ini to associate devices (as seen in the Zigbee coordinator's mqtt topics), triggers (derived from the Tasmota console), and targets (mqtt topic or TP-Link hostname).

## Notes

Switch events are debounced for five seconds regardless of need.  That should be revisited.

A separate thread should be created to handle time-based events (i.e., toggle lights at sunrise/sunset.
