# Copyright (c) 2021 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
name: debug
type: aggregate
short_description: Ansible debug handler
description:
- Handles the debug adapter socket for the debug strategy.
options:
  debug_port:
    description:
    - The port to bind the debug adapter socket to.
    default: 6845
    type: int
    ini:
    - section: ansibug
      key: port
    env:
    - name: ANSIBUG_PORT
    vars:
    - name: ansible_ansibug_port
'''

from ansible.executor.stats import (
    AggregateStats,
)

from ansible.playbook import (
    Play,
    Playbook,
)

from ansible.plugins.callback import (
    CallbackBase,
)

from ..plugin_utils.debug_adapter import (
    DebugAdapter,
)


class CallbackModule(CallbackBase):

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'debug'
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._debug = DebugAdapter()

    def v2_playbook_on_start(
            self,
            playbook: Playbook,
    ):
        # TODO: build list of valid breakpoints and the hierarchy for stepping
        # behaviour.
        host = '127.0.0.1'
        port = self.get_option('debug_port')
        self._debug.start_connection(host, port)

    def v2_playbook_on_play_start(
            self,
            play: Play,
    ):
        a = ''

    def v2_playbook_on_stats(
            self,
            stats: AggregateStats,
    ):
        self._debug.close_connection()
