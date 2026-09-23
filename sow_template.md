# CS 457 Project Statement of Work (SOW) \& Protocol Specification Template

**Student Name:** Jesse Martin  
**Date:** 2026 - 09 - 22  
**Course:** CS 457 - Computer Networks  
**Target Server Domain:** `server.Martin.edu`

\---

## 1\. Game Selection \& Scope (Sprint 0)

> Planning is going to be an iterative process through the sprints so you don't have to have all the details now. Focus on big overview concepts. You will be updating the SOW as we plan.
> You have a lot of freedom to choose a game. There are a couple caveats.  

> - It must run in the console. The lab nodes won't be able to handle extensive graphics.
> - It has to be self-contained. You can use a internet-connector to download you code, but because the architecture must run 5 nodes you won't be able to run 
> - You are encouraged to use python, but I'm not going to make it a strict requirement. The instructor and TA's ability to help with C or Rust, etc will be diminished in other languages.

### 1.1 Game Overview

* **Chosen Game:** Tic-Tac-Toe
* **Player Capacity:** 2 Players (Simulated via 2 CML Client nodes)
* **Game Summary:** 1 player is x's and 1 is O's when ever either player gets a 3 in a row playing in alternating turns they win the game.

### 1.2 Core Game Rules \& Win/Draw Conditions

* **Turn Mechanics:** 1 play per player and then passed over the other until all 9 slots are filled or someone wins
* **Victory Condition:** A player must achieve 3 in a row to win
* **Draw/Tie Condition:** Draw/tie is called a cat when neither player can make a 3 in a row with all 9 slots filled.

\---
