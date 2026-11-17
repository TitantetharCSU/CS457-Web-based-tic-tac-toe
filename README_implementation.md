# Tic-Tac-Toe Python Implementation

These files implement the repository's newline-delimited JSON protocol with a threaded TCP server, server-side move validation, and a terminal client. Requires Python 3.9+; no external packages.

## Start the server

```bash
python3 server.py -p 8080
```

## Start two clients (in separate terminals)

```bash
python3 client.py -i 127.0.0.1 -p 8080
python3 client.py -i 127.0.0.1 -p 8080
```

Use the server's DNS name or reachable IPv4 address in place of `127.0.0.1` when connecting from different computers. The server listens on `0.0.0.0`.

Each client enters a name and then types board positions `0` through `8`. Player X goes first. After a completed round, type `r` to start another round; either player can do so. Type `q` to disconnect. Scores persist across rounds while both players remain connected, and reset when a new pair is matched.

## CLI help and DNS failure

```bash
python3 server.py -h
python3 client.py -h
python3 client.py -i invalid.invalid -p 8080
```

An unresolvable hostname prints a Cisco DNS configuration hint and exits with status `1`, without a traceback.

## Integration test and submission evidence

```bash
python3 test_gameplay.py
```

This starts a server in a background thread, opens two real TCP clients, plays five alternating moves, checks both clients receive identical boards and scores, then starts round two. It writes `gameplay_log.txt`, a reproducible console log suitable as an intermediate gameplay log. For a screenshot of the interactive CLI, run the server and two `client.py` terminals as above.

## Protocol notes

The core messages are `CONNECT`, `LOBBY_WAIT`, `GAME_START`, `MOVE`, `STATE_UPDATE`, `ERROR`, `GAME_OVER`, `DISCONNECT`. `SCORE_UPDATE` extends the original Sprint 1 blueprint to satisfy Sprint 2 score synchronization. `NEW_ROUND` is an additional client request for replay. All messages have `type`, `game_id`, `player_id`, and `payload` and are encoded as single-line JSON followed by `\n`.

The server assigns `X`/`O`, maintains an authoritative nine-cell board (empty is JSON `null`), and rejects invalid, occupied, and out-of-turn moves. Each accepted client has a dedicated worker thread. A shared `threading.Lock` protects matchmaking, board, turn, scores, and message ordering; a separate per-peer lock protects socket writes. All broadcasts are sent sequentially to both clients (not literally at the same instant).

## Add to GitHub

Copy `server.py`, `client.py`, `test_gameplay.py`, and `gameplay_log.txt` into the repository, then:

```bash
git add server.py client.py test_gameplay.py gameplay_log.txt
git commit -m "Implement threaded TCP Tic-Tac-Toe server and CLI client"
git push origin main
```
