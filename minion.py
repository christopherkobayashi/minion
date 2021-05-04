#! /usr/bin/env python3

import paho.mqtt.client as mqtt
import requests # this goes away when we figure out zigbee commands over mqtt
import json
import time
import configparser
import datetime
import asyncio
import urllib
from kasa import SmartBulb
from typing import NamedTuple

# IKEA

blobs = [
         {
           "device": "kitchen_wall",
           "endpoint": 1,
           "trigger": "0006!FD",
           "targets": [ "tp-link-bulb04", ],
           "type": "tplink",
           "last": 0,
         },
         {
           "device": "kitchen_wall",
           "endpoint": 2,
           "trigger": "0006!FD",
           "targets": [ "tasmota_D98452", ],
           "type": "tasmota",
           "last": 0,
         },
         {
           "device": "kitchen_wall",
           "endpoint": 3,
           "trigger": "0006!FD",
           "targets": [ "tasmota_D9792B", ],
           "type": "tasmota",
           "last": 0,
         },

         {
           "device": "bedroom_wall_switch",
           "endpoint": 1,
           "trigger": "0006!FD",
           "targets": [ "tp-link-bulb00", ],
           "type": "tplink",
           "last": 0,
         },

         # Laundry / Shower
         {
           "device": "bathroom_wall",
           "endpoint": 1,
           "trigger": "0006!FD",
           "targets": [ "tasmota_D9D44D", ],
           "type": "tasmota",
           "last": 0,
         },
         {
           "device": "bathroom_wall",
           "endpoint": 2,
           "trigger": "0006!FD",
           "targets": [ "tp-link-bulb05", ],
           "type": "tplink",
           "last": 0,
         },
         { # Shower IKEA
           "device": "0xBB38",
           "endpoint": 2,
           "trigger": "0006!02",
           "targets": [ "tp-link-bulb05", ],
           "type": "tplink",
           "last": 0,
         },

         # Stairwell
         {
           "device": "stairs_top",
           "endpoint": 1,
           "trigger": "0006!FD",
           "targets": [ "tasmota_6FDF8A", "tasmota_8F4CBF", ],
           "type": "tasmota",
           "last": 0,
         },
         {
           "device": "stairs_bottom",
           "endpoint": 1,
           "trigger": "0006!FD",
           "targets": [ "tasmota_6FDF8A", "tasmota_8F4CBF", ],
           "type": "tasmota",
           "last": 0,
         },

         {
           "device": "chris_ikea",
           "endpoint": 1,
           "trigger": "0006!02",
           "targets": [ "tp-link-bulb02", "light-laundry", "light-living1", "light-shower", ],
           "type": "tplink",
           "last": 0,
         },
         {
           "device": "chris_wall",
           "endpoint": 1,
           "trigger": "0006!FD",
           "targets": [ "tp-link-bulb02", "light-laundry", "light-living1", "light-shower", ],
           "type": "tplink",
           "last": 0,
         },
         {
           "device": "livingroom_wall",
           "endpoint": 1,
           "trigger": "0006!FD",
           "targets": [ "living_room_zb1", "living_room_zb2", "living_room_zb3", ],
           "type": "zigbee",
           "last": 0,
         },

       ]


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
    global blob
    print(msg.topic+" "+str(msg.payload))
    payload_string=str(msg.payload.decode("utf-8","ignore"))
    payload = json.loads(payload_string)
    for blob in blobs:
      try:  
        if blob["device"] in payload["ZbReceived"]:
          print("match %s" % blob["device"])
          if blob["trigger"] in payload["ZbReceived"][blob["device"]] and blob["endpoint"] == payload["ZbReceived"][blob["device"]]["Endpoint"]:
            print("power button hit")
            if int(time.time()) > (blob["last"] + 5):
              if blob["type"] == "tplink":
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                for target in blob["targets"]:
                  result = loop.run_until_complete(toggle_bulb(target, "toggle"))
              elif blob["type"] == "tasmota":
                for target in blob["targets"]:
                  print("bleah cmnd/%s/POWER" % target)  
                  client.publish("cmnd/%s/POWER" % target, payload="TOGGLE")
              elif blob["type"] == "zigbee":
                for target in blob["targets"]:
                  cmnd = '{"Device":"%s","Send":{"Power": "toggle"}}' % target
                  print(cmnd)
                  client.publish("cmnd/zigbee_bridge/ZbSend", payload=cmnd)
              else:
                print("unhandled type %s" % blob["type"])

              blob["last"] = int(time.time())
      except:
        print("no device in blob, continuing")

def main():
  client = mqtt.Client()
  client.on_connect = on_connect
  client.on_message = on_message

  client.connect("localhost", 1883, 60)

  # Blocking call that processes network traffic, dispatches callbacks and
  # handles reconnecting.
  # Other loop*() functions are available that give a threaded interface and a
  # manual interface.
  client.loop_forever()

if __name__ == "__main__":
    main()
