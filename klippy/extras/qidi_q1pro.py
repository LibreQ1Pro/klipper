# Misc support code for the QIDI Q1 Pro (stock display and macros)
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import mcu
from . import spi_temperature, bed_mesh

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
        # Register commands
        self.gcode.register_command("ADD_Z_OFFSET_TO_BED_MESH",
                                    self.cmd_ADD_Z_OFFSET_TO_BED_MESH,
                                    desc=self.cmd_ADD_Z_OFFSET_TO_BED_MESH_help)
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
