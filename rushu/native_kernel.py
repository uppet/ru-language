"""Transport/lifecycle adapter for the native Ru AST interpreter.

This module never parses or evaluates guest source. The existing Session owns
execution identity, input validation, output retention and process replacement.
"""
from collections import deque
import json
from pathlib import Path
import secrets
import subprocess
import threading

from rulang.diagnostics import SourceOrigin, diagnostic
from rulang.frontend import RuError

ROOT = Path(__file__).resolve().parents[1]


class NativeProcess:
    def __init__(self, executable):
        executable = Path(executable).resolve(strict=True)
        self.child = subprocess.Popen([str(executable), '--stdio', str(ROOT/'rulang/stdlib')],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, bufsize=0)
        self.pid, self.sentinel = self.child.pid, None
        self.stderr = deque(maxlen=16)
        self.reader = threading.Thread(target=self._drain_errors, daemon=True,
                                       name='rushu-native-stderr')
        self.reader.start()

    def _drain_errors(self):
        while True:
            part = self.child.stderr.read(1024)
            if not part:
                return
            self.stderr.append(part)

    def is_alive(self):
        return self.child.poll() is None

    def terminate(self):
        self.child.terminate()

    def kill(self):
        self.child.kill()

    def join(self, timeout=None):
        try:
            self.child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass

    def close(self):
        self.reader.join(timeout=2)
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            stream.close()


class NativeConnection:
    def __init__(self, process):
        self.process = process
        self.lock = threading.Lock()
        self.origins = {}
        self.current_origin = None
        self.ready = False
        self.closed = False

    def send(self, command):
        kind = command['kind']
        if kind == 'execute':
            origin = SourceOrigin(**command['source_origin'])
            self.origins[origin.source_name] = origin
            self.current_origin = origin
            source, name = command['code'].encode('utf-8'), origin.source_name.encode('utf-8')
            data = f'RU2 E {len(source)} {len(name)}\n'.encode('ascii')+source+name
        elif kind == 'input':
            source = command['text'].encode('utf-8')
            data = f'RU2 I {len(source)} {int(command["eof"])}\n'.encode('ascii')+source
        elif kind in ('graphics', 'graphics_rejected'):
            name = command['canvas_id'].encode('utf-8')
            source = b''
            if kind == 'graphics':
                event = command['event']
                # Four fixed lines precede the raw key (which may contain LF).
                source = ('\n'.join((event['type'], str(event.get('x', 0)),
                    str(event.get('y', 0)), str(event.get('button', 0))))+'\n'+event.get('key', '')).encode('utf-8')
            letter = 'G' if kind == 'graphics' else 'R'
            data = f'RU2 {letter} {len(source)} {len(name)}\n'.encode('ascii')+source+name
        elif kind == 'close':
            data = b'RU2 Q 0 0\n'
        else:
            raise ValueError('native AST kernel does not support '+kind)
        with self.lock:
            if self.closed:
                raise BrokenPipeError('native kernel is closed')
            # FileIO.write may be short for large cells, especially on Windows.
            view = memoryview(data)
            while view:
                count = self.process.child.stdin.write(view)
                if not count:
                    raise BrokenPipeError('native kernel disconnected')
                view = view[count:]

    def recv(self):
        while True:
            line = self.process.child.stdout.readline(4*1024*1024+1)
            if not line:
                raise EOFError('native kernel exited')
            if not line.endswith(b'\n') or len(line) > 4*1024*1024:
                raise ValueError('invalid native kernel event size')
            event = json.loads(line.decode('utf-8'))
            if not isinstance(event, dict):
                raise ValueError('invalid native kernel event')
            if not self.ready:
                if event != {'type': 'ready', 'protocol': 2, 'engine': 'ru-ast'}:
                    raise ValueError('native kernel protocol mismatch')
                self.ready = True
                continue
            kind = event.get('type')
            if kind == 'input_request':
                event['request_id'] = secrets.token_hex(16)
            elif kind == 'error':
                name = event['source_name']
                origin = self.origins.get(name)
                message = event['message']
                category = event['category']
                line_number, column = event['line'], event['col']
                # The shared native parser already emits its own exact source
                # position. Decode that diagnostic header, never the source.
                prefix = name+':'
                if message.startswith(prefix):
                    pieces = message[len(prefix):].split(':', 3)
                    if len(pieces) == 4 and pieces[0].isdigit() and pieces[1].isdigit():
                        line_number, column = int(pieces[0]), int(pieces[1])
                        message = pieces[3].strip().removeprefix('自举编译错误：')
                error = RuError(message, line_number, column, category)
                error.source_name = name
                error.source_origin = origin
                event = dict(type='error', diagnostic=diagnostic(error, name),
                             source_name=name, line=line_number, col=column,
                             category=category, message=message)
            elif kind not in ('output', 'done', 'graphics', 'graphics_closed', 'graphics_done'):
                raise ValueError('unknown native kernel event')
            return event

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.process.child.stdin.close()
