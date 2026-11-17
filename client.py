#!/usr/bin/env python3
"""CLI client for the JSON/TCP Tic-Tac-Toe protocol."""
import argparse
import json
import socket
import sys
import threading
import uuid

MAX_LINE = 8192


def board_text(board):
    cells = [str(i) if cell is None else cell for i, cell in enumerate(board)]
    return ('\n  ' + ' | '.join(cells[0:3]) + '\n'
            ' ---+---+---\n  ' + ' | '.join(cells[3:6]) + '\n'
            ' ---+---+---\n  ' + ' | '.join(cells[6:9]) + '\n')


class Client:
    def __init__(self, sock, name):
        self.sock = sock
        self.id = 'player-' + uuid.uuid4().hex[:12]
        self.name = name
        self.game_id = 'pending'
        self.symbol = None
        self.turn = None
        self.board = [None] * 9
        self.finished = False
        self.running = True
        self.send_lock = threading.Lock()
        self.input_event = threading.Event()
        self.round = 1

    def send(self, kind, **payload):
        message = {'type': kind, 'game_id': self.game_id,
                   'player_id': self.id, 'payload': payload}
        with self.send_lock:
            self.sock.sendall((json.dumps(message, separators=(',', ':')) + '\n').encode())

    def show_turn(self):
        if self.finished:
            print('[GAME] Round complete. Enter r for another round or q to quit.', flush=True)
        elif self.turn == self.id:
            print('[TURN] Your Turn! Enter a square 0-8 (or q to quit).', flush=True)
        elif self.turn:
            print('[TURN] Waiting for Player 2...' if self.symbol == 'X' else '[TURN] Waiting for Player 1...', flush=True)

    def handle(self, msg):
        if not isinstance(msg, dict) or not isinstance(msg.get('payload'), dict):
            return
        kind = msg.get('type')
        payload = msg['payload']
        if kind == 'LOBBY_WAIT':
            self.game_id = 'pending'
            self.turn = None
            self.finished = False
            print('[LOBBY] Waiting for another player...', flush=True)
        elif kind == 'GAME_START':
            self.game_id = msg['game_id']
            self.symbol = payload['symbol']
            self.turn = payload['current_turn']
            self.board = payload['board']
            self.round = payload.get('round', 1)
            self.finished = False
            print(f'\n[GAME] Round {self.round} started! You are Player {1 if self.symbol == "X" else 2} ({self.symbol}).', flush=True)
            print(board_text(self.board), flush=True)
            self.show_turn()
        elif kind == 'STATE_UPDATE':
            self.board = payload['board']
            self.turn = payload['next_turn']
            last = payload['last_move']
            print(f'\n[MOVE] {last["symbol"]} played square {last["position"]}.', flush=True)
            print(board_text(self.board), flush=True)
            if self.turn:
                self.show_turn()
        elif kind == 'GAME_OVER':
            self.finished = True
            self.turn = None
            self.board = payload['board']
            if payload['result'] == 'DRAW':
                print('[RESULT] Draw!', flush=True)
            else:
                print('[RESULT] You win!' if payload['winner'] == self.id else '[RESULT] You lose.', flush=True)
                if payload['result'] == 'FORFEIT':
                    print('[RESULT] Opponent disconnected (forfeit).', flush=True)
            self.show_turn()
        elif kind == 'SCORE_UPDATE':
            scores = payload['scores']
            names = payload.get('names', {})
            entries = ', '.join(f'{names.get(pid, pid)}: {score}' for pid, score in scores.items())
            print(f'[SCORES] {entries} | Draws: {payload["draws"]}', flush=True)
        elif kind == 'ERROR':
            print(f'[ERROR] {payload.get("code", "UNKNOWN")}: {payload.get("message", "Unknown error")}', flush=True)
        self.input_event.set()

    def receive(self):
        buf = bytearray()
        try:
            while self.running:
                chunk = self.sock.recv(4096)
                if not chunk:
                    print('\n[CONNECTION] Server closed the connection.', flush=True)
                    break
                buf.extend(chunk)
                if len(buf) > MAX_LINE and b'\n' not in buf:
                    print('[ERROR] Oversized server message.', flush=True)
                    break
                while b'\n' in buf:
                    raw, _, rest = buf.partition(b'\n')
                    buf = bytearray(rest)
                    if len(raw) > MAX_LINE:
                        print('[ERROR] Oversized server message.', flush=True)
                        return
                    try:
                        self.handle(json.loads(raw.decode('utf-8')))
                    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                        print(f'[ERROR] Malformed server message: {exc}', flush=True)
        except OSError:
            if self.running:
                print('\n[CONNECTION] Connection lost.', flush=True)
        finally:
            self.running = False
            self.input_event.set()

    def run(self):
        threading.Thread(target=self.receive, daemon=True).start()
        self.send('CONNECT', player_name=self.name)
        print('[INFO] Commands: 0-8 = move, r = next round, q = quit.', flush=True)
        try:
            while self.running:
                # input() may block until Enter even if the connection closes.
                try:
                    choice = input('> ').strip().lower()
                except EOFError:
                    break
                if choice in ('q', 'quit', 'exit'):
                    break
                if not self.running:
                    break
                if choice == 'r':
                    if self.finished and self.game_id != 'pending':
                        self.send('NEW_ROUND')
                    else:
                        print('[INFO] Finish the current round first.', flush=True)
                elif choice.isdigit() and len(choice) == 1:
                    if self.finished or self.game_id == 'pending':
                        print('[INFO] No active round. Wait for an opponent or enter r.', flush=True)
                    elif self.turn != self.id:
                        print('[INFO] It is not your turn.', flush=True)
                    else:
                        self.send('MOVE', position=int(choice))
                else:
                    print('[INFO] Enter a square (0-8), r, or q.', flush=True)
        except (OSError, KeyboardInterrupt):
            pass
        finally:
            if self.running:
                try:
                    self.send('DISCONNECT', reason='CLIENT_EXIT')
                except OSError:
                    pass
            self.running = False
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
            print('[INFO] Disconnected.', flush=True)


def main():
    parser = argparse.ArgumentParser(description='JSON/TCP Tic-Tac-Toe CLI client')
    parser.add_argument('-i', '--hostname', required=True, help='Server DNS hostname or IPv4 address')
    parser.add_argument('-p', '--port', required=True, type=int, help='Server TCP port (1-65535)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    try:
        server_ip = socket.gethostbyname(args.hostname)
    except socket.gaierror:
        print(f"[ERROR] Unable to resolve DNS hostname '{args.hostname}'.")
        print("Please check your Cisco router DNS configuration ('ip dns server' / 'ip host') or verify domain spelling.")
        sys.exit(1)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((server_ip, args.port))
        sock.settimeout(None)
    except OSError as exc:
        print(f'[ERROR] Unable to connect to {args.hostname}:{args.port}: {exc}')
        sys.exit(1)
    print(f'[CONNECTED] {args.hostname} ({server_ip}):{args.port}', flush=True)
    try:
        name = input('Player name: ').strip()[:24] or 'Player'
    except EOFError:
        name = 'Player'
    Client(sock, name).run()

if __name__ == '__main__':
    main()
