# main.py — Game loop & state manager
# Run locally:  python src/main.py
# Web build:    pygbag src/main.py

import asyncio
import pygame
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import *
from player    import Player, RemotePlayer
from enemy     import EnemyManager
from ui        import UI
from audio     import SoundManager
from network   import LANServer, LANClient, get_local_ip


def _make_arena_bg():
    surf = pygame.Surface((SCREEN_W, SCREEN_H))
    surf.fill((18, 18, 18))
    grid = 64
    for x in range(0, SCREEN_W, grid):
        pygame.draw.line(surf, (28, 28, 28), (x, 0), (x, SCREEN_H))
    for y in range(0, SCREEN_H, grid):
        pygame.draw.line(surf, (28, 28, 28), (0, y), (SCREEN_W, y))
    pygame.draw.rect(surf, (50, 50, 50), (0, 0, SCREEN_W, SCREEN_H), 3)
    return surf


async def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption(TITLE)
    clock  = pygame.time.Clock()

    all_sprites  = pygame.sprite.Group()
    bullet_group = pygame.sprite.Group()
    player_group = pygame.sprite.GroupSingle()
    remote_group = pygame.sprite.Group()

    sound = SoundManager()
    ui    = UI()
    bg    = _make_arena_bg()

    player = Player(SCREEN_W // 2, SCREEN_H // 2, (all_sprites, player_group), slot=0)
    em     = EnemyManager(all_sprites)

    remote_players: dict = {}   # slot -> RemotePlayer

    # ── State ──────────────────────────────────────────────────────────
    state   = STATE_MENU
    elapsed = 0.0

    username       = ""
    cursor_visible = True
    cursor_timer   = 0.0
    pending_action = None

    is_host      = False
    lan_server   = None
    lan_client   = None
    local_slot   = 0
    players_info = []
    lobby_mode   = None
    join_ip      = ""
    join_cursor_visible = True
    join_cursor_timer   = 0.0
    typing_join_ip = False
    net_tick_timer = 0.0

    # Pause
    paused_game_snap  = None
    restart_countdown = -1
    restart_cd_timer  = 0.0
    pending_restart   = False

    _click_held = False

    # ── Helpers ────────────────────────────────────────────────────────

    def _start_game():
        nonlocal state, elapsed, paused_game_snap, pending_restart
        nonlocal restart_countdown, restart_cd_timer
        all_sprites.empty()
        bullet_group.empty()
        remote_group.empty()
        remote_players.clear()
        player.slot = local_slot
        player._load_sprites(local_slot)
        player.image = player.frames["idle"]
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
        sound.play_bgm()
        sound.set_crosshair()
        sound.set_paused_filter(False)

    def _ensure_remote(slot: int) -> RemotePlayer:
        if slot not in remote_players:
            rp = RemotePlayer(slot, (all_sprites, remote_group))
            remote_players[slot] = rp
        return remote_players[slot]

    def _draw_scene():
        """Draw arena + sprites + HUD (shared between PLAYING and PAUSED)."""
        screen.blit(bg, (0, 0))
        all_sprites.draw(screen)
        bullet_group.draw(screen)
        for slot, rp in remote_players.items():
            p_info = next((p for p in players_info if p["slot"] == slot), None)
            name   = p_info["username"] if p_info else rp.username
            color  = PLAYER_COLORS[slot % len(PLAYER_COLORS)]
            _draw_name_tag(screen, name, rp.rect.centerx, rp.rect.top - 4, color)
        ui.draw_hud(screen, elapsed, em.kill_counts, player.lives, players_info)
        sound.draw_crosshair(screen)

    def _net_tick_host():
        """Host networking: process client events, broadcast state."""
        for ev in lan_server.get_events():
            if ev["type"] == "hit":
                em.apply_hit_from_client(ev["eid"], ev["slot"], sound)

        client_positions = lan_server.get_client_positions()

        state_snapshot = {
            "type":           "game",
            "kill_counts":    em.kill_counts,
            "elapsed":        elapsed,
            "enemies":        em.serialise_enemies(),
            "host_pos":       player.get_net_state(),
            "remote_players": client_positions,
        }
        lan_server.push_state(state_snapshot)

        for p in players_info:
            s = p["slot"]
            p["kills"] = em.kill_counts[s] if s < len(em.kill_counts) else 0

        for slot_int, pos_data in client_positions.items():
            slot = int(slot_int)
            rp = _ensure_remote(slot)
            rp.username = pos_data.get("username", rp.username)
            rp.apply_state(pos_data, dt)

    def _net_tick_client():
        """Client networking: send position, apply host state."""
        lan_client.send_pos(player.get_net_state())

        sv = lan_client.get_state()
        if not sv:
            return sv

        if sv.get("type") == "game":
            # Sync enemies from host
            enemy_states = sv.get("enemies", [])
            em.apply_remote_enemies(enemy_states, dt)
            em.apply_remote_kill_counts(sv.get("kill_counts", []))

            # Sync host's sprite
            host_pos = sv.get("host_pos")
            if host_pos:
                hp = _ensure_remote(0)
                hp.apply_state(host_pos, dt)

            # Sync other clients' sprites
            for slot_str, pos_data in sv.get("remote_players", {}).items():
                slot = int(slot_str)
                if slot != local_slot:
                    rp = _ensure_remote(slot)
                    rp.apply_state(pos_data, dt)

            # Update local players_info kills
            for p in players_info:
                if p["slot"] == local_slot:
                    p["kills"] = em.kill_counts[local_slot]

        return sv

    # ── Main loop ──────────────────────────────────────────────────────
    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if lan_server: lan_server.stop()
                if lan_client: lan_client.stop()
                pygame.quit(); sys.exit()

            if event.type == pygame.MOUSEBUTTONUP:
                _click_held = False

            if event.type == pygame.MOUSEBUTTONDOWN:
                if state == STATE_PLAYING and event.button == 1:
                    if player.try_shoot(pygame.mouse.get_pos(), bullet_group, all_sprites):
                        sound.play("shoot")
                        # Clients report hits by eid so host can attribute kills
                        if lan_client and lan_client.connected:
                            hits = pygame.sprite.spritecollide(
                                player, em.enemies, False)  # not used; hits come from bullet
                            # Actual hit reporting happens during bullet-enemy collision below

            if event.type == pygame.KEYDOWN:
                if state == STATE_USERNAME:
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if username.strip():
                            if pending_action == "solo":
                                local_slot   = 0
                                players_info = [{"slot": 0, "username": username, "kills": 0}]
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
                        is_lan = (lan_server is not None or lan_client is not None)
                        paused_game_snap = None   # will be captured first frame of PAUSED
                        state = STATE_PAUSED
                        sound.set_paused_filter(True)
                        # Solo only: freeze bgm/steps
                        if not is_lan:
                            sound.stop_bgm()
                            sound.stop_steps()
                    elif state == STATE_PAUSED:
                        state = STATE_PLAYING
                        sound.set_paused_filter(False)
                        is_lan = (lan_server is not None or lan_client is not None)
                        if not is_lan:
                            sound.play_bgm()
                        paused_game_snap = None

        keys      = pygame.key.get_pressed()
        mouse_pos = pygame.mouse.get_pos()
        clicked   = pygame.mouse.get_pressed()[0] and not _click_held

        # ── MENU ───────────────────────────────────────────────────────
        if state == STATE_MENU:
            sound.restore_cursor()
            screen.blit(bg, (0, 0))
            action = ui.draw_menu(screen)
            if clicked:
                _click_held = True
                if action == "play_solo":
                    pending_action = "solo"; state = STATE_USERNAME
                elif action == "play_lan":
                    pending_action = "lan";  state = STATE_USERNAME
                elif action == "quit":
                    pygame.quit(); sys.exit()
                elif action == "lang":
                    ui.toggle_lang()

        # ── USERNAME ───────────────────────────────────────────────────
        elif state == STATE_USERNAME:
            sound.restore_cursor()
            cursor_timer += dt
            if cursor_timer >= 0.5:
                cursor_timer = 0.0; cursor_visible = not cursor_visible
            screen.blit(bg, (0, 0))
            action = ui.draw_username(screen, username, cursor_visible)
            if clicked:
                _click_held = True
                if action == "confirm" and username.strip():
                    if pending_action == "solo":
                        local_slot   = 0
                        players_info = [{"slot": 0, "username": username, "kills": 0}]
                        _start_game()
                    elif pending_action == "lan":
                        state = STATE_LOBBY
                elif action == "lang":
                    ui.toggle_lang()

        # ── LOBBY ──────────────────────────────────────────────────────
        elif state == STATE_LOBBY:
            sound.restore_cursor()
            join_cursor_timer += dt
            if join_cursor_timer >= 0.5:
                join_cursor_timer = 0.0; join_cursor_visible = not join_cursor_visible

            if lobby_mode is None:
                screen.blit(bg, (0, 0))
                action = _host_join_action(screen, ui, clicked)
                _draw_host_join_choice(screen, ui, clicked)
                if action == "host":
                    lobby_mode   = "host"; is_host = True; local_slot = 0
                    lan_server   = LANServer(host_username=username)
                    players_info = [{"slot": 0, "username": username, "kills": 0}]
                elif action == "join":
                    lobby_mode = "join"; is_host = False
                elif action == "back":
                    state = STATE_MENU; lobby_mode = None
                elif action == "lang":
                    ui.toggle_lang()
            else:
                if is_host and lan_server:
                    remote = lan_server.connected_players()
                    host_entry = next((p for p in players_info if p["slot"] == 0), None)
                    players_info = ([host_entry] if host_entry else []) + remote

                if lan_client and lan_client.connected:
                    lp = lan_client.lobby_players
                    if lp:
                        mine   = next((p for p in players_info if p["slot"] == local_slot), None)
                        merged = [mine] if mine else []
                        for rp in lp:
                            if rp["slot"] != local_slot:
                                ex = next((p for p in merged if p["slot"] == rp["slot"]), None)
                                if ex: ex["username"] = rp["username"]
                                else:  merged.append({"slot": rp["slot"], "username": rp["username"], "kills": 0})
                        players_info = sorted(merged, key=lambda p: p["slot"])

                screen.blit(bg, (0, 0))
                action = ui.draw_lobby(screen, get_local_ip(), players_info,
                                       is_host, join_ip, join_cursor_visible)
                if clicked:
                    _click_held = True
                    if action == "start" and is_host:
                        if lan_server: lan_server.push_state({"type": "start"})
                        local_slot = 0; _start_game()
                    elif action == "join":
                        host_ip    = join_ip.strip() or "127.0.0.1"
                        lan_client = LANClient(host_ip, username)
                        if lan_client.connected:
                            local_slot   = lan_client.slot
                            players_info = [{"slot": local_slot, "username": username, "kills": 0}]
                        else:
                            lan_client = None
                    elif action == "typing":
                        typing_join_ip = True
                    elif action == "back":
                        if lan_server: lan_server.stop(); lan_server = None
                        if lan_client: lan_client.stop(); lan_client = None
                        lobby_mode = None; state = STATE_MENU
                    elif action == "lang":
                        ui.toggle_lang()

                if lan_client and lan_client.connected:
                    sv = lan_client.get_state()
                    if sv and sv.get("type") == "start":
                        _start_game()

        # ── PLAYING ────────────────────────────────────────────────────
        elif state == STATE_PLAYING:
            elapsed += dt
            player.update(dt, keys, mouse_pos)

            moving = any([keys[pygame.K_LEFT], keys[pygame.K_a], keys[pygame.K_q],
                          keys[pygame.K_RIGHT], keys[pygame.K_d],
                          keys[pygame.K_UP], keys[pygame.K_w], keys[pygame.K_z],
                          keys[pygame.K_DOWN], keys[pygame.K_s]])
            if moving: sound.play("player_steps")
            else:      sound.stop_steps()

            bullet_group.update(dt)

            is_lan = (lan_server is not None or lan_client is not None)

            if lan_server:
                # HOST: full simulation
                em.update(dt, player.rect.center, bullet_group, player, sound, local_slot)
            elif lan_client and lan_client.connected:
                # CLIENT: detect bullet hits and report to host by eid
                for enemy in list(em.enemies):
                    hits = pygame.sprite.spritecollide(enemy, bullet_group, True)
                    if hits:
                        lan_client.send_hit(enemy.eid)
                        sound.play("monster_hurt")
                # Contact damage on client (local feel, host is authoritative for lives)
                for enemy in list(em.enemies):
                    if (not enemy._dying
                            and enemy.rect.colliderect(player.rect)
                            and enemy.can_damage_player()):
                        enemy.mark_contact()
                        player.take_damage()
                        sound.play("player_hurt")
            else:
                # SOLO: full simulation
                em.update(dt, player.rect.center, bullet_group, player, sound, local_slot)

            # Network tick
            net_tick_timer += dt
            if net_tick_timer >= 1.0 / LAN_TICK_RATE:
                net_tick_timer = 0.0
                if lan_server:
                    _net_tick_host()
                elif lan_client and lan_client.connected:
                    sv = _net_tick_client()
                    if sv:
                        if sv.get("type") == "restart_countdown":
                            restart_countdown = sv.get("secs", 5)
                        elif sv.get("type") == "restart":
                            _start_game()

            for p in players_info:
                if p["slot"] == local_slot:
                    p["kills"] = em.kill_counts[local_slot]

            if player.is_dead:
                state = STATE_DEAD
                sound.stop_bgm(); sound.restore_cursor(); sound.stop_steps()
                sound.play("player_death")

            _draw_scene()

        # ── PAUSED ─────────────────────────────────────────────────────
        elif state == STATE_PAUSED:
            is_lan = (lan_server is not None or lan_client is not None)

            # Always advance local player input and bullets (LAN) or freeze (solo)
            if is_lan:
                elapsed += dt
                player.update(dt, keys, mouse_pos)

                moving = any([keys[pygame.K_LEFT], keys[pygame.K_a], keys[pygame.K_q],
                              keys[pygame.K_RIGHT], keys[pygame.K_d],
                              keys[pygame.K_UP], keys[pygame.K_w], keys[pygame.K_z],
                              keys[pygame.K_DOWN], keys[pygame.K_s]])
                if moving: sound.play("player_steps")
                else:      sound.stop_steps()

                bullet_group.update(dt)

                if lan_server:
                    em.update(dt, player.rect.center, bullet_group, player, sound, local_slot)
                elif lan_client and lan_client.connected:
                    for enemy in list(em.enemies):
                        hits = pygame.sprite.spritecollide(enemy, bullet_group, True)
                        if hits:
                            lan_client.send_hit(enemy.eid)
                    for enemy in list(em.enemies):
                        if (not enemy._dying
                                and enemy.rect.colliderect(player.rect)
                                and enemy.can_damage_player()):
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
                            if sv.get("type") == "restart_countdown":
                                restart_countdown = sv.get("secs", 5)
                            elif sv.get("type") == "restart":
                                _start_game()

                if player.is_dead:
                    state = STATE_DEAD
                    sound.stop_bgm(); sound.restore_cursor(); sound.stop_steps()
                    sound.play("player_death")

            # Countdown tick (host restart)
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
                    continue  # skip rest of frame — state changed

            # Draw live game scene first, then pause overlay on top
            _draw_scene()

            # Capture snapshot for blur only once (first frame entering pause)
            if paused_game_snap is None:
                paused_game_snap = screen.copy()

            action = ui.draw_pause(screen, paused_game_snap,
                                   is_host=is_host, is_lan=is_lan,
                                   restart_countdown=restart_countdown)

            if clicked:
                _click_held = True
                if action == "resume":
                    state = STATE_PLAYING
                    sound.set_paused_filter(False)
                    if not is_lan: sound.play_bgm()
                    paused_game_snap = None

                elif action == "restart":
                    if is_lan and is_host:
                        # Close pause menu immediately, host keeps playing,
                        # countdown runs in background
                        pending_restart   = True
                        restart_cd_timer  = 5.0
                        restart_countdown = 5
                        state = STATE_PLAYING          # <-- unpause right away
                        sound.set_paused_filter(False)
                        paused_game_snap = None
                        if lan_server:
                            lan_server.broadcast_restart_countdown(5)
                    else:
                        # Solo restart
                        sound.set_paused_filter(False)
                        _start_game()

                elif action == "lang":
                    ui.toggle_lang()

                elif action == "quit":
                    if lan_server: lan_server.stop(); lan_server = None
                    if lan_client: lan_client.stop(); lan_client = None
                    sound.set_paused_filter(False)
                    sound.stop_bgm(); sound.restore_cursor()
                    state = STATE_MENU; lobby_mode = None
                    paused_game_snap = None

        # ── DEAD ───────────────────────────────────────────────────────
        elif state == STATE_DEAD:
            screen.blit(bg, (0, 0))
            all_sprites.draw(screen)
            action = ui.draw_death(screen, elapsed, em.kill_counts, players_info)
            if clicked:
                _click_held = True
                if action == "retry":
                    _start_game()
                elif action == "quit":
                    if lan_server: lan_server.stop(); lan_server = None
                    if lan_client: lan_client.stop(); lan_client = None
                    state = STATE_MENU; lobby_mode = None
                elif action == "lang":
                    ui.toggle_lang()

        pygame.display.flip()
        await asyncio.sleep(0)


# ── Helpers ────────────────────────────────────────────────────────────

def _draw_name_tag(surface, name, cx, top_y, color):
    font = pygame.font.SysFont("monospace", 14, bold=True)
    surf = font.render(name, True, color)
    x = cx - surf.get_width() // 2
    y = top_y - surf.get_height() - 2
    bg = pygame.Surface((surf.get_width() + 6, surf.get_height() + 2), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 120))
    surface.blit(bg,   (x - 3, y - 1))
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
        pygame.draw.rect(surface, col,       rect, border_radius=6)
        pygame.draw.rect(surface, (80,80,80),rect, width=2, border_radius=6)
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
