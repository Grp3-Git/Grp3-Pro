# main.py — Game loop & state manager
# Run locally:  python src/main.py
# Web build:    pygbag src/main.py
#
# Changes in this version:
#   - map.png in assets/ used as ground texture (auto-scaled, fallback grid)
#   - LAN: client players see correct live kill scores from host broadcast
#   - LAN: Game Over screen only appears when ALL players are dead
#   - LAN: dead players enter spectator mode, watch the others
#   - LAN: 30-second respawn timer shown next to dead player name in HUD
#   - LAN: After 30s (if any player alive), dead player respawns at center with
#           RESPAWN_LIVES HP and RESPAWN_IFRAMES seconds of invulnerability
#   - Individual player scores always visible ingame + total in bold red

import asyncio
import pygame
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import *
from player    import Player, RemotePlayer, RemoteBullet
from enemy     import EnemyManager
from ui        import UI
from audio     import SoundManager
from network   import LANServer, LANClient, get_local_ip


# ── Background ─────────────────────────────────────────────────────────

def _make_arena_bg():
    """Load map.png from assets/ if it exists, else draw a procedural grid."""
    surf = pygame.Surface((SCREEN_W, SCREEN_H))

    if os.path.isfile(MAP_IMG_PATH):
        try:
            img = pygame.image.load(MAP_IMG_PATH).convert()
            img = pygame.transform.scale(img, (SCREEN_W, SCREEN_H))
            surf.blit(img, (0, 0))
            # Subtle dark border so the play-field edges are clear
            pygame.draw.rect(surf, (30, 30, 30), (0, 0, SCREEN_W, SCREEN_H), 4)
            return surf
        except Exception as e:
            print(f"[BG] Could not load map.png: {e}")

    # Fallback: dark grid
    surf.fill((18, 18, 18))
    grid = 64
    for x in range(0, SCREEN_W, grid):
        pygame.draw.line(surf, (28, 28, 28), (x, 0), (x, SCREEN_H))
    for y in range(0, SCREEN_H, grid):
        pygame.draw.line(surf, (28, 28, 28), (0, y), (SCREEN_W, y))
    pygame.draw.rect(surf, (50, 50, 50), (0, 0, SCREEN_W, SCREEN_H), 3)
    return surf


# ── Main ───────────────────────────────────────────────────────────────

