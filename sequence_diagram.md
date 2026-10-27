# Tic-Tac-Toe State and Score Broadcast Sequence Diagram

The diagram includes the protocol's connection, lobby, start, move, validation error, state update, round completion, score update, and disconnect messages. It illustrates the **Player X move** path, including an invalid move and the possible terminal-round outcome.

```mermaid
sequenceDiagram
    autonumber
    actor C1 as Client 1 (Player X)
    participant S as TCP Game Server
    actor C2 as Client 2 (Player O)

    C1->>S: CONNECT
    S-->>C1: LOBBY_WAIT (waiting for opponent)
    C2->>S: CONNECT
    Note over S: Assign X and O; initialize board, turn, scores
    S-->>C1: GAME_START (board, turn X, scores)
    S-->>C2: GAME_START (board, turn X, scores)

    C1->>S: MOVE (row: 0, col: 2)
    Note over S: Acquire state_lock; validate sender, turn, bounds, empty cell
    alt Invalid or out-of-turn move
        S-->>C1: ERROR (reason)
        Note over S: Board and turn unchanged
    else Valid move
        Note over S: Apply X move; check win or draw; increment state_version
        alt Round continues
            Note over S: Switch active turn to Player O
            S-->>C1: STATE_UPDATE (board, turn O, version)
            S-->>C2: STATE_UPDATE (board, turn O, version)
        else X wins or board is drawn
            Note over S: Set round FINISHED; update scores once
            S-->>C1: STATE_UPDATE (final board, FINISHED)
            S-->>C2: STATE_UPDATE (final board, FINISHED)
            S-->>C1: GAME_OVER (winner or draw)
            S-->>C2: GAME_OVER (winner or draw)
            S-->>C1: SCORE_UPDATE (scores, draws)
            S-->>C2: SCORE_UPDATE (scores, draws)
        end
    end
    Note over S: Queue broadcasts in order; release lock before socket I/O

    opt A player leaves or loses connection
        C2->>S: DISCONNECT (or TCP connection closes)
        Note over S: Mark player disconnected under state_lock
        S-->>C1: DISCONNECT (opponent left)
    end
```

## Narrative

The server accepts both players independently, sends `LOBBY_WAIT` while a player is alone, and broadcasts `GAME_START` after the match is ready. Player X submits a `MOVE`; the server alone decides whether it is legal. Invalid moves produce an `ERROR` only to the sender and do not advance the turn. For a valid move, the server updates the board atomically under its shared lock and broadcasts the same `STATE_UPDATE` to both clients. When play continues, the update identifies Player O as the next active player.

If the move ends the round, the server first commits the final board and score under the lock, then queues `STATE_UPDATE`, `GAME_OVER`, and `SCORE_UPDATE` for each client in that order. The two clients receive the same authoritative result and leaderboard even though their network arrival times may differ. Each outgoing queue preserves ordering; `state_version` lets clients reject stale snapshots. On `DISCONNECT` or connection loss, the server marks the session unavailable and notifies the remaining player.
