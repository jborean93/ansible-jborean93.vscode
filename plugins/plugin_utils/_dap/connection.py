# Copyright (c) 2021 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json

from ansible.module_utils.common.text.converters import (
    to_bytes,
    to_text
)

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from .messages import (
    Breakpoint,
    Event,
    InitializeRequest,
    ProtocolMessage,
    Response,
    Request,
    Thread,
)


class DebugAdapterConnection:

    def __init__(
            self,
            supports_config_done: bool = True,
            supports_variable_type: bool = True,
    ):
        self.client_config: Optional[InitializeRequest] = None
        self.capabilities = {
            # https://microsoft.github.io/debug-adapter-protocol/specification#Types_Capabilities
            'supportsConfigurationDoneRequest': supports_config_done,
            'supportsVariableType': supports_variable_type,
        }

        self._in_buffer = None
        self._out_buffer = bytearray()
        self.__seq_num = 1

    @property
    def _seq_num(self) -> int:
        num = self.__seq_num
        self.__seq_num += 1
        return num

    def send_threads(
            self,
            request: Request,
            threads: List[Thread],
    ):
        self.send_response(request.command, request.seq,
                           body={'threads': [t.to_raw() for t in threads]})

    def set_breakpoints(
            self,
            request: Request,
            breakpoints: List[Breakpoint],
    ):
        b = [v.to_raw() for v in breakpoints]
        self.send_response(request.command, request.seq,
                           body={'breakpoints': b})

    def stop(
            self,
            reason: str,
            description: Optional[str] = None,
            thread_id: Optional[int] = None,
            preserve_focus_hint: bool = False,
            text: Optional[str] = None,
            all_threads_stopped: bool = False,
            hit_breakpoint_ids: List[int] = None,
    ):
        return self._send_event('stopped', {
            'reason': reason,
            'description': description,
            'threadId': int(thread_id) if thread_id is not None else None,
            'preserveFocusHint': preserve_focus_hint,
            'text': text,
            'allThreadsStopped': all_threads_stopped,
            'hitBreakpointsIds': hit_breakpoint_ids,
        })

    def terminate(self):
        return self._send_event('terminated')

    def data_to_send(self) -> bytes:
        data = self._out_buffer
        self._out_buffer = bytearray()
        return bytes(data)

    def receive_data(
            self,
            data: bytes,
    ) -> List[ProtocolMessage]:
        events = []

        while True:
            if not self._in_buffer:
                self._in_buffer = {
                    'buffer': bytearray(),
                    'headers': {},
                    'header_read': False,
                }

            next_msg = self._in_buffer
            next_msg['buffer'] += data

            if not next_msg['header_read']:
                split = next_msg['buffer'].find(b'\r\n\r\n')
                if split == -1:
                    break  # Need more data

                raw_headers = bytes(next_msg['buffer'][:split])
                next_msg['buffer'] = next_msg['buffer'][split + 4:]
                next_msg['header_read'] = True

                headers = dict([to_text(v).split(': ') for v in raw_headers.split(b'\r\n')])
                headers['Content-Length'] = int(headers['Content-Length'])
                next_msg['headers'] = headers

            content_length = next_msg['headers']['Content-Length']
            if len(next_msg['buffer']) < content_length:
                break  # Need more data

            b_content = bytes(next_msg['buffer'][:content_length])
            print(to_text(b_content))
            content = json.loads(to_text(b_content, errors='surrogate_or_strict'))

            msg = ProtocolMessage(content)
            events.append(msg)
            if isinstance(msg, Event):
                self._process_event(msg)

            elif isinstance(msg, Response):
                self._process_response(msg)

            elif isinstance(msg, Request):
                self._process_request(msg)

            self._in_buffer = None
            data = next_msg['buffer'][content_length:]

        return events

    def _process_event(
            self,
            event: Event,
    ):
        a = ''

    def _process_request(
            self,
            request: Request,
    ):
        if isinstance(request, InitializeRequest):
            self.client_config = request
            self.send_response(request.command, request.seq,
                               body=self.capabilities)
            self._send_event('initialized')

    def _process_response(
            self,
            response: Response,
    ):
        a = ''

    def _send_event(
            self,
            event: str,
            body: Dict[str, Any] = None,
    ):
        self._send_content('event', {
            'event': event,
            'body': body,
        })

    def send_response(
            self,
            command: str,
            request_seq: int,
            body: Dict[str, Any] = None,
            success: bool = True,
            message: Optional[str] = None,
    ):
        self._send_content('response', {
            'request_seq': request_seq,
            'success': success,
            'command': command,
            'message': message,
            'body': body,
        })

    def _send_content(
            self,
            request_type: str,
            content: Dict[str, Any],
    ):
        content['type'] = request_type
        content['seq'] = self._seq_num
        json_content = json.dumps(content, separators=(',', ':'))
        b_content = to_bytes(json_content, errors='surrogate_or_strict')
        print(json_content)

        response = b'\r\n'.join([
            b'Content-Length: %s' % to_bytes(len(b_content)),
            b'',
            b_content,
        ])
        self._out_buffer += response
