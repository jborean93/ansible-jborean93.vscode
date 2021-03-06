# Copyright (c) 2021 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)


class _MessageRegistry(type):

    __registry: Dict[str, Dict[str, Union[type, List[Optional[type]]]]] = {
        'event': {},
        'command': {},
    }

    def __init__(cls, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for idx, key in enumerate(['_REQUEST', '_RESPONSE']):
            value = getattr(cls, key, None)
            if value:
                reg = cls.__registry['command'].setdefault(value, [None, None])
                reg[idx] = cls
                break

        event = getattr(cls, '_EVENT', None)
        if event:
            cls.__registry['event'][event] = cls

    def __call__(
            cls,
            content: Dict[str, Any],
    ):
        message_type = content['type']
        if message_type == 'event':
            new_cls = cls.__registry['event'].get(content['event'], cls)

        else:
            idx = 0 if message_type == 'request' else 1
            new_cls = cls.__registry['command'].get(content['command'], (cls, cls))[idx]

        if new_cls == cls:
            new_cls = {
                'event': Event,
                'request': Request,
                'response': Response,
            }[message_type]

        return super(_MessageRegistry, new_cls).__call__(content)


class ProtocolMessage(metaclass=_MessageRegistry):

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
    _REQUEST = 'configurationDone'


class ContinueRequest(Request):
    _REQUEST = 'continue'

    @property
    def thread_id(self) -> int:
        return int(self.arguments['threadId'])


class DisconnectRequest(Request):
    _REQUEST = 'disconnect'

    @property
    def restart(self) -> bool:
        return bool(self.arguments.get('restart', False))

    @property
    def terminate_debuggee(self) -> bool:
        return bool(self.arguments.get('terminateDebuggee', False))


class InitializeRequest(Request):
    _REQUEST = 'initialize'

    @property
    def client_id(self) -> Optional[str]:
        return self.arguments.get('clientID', None)

    @property
    def client_name(self) -> Optional[str]:
        return self.arguments.get('clientName', None)

    @property
    def adapter_id(self) -> str:
        return self.arguments['adapterID']

    @property
    def locale(self) -> Optional[str]:
        return self.arguments.get('locale', None)

    @property
    def lines_start_at_1(self) -> bool:
        return self.arguments.get('linesStartAt1', True)

    @property
    def columns_start_at_1(self) -> bool:
        return self.arguments.get('columnsStartAt1', True)

    @property
    def path_format(self) -> Optional[str]:
        return self.arguments.get('pathFormat', 'path')

    @property
    def supports_variable_type(self) -> bool:
        return self.arguments.get('supportsVariableType', False)

    @property
    def supports_variable_paging(self) -> bool:
        return self.arguments.get('supportsVariablePaging', False)

    @property
    def supports_run_in_terminal_request(self) -> bool:
        return self.arguments.get('supportsRunInTerminalRequest', False)

    @property
    def supports_memory_references(self) -> bool:
        return self.arguments.get('supportsMemoryReferences', False)

    @property
    def supports_progress_reporting(self) -> bool:
        return self.arguments.get('supportsProgressReporting', False)

    @property
    def supports_invalidated_event(self) -> bool:
        return self.arguments.get('supportsInvalidatedEvent', False)


class LaunchRequest(Request):
    _REQUEST = 'launch'

    @property
    def no_debug(self) -> bool:
        return self.arguments.get('noDebug', False)


class NextRequest(Request):
    _REQUEST = 'next'

    @property
    def thread_id(self) -> int:
        return int(self.arguments['threadId'])

    @property
    def granularity(self):
        return self.arguments.get('granularity', None)


class ScopesRequest(Request):
    _REQUEST = 'scopes'

    @property
    def frame_id(self) -> int:
        return int(self.arguments['frameId'])


class SetBreakpointsRequest(Request):
    _REQUEST = 'setBreakpoints'

    @property
    def source(self) -> 'Source':
        return Source.from_raw(self.arguments['source'])

    @property
    def breakpoints(self) -> List['SourceBreakpoint']:
        return [
            SourceBreakpoint.from_raw(r)
            for r in self.arguments.get('breakpoints', [])
        ]

    @property
    def source_modified(self) -> bool:
        return self.arguments.get('sourceModified', False)


class StackTraceRequest(Request):
    _REQUEST = 'stackTrace'

    @property
    def thread_id(self) -> int:
        return int(self.arguments['threadId'])

    @property
    def start_frame(self) -> int:
        return int(self.arguments.get('startFrame', 0))

    @property
    def levels(self) -> int:
        return int(self.arguments.get('levels', 0))

    @property
    def format(self):
        return self.arguments.get('format', None)


class ThreadsRequest(Request):
    _REQUEST = 'threads'


class VariablesRequest(Request):
    _REQUEST = 'variables'

    @property
    def variables_reference(self) -> int:
        return int(self.arguments['variablesReference'])

    @property
    def filter(self) -> Optional[str]:
        return self.arguments.get('filter')

    @property
    def start(self) -> int:
        return int(self.arguments.get('start', 0))

    @property
    def count(self) -> int:
        return int(self.arguments.get('count', 0))

    @property
    def format(self):
        return self.arguments.get('format', None)


class Breakpoint:

    def __init__(
            self,
            breakpoint_id: Optional[int] = None,
            verified: bool = True,
            message: Optional[str] = None,
            source: Optional['Source'] = None,
            line: Optional[int] = None,
            column: Optional[int] = None,
            end_line: Optional[int] = None,
            end_column: Optional[int] = None,
            instruction_reference: Optional[str] = None,
            offset: Optional[int] = None,
    ):
        self.breakpoint_id = breakpoint_id
        self.verified = verified
        self.message = message
        self.source = source
        self.line = line
        self.column = column
        self.end_line = end_line
        self.end_column = end_column
        self.instruction_reference = instruction_reference
        self.offset = offset

    def to_raw(self) -> Dict[str, Any]:
        return {
            'id': (
                int(self.breakpoint_id)
                if self.breakpoint_id is not None
                else None
            ),
            'verified': self.verified,
            'message': self.message,
        }


class Scope:

    def __init__(
            self,
            name: str,
            presentation_hint: str,
            variables_reference: int,
            named_variables: Optional[int] = None,
            indexed_variables: Optional[int] = None,
            expensive: bool = False,
            source: Optional['Source'] = None,
            line: Optional[int] = None,
            column: Optional[int] = None,
            end_line: Optional[int] = None,
            end_column: Optional[int] = None,
    ):
        self.name = name
        self.presentation_hint = presentation_hint
        self.variables_reference = variables_reference
        self.named_variables = named_variables
        self.indexed_variables = indexed_variables
        self.expensive = expensive
        self.source = source
        self.line = line
        self.column = column
        self.end_line = end_line
        self.end_column = end_column

    def to_raw(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'presentationHint': self.presentation_hint,
            'variablesReference': self.variables_reference,
            'namedVariables': self.named_variables,
            'indexedVariables': self.indexed_variables,
            'expensive': self.expensive,
            'source': self.source,
            'line': self.line,
            'column': self.column,
            'endLine': self.end_line,
            'endColumn': self.end_column,
        }


class Source:

    def __init__(
            self,
            name: Optional[str] = None,
            path: Optional[str] = None,
            source_reference: Optional[int] = None,
            presentation_hint: str = 'normal',
            origin: Optional[str] = None,
            sources: List['Source'] = None,
            adapter_data: Any = None,
            checksums: List[str] = None,
    ):
        self.name = name
        self.path = path
        self.source_reference = source_reference
        self.presentation_hint = presentation_hint
        self.origin = origin
        self.sources = sources or []
        self.adapter_data = adapter_data
        self.checksums = checksums or []

    def to_raw(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'path': self.path,
        }

    @classmethod
    def from_raw(
            cls,
            raw: Dict[str, Any],
    ) -> 'Source':
        return Source(
            name=raw.get('name'),
            path=raw.get('path'),
            source_reference=int(raw['sourceReference']) if 'sourceReference' in raw else None,
            presentation_hint=raw.get('presentationHint', 'normal'),
            origin=raw.get('origin'),
            sources=[Source.from_raw(r) for r in raw.get('sources', [])],
            adapter_data=raw.get('adapterData'),
            checksums=raw.get('checksums', []),
        )


class SourceBreakpoint:

    def __init__(
            self,
            line: int,
            column: Optional[int] = None,
            condition: Optional[str] = None,
            hit_condition: Optional[str] = None,
            log_message: Optional[str] = None,
    ):
        self.line = line
        self.column = column
        self.condition = condition
        self.hit_condition = hit_condition
        self.log_message = log_message

    @classmethod
    def from_raw(
            cls,
            raw: Dict[str, Any],
    ) -> 'SourceBreakpoint':
        return SourceBreakpoint(
            line=int(raw['line']),
            column=int(raw['column']) if 'column' in raw else None,
            condition=raw.get('condition'),
            hit_condition=raw.get('hitCondition'),
            log_message=raw.get('logMessage'),
        )


class StackFrame:

    def __init__(
            self,
            stack_id: int,
            name: str,
            source: Optional[Source] = None,
            line: int = 0,
            column: int = 0,
            end_line: Optional[int] = None,
            end_column: Optional[int] = None,
            can_restart: bool = False,
            instruction_pointer_reference: Optional[str] = None,
            module_id: Union[int, str] = None,
            presentation_hint: str = 'normal',
    ):
        self.stack_id = stack_id
        self.name = name
        self.source = source
        self.line = line
        self.column = column
        self.end_line = end_line
        self.end_column = end_column
        self.can_restart = can_restart
        self.instruction_pointer_reference = instruction_pointer_reference
        self.module_id = module_id
        self.presentation_hint = presentation_hint

        self.scopes: List[Scope] = []

    def to_raw(self) -> Dict[str, Any]:
        return {
            'id': self.stack_id,
            'name': self.name,
            'source': self.source.to_raw() if self.source else None,
            'line': 0 if not self.source else self.line,
            'column': 0 if not self.source else self.column,
            'endLine': self.end_line,
            'endColumn': self.end_column,
            'canRestart': self.can_restart,
            'instructionPointerReference': self.instruction_pointer_reference,
            'moduleId': self.module_id,
            'presentationHint': self.presentation_hint,
        }


class Thread:

    def __init__(
            self,
            thread_id: int,
            name: str,
    ):
        self.thread_id = thread_id
        self.name = name
        self.stacks: List[StackFrame] = []

    def to_raw(self) -> Dict[str, Any]:
        return {
            'id': self.thread_id,
            'name': self.name,
        }


class Variable:

    def __init__(
            self,
            name: str,
            value: str,
            variables_reference: int,
            value_type: Optional[str] = None,
            presentation_hint: Optional['VariablePresentationHint'] = None,
            evaluate_name: Optional[str] = None,
            named_variables: Optional[int] = None,
            indexed_variables: Optional[int] = None,
            memory_reference: Optional[str] = None,
    ):
        self.name = name
        self.value = value
        self.variables_reference = variables_reference
        self.value_type = value_type
        self.presentation_hint = presentation_hint
        self.evaluate_name = evaluate_name
        self.named_variables = named_variables
        self.indexed_variables = indexed_variables
        self.memory_reference = memory_reference

    def to_raw(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'value': self.value,
            'type': self.value_type,
            'presentationHint': (
                self.presentation_hint.to_raw()
                if self.presentation_hint
                else None
            ),
            'evaluateName': self.evaluate_name,
            'variablesReference': self.variables_reference,
            'namedVariables': self.named_variables,
            'indexedVariables': self.indexed_variables,
            'memoryReference': self.memory_reference,
        }


class VariablePresentationHint:

    def __init__(
            self,
            kind: str,
            attributes: List[str] = None,
            visibility: Optional[str] = None,
    ):
        self.kind = kind
        self.attributes = attributes or []
        self.visibility = visibility

    def to_raw(self) -> Dict[str, Any]:
        return {
            'kind': self.kind,
            'attributes': self.attributes,
            'visibility': self.visibility,
        }