async def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption(TITLE)
    clock  = pygame.time.Clock()

    all_sprites          = pygame.sprite.Group()
    bullet_group         = pygame.sprite.Group()
    remote_bullets_group = pygame.sprite.Group()
    player_group         = pygame.sprite.GroupSingle()
    remote_group         = pygame.sprite.Group()

    sound = SoundManager()
    ui    = UI(sound)
    bg    = _make_arena_bg()

    player = Player(SCREEN_W // 2, SCREEN_H // 2, (all_sprites, player_group), slot=0)
    em     = EnemyManager(all_sprites)

    remote_players: dict = {}     # slot -> RemotePlayer
    remote_blt_sprites: dict = {} # (slot, bid) -> RemoteBullet

    _next_bid = 0

    # ── State ──────────────────────────────────────────────────────────
    state   = STATE_MENU
    elapsed = 0.0

    username       = ""
    cursor_visible = True
    cursor_timer   = 0.0
    pending_action = None

    is_host      = False
    is_lan       = False
    lan_server   = None
    lan_client   = None
    local_slot   = 0
    players_info = []   # list of {slot, username, kills, dead, respawn_timer}
    lobby_mode   = None
    join_ip      = ""
    join_cursor_visible = True
    join_cursor_timer   = 0.0
    typing_join_ip = False
    net_tick_timer = 0.0

    paused_game_snap  = None
    restart_countdown = -1
    restart_cd_timer  = 0.0
    pending_restart   = False

    # Play-Again ready table (LAN Game Over screen)
    play_again_ready_players = []   # list of {slot, username} who pressed Play Again
    play_again_host_ready    = False  # has host themselves pressed Play Again
    play_again_countdown     = -1   # -1 = not counting, 0-5 = counting down
    play_again_cd_timer      = 0.0
    game_over_broadcast_sent = False  # host only: have we sent the game_over packet?

    # Spectator / respawn (LAN)
    # local player's respawn countdown (-1 = not dead in spectator mode)
    local_respawn_timer = -1.0
    # remote players' respawn timers: slot -> float seconds remaining
    remote_respawn_timers: dict = {}

    _click_held = False

    # ── Helpers ────────────────────────────────────────────────────────

    def _start_game():
        nonlocal state, elapsed, paused_game_snap, pending_restart
        nonlocal restart_countdown, restart_cd_timer, _next_bid
        nonlocal local_respawn_timer, remote_respawn_timers
        nonlocal play_again_ready_players, play_again_host_ready
        nonlocal play_again_countdown, play_again_cd_timer, game_over_broadcast_sent
        all_sprites.empty()
        bullet_group.empty()
        remote_bullets_group.empty()
        remote_group.empty()
        remote_players.clear()
        remote_blt_sprites.clear()
        _next_bid = 0
        local_respawn_timer = -1.0
        remote_respawn_timers = {}
        play_again_ready_players = []
        play_again_host_ready    = False
        play_again_countdown     = -1
        play_again_cd_timer      = 0.0
        game_over_broadcast_sent = False
        player.slot = local_slot
        player._load_sprites(local_slot)
        player.image = player.frames["idle"]
        player.mask  = pygame.mask.from_surface(player.image)
        player.add(all_sprites, player_group)
        player.reset()
        em.reset()
        elapsed = 0.0
        paused_game_snap  = None
        pending_restart   = False
        restart_countdown = -1
        restart_cd_timer  = 0.0
        state = STATE_PLAYING
        sound.stop_bgm()
        sound.stop_menu_bgm()
        sound.play_bgm()
        sound.set_crosshair()
        sound.set_paused_filter(False)

    def _ensure_remote(slot: int) -> RemotePlayer:
        if slot not in remote_players:
            rp = RemotePlayer(slot, (all_sprites, remote_group))
            remote_players[slot] = rp
        return remote_players[slot]

    def _all_player_positions():
        """(x,y) of all living players for enemy targeting."""
        positions = []
        if not player.is_dead:
            positions.append((player.fx, player.fy))
        for rp in remote_players.values():
            if not rp.is_dead:
                positions.append((rp.fx, rp.fy))
        return positions if positions else [(SCREEN_W // 2, SCREEN_H // 2)]

    def _all_players_list():
        result = [player]
        result.extend(remote_players.values())
        return result

    def _sync_remote_bullets(bullets_by_slot: dict):
        live_keys = set()
        for slot, blist in bullets_by_slot.items():
            slot = int(slot)
            if slot == local_slot:
                continue
            for bd in blist:
                key = (slot, bd["bid"])
                live_keys.add(key)
                if key not in remote_blt_sprites:
                    rb = RemoteBullet(bd["bid"], bd["x"], bd["y"],
                                      bd["vx"], bd["vy"], (remote_bullets_group,))
                    remote_blt_sprites[key] = rb
                else:
                    rb = remote_blt_sprites[key]
                    rb.fx = bd["x"]; rb.fy = bd["y"]
                    rb.rect.centerx = int(rb.fx)
                    rb.rect.centery = int(rb.fy)

        dead_keys = [k for k in remote_blt_sprites if k not in live_keys]
        for k in dead_keys:
            remote_blt_sprites[k].kill()
            del remote_blt_sprites[k]

    def _local_bullets_snapshot():
        return [{"bid": getattr(s, "bid", 0),
                 "x": s.fx, "y": s.fy, "vx": s.vx, "vy": s.vy}
                for s in bullet_group.sprites()]

    def _get_player_info(slot):
        return next((p for p in players_info if p["slot"] == slot), None)

    def _upsert_player_info(slot, **kwargs):
        p = _get_player_info(slot)
        if p is None:
            p = {"slot": slot, "username": f"P{slot+1}", "kills": 0,
                 "dead": False, "respawn_timer": -1.0}
            players_info.append(p)
        p.update(kwargs)

    def _all_lan_players_dead():
        """True only when every player in the session is dead (game over)."""
        if not player.is_dead:
            return False
        for rp in remote_players.values():
            if not rp.is_dead:
                return False
        return True

    def _any_other_player_alive():
        """True if at least one other (remote) player is still alive."""
        for rp in remote_players.values():
            if not rp.is_dead:
                return True
        return False

    def _draw_scene():
        screen.blit(bg, (0, 0))
        all_sprites.draw(screen)
        bullet_group.draw(screen)
        remote_bullets_group.draw(screen)
        for slot, rp in remote_players.items():
            p_info = _get_player_info(slot)
            name   = p_info["username"] if p_info else rp.username
            color  = PLAYER_COLORS[slot % len(PLAYER_COLORS)]
            _draw_name_tag(screen, name, rp.rect.centerx, rp.rect.top - 4, color)
        rtimers = dict(remote_respawn_timers)
        if local_respawn_timer >= 0:
            rtimers[local_slot] = local_respawn_timer
        ui.draw_hud(screen, elapsed, em.kill_counts, player.lives,
                    players_info, respawn_timers=rtimers)
        sound.draw_crosshair(screen)

        # Restart countdown overlay (host-triggered, visible in PLAYING state)
        if pending_restart and restart_countdown >= 0:
            cd_bg = pygame.Surface((SCREEN_W, 70), pygame.SRCALPHA)
            cd_bg.fill((0, 0, 0, 160))
            screen.blit(cd_bg, (0, SCREEN_H // 2 - 35))
            font_l = pygame.font.SysFont("monospace", 52, bold=True)
            cd_surf = font_l.render(f"Beginning in {restart_countdown}…", True, (255, 210, 50))
            screen.blit(cd_surf, cd_surf.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2)))

    # ── Network helpers ────────────────────────────────────────────────

    def _net_tick_host():
        for ev in lan_server.get_events():
            if ev["type"] == "hit":
                em.apply_hit_from_client(ev["eid"], ev["slot"], sound)

        client_positions = lan_server.get_client_positions()
        client_bullets   = lan_server.get_client_bullets()

        for slot_int, pos_data in client_positions.items():
            slot = int(slot_int)
            rp = _ensure_remote(slot)
            rp.username = pos_data.get("username", rp.username)
            rp.apply_state(pos_data, dt)

        host_bullets = _local_bullets_snapshot()
        all_bullets  = {str(local_slot): host_bullets}
        for slot_int, blist in client_bullets.items():
            all_bullets[str(slot_int)] = blist

        # Sync kill counts into players_info for all players
        for p in players_info:
            s = p["slot"]
            p["kills"] = em.kill_counts[s] if s < len(em.kill_counts) else 0
            p["dead"]  = (s == local_slot and player.is_dead) or \
                         (s != local_slot and remote_players.get(s, None) is not None
                          and remote_players[s].is_dead)

        # Broadcast respawn timers for all clients
        rt_export = {}
        if local_respawn_timer >= 0:
            rt_export[str(local_slot)] = local_respawn_timer
        for s, t in remote_respawn_timers.items():
            rt_export[str(s)] = t

        state_snapshot = {
            "type":            "game",
            "kill_counts":     em.kill_counts,
            "elapsed":         elapsed,
            "enemies":         em.serialise_enemies(),
            "host_pos":        player.get_net_state(),
            "remote_players":  client_positions,
            "bullets":         all_bullets,
            "respawn_timers":  rt_export,
        }
        lan_server.push_state(state_snapshot)

    def _net_tick_client():
        lan_client.send_pos(player.get_net_state())
        lan_client.send_bullets(_local_bullets_snapshot())

        sv = lan_client.get_state()
        if not sv:
            return sv

        if sv.get("type") == "game":
            em.apply_remote_enemies(sv.get("enemies", []), dt)

            # Sync kill counts from host — this fixes clients not seeing others' scores
            kc = sv.get("kill_counts", [])
            em.apply_remote_kill_counts(kc)

            # Update players_info kills from authoritative host kill_counts
            for p in players_info:
                s = p["slot"]
                if s < len(kc):
                    p["kills"] = kc[s]

            host_pos = sv.get("host_pos")
            if host_pos:
                hp = _ensure_remote(0)
                hp.apply_state(host_pos, dt)

            for slot_str, pos_data in sv.get("remote_players", {}).items():
                slot = int(slot_str)
                if slot != local_slot:
                    rp = _ensure_remote(slot)
                    rp.apply_state(pos_data, dt)

            _sync_remote_bullets(sv.get("bullets", {}))

            # Sync respawn timers from host
            rt = sv.get("respawn_timers", {})
            nonlocal local_respawn_timer
            for slot_str, t in rt.items():
                slot = int(slot_str)
                if slot == local_slot:
                    local_respawn_timer = float(t)
                else:
                    remote_respawn_timers[slot] = float(t)
            # Clear timers for slots not in host broadcast
            for slot in list(remote_respawn_timers.keys()):
                if str(slot) not in rt and slot != local_slot:
                    del remote_respawn_timers[slot]

        return sv

    # ── Main loop ──────────────────────────────────────────────────────
    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        nonlocal_next_bid = [_next_bid]

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if lan_server: lan_server.stop()
                if lan_client: lan_client.stop()
                pygame.quit(); sys.exit()

            if event.type == pygame.MOUSEBUTTONUP:
                _click_held = False

            if event.type == pygame.MOUSEBUTTONDOWN:
                # Allow shooting even in spectator (so respawning player is ready)
                if state == STATE_PLAYING and event.button == 1:
                    if not player.is_dead:
                        bid = nonlocal_next_bid[0]
                        nonlocal_next_bid[0] += 1
                        if player.try_shoot(pygame.mouse.get_pos(), bullet_group,
                                            all_sprites, bid=bid):
                            sound.play("shoot")

            if event.type == pygame.KEYDOWN:
                if state == STATE_USERNAME:
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if username.strip():
                            if pending_action == "solo":
                                local_slot   = 0
                                players_info = [{"slot": 0, "username": username,
                                                 "kills": 0, "dead": False,
                                                 "respawn_timer": -1.0}]
                                _start_game()
                            elif pending_action == "lan":
                                state = STATE_LOBBY
                    elif event.key == pygame.K_BACKSPACE:
                        username = username[:-1]
                    elif len(username) < 16 and event.unicode.isprintable():
                        username += event.unicode

                elif state == STATE_LOBBY and typing_join_ip:
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        typing_join_ip = False
                    elif event.key == pygame.K_BACKSPACE:
                        join_ip = join_ip[:-1]
                    elif len(join_ip) < 21 and (event.unicode.isdigit() or event.unicode == "."):
                        join_ip += event.unicode

                elif event.key == pygame.K_ESCAPE:
                    if state == STATE_PLAYING:
                        paused_game_snap = None
                        state = STATE_PAUSED
                        sound.set_paused_filter(True)
                        sound.restore_cursor()        # FIX 4: show cursor in pause
                        if not is_lan:
                            sound.stop_steps()
                    elif state == STATE_PAUSED:
                        state = STATE_PLAYING
                        sound.set_paused_filter(False)
                        sound.set_crosshair()         # FIX 4: hide cursor on resume
                        paused_game_snap = None

        _next_bid = nonlocal_next_bid[0]

        keys      = pygame.key.get_pressed()
        mouse_pos = pygame.mouse.get_pos()
        clicked   = pygame.mouse.get_pressed()[0] and not _click_held

        # ── MENU ───────────────────────────────────────────────────────
        if state == STATE_MENU:
            sound.restore_cursor()
            sound.play_menu_bgm()
            screen.blit(bg, (0, 0))
            action = ui.draw_menu(screen)
            if clicked:
                _click_held = True
                if action == "play_solo":
                    sound.play_btn()
                    pending_action = "solo"; state = STATE_USERNAME
                elif action == "play_lan":
                    sound.play_btn()
                    pending_action = "lan";  state = STATE_USERNAME
                elif action == "quit":
                    sound.play_btn()
                    pygame.quit(); sys.exit()
                elif action == "lang":
                    sound.play_btn()
                    ui.toggle_lang()

        # ── USERNAME ───────────────────────────────────────────────────
        elif state == STATE_USERNAME:
            sound.restore_cursor()
            sound.play_menu_bgm()
            cursor_timer += dt
            if cursor_timer >= 0.5:
                cursor_timer = 0.0; cursor_visible = not cursor_visible
            screen.blit(bg, (0, 0))
            action = ui.draw_username(screen, username, cursor_visible)
            if clicked:
                _click_held = True
                if action == "confirm" and username.strip():
                    sound.play_btn()
                    if pending_action == "solo":
                        local_slot   = 0
                        players_info = [{"slot": 0, "username": username,
                                         "kills": 0, "dead": False, "respawn_timer": -1.0}]
                        _start_game()
                    elif pending_action == "lan":
                        state = STATE_LOBBY
                elif action == "lang":
                    sound.play_btn()
                    ui.toggle_lang()

        # ── LOBBY ──────────────────────────────────────────────────────
        elif state == STATE_LOBBY:
            sound.restore_cursor()
            sound.play_menu_bgm()
            join_cursor_timer += dt
            if join_cursor_timer >= 0.5:
                join_cursor_timer = 0.0; join_cursor_visible = not join_cursor_visible

            if lobby_mode is None:
                screen.blit(bg, (0, 0))
                action = _host_join_action(screen, ui, clicked)
                _draw_host_join_choice(screen, ui, clicked)
                if action == "host":
                    sound.play_btn()
                    lobby_mode = "host"; is_host = True; is_lan = True; local_slot = 0
                    lan_server = LANServer(host_username=username)
                    players_info = [{"slot": 0, "username": username, "kills": 0,
                                     "dead": False, "respawn_timer": -1.0}]
                elif action == "join":
                    sound.play_btn()
                    lobby_mode = "join"; is_host = False; is_lan = True
                elif action == "back":
                    sound.play_btn()
                    state = STATE_MENU; lobby_mode = None
                elif action == "lang":
                    sound.play_btn()
                    ui.toggle_lang()
            else:
                if is_host and lan_server:
                    remote = lan_server.connected_players()
                    host_entry = _get_player_info(0)
                    players_info = ([host_entry] if host_entry else []) + [
                        {"slot": r["slot"], "username": r["username"],
                         "kills": 0, "dead": False, "respawn_timer": -1.0}
                        for r in remote
                    ]

                if lan_client and lan_client.connected:
                    lp = lan_client.lobby_players
                    if lp:
                        mine = _get_player_info(local_slot)
                        merged = [mine] if mine else []
                        for rp in lp:
                            if rp["slot"] != local_slot:
                                ex = next((p for p in merged
                                           if p["slot"] == rp["slot"]), None)
                                if ex:
                                    ex["username"] = rp["username"]
                                else:
                                    merged.append({"slot": rp["slot"],
                                                   "username": rp["username"],
                                                   "kills": 0, "dead": False,
                                                   "respawn_timer": -1.0})
                        players_info = sorted(merged, key=lambda p: p["slot"])

                screen.blit(bg, (0, 0))
                action = ui.draw_lobby(screen, get_local_ip(), players_info,
                                       is_host, join_ip, join_cursor_visible)
                if clicked:
                    _click_held = True
                    if action == "start" and is_host:
                        sound.play_btn()
                        if lan_server: lan_server.push_state({"type": "start"})
                        local_slot = 0; _start_game()
                    elif action == "join":
                        sound.play_btn()
                        host_ip    = join_ip.strip() or "127.0.0.1"
                        lan_client = LANClient(host_ip, username)
                        if lan_client.connected:
                            local_slot   = lan_client.slot
                            players_info = [{"slot": local_slot, "username": username,
                                             "kills": 0, "dead": False,
                                             "respawn_timer": -1.0}]
                        else:
                            lan_client = None
                    elif action == "typing":
                        typing_join_ip = True
                    elif action == "back":
                        sound.play_btn()
                        if lan_server: lan_server.stop(); lan_server = None
                        if lan_client: lan_client.stop(); lan_client = None
                        is_lan = False; lobby_mode = None; state = STATE_MENU
                    elif action == "lang":
                        sound.play_btn()
                        ui.toggle_lang()

                if lan_client and lan_client.connected:
                    sv = lan_client.get_state()
                    if sv and sv.get("type") == "start":
                        _start_game()

        # ── PLAYING ────────────────────────────────────────────────────
        elif state == STATE_PLAYING:
            elapsed += dt

            # Only update local player if they're alive (or still in dying anim)
            if not player.is_dead:
                player.update(dt, keys, mouse_pos)
                moving = any([keys[pygame.K_LEFT], keys[pygame.K_a], keys[pygame.K_q],
                              keys[pygame.K_RIGHT], keys[pygame.K_d],
                              keys[pygame.K_UP], keys[pygame.K_w], keys[pygame.K_z],
                              keys[pygame.K_DOWN], keys[pygame.K_s]])
                if moving: sound.play("player_steps")
                else:      sound.stop_steps()
            else:
                sound.stop_steps()

            bullet_group.update(dt)
            remote_bullets_group.update(dt)

            all_pos = _all_player_positions()
            all_pls = _all_players_list()

            if lan_server:
                em.update(dt, all_pos, bullet_group, all_pls, sound, local_slot)
            elif lan_client and lan_client.connected:
                for enemy in list(em.enemies):
                    hits = pygame.sprite.spritecollide(
                        enemy, bullet_group, True, pygame.sprite.collide_mask)
                    if hits:
                        lan_client.send_hit(enemy.eid)
                        sound.play("monster_hurt")
                if not player.is_dead:
                    for enemy in list(em.enemies):
                        if not enemy._dying and enemy.can_damage_player():
                            if (enemy.rect.colliderect(player.rect) and
                                    _mask_overlap(enemy, player)):
                                enemy.mark_contact()
                                player.take_damage()
                                sound.play("player_hurt")
            else:
                em.update(dt, all_pos, bullet_group, all_pls, sound, local_slot)

            # ── Respawn / spectator logic (LAN only) ───────────────────
            if is_lan:
                # Tick local respawn timer
                if player.is_dead:
                    if local_respawn_timer < 0:
                        # FIX 1: check if ALL players are already dead before
                        # starting a respawn countdown — if so, go straight to game over
                        if not _any_other_player_alive():
                            state = STATE_DEAD
                            sound.stop_bgm(); sound.restore_cursor(); sound.stop_steps()
                        else:
                            # Start respawn countdown
                            local_respawn_timer = RESPAWN_DELAY
                            sound.stop_bgm()
                            sound.restore_cursor()
                            sound.stop_steps()
                            sound.play("player_death")
                    else:
                        local_respawn_timer = max(0.0, local_respawn_timer - dt)
                        if local_respawn_timer <= 0 and _any_other_player_alive():
                            # RESPAWN
                            player.respawn(SCREEN_W // 2, SCREEN_H // 2,
                                           RESPAWN_LIVES, RESPAWN_IFRAMES)
                            local_respawn_timer = -1.0
                            sound.play_bgm()
                            sound.set_crosshair()
                        elif local_respawn_timer <= 0 and not _any_other_player_alive():
                            # Everyone dead — real game over
                            local_respawn_timer = -1.0
                            state = STATE_DEAD

                # Tick remote respawn timers (host only — authoritative)
                if is_host:
                    for slot, rp in list(remote_players.items()):
                        if rp.is_dead:
                            if slot not in remote_respawn_timers:
                                remote_respawn_timers[slot] = RESPAWN_DELAY
                            else:
                                remote_respawn_timers[slot] = max(
                                    0.0, remote_respawn_timers[slot] - dt)
                        else:
                            remote_respawn_timers.pop(slot, None)

                    # Send respawn command to clients whose timer hit 0
                    for slot in list(remote_respawn_timers.keys()):
                        if remote_respawn_timers[slot] <= 0:
                            # Host will send a state packet with respawn_slot
                            lan_server.send_respawn(slot)
                            del remote_respawn_timers[slot]

                # Check all-dead (LAN game over)
                if _all_lan_players_dead() and local_respawn_timer < 0:
                    if is_host and not game_over_broadcast_sent:
                        game_over_broadcast_sent = True
                        lan_server.broadcast_game_over()
                    state = STATE_DEAD
                    sound.stop_bgm(); sound.restore_cursor(); sound.stop_steps()

            else:
                # Solo: standard death
                if player.is_dead:
                    state = STATE_DEAD
                    sound.stop_bgm(); sound.restore_cursor(); sound.stop_steps()
                    sound.play("player_death")

            # Countdown for host-triggered restart
            if pending_restart:
                restart_cd_timer -= dt
                remaining = max(0, int(restart_cd_timer))
                if restart_countdown != remaining:
                    restart_countdown = remaining
                    if lan_server:
                        lan_server.broadcast_restart_countdown(remaining)
                if restart_cd_timer <= 0:
                    if lan_server:
                        lan_server.broadcast_restart()
                    _start_game()
                    continue

            # Network tick
            net_tick_timer += dt
            if net_tick_timer >= 1.0 / LAN_TICK_RATE:
                net_tick_timer = 0.0
                if lan_server:
                    _net_tick_host()
                elif lan_client and lan_client.connected:
                    sv = _net_tick_client()
                    if sv:
                        t = sv.get("type")
                        if t == "restart_countdown":
                            restart_countdown = sv.get("secs", 5)
                        elif t == "restart":
                            _start_game()
                        elif t == "respawn":
                            if sv.get("slot") == local_slot:
                                player.respawn(SCREEN_W // 2, SCREEN_H // 2,
                                               RESPAWN_LIVES, RESPAWN_IFRAMES)
                                local_respawn_timer = -1.0
                                sound.play_bgm()
                                sound.set_crosshair()
                        elif t == "game_over":
                            state = STATE_DEAD
                            sound.stop_bgm(); sound.restore_cursor(); sound.stop_steps()
                        elif t == "quit_to_menu":
                            if lan_client: lan_client.stop(); lan_client = None
                            is_lan = False; lobby_mode = None
                            state = STATE_MENU
                            sound.stop_bgm(); sound.restore_cursor()
                            sound.play_menu_bgm()
                        elif t == "play_again_ready":
                            play_again_ready_players = sv.get("ready", [])
                        elif t == "play_again_countdown":
                            play_again_countdown = sv.get("secs", 5)
                        elif t == "play_again_start":
                            _start_game()

            # Sync players_info kills for local slot
            p_local = _get_player_info(local_slot)
            if p_local:
                p_local["kills"] = em.kill_counts[local_slot]
                p_local["dead"]  = player.is_dead
                p_local["respawn_timer"] = local_respawn_timer

            _draw_scene()

        # ── PAUSED ─────────────────────────────────────────────────────
        elif state == STATE_PAUSED:
            if is_lan:
                elapsed += dt
                if not player.is_dead:
                    player.update(dt, keys, mouse_pos)
                    moving = any([keys[pygame.K_LEFT], keys[pygame.K_a], keys[pygame.K_q],
                                  keys[pygame.K_RIGHT], keys[pygame.K_d],
                                  keys[pygame.K_UP], keys[pygame.K_w], keys[pygame.K_z],
                                  keys[pygame.K_DOWN], keys[pygame.K_s]])
                    if moving: sound.play("player_steps")
                    else:      sound.stop_steps()

                bullet_group.update(dt)
                remote_bullets_group.update(dt)

                all_pos = _all_player_positions()
                all_pls = _all_players_list()

                if lan_server:
                    em.update(dt, all_pos, bullet_group, all_pls, sound, local_slot)
                elif lan_client and lan_client.connected:
                    for enemy in list(em.enemies):
                        hits = pygame.sprite.spritecollide(
                            enemy, bullet_group, True, pygame.sprite.collide_mask)
                        if hits:
                            lan_client.send_hit(enemy.eid)
                    if not player.is_dead:
                        for enemy in list(em.enemies):
                            if not enemy._dying and enemy.can_damage_player():
                                if (enemy.rect.colliderect(player.rect) and
                                        _mask_overlap(enemy, player)):
                                    enemy.mark_contact()
                                    player.take_damage()

                net_tick_timer += dt
                if net_tick_timer >= 1.0 / LAN_TICK_RATE:
                    net_tick_timer = 0.0
                    if lan_server:
                        _net_tick_host()
                    elif lan_client and lan_client.connected:
                        sv = _net_tick_client()
                        if sv:
                            t = sv.get("type")
                            if t == "restart_countdown":
                                restart_countdown = sv.get("secs", 5)
                            elif t == "restart":
                                _start_game()
                            elif t == "respawn" and sv.get("slot") == local_slot:
                                player.respawn(SCREEN_W // 2, SCREEN_H // 2,
                                               RESPAWN_LIVES, RESPAWN_IFRAMES)
                                local_respawn_timer = -1.0
                                sound.play_bgm()
                                sound.set_crosshair()
                            elif t == "game_over":
                                state = STATE_DEAD
                                sound.stop_bgm(); sound.restore_cursor()
                                paused_game_snap = None
                            elif t == "quit_to_menu":
                                if lan_client: lan_client.stop(); lan_client = None
                                is_lan = False; lobby_mode = None
                                state = STATE_MENU; paused_game_snap = None
                                sound.set_paused_filter(False)
                                sound.stop_bgm(); sound.restore_cursor()
                                sound.play_menu_bgm()
                            elif t == "play_again_ready":
                                play_again_ready_players = sv.get("ready", [])
                            elif t == "play_again_countdown":
                                play_again_countdown = sv.get("secs", 5)
                            elif t == "play_again_start":
                                _start_game()

                if is_lan and _all_lan_players_dead() and local_respawn_timer < 0:
                    if is_host and not game_over_broadcast_sent:
                        game_over_broadcast_sent = True
                        lan_server.broadcast_game_over()
                    state = STATE_DEAD
                    sound.stop_bgm(); sound.restore_cursor()
                    paused_game_snap = None

            if pending_restart:
                restart_cd_timer -= dt
                remaining = max(0, int(restart_cd_timer))
                if restart_countdown != remaining:
                    restart_countdown = remaining
                    if lan_server:
                        lan_server.broadcast_restart_countdown(remaining)
                if restart_cd_timer <= 0:
                    if lan_server:
                        lan_server.broadcast_restart()
                    _start_game()
                    continue

            _draw_scene()

            if paused_game_snap is None:
                paused_game_snap = screen.copy()

            # Only show the pause sidebar when NOT counting down (restart countdown
            # is displayed as a full-screen overlay directly in draw_pause).
            action = ui.draw_pause(screen, paused_game_snap,
                                   is_host=is_host, is_lan=is_lan,
                                   restart_countdown=restart_countdown)

            if clicked:
                _click_held = True
                if action == "resume":
                    sound.play_btn()
                    state = STATE_PLAYING
                    sound.set_paused_filter(False)
                    sound.set_crosshair()
                    paused_game_snap = None
                elif action == "restart":
                    sound.play_btn()
                    if is_lan and is_host:
                        # Close pause immediately, go to PLAYING, countdown shown there
                        pending_restart   = True
                        restart_cd_timer  = 5.0
                        restart_countdown = 5
                        state = STATE_PLAYING       # ← leave pause right away
                        sound.set_paused_filter(False)
                        sound.set_crosshair()
                        paused_game_snap = None
                        if lan_server:
                            lan_server.broadcast_restart_countdown(5)
                    else:
                        sound.set_paused_filter(False)
                        sound.set_crosshair()
                        _start_game()
                elif action == "lang":
                    sound.play_btn()
                    ui.toggle_lang()
                elif action == "quit":
                    sound.play_btn()
                    if is_host and lan_server:
                        lan_server.broadcast_quit_to_menu()
                        lan_server.stop(); lan_server = None
                    if lan_client: lan_client.stop(); lan_client = None
                    is_lan = False
                    sound.set_paused_filter(False)
                    sound.stop_bgm(); sound.restore_cursor()
                    state = STATE_MENU; lobby_mode = None
                    paused_game_snap = None

        # ── DEAD ───────────────────────────────────────────────────────
        elif state == STATE_DEAD:
            screen.blit(bg, (0, 0))
            all_sprites.draw(screen)

            # ── Host: tick Play-Again countdown ────────────────────────
            if is_lan and is_host and play_again_countdown >= 0:
                play_again_cd_timer -= dt
                remaining = max(0, int(play_again_cd_timer))
                if play_again_countdown != remaining:
                    play_again_countdown = remaining
                    lan_server.broadcast_play_again_countdown(remaining)
                if play_again_cd_timer <= 0:
                    # Broadcast the restart then start locally
                    lan_server.broadcast_restart()
                    lan_server.clear_play_again_flags()
                    _start_game()
                    continue

            # ── Host: collect incoming play_again events ───────────────
            if is_lan and is_host and lan_server:
                for ev in lan_server.get_events():
                    if ev["type"] == "play_again":
                        # Rebuild ready list from server
                        play_again_ready_players = lan_server.get_play_again_clients()
                        # Add host too if already ready
                        if play_again_host_ready:
                            host_entry = {"slot": 0, "username": players_info[0]["username"]
                                          if players_info else "Host"}
                            if not any(r["slot"] == 0 for r in play_again_ready_players):
                                play_again_ready_players = [host_entry] + play_again_ready_players
                        lan_server.broadcast_play_again_ready(play_again_ready_players)

            # ── Client: poll for play_again_ready / countdown / restart ─
            if is_lan and lan_client and lan_client.connected:
                sv = lan_client.get_state()
                if sv:
                    t = sv.get("type")
                    if t == "play_again_ready":
                        play_again_ready_players = sv.get("ready", [])
                    elif t == "play_again_countdown":
                        play_again_countdown = sv.get("secs", 5)
                    elif t == "restart":
                        _start_game()
                        continue
                    elif t == "quit_to_menu":
                        if lan_client: lan_client.stop(); lan_client = None
                        is_lan = False; lobby_mode = None
                        state = STATE_MENU
                        sound.stop_bgm(); sound.restore_cursor()
                        sound.play_menu_bgm()
                        continue

            action = ui.draw_death(
                screen, elapsed, em.kill_counts, players_info,
                is_lan=is_lan, is_host=is_host,
                ready_players=play_again_ready_players if is_lan else None,
                play_again_countdown=play_again_countdown,
            )

            if clicked:
                _click_held = True
                if action == "retry":
                    sound.play_btn()
                    if not is_lan:
                        # Solo: just restart
                        _start_game()
                    elif is_host:
                        # Host pressed Play Again: mark host as ready, start countdown
                        play_again_host_ready = True
                        host_name = players_info[0]["username"] if players_info else "Host"
                        host_entry = {"slot": 0, "username": host_name}
                        if not any(r["slot"] == 0 for r in play_again_ready_players):
                            play_again_ready_players = [host_entry] + play_again_ready_players
                        # Also include any clients already ready
                        play_again_ready_players = [host_entry] + \
                            lan_server.get_play_again_clients()
                        lan_server.broadcast_play_again_ready(play_again_ready_players)
                        # Start 5-second countdown
                        play_again_countdown = 5
                        play_again_cd_timer  = 5.0
                        lan_server.broadcast_play_again_countdown(5)
                    else:
                        # Client pressed Play Again: tell host
                        if lan_client: lan_client.send_play_again()

                elif action == "quit":
                    sound.play_btn()
                    if is_host and lan_server:
                        # Host quits → everyone goes to menu
                        lan_server.broadcast_quit_to_menu()
                        lan_server.stop(); lan_server = None
                    elif lan_client:
                        # Client quits → only this client leaves
                        lan_client.stop(); lan_client = None
                    is_lan = False
                    state = STATE_MENU; lobby_mode = None
                    sound.play_menu_bgm()

                elif action == "lang":
                    sound.play_btn()
                    ui.toggle_lang()

        pygame.display.flip()
        await asyncio.sleep(0)


# ── Helpers ────────────────────────────────────────────────────────────

def _mask_overlap(sprite_a, sprite_b) -> bool:
    mask_a = getattr(sprite_a, 'mask', None) or pygame.mask.from_surface(sprite_a.image)
    mask_b = getattr(sprite_b, 'mask', None) or pygame.mask.from_surface(sprite_b.image)
    offset = (sprite_a.rect.x - sprite_b.rect.x, sprite_a.rect.y - sprite_b.rect.y)
    return bool(mask_b.overlap(mask_a, offset))


def _draw_name_tag(surface, name, cx, top_y, color):
    font = pygame.font.SysFont("monospace", 14, bold=True)
    surf = font.render(name, True, color)
    x = cx - surf.get_width() // 2
    y = top_y - surf.get_height() - 2
    bg_s = pygame.Surface((surf.get_width() + 6, surf.get_height() + 2), pygame.SRCALPHA)
    bg_s.fill((0, 0, 0, 120))
    surface.blit(bg_s, (x - 3, y - 1))
    surface.blit(surf, (x, y))


_hj_host_rect = None
_hj_join_rect = None
_hj_back_rect = None


def _draw_host_join_choice(surface, ui, clicked):
    global _hj_host_rect, _hj_join_rect, _hj_back_rect
    overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 220))
    surface.blit(overlay, (0, 0))

    font_l = pygame.font.SysFont("monospace", 52, bold=True)
    font_m = pygame.font.SysFont("monospace", 32, bold=True)

    title = font_l.render(ui.t("lobby_title"), True, YELLOW)
    surface.blit(title, title.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 120)))

    cx = SCREEN_W // 2
    bw, bh = 220, 56
    _hj_host_rect = pygame.Rect(cx - bw // 2, SCREEN_H // 2 - 20, bw, bh)
    _hj_join_rect = pygame.Rect(cx - bw // 2, SCREEN_H // 2 + 56, bw, bh)
    _hj_back_rect = pygame.Rect(20, SCREEN_H - 60, 120, 40)

    def btn(text, rect, bg_col):
        hover = rect.collidepoint(pygame.mouse.get_pos())
        col   = tuple(min(255, c + 30) for c in bg_col) if hover else bg_col
        pygame.draw.rect(surface, col,         rect, border_radius=6)
        pygame.draw.rect(surface, (80, 80, 80), rect, width=2, border_radius=6)
        lbl = font_m.render(text, True, WHITE)
        surface.blit(lbl, lbl.get_rect(center=rect.center))

    btn(ui.t("lobby_host"), _hj_host_rect, (30,  80, 150))
    btn(ui.t("lobby_join"), _hj_join_rect, (80,  40, 120))
    btn(ui.t("back"),       _hj_back_rect, (60,  30,  30))


def _host_join_action(surface, ui, clicked):
    if not clicked: return None
    mouse = pygame.mouse.get_pos()
    if _hj_host_rect and _hj_host_rect.collidepoint(mouse): return "host"
    if _hj_join_rect and _hj_join_rect.collidepoint(mouse): return "join"
    if _hj_back_rect and _hj_back_rect.collidepoint(mouse): return "back"
    return None


if __name__ == "__main__":
    asyncio.run(main())