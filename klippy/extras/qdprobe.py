# Support for a second probe pin on the QIDI Q1 Pro
#
# The QIDI Q1 Pro has two Z sensors: strain gauges under the bed (nozzle
# touch, configured as [smart_effector]) and an inductive probe on the
# toolhead (configured as [qdprobe]).  This module allows the main probe
# to be switched between the two sensors at run-time.
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import probe

class QidiProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        if not config.has_section('smart_effector'):
            raise config.error("[qdprobe] requires a [smart_effector] section")
        main_probe = self.printer.load_object(config, 'smart_effector')
        self.mcu_probe = main_probe.mcu_probe
        # Pin 1 is the [smart_effector] pin, pin 2 is the [qdprobe] pin
        self.wrappers = [self.mcu_probe.probe_wrapper,
                         probe.ProbeEndstopWrapper(config,
                                                   main_probe.probe_offsets,
                                                   main_probe.param_helper)]
        self.active_pin = 1
        # Report the state of the active pin in QUERY_PROBE / QUERY_ENDSTOPS
        main_probe.cmd_helper.query_endstop = self._query_endstop
        ppins = self.printer.lookup_object('pins')
        ppins.chips['probe'].query_endstop_cb = self._query_endstop
        # Register commands
        gcode = self.printer.lookup_object('gcode')
        for prefix in ['QIDI', 'MKS']:
            gcode.register_command(prefix + '_PROBE_PIN_1',
                                   self.cmd_PROBE_PIN_1,
                                   desc=self.cmd_PROBE_PIN_1_help)
            gcode.register_command(prefix + '_PROBE_PIN_2',
                                   self.cmd_PROBE_PIN_2,
                                   desc=self.cmd_PROBE_PIN_2_help)
    def _query_endstop(self, print_time):
        return self.wrappers[self.active_pin - 1].query_endstop(print_time)
    def _set_active_pin(self, pin):
        if self.mcu_probe.probe_session is not None:
            raise self.printer.command_error(
                "Can not change probe pin while probing")
        self.active_pin = pin
        self.mcu_probe.probe_wrapper = self.wrappers[pin - 1]
    cmd_PROBE_PIN_1_help = "Use the [smart_effector] pin (bed sensors) to probe"
    def cmd_PROBE_PIN_1(self, gcmd):
        self._set_active_pin(1)
    cmd_PROBE_PIN_2_help = "Use the [qdprobe] pin (toolhead sensor) to probe"
    def cmd_PROBE_PIN_2(self, gcmd):
        self._set_active_pin(2)
    def get_status(self, eventtime):
        return {'active_pin': self.active_pin}

def load_config(config):
    return QidiProbe(config)
