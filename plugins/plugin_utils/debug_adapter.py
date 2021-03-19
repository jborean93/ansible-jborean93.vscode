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
    Optional,
)


class ProtocolMessage:

    def __init__(
            self,
            content: Dict[str, Any],
    ):
        self.seq: int = int(content['seq'])
        self.type: str = content['type']
        self._content: Dict[str, Any] = content


class Event(ProtocolMessage):

    @property
    def event(self) -> str:
        return self._content['event']

    @property
    def body(self) -> Any:
        return self._content.get('body')


class Request(ProtocolMessage):

    @property
    def command(self) -> str:
        return self._content['command']

    @property
    def arguments(self) -> Any:
        return self._content.get('arguments')


class Response(ProtocolMessage):

    @property
    def request_seq(self) -> int:
        return int(self._content['request_seq'])

    @property
    def success(self) -> bool:
        return bool(self._content['success'])

    @property
    def command(self) -> str:
        return self._content['command']

    @property
    def message(self) -> Optional[str]:
        return self._content.get('message')

    @property
    def body(self) -> Any:
        return self._content.get('body')


class ConfigurationDoneRequest(Request):
    pass


class ContinueRequest(Request):

    @property
    def thread_id(self) -> int:
        return int(self.arguments['threadId'])


class DisconnectRequest(Request):

    @property
    def restart(self) -> bool:
        return bool(self.arguments.get('restart', False))

    @property
    def terminate_debuggee(self) -> bool:
        return bool(self.arguments.get('terminateDebuggee', False))


class InitializeRequest(Request):

    @property
    def client_id(self):
        return self.arguments.get('clientID', None)

    @property
    def client_name(self):
        return self.arguments.get('clientName', None)

    @property
    def adapter_id(self):
        return self.arguments.get('adapterID', None)

    @property
    def locale(self):
        return self.arguments.get('locale', None)

    @property
    def lines_start_at_1(self):
        return self.arguments.get('linesStartAt1', True)

    @property
    def columns_start_at_1(self):
        return self.arguments.get('columnsStartAt1', True)

    @property
    def path_format(self):
        return self.arguments.get('pathFormat', 'path')

    @property
    def supports_variable_type(self):
        return self.arguments.get('supportsVariableType', False)

    @property
    def supports_variable_paging(self):
        return self.arguments.get('supportsVariablePaging', False)

    @property
    def supports_run_in_terminal_request(self):
        return self.arguments.get('supportsRunInTerminalRequest', False)

    @property
    def supports_memory_references(self):
        return self.arguments.get('supportsMemoryReferences', False)

    @property
    def supports_progress_reporting(self):
        return self.arguments.get('supportsProgressReporting', False)

    @property
    def supports_invalidated_event(self):
        return self.arguments.get('supportsInvalidatedEvent', False)


class LaunchRequest(DebugEvent):

    @property
    def no_debug(self):
        return self.arguments.get('noDebug', False)


class NextRequest(DebugEvent):

    @property
    def thread_id(self):
        return int(self.arguments['threadId'])

    @property
    def granularity(self):
        return self.arguments.get('granularity', None)


class ScopesRequest(DebugEvent):

    @property
    def frame_id(self):
        return int(self.arguments['frameId'])


class SetBreakpointsRequest(DebugEvent):

    @property
    def source(self):
        raw = self.arguments.get('source', None)

        return Source(
            raw.get('name'),
            path=raw.get('path'),
            source_reference=int(raw['sourceReference']) if 'sourceReference' in raw else None,
            presentation_hint=raw.get('presentationHint'),
            origin=raw.get('origin'),
            sources=raw.get('sources'),
            adapter_data=raw.get('adapterData'),
            checksums=raw.get('checksums'),
        )

    @property
    def breakpoints(self):
        return [
            SourceBreakpoint(
                int(b['line']),
                column=int(b['column']) if 'column' in b else None,
                condition=b.get('condition'),
                hit_condition=b.get('hitCondition'),
                log_message=b.get('logMessage'),
            )
            for b in self.arguments.get('breakpoints', [])
        ]

    @property
    def source_modified(self):
        return self.arguments.get('sourceModified', False)


class StackTraceRequest(DebugEvent):

    def thread_id(self):
        return int(self.arguments['threadId'])

    def start_frame(self):
        return int(self.arguments.get('startFrame', 0))

    def levels(self):
        return int(self.arguments.get('levels', 0))

    def format(self):
        return self.arguments.get('format', None)


