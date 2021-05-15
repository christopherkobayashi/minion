#! /usr/bin/env python3

import sys
import paho.mqtt.client as mqtt
import json
import schedule
import time
import configparser
import datetime
import asyncio
from kasa import SmartBulb
from typing import NamedTuple
#import astral

mqtt_client = mqtt.Client()
config = []
lastfrobbed = {}

class MinionDevice(NamedTuple):
        device:         str
        endpoint:       int
        trigger:        bytes
        targets:        list[str]
        type:           str

class MinionConfig(NamedTuple):
        mqtt_server:    str
        mqtt_port:      int
        switch_debounce: int
        goodnight: str
        nightlight_start: str
        nightlight_end: str
        nightlight_targets: list[str]
        nightlight_targets_type: str
        devices:        list[MinionDevice]

def read_config(config_file):
        devices = []
        config = configparser.RawConfigParser()
        config.read(config_file)
        for section in config.sections():
          if section != "global":
            device_parsed = MinionDevice (
                            config.get (section, 'device'),
                            config.getint (section, 'endpoint'),
                            config.get (section, 'trigger'),
                            config.get (section, 'targets').split(),
                            config.get (section, 'type'),
                            )
            devices.append(device_parsed)
            lastfrobbed[device_parsed.device] = 0
        config_parsed = MinionConfig     (
                        config.get      ('global', 'mqtt_server'),
                        config.getint   ('global', 'mqtt_port'),
                        config.getint   ('global', 'switch_debounce'),
                        config.get      ('global', 'goodnight'),
                        config.get      ('global', 'nightlight_start'),
                        config.get      ('global', 'nightlight_end'),
                        config.get      ('global', 'nightlight_targets').split(),
                        config.get      ('global', 'nightlight_targets_type'),
                        devices
                )

        for device in config_parsed.devices:
          print("registered:", device.device, "endpoint:", device.endpoint, "targets:", device.targets)
        
        return config_parsed

def on_connect(mqtt_client, userdata, flags, rc):
    print("Connected with result code "+str(rc))
    mqtt_client.subscribe("tele/zigbee_bridge/SENSOR/#")

async def toggle_bulb(bulb, state):
  p = SmartBulb(bulb)
  await p.update()
  if state == "off":
    await p.turn_on()
  elif state == "on":
    await p.turn_off()
  elif state == "toggle":
    if p.is_off:
      await p.turn_on()
    elif p.is_on:
      await p.turn_off()
    else:
      print("weird, %s is neither on nor off" % bulb)

def tplink_command(target, command):
  try:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(toggle_bulb(target, "toggle"))
  except:
    print("something fried with tp-link %s" % target)

def tasmota_command(target, command):
  global mqtt_client
  try:
    mqtt_client.publish("cmnd/%s/POWER" % target, payload=command.upper())
  except:
    print("something fried with tasmota %s" % target)

def zigbee_command(target, command):
  global mqtt_client
  try:
    cmnd = '{"Device":"%s","Send":{"Power": "toggle"}}' % target  # fixme!
    mqtt_client.publish("cmnd/zigbee_bridge/ZbSend", payload=cmnd)
  except:
    print("something fried with tasmota %s" % target)

def goodnight():
  global config
  for target in config.nightlight_targets:
    if target.targets not in config.nightlight_targets:
      eval(config.nightlight_targets_type + '_command(target, "off")')

def nightlight_on():
  global config
  for target in config.nightlight_targets:
    eval(config.nightlight_targets_type + '_command(target, "on")')

def nightlight_off():
  global config
  for target in config.nightlight_targets:
    eval(config.nightlight_targets_type + '_command(target, "off")')

# The callback for when a PUBLISH message is received from the server.
def on_message(mqtt_client, userdata, msg):
    global config
    global lastfrobbed
    print(msg.topic, str(msg.payload))

    # Run scheduled events -- handle this elsewhere?
    schedule.run_pending()

    try:
      payload_string = str(msg.payload.decode("utf-8","ignore"))
    except:
      print("could not decode UTF-8 payload, ignoring")
      return

    try:
      payload = json.loads(payload_string)
    except:
      print("json.loads failed, ignoring")
      return

    for blob in config.devices:
      try:
        if blob.device in payload["ZbReceived"]:
          print("match %s" % blob.device)
          if blob.trigger in payload["ZbReceived"][blob.device] and blob.endpoint == payload["ZbReceived"][blob.device]["Endpoint"]:
            print("power button hit")
            if int(time.time()) > (lastfrobbed[blob.device]) + config.switch_debounce:
              for target in blob.targets:
                eval(blob.type + '_command(target, "toggle")')
              lastfrobbed[blob.device] = int(time.time())
            else:
              print("debouncing for %i seconds" % config.switch_debounce)
      except:
        print("No ZbReceived in payload")

def main():
  global mqtt_client
  try:
    global config
    config = read_config('./minion.ini')
  except:
    print('No configuration file.')
    sys.exit()
  mqtt_client.on_connect = on_connect
  mqtt_client.on_message = on_message

  mqtt_client.connect(config.mqtt_server, config.mqtt_port, 60)

  # Schedule nightlight events
  schedule.every().day.at(config.nightlight_start).do(nightlight_on)
  schedule.every().day.at(config.nightlight_end).do(nightlight_off)

  # Schedule goodnight
  schedule.every().day.at(config.goodnight).do(goodnight)

  # Blocking call that processes network traffic, dispatches callbacks and
  # handles reconnecting.
  # Other loop*() functions are available that give a threaded interface and a
  # manual interface.
  while True:
    try:
      mqtt_client.loop_forever()
    except KeyboardInterrupt:
      print("Exiting.")
      sys.exit()
    except:
      print("Probably received json.decoder.JSONDecodeError: Invalid control character at")

if __name__ == "__main__":
    main()
