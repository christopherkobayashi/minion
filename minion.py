#! /usr/bin/env python3

import sys
import paho.mqtt.client as mqtt
import json
import time
import configparser
import datetime
import asyncio
from kasa import SmartBulb
from typing import NamedTuple

# IKEA

config = []
blobs = []
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
        devices:           list[MinionDevice]

def read_config(config_file):
        devices = []
        config = configparser.RawConfigParser()
        config.read(config_file)
        for section in config.sections():
          if section != "global":
            print(section)
            device_parsed = MinionDevice (
                            config.get (section, 'device'),
                            config.getint (section, 'endpoint'),
                            config.get (section, 'trigger'),
                            config.get (section, 'targets').split(),
                            config.get (section, 'type'),
                            )
            devices.append(device_parsed)
            lastfrobbed[section] = 0
        config_parsed = MinionConfig     (
                        config.get      ('global', 'mqtt_server'),
                        config.getint   ('global', 'mqtt_port'),
                        devices
                )

        for device in config_parsed.devices:
          print("registered:", device.device, "endpoint:", device.endpoint, "targets:", device.targets)
        
        return config_parsed

def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))
    client.subscribe("tele/zigbee_bridge/SENSOR/#")

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
      print("weird, %s is neither on nor off", bulb)

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    global config
    global lastfrobbed
    print(msg.topic+" "+str(msg.payload))
    payload_string=str(msg.payload.decode("utf-8","ignore"))
    payload = json.loads(payload_string)
    for blob in config.devices:
      try:
        if blob.device in payload["ZbReceived"]:
          print("match %s" % blob.device)
          if blob.trigger in payload["ZbReceived"][blob.device] and blob.endpoint == payload["ZbReceived"][blob.device]["Endpoint"]:
            print("power button hit")
            if int(time.time()) > (lastfrobbed[blob.device]) + 5:
              if blob.type == "tplink":
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                for target in blob.targets:
                  result = loop.run_until_complete(toggle_bulb(target, "toggle"))
              elif blob.type == "tasmota":
                for target in blob.targets:
                  print("cmnd/%s/POWER" % target)  
                  client.publish("cmnd/%s/POWER" % target, payload="TOGGLE")
              elif blob.type == "zigbee":
                for target in blob.targets:
                  cmnd = '{"Device":"%s","Send":{"Power": "toggle"}}' % target
                  print(cmnd)
                  client.publish("cmnd/zigbee_bridge/ZbSend", payload=cmnd)
              else:
                print("unhandled type %s" % blob.type)
              lastfrobbed[blob.device] = int(time.time())
      except:
        print("something happened, comment the exception handler and try again")

def main():
  try:
    global config
    config = read_config('./minion.ini')
  except:
    print('No configuration file.')
    sys.exit()
  client = mqtt.Client()
  client.on_connect = on_connect
  client.on_message = on_message

  client.connect(config.mqtt_server, config.mqtt_port, 60)

  # Blocking call that processes network traffic, dispatches callbacks and
  # handles reconnecting.
  # Other loop*() functions are available that give a threaded interface and a
  # manual interface.
  client.loop_forever()

if __name__ == "__main__":
    main()
