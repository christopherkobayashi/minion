#! /usr/bin/env python3

import sys
import paho.mqtt.client as mqtt
import json
import schedule
import time
import configparser
import datetime
import asyncio
import aiohttp
import websockets
from kasa import SmartBulb
from typing import NamedTuple
from datetime import datetime
from datetime import timedelta
from suntime import Sun, SunTimeException
from geopy import Nominatim

mqtt_client = mqtt.Client()
config = []
lastfrobbed = {}
sunset_job = datetime.now()
sunrise_job = datetime.now()

class SunStuff(NamedTuple):
        sunrise:        datetime
        sunset:         datetime

class MinionDevice(NamedTuple):
        device:         str
        endpoint:       int
        trigger:        bytes
        targets:        list[str]
        type:           str

class MinionConfig(NamedTuple):
        mqtt_server:    str
        mqtt_port:      int
        websocket:      str
        rest:           str
        switch_debounce: int
        location: str
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
                            config.getint (section, 'endpoint', fallback=1),
                            config.get (section, 'trigger', fallback='dummy'),
                            config.get (section, 'targets').split(),
                            config.get (section, 'type', fallback='tasmota'),
                            )
            devices.append(device_parsed)
            lastfrobbed[device_parsed.device] = 0
        config_parsed = MinionConfig     (
                        config.get      ('global', 'mqtt_server', fallback='localhost'),
                        config.getint   ('global', 'mqtt_port', fallback=1883),
                        config.get      ('global', 'websocket', fallback='ws://localhost:443/'),
                        config.get      ('global', 'rest', fallback='http://localhost/api/CHANGEME/'),
                        config.getint   ('global', 'switch_debounce', fallback=3),
                        config.get      ('global', 'location', fallback='Tokyo Japan'),
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

def get_sunstuff(location):
  geolocator = Nominatim(user_agent='myapplication')
  location = geolocator.geocode(location)
  sun = Sun(location.latitude, location.longitude)
  return SunStuff( sun.get_local_sunrise_time(), sun.get_local_sunset_time())

def on_connect(mqtt_client, userdata, flags, rc):
  global config
  print(datetime.now(), "Connected with result code", rc)
  for channel in config.mqtt_channels:
    mqtt_client.subscribe( channel )

async def extend_websocket_data(websocket_json):
  global config
  async with aiohttp.ClientSession() as session:

    handlers = {
                 "sensors": "sensors/" + websocket_json['id'],
                 "lights": "lights/" + websocket_json['id'],
                 "groups": "groups/" + websocket_json['id'],
               }

    try:
      if websocket_json['r'] in handlers:
        print(config.rest + handlers[websocket_json['r']])
        response = await rest_fetch(session, config.rest + handlers[websocket_json['r']])
        return json.loads(response)
    except:
      print(f"No extended REST data available for {websocket_json['r']}")
      pass
                
    return {}

async def websocket_message_loop(websocket):
  async for message in websocket:
    print(f"<<deconz<< {message}")
    message_json = json.loads(message)

    rest_extended_data = await extend_websocket_data(message_json)

    print("we are here0")

#    topic = mqtt_topic_function(message_json, rest_extended_data)
#    print("we are here1")
#    message = mqtt_message_function(message_json, rest_extended_data)
#    print("we are here2")

#    print(f">>mqtt>> topic: {topic}: {message}")
#    await send_mqtt(topic, message)

async def receive_deconz_messages():
  global config
  while True:
    try:
      async with websockets.connect(config.websocket) as websocket:
        await websocket_message_loop(websocket)
    except:
      pass

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
  global sunrise_job
  global sunset_job
  for target in config.nightlight_targets:
    eval(config.nightlight_targets_type + '_command(target, "on")')
  schedule.cancel_job(sunset_job)

  geolocator = Nominatim(user_agent='myapplication')
  location = geolocator.geocode(config.location)
  sun = Sun(location.latitude, location.longitude)
  sunrise = sun.get_local_sunrise_time()
  do_sunrise = sun.get_local_sunrise_time() + timedelta(minutes=30)
  print(datetime.now(), 'Scheduling sunrise for', do_sunrise.strftime('%H:%M'))
  sunrise_job = schedule.every().day.at(do_sunrise.strftime('%H:%M')).do(nightlight_off)

def nightlight_off():
  global config
  global sunrise_job
  global sunset_job
  for target in config.nightlight_targets:
    eval(config.nightlight_targets_type + '_command(target, "off")')
  schedule.cancel_job(sunrise_job)

  geolocator = Nominatim(user_agent='myapplication')
  location = geolocator.geocode(config.location)
  sun = Sun(location.latitude, location.longitude)
  sunset = sun.get_local_sunset_time()
  do_sunset = sun.get_local_sunset_time() - timedelta(minutes=30)
  print(datetime.now(), 'Scheduling today sunset for', do_sunset.strftime('%H:%M'))     
  sunset_job = schedule.every().day.at(do_sunset.strftime('%H:%M')).do(nightlight_on)

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
                print(datetime.now(), 'toggling target', target)
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
  global sunset_job
  global mqtt_client
  global config
  config = read_config('./minion.ini')
  mqtt_client.on_connect = on_connect
  mqtt_client.on_message = on_message

  mqtt_client.connect(config.mqtt_server, config.mqtt_port, 60)

  geolocator = Nominatim(user_agent='myapplication')
  location = geolocator.geocode(config.location)

  sun = Sun(location.latitude, location.longitude)
  sunset = sun.get_local_sunset_time()
  do_sunset = sun.get_local_sunset_time() - timedelta(minutes=30)
  print(datetime.now(), 'First sunset at', sunset.strftime('%H:%M'))
  print(datetime.now(), 'Scheduling today sunset for', do_sunset.strftime('%H:%M'))

  # Schedule nightlight events
  sunset_job = schedule.every().day.at(do_sunset.strftime('%H:%M')).do(nightlight_on)

  # Schedule goodnight
  schedule.every().day.at(config.goodnight).do(goodnight)

  # Blocking call that processes network traffic, dispatches callbacks and
  # handles reconnecting.
  # Other loop*() functions are available that give a threaded interface and a
  # manual interface.
  while True:
    try:
      #asyncio.get_event_loop().run_until_complete(receive_deconz_messages())
      mqtt_client.loop_forever()
    except KeyboardInterrupt:
      print(datetime.now(), "Exiting.")
      sys.exit()

if __name__ == "__main__":
    main()
