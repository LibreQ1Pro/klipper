# Misc support code for the QIDI Q1 Pro (stock display and macros)
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import mcu
from . import spi_temperature, bed_mesh, homing

# MAX6675 sensor with a correction factor applied to the readings
class MAX6675Scaled(spi_temperature.MAX6675):
    def __init__(self, config, scale):
        self.scale = scale
        spi_temperature.MAX6675.__init__(self, config)
    def calc_temp(self, adc):
        return spi_temperature.MAX6675.calc_temp(self, adc) * self.scale
    def calc_adc(self, temp):
        return spi_temperature.MAX6675.calc_adc(self, temp / self.scale)

class QidiQ1Pro:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        # Homing timeout when the probe and steppers are on different mcus
        mcu.TRSYNC_TIMEOUT = config.getfloat('trsync_timeout',
                                             mcu.TRSYNC_TIMEOUT, above=0.)
        # "MAX6675_QIDI" sensor type (stock firmware scaled readings by 0.97)
        scale = config.getfloat('max6675_scale', 0.97, above=0.)
        pheaters = self.printer.load_object(config, 'heaters')
        pheaters.add_sensor_factory(
            "MAX6675_QIDI", (lambda config: MAX6675Scaled(config, scale)))
        # Endpoints used by the stock display to abort a running macro
        self.break_command = config.get('break_until_command', 'CANCEL_PRINT')
        self.break_timeout = config.getfloat('break_timeout', 60., above=0.)
        self.break_timer = self.reactor.register_timer(self._break_expired)
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint("breakmacro", self._handle_breakmacro)
        webhooks.register_endpoint("breakheater", self._handle_breakmacro)
        webhooks.register_endpoint("resumemacro", self._handle_resumemacro)
        # Homing Z to its maximum with a sensorless endstop per Z stepper
        # (stock REVERSE_HOMING, used by M4031 to level the bed against
        # the bottom of the frame)
        self.reverse_endstops = []
        self.reverse_stepper_names = []
        steppers = config.getlist('reverse_homing_steppers', None)
        if steppers is not None:
            pins = config.getlist('reverse_homing_endstop_pins')
            if len(pins) != len(steppers):
                raise config.error("reverse_homing_endstop_pins must list"
                                   " one pin per reverse_homing_steppers")
            self.reverse_position = config.getfloat('reverse_homing_position')
            self.reverse_speed = config.getfloat('reverse_homing_speed', 5.,
                                                 above=0.)
            ppins = self.printer.lookup_object('pins')
            for stepper_name, pin in zip(steppers, pins):
                # The tmc driver section registers its virtual_endstop pin
                chip_name = pin.split(':')[0].strip()
                self.printer.load_object(config,
                                         chip_name.replace('_', ' ', 1))
                mcu_endstop = ppins.setup_pin('endstop', pin)
                self.reverse_endstops.append((mcu_endstop, stepper_name))
            self.printer.register_event_handler("klippy:mcu_identify",
                                                self._handle_mcu_identify)
            self.gcode.register_command("REVERSE_HOMING",
                                        self.cmd_REVERSE_HOMING,
                                        desc=self.cmd_REVERSE_HOMING_help)
        # Register commands
        self.gcode.register_command("ADD_Z_OFFSET_TO_BED_MESH",
                                    self.cmd_ADD_Z_OFFSET_TO_BED_MESH,
                                    desc=self.cmd_ADD_Z_OFFSET_TO_BED_MESH_help)
    def _handle_mcu_identify(self):
        force_move = self.printer.lookup_object('force_move')
        for mcu_endstop, stepper_name in self.reverse_endstops:
            mcu_endstop.add_stepper(force_move.lookup_stepper(stepper_name))
    # Reverse homing
    cmd_REVERSE_HOMING_help = "Home Z to its maximum (sensorless endstops)"
    def cmd_REVERSE_HOMING(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        distance = gcmd.get_float('DISTANCE', None, above=0.)
        if distance is not None:
            # Only move Z down by the given distance, stopping early if the
            # bed hits the bottom of the frame (Z must be "homed" with
            # SET_KINEMATIC_POSITION; the position is kept, not homed)
            movepos = toolhead.get_position()
            movepos[2] += distance
            hmove = homing.HomingMove(self.printer, self.reverse_endstops,
                                      toolhead)
            hmove.homing_move(movepos, self.reverse_speed, probe_pos=True,
                              check_triggered=False)
            return
        status = toolhead.get_status(self.reactor.monotonic())
        zmin = status['axis_minimum'][2]
        # Each Z stepper stops on its own endstop, as in a G28
        pos = toolhead.get_position()
        pos[2] = self.reverse_position - 1.5 * (self.reverse_position - zmin)
        toolhead.set_position(pos, homing_axes="z")
        movepos = list(pos)
        movepos[2] = self.reverse_position
        phoming = self.printer.lookup_object('homing')
        try:
            phoming.manual_home(toolhead, self.reverse_endstops, movepos,
                                self.reverse_speed, False, True, True)
        except self.printer.command_error:
            self.printer.lookup_object('stepper_enable').motor_off()
            raise
        pos = toolhead.get_position()
        pos[2] = self.reverse_position
        toolhead.set_position(pos, homing_axes="z")
    # Macro interruption
    def _handle_breakmacro(self, web_request):
        logging.info("Skipping g-code commands until %s", self.break_command)
        self.gcode.set_break(self.break_command)
        self.reactor.update_timer(self.break_timer,
                                  self.reactor.monotonic() + self.break_timeout)
    def _handle_resumemacro(self, web_request):
        self.gcode.set_break(None)
        self.reactor.update_timer(self.break_timer, self.reactor.NEVER)
    def _break_expired(self, eventtime):
        if self.gcode.is_break_pending():
            logging.info("Timeout waiting for %s - no longer skipping"
                         " g-code commands", self.break_command)
            self.gcode.set_break(None)
        return self.reactor.NEVER
    # Bed mesh helpers
    cmd_ADD_Z_OFFSET_TO_BED_MESH_help = "Add a Z offset to the current bed mesh"
    def cmd_ADD_Z_OFFSET_TO_BED_MESH(self, gcmd):
        offset = gcmd.get_float('ZOFFSET', 0.)
        bedmesh = self.printer.lookup_object('bed_mesh')
        mesh = bedmesh.get_mesh()
        if mesh is None:
            raise gcmd.error("No bed mesh is active")
        matrix = [[z + offset for z in line]
                  for line in mesh.get_probed_matrix()]
        name = mesh.get_profile_name()
        new_mesh = bed_mesh.ZMesh(mesh.get_mesh_params(), name)
        try:
            new_mesh.build_mesh(matrix)
        except bed_mesh.BedMeshError as e:
            raise gcmd.error(str(e))
        bedmesh.set_mesh(new_mesh)
        if not name.startswith("adaptive-"):
            bedmesh.save_profile(name)

def load_config(config):
    return QidiQ1Pro(config)
