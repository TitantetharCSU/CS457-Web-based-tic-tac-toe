#!/usr/bin/env python3
"""Threaded, server-authoritative NDJSON Tic-Tac-Toe server."""
import argparse
import json
import socket
import threading
import uuid
from collections import deque

MAX_LINE = 8192
WINS = ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))


def packet(kind, game_id, **payload):
    return {"type": kind, "game_id": game_id, "player_id": "server", "payload": payload}


class Peer:
    def __init__(self, sock, address):
        self.sock, self.address = sock, address
        self.send_lock = threading.Lock()
        self.id = None
        self.name = None
        self.game = None
        self.connected = True

    def send(self, message):
        data = (json.dumps(message, separators=(',', ':')) + '\n').encode('utf-8')
        try:
            with self.send_lock:
                if not self.connected:
                    return False
                self.sock.sendall(data)
            return True
        except OSError:
            return False


class Game:
    def __init__(self, first, second):
        self.id = 'game-' + uuid.uuid4().hex[:8]
        self.players = [first, second]
        self.board = [None] * 9
        self.turn = first.id
        self.status = 'ACTIVE'
        self.scores = {first.id: 0, second.id: 0}
        self.draws = 0
        self.round = 1
        self.version = 1
        self.fsm = 'GAME_START'
        self.fsm = 'PLAYER_TURN'

    def score_packet(self):
        return packet('SCORE_UPDATE', self.id, scores=dict(self.scores),
                      names={p.id: p.name for p in self.players}, draws=self.draws,
                      round=self.round, state_version=self.version)


def winner(board):
    for a, b, c in WINS:
        if board[a] is not None and board[a] == board[b] == board[c]:
            return board[a]
    return None


