# Copyright (c) 2021 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import atexit
import select
import socket
import threading

from ansible.utils.singleton import (
    Singleton,
)

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from ._dap.connection import (
    DebugAdapterConnection,
)

from ._dap.messages import (
    Breakpoint,
    ConfigurationDoneRequest,
    ContinueRequest,
    LaunchRequest,
    NextRequest,
    Scope,
    ScopesRequest,
    SetBreakpointsRequest,
    Source,
    StackFrame,
    StackTraceRequest,
    Thread,
    ThreadsRequest,
    Variable,
    VariablesRequest,
)

from .socket import (
    SocketClient,
    SocketServer,
)


class DebugAdapter(metaclass=Singleton):

    def __init__(
            self,
            host: str,
            port: int,
            supports_config_done: bool = True,
            supports_variable_type: bool = True,
    ):
        self._adapter: DebugAdapterConnection = DebugAdapterConnection(
            supports_config_done=supports_config_done,
            supports_variable_type=supports_variable_type,
        )
        self._host: str = host
        self._port: int = port
        self._server_sock: Optional[SocketServer] = None
        self._client_sock: Optional[SocketClient] = None

        self._counters = {
            'breakpoint': 1,
            'thread': 1,
            'stack': 1,
            'variable': 1,
        }
        self._counter_lock = threading.Lock()

        self._breakpoints: Dict[str, List[Breakpoint]] = {}
        self._threads: Dict[int, Thread] = {}
        self._thread_waits: Dict[int, threading.Event] = {}
        self._stacks: Dict[int, int] = {}
        self._variables: Dict[int, List[Variable]] = {}
        self._var_references: Dict[int, int] = {}
        self._config_done: threading.Event = threading.Event()

        self._receive_thread = threading.Thread(target=self._listen)
        self._thread_wsock, self._thread_rsock = socket.socketpair()
        self._step: Dict[int, bool] = {}

        atexit.register(self.close_connection)

    def add_thread(
            self,
            name: str,
    ) -> Thread:
        thread = Thread(self._counter('thread'), name)
        self._threads[thread.thread_id] = thread

        return thread

    def remove_thread(
            self,
            thread_id: int,
    ):
        thread = self._threads[thread_id]
        for stack in thread.stacks:
            self.remove_stack(stack.stack_id)

        del self._threads[thread_id]

    def add_stack(
            self,
            thread: Thread,
            name: str,
            source: Optional[Source] = None,
            line: int = 0,
            column: int = 0,
            presentation_hint: str = 'normal',
    ) -> StackFrame:
        stack = StackFrame(
            stack_id=self._counter('stack'),
            name=name,
            source=source,
            line=line,
            column=column,
            presentation_hint=presentation_hint,
        )
        thread.stacks.append(stack)
        self._stacks[stack.stack_id] = thread.thread_id

        return stack

    def remove_stack(
            self,
            stack_id: int,
    ):
        thread_id = self._stacks[stack_id]
        thread = self._threads[thread_id]

        stack_idx, stack = next(iter(
            (idx, stack)
            for idx, stack in enumerate(thread.stacks)
            if stack.stack_id == stack_id
        ))

        for scope in stack.scopes:
            self.remove_scope(stack.stack_id, scope.name)

        del self._threads[thread_id].stacks[stack_idx]
        del self._stacks[stack_id]

    def add_scope(
            self,
            stack: StackFrame,
            name: str,
            presentation_hint: str = 'normal',
            variables: Dict[str, Any] = None,
    ) -> Scope:
        var_reference = 0
        if variables:
            var_reference = self.add_variables(variables)

        scope = Scope(
            name=name,
            variables_reference=var_reference,
            presentation_hint=presentation_hint,
        )
        stack.scopes.append(scope)

        return scope

    def remove_scope(
            self,
            stack_id: int,
            name: str,
    ):
        thread_id = self._stacks[stack_id]
        stack = next(iter(
            stack
            for stack in self._threads[thread_id].stacks
            if stack.stack_id == stack_id
        ))
        scope_idx, scope = next(iter(
            (idx, scope)
            for idx, scope in enumerate(stack.scopes)
            if scope.name == name
        ))
        del stack.scopes[scope_idx]
        self.remove_variables(scope.variables_reference)

    def add_variables(
            self,
            variables: Dict[str, Any],
    ) -> int:
        ref_id = self._counter('variable')

        var_list = []
        for key, value in variables.items():
            variables_reference = 0
            named_variables = 0
            indexed_variables = 0

            if isinstance(value, list):
                indexed_variables = len(value)
                variables_reference = self.add_variables({
                    str(idx): entry
                    for idx, entry in enumerate(value)
                })

            elif isinstance(value, dict):
                named_variables = len(value)
                variables_reference = self.add_variables(value)

            var_list.append(Variable(
                name=str(key),
                value=repr(value),
                value_type=type(value).__name__,
                variables_reference=variables_reference,
                named_variables=named_variables,
                indexed_variables=indexed_variables,
            ))

        self._variables[ref_id] = var_list
        self._var_references.setdefault(ref_id, 0)
        self._var_references[ref_id] += 1

        return ref_id

    def remove_variables(
            self,
            variables_reference: int,
    ):
        self._var_references[variables_reference] -= 1
        if self._var_references[variables_reference] < 1:
            scan_vars = self._variables.pop(variables_reference)
            for v in scan_vars:
                if v.variables_reference == 0:
                    continue
                self.remove_variables(v.variables_reference)

    def close_connection(self):
        if self._server_sock:
            self._server_sock.close()
            self._server_sock = None

        if self._receive_thread.is_alive():
            self._thread_wsock.send(b'\x00')
            self._thread_wsock.shutdown(socket.SHUT_RDWR)
            self._thread_wsock.close()

            self._receive_thread.join()
            self._thread_rsock.close()

        if self._client_sock:
            self._client_sock.close()

    def start_connection(self):
        if not self._server_sock:
            self._server_sock = SocketServer(self._host, self._port)

        if not self._client_sock:
            self._client_sock = self._server_sock.accept()

        if not self._receive_thread.is_alive():
            self._receive_thread.start()

    def wait_config_done(self):
        self._config_done.wait()

    def wait_for_breakpoint(
            self,
            thread: Thread,
            path: str,
            line: int,
    ):
        bp_list = self._breakpoints.get(path, [])
        for bp in bp_list:
            if bp.line == line:
                self._adapter.stop(
                    'breakpoint',
                    thread_id=thread.thread_id,
                    hit_breakpoint_ids=[bp.breakpoint_id],
                    all_threads_stopped=False,
                )
                self._client_sock.send(self._adapter.data_to_send())

                wait = self._thread_waits.setdefault(thread.thread_id,
                                                     threading.Event())
                wait.wait()
                return

        if self._step.setdefault(thread.thread_id, False):
            self._adapter.stop(
                'step',
                thread_id=thread.thread_id,
                all_threads_stopped=False,
            )
            self._client_sock.send(self._adapter.data_to_send())

            wait = self._thread_waits.setdefault(thread.thread_id,
                                                 threading.Event())
            wait.wait()

    def _counter(
            self,
            name: str,
    ) -> int:
        with self._counter_lock:
            num = self._counters[name]
            self._counters[name] += 1
            return num

    def _listen(self):
        while True:
            read = select.select([self._client_sock.sock,
                                 self._thread_rsock], [], [])[0]

            if self._client_sock.sock in read:
                self._process_dap_msg()

            if self._thread_rsock in read:
                self._thread_rsock.recv(1024)
                break

        self._adapter.terminate()
        self._client_sock.send(self._adapter.data_to_send())
        disconnect = self._adapter.receive_data(self._client_sock.recv())[0]
        self._adapter.send_response(disconnect.command, disconnect.seq)
        self._client_sock.send(self._adapter.data_to_send())

    def _process_dap_msg(self):
        in_data = self._client_sock.recv()
        messages = self._adapter.receive_data(in_data)

        for msg in messages:
            if isinstance(msg, ConfigurationDoneRequest):
                self._config_done.set()
                self._adapter.send_response(msg.command, msg.seq)

            elif isinstance(msg, ContinueRequest):
                self._step[msg.thread_id] = False

                bp_event = self._thread_waits[msg.thread_id]
                bp_event.set()
                bp_event.clear()

                self._adapter.send_response(msg.command, msg.seq, body={
                    'allThreadsContinued': False,
                })

            elif isinstance(msg, LaunchRequest):
                # Meant to launch Ansible, we have already done that.
                self._adapter.send_response(msg.command, msg.seq)

            elif isinstance(msg, NextRequest):
                self._step[msg.thread_id] = True

                bp_event = self._thread_waits[msg.thread_id]
                bp_event.set()
                bp_event.clear()

                self._adapter.send_response(msg.command, msg.seq)

            elif isinstance(msg, ScopesRequest):
                thread_id = self._stacks[msg.frame_id]
                thread = self._threads[thread_id]
                stack = next(iter(
                    s
                    for s in thread.stacks
                    if s.stack_id == msg.frame_id
                ))

                self._adapter.send_response(msg.command, msg.seq, body={
                    'scopes': [s.to_raw() for s in stack.scopes],
                })

            elif isinstance(msg, SetBreakpointsRequest):
                # TODO: Validate it exists and verify/updatepath
                breakpoints = [
                    Breakpoint(
                        breakpoint_id=self._counter('breakpoint'),
                        verified=True,
                        source=msg.source,
                        line=b.line,
                        column=b.column,
                    )
                    for idx, b in enumerate(msg.breakpoints, start=1)
                ]
                self._breakpoints[msg.source.path] = breakpoints

                self._adapter.send_response(msg.command, msg.seq, body={
                    'breakpoints': [b.to_raw() for b in breakpoints],
                })

            elif isinstance(msg, StackTraceRequest):
                stacks = list(reversed(self._threads[msg.thread_id].stacks))

                self._adapter.send_response(msg.command, msg.seq, body={
                    'stackFrames': [s.to_raw() for s in stacks],
                    'totalFrames': len(stacks),
                })

            elif isinstance(msg, ThreadsRequest):
                self._adapter.send_response(msg.command, msg.seq, body={
                    'threads': [t.to_raw() for t in self._threads.values()],
                })

            elif isinstance(msg, VariablesRequest):
                variables = self._variables[msg.variables_reference]

                self._adapter.send_response(msg.command, msg.seq, body={
                    'variables': [v.to_raw() for v in variables],
                })

        out_data = self._adapter.data_to_send()
        if out_data:
            self._client_sock.send(out_data)