class ThreadRequest(DebugEvent):
    pass


class VariablesRequest(DebugEvent):

    @property
    def variable_reference(self):
        return int(self.arguments['variablesReference'])

    @property
    def filter(self):
        return self.arguments.get('filter')

    @property
    def start(self):
        return int(self.arguments.get('start', 0))

    @property
    def count(self):
        return int(self.arguments.get('count', 0))

    @property
    def format(self):
        return self.arguments.get('format', None)


class Breakpoint:

    def __init__(self, bid, verified, message=None, source=None, line=None, column=None, end_line=None,
                 end_column=None, instruction_reference=None, offset=None):
        self.bid = bid
        self.verified = verified
        self.message = message
        self.source = source
        self.line = line
        self.column = column
        self.end_line = end_line
        self.end_column = end_column
        self.instruction_reference = instruction_reference
        self.offset = offset

    def to_value(self):
        return {
            'id': int(self.bid),
            'verified': self.verified,
            'message': self.message,
        }


class Source:

    def __init__(self, name, path=None, source_reference=None, presentation_hint=None, origin=None, sources=None,
                 adapter_data=None, checksums=None):
        self.name = name
        self.path = path
        self.source_reference = source_reference
        self.presentation_hint = presentation_hint
        self.origin = origin
        self.sources = sources or []
        self.adapter_data = adapter_data
        self.checksums = checksums or []

    def to_value(self):
        return {
            'name': self.name,
            'path': self.path,
        }


class SourceBreakpoint:

    def __init__(self, line, column=None, condition=None, hit_condition=None, log_message=None):
        self.line = line
        self.column = column
        self.condition = condition
        self.hit_condition = hit_condition
        self.log_message = log_message


