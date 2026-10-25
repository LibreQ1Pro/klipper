# Setting Z by touching the bed with the nozzle
#
# Some printers (eg, the QIDI Q1 Pro) have a regular [probe] on the
# toolhead and strain gauges under the bed, which detect the nozzle
# touching the bed.  The probe homes Z and measures bed meshes, the
# nozzle touch sets the exact Z position.
#
# Copyright (C) 2026  LibreQ1Pro
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import probe

class NozzleTouch:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.z_offset = config.getfloat('z_offset')
        self.accel = config.getfloat('accel', None, above=0.)
        param_helper = probe.ProbeParameterHelper(config)
        mcu_probe = probe.ProbeEndstopWrapper(config, self, param_helper)
        self.probe_session = probe.SampleAveragingHelper(
            config, param_helper, mcu_probe.start_probe_session)
        self.last_z_adjust = 0.
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('NOZZLE_TOUCH', self.cmd_NOZZLE_TOUCH,
                               desc=self.cmd_NOZZLE_TOUCH_help)
    def get_offsets(self, gcmd=None):
        return 0., 0., self.z_offset
    def _touch(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        max_accel = toolhead.get_max_velocity()[1]
        if self.accel is not None:
            toolhead.set_max_velocities(None, self.accel, None, None)
        try:
            return probe.run_single_probe(self.probe_session, gcmd)
        finally:
            toolhead.set_max_velocities(None, max_accel, None, None)
    cmd_NOZZLE_TOUCH_help = "Set Z by touching the bed with the nozzle"
    def cmd_NOZZLE_TOUCH(self, gcmd):
        epos = self._touch(gcmd)
        # The bed is at epos.bed_z: shift Z so that it is at 0
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        pos[2] -= epos.bed_z
        toolhead.set_position(pos)
        self.last_z_adjust = -epos.bed_z
        gcmd.respond_info("nozzle_touch: Z adjusted by %.6f"
                          % (self.last_z_adjust,))
    def get_status(self, eventtime):
        return {'last_z_adjust': self.last_z_adjust}

def load_config(config):
    return NozzleTouch(config)