class Server:
    def __init__(self):
        self.lock = threading.Lock()
        self.waiting = deque()
        self.games = {}
        self.peers = set()

    def dispatch(self, deliveries):
        # Called under the shared state lock to preserve per-game message ordering.
        # Individual socket send locks prevent writes from interleaving.
        for peer, message in deliveries:
            if not peer.send(message):
                # The peer's recv thread will handle socket closure, or next I/O will fail.
                try:
                    peer.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def error(self, peer, code, message):
        gid = peer.game.id if peer.game else 'pending'
        return [(peer, packet('ERROR', gid, code=code, message=message))]

    def connect(self, peer, msg):
        if peer.id is not None:
            return self.error(peer, 'INVALID_MESSAGE', 'CONNECT may only be sent once.')
        pid = msg.get('player_id')
        name = msg['payload'].get('player_name')
        if not isinstance(pid, str) or not (1 <= len(pid) <= 64) or not isinstance(name, str) or not (1 <= len(name.strip()) <= 24):
            return self.error(peer, 'INVALID_MESSAGE', 'Provide a valid player ID and name (1-24 characters).')
        if any(p.id == pid for p in self.peers if p is not peer):
            return self.error(peer, 'INVALID_MESSAGE', 'Player ID already connected.')
        peer.id, peer.name = pid, name.strip().replace('\n', ' ').replace('\r', ' ')
        if self.waiting:
            other = self.waiting.popleft()
            game = Game(other, peer)
            other.game = peer.game = game
            self.games[game.id] = game
            result = []
            for index, p in enumerate(game.players):
                result.append((p, packet('GAME_START', game.id,
                    role='PLAYER_1' if index == 0 else 'PLAYER_2',
                    symbol='X' if index == 0 else 'O',
                    opponent_id=game.players[1-index].id,
                    board=list(game.board), current_turn=game.turn,
                    round=game.round, state_version=game.version)))
            result.extend((p, game.score_packet()) for p in game.players)
            print(f'[GAME] {game.id}: {other.name} (X) vs {peer.name} (O)', flush=True)
            return result
        self.waiting.append(peer)
        return [(peer, packet('LOBBY_WAIT', 'pending', players_waiting=len(self.waiting)))]

    def move(self, peer, msg):
        game = peer.game
        if not game or msg['game_id'] != game.id or game.id not in self.games:
            return self.error(peer, 'GAME_NOT_FOUND', 'No matching active game.')
        if peer not in game.players:
            return self.error(peer, 'NOT_PLAYER', 'You are not a participant.')
        if game.status != 'ACTIVE':
            return self.error(peer, 'GAME_OVER', 'This round is finished.')
        if game.turn != peer.id:
            return self.error(peer, 'OUT_OF_TURN', 'It is not your turn.')
        pos = msg['payload'].get('position')
        if type(pos) is not int or not 0 <= pos <= 8:
            return self.error(peer, 'INVALID_POSITION', 'Choose a position from 0 to 8.')
        if game.board[pos] is not None:
            return self.error(peer, 'OCCUPIED_POSITION', 'That square is already occupied.')
        game.fsm = 'EVALUATE_MOVE'
        symbol = 'X' if peer is game.players[0] else 'O'
        game.board[pos] = symbol
        win = winner(game.board)
        draw = win is None and all(v is not None for v in game.board)
        game.turn = None if win or draw else game.players[1 if peer is game.players[0] else 0].id
        game.version += 1
        state = packet('STATE_UPDATE', game.id, board=list(game.board),
                       last_move={'player_id': peer.id, 'position': pos, 'symbol': symbol},
                       next_turn=game.turn, state_version=game.version)
        deliveries = [(p, state) for p in game.players]
        print(f'[MOVE] {game.id}: {peer.name} ({symbol}) -> {pos}', flush=True)
        if win or draw:
            game.status = 'FINISHED'
            game.fsm = 'GAME_OVER'
            if win:
                game.scores[peer.id] += 1
            else:
                game.draws += 1
            result = packet('GAME_OVER', game.id, result='WIN' if win else 'DRAW',
                            winner=peer.id if win else None,
                            reason='THREE_IN_A_ROW' if win else 'BOARD_FULL',
                            board=list(game.board), round=game.round)
            deliveries.extend((p, result) for p in game.players)
            deliveries.extend((p, game.score_packet()) for p in game.players)
            print(f'[RESULT] {game.id}: {"winner=" + peer.name if win else "draw"}', flush=True)
        else:
            game.fsm = 'PLAYER_TURN'
        return deliveries

    def new_round(self, peer, msg):
        game = peer.game
        if not game or msg['game_id'] != game.id or game.id not in self.games:
            return self.error(peer, 'GAME_NOT_FOUND', 'No matching game.')
        if game.status != 'FINISHED':
            return self.error(peer, 'INVALID_MESSAGE', 'Current round has not finished.')
        # Either player may request another round. All clients receive the new state.
        game.round += 1
        game.board = [None] * 9
        game.turn = game.players[(game.round - 1) % 2].id
        game.status = 'ACTIVE'
        game.fsm = 'PLAYER_TURN'
        game.version += 1
        deliveries = []
        for i, p in enumerate(game.players):
            deliveries.append((p, packet('GAME_START', game.id,
                role='PLAYER_1' if i == 0 else 'PLAYER_2',
                symbol='X' if i == 0 else 'O',
                opponent_id=game.players[1-i].id,
                board=list(game.board), current_turn=game.turn,
                round=game.round, state_version=game.version)))
        deliveries.extend((p, game.score_packet()) for p in game.players)
        return deliveries

    def process(self, peer, msg):
        if not isinstance(msg, dict) or not all(k in msg for k in ('type','game_id','player_id','payload')) or not isinstance(msg['payload'], dict) or not isinstance(msg['game_id'], str):
            return self.error(peer, 'INVALID_MESSAGE', 'Expected type, game_id, player_id, and object payload.')
        kind = msg['type']
        if kind == 'CONNECT':
            if msg['game_id'] != 'pending':
                return self.error(peer, 'INVALID_MESSAGE', 'CONNECT game_id must be pending.')
            return self.connect(peer, msg)
        if peer.id is None:
            return self.error(peer, 'INVALID_MESSAGE', 'Send CONNECT first.')
        if msg['player_id'] != peer.id:
            return self.error(peer, 'NOT_PLAYER', 'Player ID does not match the connection.')
        if kind == 'MOVE':
            return self.move(peer, msg)
        if kind == 'NEW_ROUND':
            return self.new_round(peer, msg)
        if kind == 'DISCONNECT':
            return []
        return self.error(peer, 'INVALID_MESSAGE', 'Unknown message type.')

    def remove(self, peer):
        if not peer.connected:
            return
        peer.connected = False
        self.peers.discard(peer)
        try:
            self.waiting.remove(peer)
        except ValueError:
            pass
        game = peer.game
        if game and game.id in self.games:
            opponent = game.players[1] if peer is game.players[0] else game.players[0]
            if game.status == 'ACTIVE':
                game.status = 'FINISHED'
                game.fsm = 'GAME_OVER'
                game.scores[opponent.id] += 1
                game.version += 1
                self.dispatch([(opponent, packet('GAME_OVER', game.id, result='FORFEIT',
                    winner=opponent.id, reason='PLAYER_DISCONNECTED', board=list(game.board))),
                    (opponent, game.score_packet())])
            opponent.game = None
            if opponent.connected:
                self.waiting.append(opponent)
                self.dispatch([(opponent, packet('LOBBY_WAIT', 'pending', players_waiting=len(self.waiting)))])
            del self.games[game.id]
        peer.game = None
        try:
            peer.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        peer.sock.close()
        print(f'[LEFT] {peer.name or peer.address}', flush=True)

    def worker(self, peer):
        buffer = bytearray()
        try:
            while True:
                chunk = peer.sock.recv(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > MAX_LINE and b'\n' not in buffer:
                    with self.lock:
                        self.dispatch(self.error(peer, 'INVALID_MESSAGE', 'Message too large.'))
                    break
                while b'\n' in buffer:
                    raw, _, remainder = buffer.partition(b'\n')
                    buffer = bytearray(remainder)
                    if len(raw) > MAX_LINE:
                        with self.lock:
                            self.dispatch(self.error(peer, 'INVALID_MESSAGE', 'Message too large.'))
                        return
                    if not raw.strip():
                        continue
                    try:
                        msg = json.loads(raw.decode('utf-8'))
                    except (UnicodeError, json.JSONDecodeError):
                        with self.lock:
                            self.dispatch(self.error(peer, 'INVALID_JSON', 'Invalid JSON message.'))
                        continue
                    with self.lock:
                        self.dispatch(self.process(peer, msg))
                    if isinstance(msg, dict) and msg.get('type') == 'DISCONNECT' and peer.id and msg.get('player_id') == peer.id:
                        return
        except OSError:
            pass
        finally:
            with self.lock:
                self.remove(peer)

    def serve(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('0.0.0.0', port))
            listener.listen()
            print(f'[SERVER] Listening on 0.0.0.0:{port}', flush=True)
            try:
                while True:
                    sock, addr = listener.accept()
                    peer = Peer(sock, addr)
                    with self.lock:
                        self.peers.add(peer)
                    print(f'[JOIN] TCP connection from {addr}', flush=True)
                    threading.Thread(target=self.worker, args=(peer,), daemon=True).start()
            except KeyboardInterrupt:
                print('\n[SERVER] Shutting down.', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Threaded JSON/TCP Tic-Tac-Toe server')
    parser.add_argument('-p', '--port', type=int, required=True, help='Listening TCP port (1-65535)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    try:
        Server().serve(args.port)
    except OSError as exc:
        parser.exit(1, f'[ERROR] Unable to start server: {exc}\n')

if __name__ == '__main__':
    main()
