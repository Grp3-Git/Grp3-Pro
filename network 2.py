# network.py — LAN multiplayer networking layer
# HOST is authoritative for ALL game state (enemies, kills, elapsed time).
# Clients send: position snapshots + bullet data + hit events.
# Host sends:   full game state (enemies, all player positions, ALL bullets, kills).

import socket
import threading
import json
import time
from constants import LAN_PORT, LAN_MAX_PLAYERS, LAN_TIMEOUT


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _send(sock, data: dict):
    try:
        sock.sendall((json.dumps(data) + "\n").encode())
    except Exception:
        pass


def _recv_lines(sock, buf: list) -> list:
    messages = []
    try:
        sock.setblocking(False)
        chunk = sock.recv(65536)
        if chunk:
            buf.append(chunk.decode(errors="replace"))
    except BlockingIOError:
        pass
    except Exception:
        pass
    finally:
        sock.setblocking(True)

    raw = "".join(buf)
    lines = raw.split("\n")
    buf.clear()
    buf.append(lines[-1])
    for line in lines[:-1]:
        line = line.strip()
        if line:
            try:
                messages.append(json.loads(line))
            except Exception:
                pass
    return messages


# ─────────────────────────────────────────────────────────────
# LAN Server  (HOST)
# ─────────────────────────────────────────────────────────────

