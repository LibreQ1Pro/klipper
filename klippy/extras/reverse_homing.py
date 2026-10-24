# Homing Z to its maximum with a sensorless endstop per Z stepper
#
# Copyright (C) 2026  LibreQ1Pro
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import homing

class ReverseHoming:
    def __init__(self, config):
        self.printer = config.get_printer()
        steppers = config.getlist('steppers')
        pins = config.getlist('endstop_pins')
        if len(pins) != len(steppers):
            raise config.error("endstop_pins must list one pin per stepper"
                               " in steppers")
        self.speed = config.getfloat('speed', 5., above=0.)
        self.printer.load_object(config, 'force_move')
        ppins = self.printer.lookup_object('pins')
        self.endstops = []
        for stepper_name, pin in zip(steppers, pins):
            # The tmc driver section registers its virtual_endstop pin
            chip_name = pin.split(':')[0].strip()
            self.printer.load_object(config, chip_name.replace('_', ' ', 1))
            mcu_endstop = ppins.setup_pin('endstop', pin)
            self.endstops.append((mcu_endstop, stepper_name))
        self.printer.register_event_handler("klippy:mcu_identify",
                                            self._handle_mcu_identify)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command("REVERSE_HOMING", self.cmd_REVERSE_HOMING,
                               desc=self.cmd_REVERSE_HOMING_help)
    def _handle_mcu_identify(self):
        force_move = self.printer.lookup_object('force_move')
        for mcu_endstop, stepper_name in self.endstops:
            mcu_endstop.add_stepper(force_move.lookup_stepper(stepper_name))
    def _move_distance(self, distance):
        # Move Z towards its maximum, stopping early if the endstops
        # trigger (the position is kept, Z is not homed)
        toolhead = self.printer.lookup_object('toolhead')
        movepos = toolhead.get_position()
        movepos[2] += distance
        hmove = homing.HomingMove(self.printer, self.endstops, toolhead)
        hmove.homing_move(movepos, self.speed, probe_pos=True,
                          check_triggered=False)
    def _home(self):
        toolhead = self.printer.lookup_object('toolhead')
        status = toolhead.get_status(self.printer.get_reactor().monotonic())
        zmin = status['axis_minimum'][2]
        zmax = status['axis_maximum'][2]
        # Each Z stepper stops on its own endstop, as in a G28
        pos = toolhead.get_position()
        pos[2] = zmax - 1.5 * (zmax - zmin)
        toolhead.set_position(pos, homing_axes="z")
        movepos = list(pos)
        movepos[2] = zmax
        phoming = self.printer.lookup_object('homing')
        try:
            phoming.manual_home(toolhead, self.endstops, movepos,
                                self.speed, False, True, True)
        except self.printer.command_error:
            self.printer.lookup_object('stepper_enable').motor_off()
            raise
        # The endstops are assumed to be at the Z maximum
        pos = toolhead.get_position()
        pos[2] = zmax
        toolhead.set_position(pos, homing_axes="z")
    cmd_REVERSE_HOMING_help = "Home Z to its maximum (sensorless endstops)"
    def cmd_REVERSE_HOMING(self, gcmd):
        distance = gcmd.get_float('DISTANCE', None, above=0.)
        if distance is not None:
            self._move_distance(distance)
        else:
            self._home()

def load_config(config):
    return ReverseHoming(config)
