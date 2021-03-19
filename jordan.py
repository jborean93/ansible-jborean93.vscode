#!/usr/bin/env python

import socket

from plugins.plugin_utils.debug_adapter import (
    Breakpoint,
    ConfigurationDoneRequest,
    DebugAdapter,
    DisconnectRequest,
    LaunchRequest,
    SetBreakpointsRequest,
    StackTraceRequest,
    ThreadRequest,
)

adapter = DebugAdapter()


def actual(client):
    bid = 1
    run = True

    while run:
        in_data = client.recv(1024)
        events = adapter.receive_data(in_data)

        for event in events:
            if isinstance(event, ConfigurationDoneRequest):
                adapter.stop('breakpoint', description='description here', text='text here', hit_breakpoint_ids=1,
                             thread_id=1)

            elif isinstance(event, DisconnectRequest):
                run = False

            elif isinstance(event, SetBreakpointsRequest):
                new_breakpoints = []
                for source_b in event.breakpoints:
                    b = Breakpoint(bid, True)
                    bid += 1
                    new_breakpoints.append(b)

                adapter.set_breakpoints(event.seq, new_breakpoints)

            elif isinstance(event, StackTraceRequest):
                a = ''

            elif isinstance(event, ThreadRequest):
                adapter.send_threads(event.seq, ['main'])

        while True:
            out_data = adapter.data_to_send()
            if not out_data:
                break

            client.send(out_data)


def test(client):
    data = client.recv(1024)

    #first = b'{"seq":1,"type":"response","request_seq":1,"command":"initialize","success":true,"body":{}}'
    #second = b'{"seq":2,"type":"event","event":"initialized"}'

    first = b'{"request_seq":1,"success":true,"command":"initialize","body":{},"type":"response","seq":1}'
    second = b'{"event":"initialized","type":"event","seq":2}'

    client.send(b'Content-Length: %s\r\n\r\n%s' % (str(len(first)).encode(), first))
    client.send(b'Content-Length: %s\r\n\r\n%s' % (str(len(second)).encode(), second))
    data = client.recv(1024)
    print(data)
    a = ''


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 6845))  # TODO get port from env var, should we use '' on the host for INADDR_ANY?
    s.listen(1)
    client, addr = s.accept()

    with client:
        actual(client)
        #test(client)
