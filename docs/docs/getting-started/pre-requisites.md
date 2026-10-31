---
title: Pre-requisites
sidebar_position: 0
---

# Pre-requisites

In order to make valuable use of NSPanel Manager you must full-fill the following requirements:

* ✅ Own at least one NSPanel (be careful, all NSPanel are not supported, take a look at [supported devices](./supported-devices))
* ✅ Have an MQTT server up and running 
  * Note that Home Assistant and OpenHab are both providing integration for embedded MQTT server in case you don't want to setup a standalone server.
* ✅ Have a server able to host the service 24/7 (your own laptop is not recommended for a daily use as it will goes off)
  * A home assistant server
  * NAS with Docker support
  * Intel NUC
  * Raspberry Pi
  * A linux machine having docker
  * ...

:::tip Disable Nagle's algorithm on your MQTT server
By default, TCP holds back a small packet until the data sent before it has been acknowledged
([Nagle's algorithm](https://en.wikipedia.org/wiki/Nagle%27s_algorithm)). Most MQTT messages between
NSPanel Manager and your panels are small, so this can delay them by up to a few hundred milliseconds,
for example when you switch rooms on a panel. We recommend disabling Nagle's algorithm on your MQTT server.

If you use Mosquitto, add this line to your `mosquitto.conf` and restart the broker:

```
set_tcp_nodelay true
```

This option needs Mosquitto 2.0 or newer. Older versions refuse to start with it.
:::

When you match all the requirements, you are then ready for the first step: [Flash our custom firmware into your NSPanel](./flash-nspanel).

:::info
You are not sure? Join us on [Discord](https://discord.gg/RwXvAH56fE) we will try to help you 👍
:::
