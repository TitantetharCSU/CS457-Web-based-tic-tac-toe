#!/usr/bin/env python3
"""Automated integration test and reproducible gameplay console transcript."""
import json
import socket
import threading
from server import Server
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def send(sock, kind, gid, pid, **payload):
    sock.sendall((json.dumps({'type':kind,'game_id':gid,'player_id':pid,'payload':payload})+'\n').encode())

def receive(sock, expected):
    while True:
        line = sock.makefile('rb').readline()  # one buffered reader per socket is required
        if not line:
            raise AssertionError('Connection closed')
        obj = json.loads(line)
        if obj['type'] == expected:
            return obj
        raise AssertionError(f'Expected {expected}, received {obj}')


def run():
    listener = socket.socket()
    listener.bind(('127.0.0.1',0))
    port = listener.getsockname()[1]
    listener.close()
    threading.Thread(target=Server().serve, args=(port,), daemon=True).start()
    a = b = None
    log = []
    def out(text):
        print(text)
        log.append(text)
    try:
        time.sleep(.25)
        a = socket.create_connection(('127.0.0.1',port),timeout=5)
        b = socket.create_connection(('127.0.0.1',port),timeout=5)
        a.settimeout(5); b.settimeout(5)
        # Buffered readers must be persistent across calls.
        ar = a.makefile('rb'); br = b.makefile('rb')
        def get(reader, kind):
            obj = json.loads(reader.readline())
            assert obj['type'] == kind, obj
            return obj
        send(a,'CONNECT','pending','player-a',player_name='Alice')
        out('CLIENT 1: CONNECT Alice')
        assert get(ar,'LOBBY_WAIT')['payload']['players_waiting'] == 1
        out('CLIENT 1: LOBBY_WAIT (waiting for opponent)')
        send(b,'CONNECT','pending','player-b',player_name='Bob')
        out('CLIENT 2: CONNECT Bob')
        start_a = get(ar,'GAME_START'); start_b = get(br,'GAME_START')
        gid = start_a['game_id']
        assert gid == start_b['game_id']
        get(ar,'SCORE_UPDATE'); get(br,'SCORE_UPDATE')
        out('CLIENT 1: GAME_START as X; your turn')
        out('CLIENT 2: GAME_START as O; waiting for Player 1')
        for idx,(sock,pid,pos) in enumerate([(a,'player-a',0),(b,'player-b',3),(a,'player-a',1),(b,'player-b',4),(a,'player-a',2)],1):
            send(sock,'MOVE',gid,pid,position=pos)
            update_a=get(ar,'STATE_UPDATE'); update_b=get(br,'STATE_UPDATE')
            assert update_a['payload']['board']==update_b['payload']['board']
            out(f'TURN {idx}: {pid} MOVE {pos}; both clients received STATE_UPDATE')
        result_a=get(ar,'GAME_OVER'); result_b=get(br,'GAME_OVER')
        assert result_a['payload']['winner']=='player-a'
        assert result_b['payload']['result']=='WIN'
        scores_a=get(ar,'SCORE_UPDATE'); scores_b=get(br,'SCORE_UPDATE')
        assert scores_a['payload']['scores']['player-a']==1
        assert scores_a['payload']['scores']==scores_b['payload']['scores']
        out('CLIENT 1: GAME_OVER (WIN); SCORE_UPDATE Alice=1 Bob=0')
        out('CLIENT 2: GAME_OVER (LOSS); SCORE_UPDATE Alice=1 Bob=0')
        send(a,'NEW_ROUND',gid,'player-a')
        assert get(ar,'GAME_START')['payload']['round']==2
        assert get(br,'GAME_START')['payload']['round']==2
        get(ar,'SCORE_UPDATE'); get(br,'SCORE_UPDATE')
        out('BOTH CLIENTS: NEW_ROUND confirmed; scores preserved')
        send(a,'DISCONNECT',gid,'player-a',reason='CLIENT_EXIT')
        out('CLIENT 1: DISCONNECT')
        (ROOT/'gameplay_log.txt').write_text('\n'.join(log)+'\n')
        out('PASS: full TCP integration test')
    finally:
        for s in (a,b):
            if s:
                s.close()
        # Daemon server thread exits when the test process exits.

if __name__=='__main__':
    run()
