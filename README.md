# Arena RPG — LAN Co-op

A pixel arena survival game for up to 4 players over LAN.  
**Python + Pygame → runs in the browser via pygbag.**

---

## How to run

```bash
pip install pygame pygbag
python src/main.py          # local desktop
pygbag src/main.py          # web build
```

---

## Project structure

```
arena-rpg-lan/
├── src/
│   ├── main.py        # Game loop & state manager     (M1)
│   ├── player.py      # Local player + RemotePlayer   (M2)
│   ├── enemy.py       # Enemy + EnemyManager          (M3)
│   ├── ui.py          # All UI screens & HUD          (M4)
│   ├── audio.py       # Sound manager                 (M5)
│   ├── network.py     # LAN server / client           (M6)
│   └── constants.py   # Shared constants
├── assets/
│   ├── sprites/       # Player_idle.png etc.
│   ├── sounds/        # bgm.ogg, shoot.ogg …
│   └── cursors/       # crosshair.png
└── locales/
    ├── en.json
    └── fr.json
```

---

## Sprite naming convention

| Slot | Suffix  | Example files                           |
|------|---------|-----------------------------------------|
| P1   | _(none)_ | `Player_idle.png`, `Player_w-1.png` … |
| P2   | `_2`    | `Player_idle_2.png`, `Player_w-1_2.png` … |
| P3   | `_3`    | `Player_idle_3.png`, `Player_w-1_3.png` … |
| P4   | `_4`    | `Player_idle_4.png`, `Player_w-1_4.png` … |

Each player needs: `Player_idle_N.png`, `Player_w-1_N.png`, `Player_w-2_N.png`, `Player_Dead_N.png`  
Drop them in `assets/sprites/` and they load automatically.

---

## Controls

| Action   | Keys                    |
|----------|-------------------------|
| Move     | WASD / ZQSD / Arrow keys |
| Shoot    | Left click              |
| Pause    | ESC                     |

---

## Pause menu (ESC)

- **Solo:** game freezes, music stops. Options: Resume, Restart, Language, Quit.  
- **LAN:** game continues for other players. Options same except **only the host** sees Restart.  
  When host restarts → 5-second countdown shown to all, then game resets for everyone.

---

## LAN setup

1. One player hosts: `LAN CO-OP → Host`. Share your IP shown on screen.  
2. Others join: `LAN CO-OP → Join`, enter host IP → Connect.  
3. Lobby shows each player's name as they connect.  
4. Host presses **START GAME** when ready.

---

## Enemy wave system

| Time elapsed | Max enemies on screen |
|---|---|
| 0 – 9 s  | 5 |
| 10 – 19 s | 6 |
| 20 – 29 s | 7 |
| … | … |

Enemies always spawn off-screen and walk toward the nearest player.  
A new enemy spawns immediately whenever one dies.

---

## Module ownership (5-person team)

| Module | File | Owner |
|--------|------|-------|
| M1 — Game loop | `main.py` | Member 1 |
| M2 — Player | `player.py` | Member 2 |
| M3 — Enemies | `enemy.py` | Member 3 |
| M4 — UI | `ui.py` | Member 4 |
| M5 — Audio | `audio.py` | Member 5 |
| M6 — Network | `network.py` | Shared |
| Assets | `assets/` | All |
