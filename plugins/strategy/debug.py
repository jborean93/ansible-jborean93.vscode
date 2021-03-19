# Copyright (c) 2021 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
name: jborean93.vscode.debug
short_description: Executes tasks with a debugger for use in VSCode.
description:
- Acts like the linear strategy plugin but adds functionality for interacting
  with a debugger in Visual Studio Code.
author: Jordan Borean (@jborean93)
'''

import errno
import json
import queue
import select
import socket
import struct
import threading

from ansible import constants as C
from ansible.errors import AnsibleError, AnsibleAssertionError
from ansible.executor.play_iterator import PlayIterator
from ansible.module_utils.six import iteritems
from ansible.module_utils.common.text.converters import to_text
from ansible.playbook.block import Block
from ansible.playbook.included_file import IncludedFile
from ansible.playbook.task import Task
from ansible.plugins.loader import action_loader
from ansible.plugins.strategy import StrategyBase
from ansible.template import Templar
from ansible.utils.display import Display

from ansible_collections.jborean93.vscode.plugins.plugin_utils.debug_adapter import DebugAdapter


display = Display()


def _recv_raw(sock, length):
    buffer = bytearray(length)
    offset = 0
    while offset < length:
        read_len = length - offset

        try:
            b_data = sock.recv(read_len)
        except socket.error as e:
            if e.errno not in [errno.ESHUTDOWN, errno.ECONNRESET]:
                raise
            b_data = b''

        if not b_data:
            return

        read_len = len(b_data)
        buffer[offset:offset + read_len] = b_data
        offset += read_len

    return bytes(buffer)


def _recv_data(sock):
    b_len = _recv_raw(sock, 4)
    if not b_len:
        return

    length = struct.unpack('<I', b_len)[0]
    packet = _recv_raw(sock, length)
    if not packet:
        return

    return packet


class AnsibleBreakpoint:

    def __init__(
            self,
            path,
            condition=None,
    ):
        self.path = path
        self.enabled = True
        self._condition = condition
        self._wait = threading.Event()

    def __repr__(self):
        condition = self._condition if self._condition else 'None'
        return '%s.%s(path=%s, condition=%s)' % (type(self).__module__, type(self).__name__, self.path, condition)

    def set(self):
        self._wait.set()

    def wait(self):
        # TODO: Send notification to peer that breakpoint was hit
        self._wait.wait()


class StrategyModule(StrategyBase):

    noop_task = None

    def __init__(self, tqm):
        super(StrategyModule, self).__init__(tqm)
        self._breakpoints = {}
        self._breakpoint_lock = threading.Lock()
        self._breakpoint_event = threading.Event()

    def _replace_with_noop(self, target):
        if self.noop_task is None:
            raise AnsibleAssertionError('strategy.linear.StrategyModule.noop_task is None, need Task()')

        result = []
        for el in target:
            if isinstance(el, Task):
                result.append(self.noop_task)
            elif isinstance(el, Block):
                result.append(self._create_noop_block_from(el, el._parent))
        return result

    def _create_noop_block_from(self, original_block, parent):
        noop_block = Block(parent_block=parent)
        noop_block.block = self._replace_with_noop(original_block.block)
        noop_block.always = self._replace_with_noop(original_block.always)
        noop_block.rescue = self._replace_with_noop(original_block.rescue)

        return noop_block

    def _prepare_and_create_noop_block_from(self, original_block, parent, iterator):
        self.noop_task = Task()
        self.noop_task.action = 'meta'
        self.noop_task.args['_raw_params'] = 'noop'
        self.noop_task.implicit = True
        self.noop_task.set_loader(iterator._play._loader)

        return self._create_noop_block_from(original_block, parent)

    def _get_next_task_lockstep(self, hosts, iterator):
        '''
        Returns a list of (host, task) tuples, where the task may
        be a noop task to keep the iterator in lock step across
        all hosts.
        '''

        noop_task = Task()
        noop_task.action = 'meta'
        noop_task.args['_raw_params'] = 'noop'
        noop_task.implicit = True
        noop_task.set_loader(iterator._play._loader)

        host_tasks = {}
        display.debug("building list of next tasks for hosts")
        for host in hosts:
            host_tasks[host.name] = iterator.get_next_task_for_host(host, peek=True)
        display.debug("done building task lists")

        num_setups = 0
        num_tasks = 0
        num_rescue = 0
        num_always = 0

        display.debug("counting tasks in each state of execution")
        host_tasks_to_run = [(host, state_task)
                             for host, state_task in iteritems(host_tasks)
                             if state_task and state_task[1]]

        if host_tasks_to_run:
            try:
                lowest_cur_block = min(
                    (iterator.get_active_state(s).cur_block for h, (s, t) in host_tasks_to_run
                     if s.run_state != PlayIterator.ITERATING_COMPLETE))
            except ValueError:
                lowest_cur_block = None
        else:
            # empty host_tasks_to_run will just run till the end of the function
            # without ever touching lowest_cur_block
            lowest_cur_block = None

        for (k, v) in host_tasks_to_run:
            (s, t) = v

            s = iterator.get_active_state(s)
            if s.cur_block > lowest_cur_block:
                # Not the current block, ignore it
                continue

            if s.run_state == PlayIterator.ITERATING_SETUP:
                num_setups += 1
            elif s.run_state == PlayIterator.ITERATING_TASKS:
                num_tasks += 1
            elif s.run_state == PlayIterator.ITERATING_RESCUE:
                num_rescue += 1
            elif s.run_state == PlayIterator.ITERATING_ALWAYS:
                num_always += 1
        display.debug("done counting tasks in each state of execution:\n\tnum_setups: %s\n\tnum_tasks: %s\n\tnum_rescue: %s\n\tnum_always: %s" % (num_setups,
                                                                                                                                                  num_tasks,
                                                                                                                                                  num_rescue,
                                                                                                                                                  num_always))

        def _advance_selected_hosts(hosts, cur_block, cur_state):
            '''
            This helper returns the task for all hosts in the requested
            state, otherwise they get a noop dummy task. This also advances
            the state of the host, since the given states are determined
            while using peek=True.
            '''
            # we return the values in the order they were originally
            # specified in the given hosts array
            rvals = []
            display.debug("starting to advance hosts")
            for host in hosts:
                host_state_task = host_tasks.get(host.name)
                if host_state_task is None:
                    continue
                (s, t) = host_state_task
                s = iterator.get_active_state(s)
                if t is None:
                    continue
                if s.run_state == cur_state and s.cur_block == cur_block:
                    new_t = iterator.get_next_task_for_host(host)
                    rvals.append((host, t))
                else:
                    rvals.append((host, noop_task))
            display.debug("done advancing hosts to next task")
            return rvals

        # if any hosts are in ITERATING_SETUP, return the setup task
        # while all other hosts get a noop
        if num_setups:
            display.debug("advancing hosts in ITERATING_SETUP")
            return _advance_selected_hosts(hosts, lowest_cur_block, PlayIterator.ITERATING_SETUP)

        # if any hosts are in ITERATING_TASKS, return the next normal
        # task for these hosts, while all other hosts get a noop
        if num_tasks:
            display.debug("advancing hosts in ITERATING_TASKS")
            return _advance_selected_hosts(hosts, lowest_cur_block, PlayIterator.ITERATING_TASKS)

        # if any hosts are in ITERATING_RESCUE, return the next rescue
        # task for these hosts, while all other hosts get a noop
        if num_rescue:
            display.debug("advancing hosts in ITERATING_RESCUE")
            return _advance_selected_hosts(hosts, lowest_cur_block, PlayIterator.ITERATING_RESCUE)

        # if any hosts are in ITERATING_ALWAYS, return the next always
        # task for these hosts, while all other hosts get a noop
        if num_always:
            display.debug("advancing hosts in ITERATING_ALWAYS")
            return _advance_selected_hosts(hosts, lowest_cur_block, PlayIterator.ITERATING_ALWAYS)

        # at this point, everything must be ITERATING_COMPLETE, so we
        # return None for all hosts in the list
        display.debug("all hosts are done, so returning None's for all hosts")
        return [(host, None) for host in hosts]

    def _process_client(self, sock, signal_sock):
        try:
            client, addr = sock.accept()
        except OSError:
            # If the socket was closed before anyone accepted then it raises OSError invalid argument.
            return

        with client:
            debug_adapter = DebugAdapter()

            while True:
                # We need to be notified from the main thread that the run has ended so wait on either a response on
                # the client or signal socket from the main thread.
                read = select.select([client, signal_sock], [], [])[0]

                if client in read:
                    in_data = client.recv(1024)
                    events = debug_adapter.receive_data(in_data)
                    if not events:
                        continue

                    while True:
                        out_data = debug_adapter.data_to_send()
                        if not out_data:
                            break

                        offset = 0
                        while offset < len(out_data):
                            offset += client.send(out_data[offset:])

                    action_type = 0
                    if action_type == 1:
                        # SetBreakpoint
                        # state (4)  (0 is disabled, 1 is enabled, 2 is removed)
                        # path_length (4)
                        # condition_length (4)
                        # path (variable)
                        # condition (variable)
                        # TODO: Remove once hit
                        state = struct.unpack("<I", packet[4:8])[0]
                        path_len = struct.unpack("<I", packet[8:12])[0]
                        condition_len = struct.unpack("<I", packet[12:16])[0]
                        path_end = 16 + path_len
                        path = to_text(packet[16:path_end], errors='surrogate_or_strict')
                        condition = to_text(packet[path_end:path_end + condition_len], errors='surrogate_or_strict')

                        with self._breakpoint_lock:
                            bp = self._breakpoints.setdefault(path, AnsibleBreakpoint(path, (condition or None)))

                            if state == 0:
                                bp.enabled = False

                            elif state == 1:
                                bp.enabled = True

                            elif state == 2:
                                del self._breakpoints[path]

                    elif action_type == 2:
                        # Continue
                        # N/A
                        self._breakpoint_event.set()
                        self._breakpoint_event.clear()

                    elif action_type == 3:
                        # GetVariable
                        a = ''

                    elif action_type == 4:
                        # SetVariable
                        a = ''

                if signal_sock in read:
                    # Have been signaled by the parent to stop listening.
                    signal_sock.recv(1024)  # Just clear out the buffer
                    break

            client.shutdown(socket.SHUT_RDWR)

    def run(self, iterator, play_context):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', 6845))  # TODO get port from env var, should we use '' on the host for INADDR_ANY?
            s.listen(1)

            wsock, rsock = socket.socketpair()
            client_task = threading.Thread(name='debug-client', target=self._process_client, args=(s, rsock))
            try:
                client_task.start()

                # Wait until a client connects before running
                print("Waiting for client connection")
                self._breakpoint_event.wait()

                return self._run(iterator, play_context)

            finally:
                s.shutdown(socket.SHUT_RDWR)

                # Signal the debug task listener to stop so we can join the thread and continue on.
                wsock.send(b'\x00')
                wsock.close()
                client_task.join()
                rsock.close()

    def _run(self, iterator, play_context):
        result = self._tqm.RUN_OK
        work_to_do = True

        self._set_hosts_cache(iterator._play)

        while work_to_do and not self._tqm._terminated:

            try:
                display.debug("getting the remaining hosts for this loop")
                hosts_left = self.get_hosts_left(iterator)
                display.debug("done getting the remaining hosts for this loop")

                # queue up this task for each host in the inventory
                callback_sent = False
                work_to_do = False

                host_results = []
                host_tasks = self._get_next_task_lockstep(hosts_left, iterator)

                # skip control
                skip_rest = False
                choose_step = True

                # flag set if task is set to any_errors_fatal
                any_errors_fatal = False

                results = []
                for (host, task) in host_tasks:
                    if not task:
                        continue

                    if self._tqm._terminated:
                        break

                    run_once = False
                    work_to_do = True

                    # check to see if this task should be skipped, due to it being a member of a
                    # role which has already run (and whether that role allows duplicate execution)
                    if task._role and task._role.has_run(host):
                        # If there is no metadata, the default behavior is to not allow duplicates,
                        # if there is metadata, check to see if the allow_duplicates flag was set to true
                        if task._role._metadata is None or task._role._metadata and not task._role._metadata.allow_duplicates:
                            display.debug("'%s' skipped because role has already run" % task)
                            continue

                    display.debug("getting variables")
                    task_vars = self._variable_manager.get_vars(play=iterator._play, host=host, task=task,
                                                                _hosts=self._hosts_cache, _hosts_all=self._hosts_cache_all)
                    self.add_tqm_variables(task_vars, play=iterator._play)
                    templar = Templar(loader=self._loader, variables=task_vars)
                    display.debug("done getting variables")

                    # test to see if the task across all hosts points to an action plugin which
                    # sets BYPASS_HOST_LOOP to true, or if it has run_once enabled. If so, we
                    # will only send this task to the first host in the list.

                    task.action = templar.template(task.action)

                    try:
                        action = action_loader.get(task.action, class_only=True, collection_list=task.collections)
                    except KeyError:
                        # we don't care here, because the action may simply not have a
                        # corresponding action plugin
                        action = None

                    if task.action in C._ACTION_META:
                        # for the linear strategy, we run meta tasks just once and for
                        # all hosts currently being iterated over rather than one host
                        results.extend(self._execute_meta(task, play_context, iterator, host))
                        if task.args.get('_raw_params', None) not in ('noop', 'reset_connection', 'end_host', 'role_complete'):
                            run_once = True
                        if (task.any_errors_fatal or run_once) and not task.ignore_errors:
                            any_errors_fatal = True
                    else:
                        # handle step if needed, skip meta actions as they are used internally
                        if self._step and choose_step:
                            if self._take_step(task):
                                choose_step = False
                            else:
                                skip_rest = True
                                break

                        run_once = templar.template(task.run_once) or action and getattr(action, 'BYPASS_HOST_LOOP', False)

                        if (task.any_errors_fatal or run_once) and not task.ignore_errors:
                            any_errors_fatal = True

                        if not callback_sent:
                            display.debug("sending task start callback, copying the task so we can template it temporarily")
                            saved_name = task.name
                            display.debug("done copying, going to template now")
                            try:
                                task.name = to_text(templar.template(task.name, fail_on_undefined=False), nonstring='empty')
                                display.debug("done templating")
                            except Exception:
                                # just ignore any errors during task name templating,
                                # we don't care if it just shows the raw name
                                display.debug("templating failed for some reason")
                            display.debug("here goes the callback...")
                            self._tqm.send_callback('v2_playbook_on_task_start', task, is_conditional=False)
                            task.name = saved_name
                            callback_sent = True
                            display.debug("sending task start callback")

                        self._blocked_hosts[host.get_name()] = True

                        task_path = task.get_path()
                        with self._breakpoint_lock:
                            bp = self._breakpoints.get(task_path, None)

                        # TODO: evaluate condition
                        if bp:
                            print(f"Found breakpoint {bp!r} waiting")
                            self._breakpoint_event.wait()
                            print(f"Continuing from breakpoinrt {bp!r}")

                        self._queue_task(host, task, task_vars, play_context)
                        del task_vars

                    # if we're bypassing the host loop, break out now
                    if run_once:
                        break

                    results += self._process_pending_results(iterator, max_passes=max(1, int(len(self._tqm._workers) * 0.1)))

                # go to next host/task group
                if skip_rest:
                    continue

                display.debug("done queuing things up, now waiting for results queue to drain")
                if self._pending_results > 0:
                    results += self._wait_on_pending_results(iterator)

                host_results.extend(results)

                self.update_active_connections(results)

                included_files = IncludedFile.process_include_results(
                    host_results,
                    iterator=iterator,
                    loader=self._loader,
                    variable_manager=self._variable_manager
                )

                include_failure = False
                if len(included_files) > 0:
                    display.debug("we have included files to process")

                    display.debug("generating all_blocks data")
                    all_blocks = dict((host, []) for host in hosts_left)
                    display.debug("done generating all_blocks data")
                    for included_file in included_files:
                        display.debug("processing included file: %s" % included_file._filename)
                        # included hosts get the task list while those excluded get an equal-length
                        # list of noop tasks, to make sure that they continue running in lock-step
                        try:
                            if included_file._is_role:
                                new_ir = self._copy_included_file(included_file)

                                new_blocks, handler_blocks = new_ir.get_block_list(
                                    play=iterator._play,
                                    variable_manager=self._variable_manager,
                                    loader=self._loader,
                                )
                            else:
                                new_blocks = self._load_included_file(included_file, iterator=iterator)

                            display.debug("iterating over new_blocks loaded from include file")
                            for new_block in new_blocks:
                                task_vars = self._variable_manager.get_vars(
                                    play=iterator._play,
                                    task=new_block.get_first_parent_include(),
                                    _hosts=self._hosts_cache,
                                    _hosts_all=self._hosts_cache_all,
                                )
                                display.debug("filtering new block on tags")
                                final_block = new_block.filter_tagged_tasks(task_vars)
                                display.debug("done filtering new block on tags")

                                noop_block = self._prepare_and_create_noop_block_from(final_block, task._parent, iterator)

                                for host in hosts_left:
                                    if host in included_file._hosts:
                                        all_blocks[host].append(final_block)
                                    else:
                                        all_blocks[host].append(noop_block)
                            display.debug("done iterating over new_blocks loaded from include file")

                        except AnsibleError as e:
                            for host in included_file._hosts:
                                self._tqm._failed_hosts[host.name] = True
                                iterator.mark_host_failed(host)
                            display.error(to_text(e), wrap_text=False)
                            include_failure = True
                            continue

                    # finally go through all of the hosts and append the
                    # accumulated blocks to their list of tasks
                    display.debug("extending task lists for all hosts with included blocks")

                    for host in hosts_left:
                        iterator.add_tasks(host, all_blocks[host])

                    display.debug("done extending task lists")
                    display.debug("done processing included files")

                display.debug("results queue empty")

                display.debug("checking for any_errors_fatal")
                failed_hosts = []
                unreachable_hosts = []
                for res in results:
                    # execute_meta() does not set 'failed' in the TaskResult
                    # so we skip checking it with the meta tasks and look just at the iterator
                    if (res.is_failed() or res._task.action in C._ACTION_META) and iterator.is_failed(res._host):
                        failed_hosts.append(res._host.name)
                    elif res.is_unreachable():
                        unreachable_hosts.append(res._host.name)

                # if any_errors_fatal and we had an error, mark all hosts as failed
                if any_errors_fatal and (len(failed_hosts) > 0 or len(unreachable_hosts) > 0):
                    dont_fail_states = frozenset([iterator.ITERATING_RESCUE, iterator.ITERATING_ALWAYS])
                    for host in hosts_left:
                        (s, _) = iterator.get_next_task_for_host(host, peek=True)
                        # the state may actually be in a child state, use the get_active_state()
                        # method in the iterator to figure out the true active state
                        s = iterator.get_active_state(s)
                        if s.run_state not in dont_fail_states or \
                           s.run_state == iterator.ITERATING_RESCUE and s.fail_state & iterator.FAILED_RESCUE != 0:
                            self._tqm._failed_hosts[host.name] = True
                            result |= self._tqm.RUN_FAILED_BREAK_PLAY
                display.debug("done checking for any_errors_fatal")

                display.debug("checking for max_fail_percentage")
                if iterator._play.max_fail_percentage is not None and len(results) > 0:
                    percentage = iterator._play.max_fail_percentage / 100.0

                    if (len(self._tqm._failed_hosts) / iterator.batch_size) > percentage:
                        for host in hosts_left:
                            # don't double-mark hosts, or the iterator will potentially
                            # fail them out of the rescue/always states
                            if host.name not in failed_hosts:
                                self._tqm._failed_hosts[host.name] = True
                                iterator.mark_host_failed(host)
                        self._tqm.send_callback('v2_playbook_on_no_hosts_remaining')
                        result |= self._tqm.RUN_FAILED_BREAK_PLAY
                    display.debug('(%s failed / %s total )> %s max fail' % (len(self._tqm._failed_hosts), iterator.batch_size, percentage))
                display.debug("done checking for max_fail_percentage")

                display.debug("checking to see if all hosts have failed and the running result is not ok")
                if result != self._tqm.RUN_OK and len(self._tqm._failed_hosts) >= len(hosts_left):
                    display.debug("^ not ok, so returning result now")
                    self._tqm.send_callback('v2_playbook_on_no_hosts_remaining')
                    return result
                display.debug("done checking to see if all hosts have failed")

            except (IOError, EOFError) as e:
                display.debug("got IOError/EOFError in task loop: %s" % e)
                # most likely an abort, return failed
                return self._tqm.RUN_UNKNOWN_ERROR

        # run the base class run() method, which executes the cleanup function
        # and runs any outstanding handlers which have been triggered

        return super(StrategyModule, self).run(iterator, play_context, result)
