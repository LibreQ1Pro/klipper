# Support fans that are enabled while a heater is active (with idle timeout)
#
# Based on the QIDI Q1 Pro chamber_fan module.
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import fan

PIN_MIN_TIME = 0.100

class ChamberFan:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.load_object(config, 'heaters')
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.heater_names = config.getlist("heater", ())
        self.heaters = []
        self.fan = fan.Fan(config)
        self.fan_speed = config.getfloat("fan_speed", 1., minval=0., maxval=1.)
        self.idle_speed = config.getfloat("idle_speed", self.fan_speed,
                                          minval=0., maxval=1.)
        self.idle_timeout = config.getint("idle_timeout", 30, minval=0)
        self.fan_on = True
        self.last_on = self.idle_timeout
        self.last_speed = 0.
        gcode = self.printer.lookup_object("gcode")
        gcode.register_command("TOGGLE_CHAMBER_FAN",
                               self.cmd_TOGGLE_CHAMBER_FAN,
                               desc=self.cmd_TOGGLE_CHAMBER_FAN_help)
    def handle_ready(self):
        pheaters = self.printer.lookup_object('heaters')
        self.heaters = [pheaters.lookup_heater(n) for n in self.heater_names]
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.callback, reactor.monotonic()+PIN_MIN_TIME)
    def get_status(self, eventtime):
        return self.fan.get_status(eventtime)
    cmd_TOGGLE_CHAMBER_FAN_help = "Enable/disable the chamber fan"
    def cmd_TOGGLE_CHAMBER_FAN(self, gcmd):
        self.fan_on = not self.fan_on
    def callback(self, eventtime):
        speed = 0.
        active = False
        for heater in self.heaters:
            current_temp, target_temp = heater.get_temp(eventtime)
            if target_temp:
                active = True
        if active:
            self.last_on = 0
            speed = self.fan_speed
        elif self.last_on < self.idle_timeout:
            speed = self.idle_speed
            self.last_on += 1
        if not self.fan_on:
            speed = 0.
        if speed != self.last_speed:
            self.last_speed = speed
            self.fan.set_speed(speed)
        return eventtime + 1.

def load_config_prefix(config):
    return ChamberFan(config)
