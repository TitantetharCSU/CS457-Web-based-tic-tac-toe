# Tic-Tac-Toe Server Concurrency Architecture

## 2.1 Server Concurrency Model Selection

**Selected architecture: Option A — Multi-Threading (`threading.Thread`).**

The Python TCP server accepts connections on a listening socket and starts one worker thread per connected client. Each worker blocks on socket reads independently, so one player's slow connection does not prevent the other player from sending moves. A shared `GameSession` stores the authoritative board, player assignments, active turn, round status, and cumulative scores. The server—not either client—validates moves and decides the next state.

### Shared server state

| Field | Type | Purpose |
| --- | --- | --- |
| `players` | `dict[player_id, socket]` | Maps assigned players to connected sockets. |
| `board` | `list[list[str]]` | 3×3 board; cells contain `"X"`, `"O"`, or `""`. |
| `active_turn` | `str` | Player ID permitted to move next. |
| `round_status` | `str` | `WAITING`, `ACTIVE`, or `FINISHED`. |
| `scores` | `dict[player_id, int]` | Number of rounds won by each player. |
| `draws` | `int` | Number of drawn rounds. |
| `round_number` | `int` | Current round identifier. |
| `state_version` | `int` | Monotonically increasing revision for ordered updates. |

The server creates a `threading.Lock` named `state_lock`. Every operation that reads and then changes game state—joining, validating a move, applying a move, checking for a win or draw, updating scores, starting another round, or processing a disconnect—runs inside `with state_lock:`. This prevents two client threads from accepting moves based on the same turn or overwriting a board cell.

### Lock acquisition and broadcast strategy

1. A worker receives one complete JSON message using newline-delimited framing (`\n`). A TCP read can contain part of a message or multiple messages, so each worker buffers bytes until a full line is available.
2. For `MOVE`, the worker acquires `state_lock`, verifies the player identity, `round_status`, current turn, coordinates, and empty cell, and either creates an `ERROR` response or updates the authoritative board.
3. On a valid nonterminal move, the worker switches `active_turn`, increments `state_version`, and constructs a `STATE_UPDATE` snapshot for **both** players.
4. On a winning or drawn move, the worker marks the round finished, updates the winner's score (or draw count) **exactly once**, increments `state_version`, and constructs `STATE_UPDATE`, `GAME_OVER`, and `SCORE_UPDATE` messages for both players. No further `MOVE` is accepted until a new round begins.
5. The lock is released before potentially slow socket writes. Outbound messages are placed into a **single ordered per-client send queue**, serviced by a dedicated sender loop or equivalent serialized send mechanism. Enqueue all recipients' messages while holding `state_lock` so later turns cannot overtake earlier updates; never hold `state_lock` during network I/O.
6. Each client processes updates in order, using `state_version` and `round_number` to detect stale or out-of-order state. A send failure is handled as a disconnect and processed through the same locked state transition.

**Lock ordering:** Only `state_lock` guards the shared game session; no nested game-state locks are used. Each client's outgoing queue is thread-safe. Do not acquire `state_lock` from within an outbound sender while holding any socket-specific lock. This minimizes deadlock risk.

**Why threading:** With two players, a thread per client is inexpensive and easy to reason about. Unlike a single `selectors` event loop, blocking receive operations are simple. The tradeoff is that shared mutable data requires explicit synchronization. The Python GIL is **not** a replacement for a lock around multi-step game operations.

## 2.2 Client State and Turn Synchronization

1. Client 1 and Client 2 send `CONNECT`. The server assigns `X` and `O`, sends `LOBBY_WAIT` to a player waiting alone, and sends `GAME_START` to both after the second player joins.
2. The server identifies the first active player (X). Clients display the server-provided board and turn; neither client locally decides whether a move is valid.
3. Player X sends `MOVE` with `row` and `col`. The server checks that the round is active, the sender is X, coordinates are integers between 0 and 2, and the target cell is empty.
4. If invalid, only the sender receives `ERROR`, and the board and active turn stay unchanged.
5. If valid, the server changes the board, checks for a terminal result, and broadcasts `STATE_UPDATE` to **both** clients. For an unfinished round, the active turn changes to O.
6. If the move ends the round, the server sends `GAME_OVER` and then `SCORE_UPDATE` to both clients, in the same logical update batch.
7. If a client sends `DISCONNECT` or the TCP connection closes, the server removes that client and informs the remaining player. The session must not continue accepting moves as if two players were connected.

**Broadcast semantics:** The server queues identical state snapshots for both clients as one logical operation. Network delivery cannot be literally simultaneous; the per-client queues ensure each client receives the same ordered authoritative state without one slow socket blocking the other.

### JSON message conventions

Each message is a JSON object followed by `\n`. The `type` field identifies the message. Server messages that represent a game state include `round_number` and `state_version`.

Example valid move:

```json
{"type":"MOVE","row":0,"col":2}
```

Example state broadcast:

```json
{"type":"STATE_UPDATE","board":[["X","","X"],["","O",""],["","",""]],"active_turn":"player2","round_number":1,"state_version":4,"round_status":"ACTIVE"}
```

Example score broadcast:

```json
{"type":"SCORE_UPDATE","scores":{"player1":1,"player2":0},"draws":0,"round_number":1,"state_version":8}
```

The player identity is determined from the authenticated/assigned connection, not from an untrusted `player_id` in a `MOVE` payload.

## 2.3 Score and Leaderboard Synchronization

The authoritative leaderboard is held in the server's in-memory `scores` dictionary, with a separate `draws` counter. Player IDs are mapped to the players assigned to the current session. Scores start at zero and persist across rounds **for the lifetime of the session**, but are lost if the server process restarts unless persistence is added.

At round completion, the same thread that applies the winning or final move checks the outcome under `state_lock`. It sets `round_status = "FINISHED"` before awarding a point, ensuring that later `MOVE` requests cannot score the same round again. A win increments the winner's score by one; a draw increments `draws`. The server constructs a single consistent score snapshot and enqueues `GAME_OVER` and `SCORE_UPDATE` to both players in order. Clients replace their local displayed leaderboard with the received score snapshot instead of incrementing scores locally. On a new round, the board resets but cumulative scores remain unchanged.

See [sequence_diagram.md](sequence_diagram.md) for the complete Mermaid message flow.