class LANServer:
    def __init__(self, host_username: str):
        self.host_username = host_username
        self._clients: dict = {}  # slot -> {sock, buf, username, kills, last_seen, pos, bullets}
        self._lock    = threading.Lock()
        self._events  = []
        self._running = True
        self._next_slot = 1

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("0.0.0.0", LAN_PORT))
        self._server_sock.listen(LAN_MAX_PLAYERS - 1)
        self._server_sock.settimeout(0.5)
        self.local_ip = get_local_ip()

        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._recv_loop,   daemon=True).start()

    # ── Public API ───────────────────────────────────────────

    def push_state(self, state: dict):
        """Broadcast full authoritative game state to all clients."""
        msg = {"type": "state", "data": state}
        with self._lock:
            dead = []
            for slot, cl in self._clients.items():
                try:
                    _send(cl["sock"], msg)
                except Exception:
                    dead.append(slot)
            for s in dead:
                self._disconnect(s)

    def get_events(self) -> list:
        with self._lock:
            ev = list(self._events)
            self._events.clear()
        return ev

    def get_play_again_clients(self) -> list:
        """Return list of {slot, username} for clients who pressed Play Again."""
        with self._lock:
            return [{"slot": s, "username": c["username"]}
                    for s, c in self._clients.items()
                    if c.get("play_again")]

    def clear_play_again_flags(self):
        """Reset all clients' play_again flags (called when countdown finishes)."""
        with self._lock:
            for c in self._clients.values():
                c["play_again"] = False

    def connected_players(self) -> list:
        with self._lock:
            return [{"slot": s, "username": c["username"], "kills": c["kills"]}
                    for s, c in self._clients.items()]

    def get_client_positions(self) -> dict:
        """Returns {slot: pos_dict} for all connected clients."""
        with self._lock:
            return {slot: cl["pos"] for slot, cl in self._clients.items()
                    if cl.get("pos")}

    def get_client_bullets(self) -> dict:
        """Returns {slot: [bullet_dict, ...]} for all connected clients."""
        with self._lock:
            return {slot: list(cl.get("bullets", []))
                    for slot, cl in self._clients.items()}

    def broadcast_restart_countdown(self, secs: int):
        msg = {"type": "state", "data": {"type": "restart_countdown", "secs": secs}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def broadcast_restart(self):
        msg = {"type": "state", "data": {"type": "restart"}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def broadcast_game_over(self):
        """Tell all clients to show the Game Over screen."""
        msg = {"type": "state", "data": {"type": "game_over"}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def broadcast_quit_to_menu(self):
        """Host is quitting — tell every client to return to main menu."""
        msg = {"type": "state", "data": {"type": "quit_to_menu"}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def broadcast_play_again_ready(self, ready_slots: list):
        """Push ready-table update to all clients.
        ready_slots: list of {slot, username} dicts."""
        msg = {"type": "state", "data": {"type": "play_again_ready",
                                          "ready": ready_slots}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def broadcast_play_again_countdown(self, secs: int):
        """Push the Play-Again countdown value to all clients."""
        msg = {"type": "state", "data": {"type": "play_again_countdown", "secs": secs}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def send_respawn(self, slot: int):
        """Tell all clients that the given slot should respawn now."""
        msg = {"type": "state", "data": {"type": "respawn", "slot": slot}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def stop(self):
        self._running = False
        try: self._server_sock.close()
        except Exception: pass

    # ── Internal ─────────────────────────────────────────────

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server_sock.accept()
                conn.settimeout(LAN_TIMEOUT)
                with self._lock:
                    if self._next_slot >= LAN_MAX_PLAYERS:
                        _send(conn, {"type": "reject", "reason": "full"})
                        conn.close()
                        continue
                    slot = self._next_slot
                    self._next_slot += 1
                    self._clients[slot] = {
                        "sock": conn, "buf": [], "username": f"Player{slot}",
                        "kills": 0, "last_seen": time.time(),
                        "pos": None, "bullets": [],
                    }
                _send(conn, {"type": "assign", "slot": slot})
                threading.Thread(target=self._client_handshake,
                                 args=(slot,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _client_handshake(self, slot):
        with self._lock:
            cl = self._clients.get(slot)
        if not cl: return
        buf = []
        try:
            cl["sock"].settimeout(10.0)
            while True:
                for m in _recv_lines(cl["sock"], buf):
                    if m.get("type") == "hello":
                        with self._lock:
                            if slot in self._clients:
                                self._clients[slot]["username"] = \
                                    m.get("username", f"Player{slot}")[:16]
                        self._broadcast_lobby_update()
                        return
        except Exception:
            pass

    def _broadcast_lobby_update(self):
        """Tell all connected clients who is currently in the lobby."""
        with self._lock:
            players_list = [{"slot": s, "username": c["username"]}
                            for s, c in self._clients.items()]
        msg = {"type": "state", "data": {"type": "lobby_update", "players": players_list}}
        with self._lock:
            for cl in self._clients.values():
                try: _send(cl["sock"], msg)
                except Exception: pass

    def _recv_loop(self):
        while self._running:
            time.sleep(1 / 60)
            with self._lock:
                slots = list(self._clients.keys())
            for slot in slots:
                with self._lock:
                    cl = self._clients.get(slot)
                if not cl: continue
                for m in _recv_lines(cl["sock"], cl["buf"]):
                    cl["last_seen"] = time.time()
                    mtype = m.get("type")
                    if mtype == "hit":
                        self._events.append({"type": "hit", "slot": slot,
                                             "eid": m.get("eid", -1)})
                    elif mtype == "pos":
                        with self._lock:
                            if slot in self._clients:
                                self._clients[slot]["pos"] = {
                                    "x":       m.get("x", 0),
                                    "y":       m.get("y", 0),
                                    "angle":   m.get("angle", 0),
                                    "moving":  m.get("moving", False),
                                    "is_dead": m.get("is_dead", False),
                                    "username": self._clients[slot]["username"],
                                }
                    elif mtype == "bullets":
                        # Client sends list of its active bullets each tick
                        with self._lock:
                            if slot in self._clients:
                                self._clients[slot]["bullets"] = m.get("list", [])
                    elif mtype == "play_again":
                        with self._lock:
                            if slot in self._clients:
                                self._clients[slot]["play_again"] = True
                        self._events.append({"type": "play_again", "slot": slot})
                    elif mtype == "ping":
                        _send(cl["sock"], {"type": "pong"})
                if time.time() - cl.get("last_seen", 0) > LAN_TIMEOUT:
                    with self._lock:
                        self._disconnect(slot)

    def _disconnect(self, slot):
        cl = self._clients.pop(slot, None)
        if cl:
            try: cl["sock"].close()
            except Exception: pass


# ─────────────────────────────────────────────────────────────
# LAN Client
# ─────────────────────────────────────────────────────────────

class LANClient:
    def __init__(self, host_ip: str, username: str):
        self.slot      = -1
        self.connected = False
        self.username  = username
        self._state    = None
        self._buf      = []
        self._lock     = threading.Lock()
        self._running  = True
        self.lobby_players = []

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(5.0)
        try:
            self._sock.connect((host_ip, LAN_PORT))
            self.connected = True
        except Exception as e:
            self.error = str(e)
            return

        self._handshake()
        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()

    # ── Public API ───────────────────────────────────────────

    def send_hit(self, eid: int):
        """Tell host that our bullet hit enemy with this eid."""
        _send(self._sock, {"type": "hit", "eid": eid})

    def send_pos(self, state: dict):
        _send(self._sock, {"type": "pos", **state})

    def send_bullets(self, bullet_list: list):
        """Send list of active bullet dicts {bid, x, y, vx, vy} to host."""
        _send(self._sock, {"type": "bullets", "list": bullet_list})

    def send_play_again(self):
        """Tell host this client wants to play again."""
        _send(self._sock, {"type": "play_again"})

    def get_state(self):
        with self._lock:
            return self._state

    def stop(self):
        self._running = False
        try: self._sock.close()
        except Exception: pass

    # ── Internal ─────────────────────────────────────────────

    def _handshake(self):
        buf = []
        self._sock.settimeout(10.0)
        while self.slot == -1:
            for m in _recv_lines(self._sock, buf):
                if m.get("type") == "assign":
                    self.slot = m["slot"]
                elif m.get("type") == "reject":
                    self.connected = False
                    return
        _send(self._sock, {"type": "hello", "username": self.username})
        self._sock.settimeout(None)

    def _recv_loop(self):
        while self._running and self.connected:
            time.sleep(1 / 60)
            for m in _recv_lines(self._sock, self._buf):
                if m.get("type") == "state":
                    data = m.get("data", {})
                    if data.get("type") == "lobby_update":
                        with self._lock:
                            self.lobby_players = data.get("players", [])
                    else:
                        with self._lock:
                            self._state = data

    def _ping_loop(self):
        while self._running and self.connected:
            time.sleep(2.0)
            try:
                _send(self._sock, {"type": "ping"})
            except Exception:
                self.connected = False
                break
