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
from datetime import datetime
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
        mqtt_channels: list[str]
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
                        config.get      ('global', 'mqtt_channels').split(),
                        devices
                )

        for device in config_parsed.devices:
          print(datetime.now(), "registered:", device.device, "endpoint:", device.endpoint, "targets:", device.targets)
        
        return config_parsed

def on_connect(mqtt_client, userdata, flags, rc):
  global config
  print(datetime.now(), "Connected with result code", rc)
  for channel in config.mqtt_channels:
    mqtt_client.subscribe( channel )

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
      print(datetime.now(), "weird, %s is neither on nor off" % bulb)

def tplink_command(target, command):
  try:
    print(datetime.now(), "tplink_command:", target)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(toggle_bulb(target, "toggle"))
  except:
    print(datetime.now(), "something fried with tp-link %s" % target)

def tasmota_command(target, command):
  global mqtt_client
  try:
    print(datetime.now(), "tasmota_command:", target)
    mqtt_client.publish("cmnd/%s/POWER" % target, payload=command.upper())
  except:
    print(datetime.now(), "something fried with tasmota %s" % target)

def zigbee_command(target, command):
  global mqtt_client
  try:
    print(datetime.now(), "zigbee_command:", target)
    if command == 'DimmerUp':
      cmnd = '{"device":"' + target + '","send": {"DimmerUp"} }'
    elif command == 'DimmerDown':
      cmnd = '{"Device":"' + target + '","Send":{"DimmerDown"}}'
    else:
      cmnd = '{"Device":"' + target + '","Send":{"Power": "' + command + '"}}'
    print(datetime.now(), "ZbSend: ", cmnd)
    mqtt_client.publish("cmnd/zigbee_bridge/ZbSend", payload=cmnd)
  except:
    print(datetime.now(), "something fried with tasmota %s" % target)

def goodnight():
  global config
  targets = set()
  for target in config.devices:
    for end_target in target.targets:
      targets.add(end_target)
  for thisone in targets:
    if thisone not in config.nightlight_targets:
        eval(config.nightlight_targets_type + '_command(thisone, "off")')

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

    # Run scheduled events -- handle this elsewhere?
    schedule.run_pending()

    try:
      payload_string = str(msg.payload.decode("utf-8","ignore"))
    except:
      print(datetime.now(), "could not decode UTF-8 payload, ignoring")
      return

    try:
      payload = json.loads(payload_string)
    except:
      print(datetime.now(), "json.loads failed, ignoring")
      return


    topic_split = msg.topic.split('/')

    if topic_split[0] == 'deconz':
      device = topic_split[-1]
      print (datetime.now(), 'deconz, with device "'+device+'"')
      for blob in config.devices:
        if device == blob.device:
          if payload['button'] is not None and blob.endpoint == int(payload['button'][-1]):
            if int(time.time()) > (lastfrobbed[blob.device]) + config.switch_debounce:
              for target in blob.targets:
                eval(blob.type + '_command(target, "toggle")')
              lastfrobbed[blob.device] = int(time.time())
            else:
              print(datetime.now(), "debouncing for %i seconds" % config.switch_debounce)
#          return
      
      return

    # not deconz, so do legacy stuff
    for blob in config.devices:
      try:
        if blob.device in payload["ZbReceived"]:
          print(datetime.now(), "match %s" % blob.device)
          if blob.trigger in payload["ZbReceived"][blob.device] and blob.endpoint == payload["ZbReceived"][blob.device]["Endpoint"]:
            print(datetime.now(), "power button hit")
            if int(time.time()) > (lastfrobbed[blob.device]) + config.switch_debounce:
              for target in blob.targets:
                eval(blob.type + '_command(target, "toggle")')
              lastfrobbed[blob.device] = int(time.time())
            else:
              print(datetime.now(), "debouncing for %i seconds" % config.switch_debounce)
          # we need to do this right
          elif '0008!06' in payload["ZbReceived"][blob.device] and blob.endpoint == payload["ZbReceived"][blob.device]["Endpoint"]:
            print(datetime.now(), "dimmer_up hit")
            if int(time.time()) > (lastfrobbed[blob.device]) + config.switch_debounce:
              for target in blob.targets:
                eval(blob.type + '_command(target, "DimmerUp")')
              lastfrobbed[blob.device] = int(time.time())
            else:
              print(datetime.now(), "debouncing for %i seconds" % config.switch_debounce)
          # we need to do this right
          elif '0008!02' in payload["ZbReceived"][blob.device] and blob.endpoint == payload["ZbReceived"][blob.device]["Endpoint"]:
            print(datetime.now(), "dimmer_down hit")
            if int(time.time()) > (lastfrobbed[blob.device]) + config.switch_debounce:
              for target in blob.targets:
                eval(blob.type + '_command(target, "DimmerDown")')
              lastfrobbed[blob.device] = int(time.time())
            else:
              print(datetime.now(), "debouncing for %i seconds" % config.switch_debounce)

      except:
        print(datetime.now(), "No ZbReceived in payload")

def main():
  global mqtt_client
  global config
  config = read_config('./minion.ini')
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
      print(datetime.now(), "Exiting.")
      sys.exit()

if __name__ == "__main__":
    main()