class DebugAdapter:

    def __init__(self):
        self._in_buffer = None
        self._out_buffer = []
        self.__seq_num = 1
        self.__out_seq_num = 1

        self.client_id = None
        self.client_name = None
        self.adapter_id = None
        self.locale = None
        self.lines_start_at_1 = False
        self.columns_start_at_1 = False
        self.path_format = None
        self.supports_variable_type = False
        self.supports_variable_paging = False
        self.supports_run_in_terminal_request = False
        self.supports_memory_references = False
        self.supports_progress_reporting = False
        self.supports_invalidated_event = False

    @property
    def _seq_num(self):
        num = self.__seq_num
        self.__seq_num += 1
        return num

    @property
    def _out_seq_num(self):
        num = self.__out_seq_num
        self.__out_seq_num += 1
        return num

    def send_threads(self, req_seq, threads):
        self._send_response('threads', req_seq, {'threads': [{"id": 1, "name": "main"}]})

    def set_breakpoints(self, req_seq, breakpoints):
        b = [v.to_value() for v in breakpoints]
        self._send_response('setBreakpoints', req_seq, {'breakpoints': b})

    def stop(self, reason, description=None, thread_id=None, preserve_focus_hint=False, text=None,
             all_threads_stopped=False, hit_breakpoint_ids=None):
        breakpoint_ids = []
        if isinstance(hit_breakpoint_ids, int):
            breakpoint_ids.append(hit_breakpoint_ids)
        elif isinstance(hit_breakpoint_ids, list):
            breakpoint_ids.extend(breakpoint_ids)

        return self._send_event('stopped', {
            'reason': reason,
            'description': description,
            'threadId': int(thread_id) if thread_id is not None else None,
            'preserveFocusHint': preserve_focus_hint,
            'text': text,
            'allThreadsStopped': all_threads_stopped,
            'hitBreakpointsIds': breakpoint_ids,
        })

    def data_to_send(self):
        if not self._out_buffer:
            return

        return self._out_buffer.pop(0)

    def receive_data(self, data):
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

            expected_seq_num = self._seq_num
            if content['seq'] != expected_seq_num:
                raise Exception("Sequence numbers %d does not match expected %d" % (content['seq'], expected_seq_num))

            if content['type'] == 'event':
                events.append(self._process_event(content))

            elif content['type'] == 'request':
                events.append(self._process_request(content))

            elif content['type'] == 'response':
                events.append(self._process_response(content))

            self._in_buffer = None
            data = next_msg['buffer'][content_length:]

        return events

    def _process_event(self, event):
        a = ''

    def _process_request(self, request):
        command = request['command']
        arguments = request.get('arguments', {})
        seq = request['seq']

        if command == 'configurationDone':
            event = ConfigurationDoneRequest(seq, arguments)
            self._send_response(command, seq)

        elif command == 'continue':
            event = ContinueRequest(seq, arguments)
            self._send_response(command, seq, {
                'allThreadsContinued': True,
            })

        elif command == 'disconnect':
            event = DisconnectRequest(seq, arguments)
            self._send_response(command, seq)

        elif command == 'initialize':
            # https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Initialize
            event = InitializeRequest(seq, arguments)
            self.client_id = event.client_id
            self.client_name = event.client_name
            self.adapter_id = event.adapter_id
            self.locale = event.locale
            self.lines_start_at_1 = event.lines_start_at_1
            self.columns_start_at_1 = event.columns_start_at_1
            self.path_format = event.path_format
            self.supports_variable_type = event.supports_variable_type
            self.supports_variable_paging = event.supports_variable_paging
            self.supports_run_in_terminal_request = event.supports_run_in_terminal_request
            self.supports_memory_references = event.supports_memory_references
            self.supports_progress_reporting = event.supports_progress_reporting
            self.supports_invalidated_event = event.supports_invalidated_event

            capabilities = {
                # https://microsoft.github.io/debug-adapter-protocol/specification#Types_Capabilities
                'supportsConfigurationDoneRequest': True,
                'supportsVariableType': True,
            }
            self._send_response(command, seq, capabilities)
            self._send_event('initialized')

        elif command == 'launch':
            event = LaunchRequest(seq, arguments)
            self._send_response(command, seq)

        elif command == 'next':
            event = NextRequest(seq, arguments)
            self._send_response(command, seq)

        elif command == 'scopes':
            event = ScopesRequest(seq, arguments)
            self._send_response(command, seq, {
                'scopes': [
                    {
                        'name': 'my scope',
                        'presentationHint': 'arguments',
                        'variablesReference': 1,
                        'namedVariables': 10,
                        'indexedVariables': 20,
                        'expensive': False,
                    },
                    {
                        'name': 'my scope locals',
                        'presentationHint': 'locals',
                        'variablesReference': 1,
                        'namedVariables': 10,
                        'indexedVariables': 20,
                        'expensive': False,
                    },
                    {
                        'name': 'my scope registers',
                        'presentationHint': 'registers',
                        'variablesReference': 1,
                        'namedVariables': 10,
                        'indexedVariables': 20,
                        'expensive': False,
                    }
                ]
            })

        elif command == 'setBreakpoints':
            event = SetBreakpointsRequest(seq, arguments)

        elif command == 'stackTrace':
            event = StackTraceRequest(seq, arguments)
            self._send_response(command, seq, {
                'stackFrames': [
                    {
                        'id': 1,
                        'name': 'stack frame name',
                        'source': Source(
                            'main.yml',
                            path='/home/jborean/dev/vscode-mock-debug/sampleWorkspace/main.yml'
                        ).to_value(),
                        'line': 4,
                        'column': 0,
                    },
                    {
                        'id': 2,
                        'name': 'other frame',
                        'source': Source(
                            'main.yml',
                            path='/home/jborean/dev/vscode-mock-debug/sampleWorkspace/main.yml',
                        ).to_value(),
                        'line': 1,
                        'column': 0,
                    }
                ],
                'totalFrames': 2,
            })

        elif command == 'threads':
            event = ThreadRequest(seq, arguments)

        elif command == 'variables':
            event = VariablesRequest(seq, arguments)
            self._send_response(command, seq, {
                'variables': [
                    {
                        'name': 'variable',
                        'value': 'var value',
                        'variablesReference': 1,
                        'type': 'str',
                    }
                ]
            })

        else:
            event = command

        return event

    def _process_response(self, response):
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

    def _send_response(
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
        content['seq'] = self._out_seq_num
        json_content = json.dumps(content, separators=(',', ':'))
        b_content = to_bytes(json_content, errors='surrogate_or_strict')
        print(json_content)

        response = b'\r\n'.join([
            b'Content-Length: %s' % to_bytes(len(b_content)),
            b'',
            b_content,
        ])
        self._out_buffer.append(response)
