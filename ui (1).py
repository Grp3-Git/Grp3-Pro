# ui.py — UI module (M4)
# LAN update: username entry, lobby, CoD-Zombies scoreboard HUD
# NEW: pause sidebar, blur overlay, per-player scores always ingame,
#      total kills in bold red, respawn timers next to dead player names,
#      Game Over only when all dead (LAN)
# UPDATED: Game Over for LAN now shows ready-to-restart table + "PLAY AGAIN"/QUIT buttons

import pygame
import json
import os
import math
from constants import *


def _load_strings(lang: str) -> dict:
    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[UI] Could not load locale '{lang}': {e}")
        return {}


def _blur_surface(surf: pygame.Surface, strength: int = 6) -> pygame.Surface:
    w, h = surf.get_size()
    small_w = max(1, w // strength)
    small_h = max(1, h // strength)
    small = pygame.transform.smoothscale(surf, (small_w, small_h))
    return pygame.transform.smoothscale(small, (w, h))


class UI:
    """
    Public interface used by main.py:
        ui.lang / ui.toggle_lang()
        ui.draw_menu(surface) -> action
        ui.draw_username(surface, username, cursor_visible) -> action
        ui.draw_lobby(surface, local_ip, players, is_host, join_ip, join_cursor) -> action
        ui.draw_hud(surface, elapsed, kill_counts, lives, players_info,
                    respawn_timers={})
        ui.draw_death(surface, elapsed, kill_counts, players_info, is_lan=False, is_host=False, ready_slots=None, post_countdown=-1) -> action
        ui.draw_pause(surface, game_surface, is_host, is_lan,
                      restart_countdown) -> action
    """

    def __init__(self, sound=None):
        self.lang   = DEFAULT_LANG
        self._str   = _load_strings(self.lang)
        self._sound = sound

        self._font_large  = pygame.font.SysFont("monospace", 52, bold=True)
        self._font_medium = pygame.font.SysFont("monospace", 32, bold=True)
        self._font_small  = pygame.font.SysFont("monospace", 22)
        self._font_hud    = pygame.font.SysFont("monospace", 26, bold=True)
        self._font_tiny   = pygame.font.SysFont("monospace", 18)
        self._font_score  = pygame.font.SysFont("monospace", 20, bold=True)
        self._font_bold   = pygame.font.SysFont("monospace", 24, bold=True)

        self._lang_btn_rect   = pygame.Rect(10, 10, 60, 34)
        self._play_btn_rect   = None
        self._lan_btn_rect    = None
        self._quit_btn_rect   = None
        self._retry_btn_rect  = None
        self._death_quit_rect = None
        self._confirm_btn     = None
        self._host_btn_rect   = None
        self._join_btn_rect   = None
        self._back_btn_rect   = None
        self._start_btn_rect  = None
        self._pause_rects     = {}

    def toggle_lang(self):
        idx = LANGUAGES.index(self.lang)
        self.lang = LANGUAGES[(idx + 1) % len(LANGUAGES)]
        self._str = _load_strings(self.lang)

    def t(self, key: str, **kwargs) -> str:
        s = self._str.get(key, key)
        for k, v in kwargs.items():
            s = s.replace("{" + k + "}", str(v))
        return s

    def draw_username(self, surface, username: str, cursor_visible: bool):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 230))
        surface.blit(overlay, (0, 0))

        cx = SCREEN_W // 2
        cy = SCREEN_H // 2

        title = self._font_large.render(self.t("username_title"), True, YELLOW)
        surface.blit(title, title.get_rect(center=(cx, cy - 120)))

        hint = self._font_tiny.render(self.t("username_hint"), True, (150, 150, 150))
        surface.blit(hint, hint.get_rect(center=(cx, cy - 68)))

        box_w, box_h = 420, 56
        box_rect = pygame.Rect(cx - box_w // 2, cy - box_h // 2, box_w, box_h)
        pygame.draw.rect(surface, (20, 20, 20), box_rect, border_radius=6)
        pygame.draw.rect(surface, (100, 180, 255), box_rect, width=2, border_radius=6)

        display = username + ("|" if cursor_visible else " ")
        txt = self._font_medium.render(display, True, WHITE)
        surface.blit(txt, txt.get_rect(center=box_rect.center))

        bw, bh = 200, 50
        self._confirm_btn = pygame.Rect(cx - bw // 2, cy + 60, bw, bh)
        self._draw_button(surface, self.t("confirm"), self._confirm_btn,
                          self._font_medium, bg=(40, 120, 60), fg=WHITE)

        self._draw_button(surface, self.t("lang_btn"), self._lang_btn_rect,
                          self._font_tiny, bg=(30, 30, 30), fg=WHITE, border=(80, 80, 80))

        mouse   = pygame.mouse.get_pos()
        clicked = pygame.mouse.get_pressed()[0]
        if clicked and self._confirm_btn.collidepoint(mouse) and username.strip():
            return "confirm"
        if clicked and self._lang_btn_rect.collidepoint(mouse):
            return "lang"
        return None

    def draw_lobby(self, surface, local_ip: str, players: list,
                   is_host: bool, join_ip: str, join_cursor: bool):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 220))
        surface.blit(overlay, (0, 0))

        cx = SCREEN_W // 2

        mode  = self.t("lobby_host") if is_host else self.t("lobby_join")
        title = self._font_large.render(f"LAN — {mode}", True, YELLOW)
        surface.blit(title, title.get_rect(center=(cx, 80)))

        if is_host:
            ip_text = self._font_small.render(
                f"{self.t('lobby_your_ip')}: {local_ip}:{LAN_PORT}", True, (180, 230, 180))
            surface.blit(ip_text, ip_text.get_rect(center=(cx, 140)))

        panel_w, panel_h = 600, 240
        panel_rect = pygame.Rect(cx - panel_w // 2, 180, panel_w, panel_h)
        pygame.draw.rect(surface, (15, 15, 15), panel_rect, border_radius=8)
        pygame.draw.rect(surface, (60, 60, 60), panel_rect, width=1, border_radius=8)

        for slot in range(LAN_MAX_PLAYERS):
            row_y = panel_rect.y + 20 + slot * 52
            color = PLAYER_COLORS[slot]
            pygame.draw.rect(surface, color,
                             pygame.Rect(panel_rect.x + 16, row_y + 8, 8, 32),
                             border_radius=3)
            p = next((p for p in players if p["slot"] == slot), None)
            if p:
                name_surf  = self._font_score.render(f"P{slot + 1}  {p['username']}", True, color)
                ready_surf = self._font_tiny.render(self.t("lobby_ready"), True, (80, 220, 80))
                surface.blit(name_surf,  (panel_rect.x + 36, row_y + 10))
                surface.blit(ready_surf, (panel_rect.right - 80, row_y + 14))
            else:
                empty_surf = self._font_score.render(
                    f"P{slot + 1}  {self.t('lobby_empty')}", True, (60, 60, 60))
                surface.blit(empty_surf, (panel_rect.x + 36, row_y + 10))

        btn_y  = panel_rect.bottom + 30
        result = None

        if is_host:
            bw, bh = 220, 50
            self._start_btn_rect = pygame.Rect(cx - bw // 2, btn_y, bw, bh)
            can_start = len(players) >= 1
            start_bg  = (40, 120, 60) if can_start else (30, 50, 30)
            self._draw_button(surface, self.t("lobby_start"), self._start_btn_rect,
                              self._font_medium, bg=start_bg, fg=WHITE)
            mouse   = pygame.mouse.get_pos()
            clicked = pygame.mouse.get_pressed()[0]
            if clicked and can_start and self._start_btn_rect.collidepoint(mouse):
                result = "start"
        else:
            label = self._font_tiny.render(self.t("lobby_host_ip"), True, (180, 180, 180))
            surface.blit(label, (cx - 210, btn_y - 28))

            box_w, box_h = 420, 46
            ip_box = pygame.Rect(cx - box_w // 2, btn_y, box_w, box_h)
            pygame.draw.rect(surface, (20, 20, 20), ip_box, border_radius=6)
            pygame.draw.rect(surface, (100, 180, 255), ip_box, width=2, border_radius=6)
            display_ip = join_ip + ("|" if join_cursor else " ")
            ip_surf = self._font_small.render(display_ip, True, WHITE)
            surface.blit(ip_surf, ip_surf.get_rect(center=ip_box.center))

            bw, bh = 160, 46
            self._join_btn_rect = pygame.Rect(cx - bw // 2, btn_y + 60, bw, bh)
            self._draw_button(surface, self.t("lobby_connect"), self._join_btn_rect,
                              self._font_medium, bg=(40, 80, 160), fg=WHITE)

            mouse   = pygame.mouse.get_pos()
            clicked = pygame.mouse.get_pressed()[0]
            if clicked:
                if self._join_btn_rect and self._join_btn_rect.collidepoint(mouse):
                    result = "join"
                elif ip_box.collidepoint(mouse):
                    result = "typing"

        bw2, bh2 = 120, 40
        self._back_btn_rect = pygame.Rect(20, SCREEN_H - 60, bw2, bh2)
        self._draw_button(surface, self.t("back"), self._back_btn_rect,
                          self._font_tiny, bg=(60, 30, 30), fg=WHITE)
        mouse   = pygame.mouse.get_pos()
        clicked = pygame.mouse.get_pressed()[0]
        if clicked and self._back_btn_rect.collidepoint(mouse):
            result = "back"

        self._draw_button(surface, self.t("lang_btn"), self._lang_btn_rect,
                          self._font_tiny, bg=(30, 30, 30), fg=WHITE, border=(80, 80, 80))
        if clicked and self._lang_btn_rect.collidepoint(mouse):
            result = "lang"

        return result

    def draw_hud(self, surface, elapsed: float, kill_counts: list,
                 lives: int, players_info: list, respawn_timers: dict = None):
        if respawn_timers is None:
            respawn_timers = {}

        self._draw_button(surface, self.t("lang_btn"),
                          self._lang_btn_rect, self._font_tiny,
                          bg=(30, 30, 30), fg=WHITE, border=(80, 80, 80))

        minutes  = int(elapsed) // 60
        seconds  = int(elapsed) % 60
        time_str = f"{self.t('hud_time')}: {minutes:02d}:{seconds:02d}"

        hearts = "♥ " * max(0, lives)
        lives_str = f"{self.t('hud_lives')}: {hearts}" if lives > 0 else f"{self.t('hud_lives')}: —"

        pad = 12
        for i, (text, col) in enumerate([(time_str, HUD_TEXT), (lives_str, HUD_TEXT)]):
            surf = self._font_hud.render(text, True, col)
            y    = 10 + i * 34
            bg_s = pygame.Surface((surf.get_width() + pad * 2, 30), pygame.SRCALPHA)
            bg_s.fill((10, 10, 10, 160))
            surface.blit(bg_s,  (10, y + 50))
            surface.blit(surf,  (10 + pad, y + 52))

        self._draw_scoreboard(surface, kill_counts, players_info, respawn_timers)

    def _draw_scoreboard(self, surface, kill_counts: list,
                         players_info: list, respawn_timers: dict):
        panel_w = 250
        panel_x = SCREEN_W - panel_w - 8
        panel_y = 8

        total = sum(kill_counts)
        rows  = []
        for slot in range(LAN_MAX_PLAYERS):
            kc = kill_counts[slot] if slot < len(kill_counts) else 0
            p  = next((p for p in players_info if p["slot"] == slot), None)
            if kc > 0 or p is not None:
                name = p["username"] if p else (f"P{slot + 1}" if slot == 0 else None)
                if name:
                    is_dead = p.get("dead", False) if p else False
                    rt = respawn_timers.get(slot, -1.0)
                    rows.append((slot, name, kc, is_dead, rt))

        panel_h = 44 + len(rows) * 38 + 8
        bg_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg_surf.fill((8, 8, 8, 190))
        surface.blit(bg_surf, (panel_x, panel_y))
        pygame.draw.rect(surface, (50, 50, 50),
                         pygame.Rect(panel_x, panel_y, panel_w, panel_h),
                         width=1, border_radius=4)

        total_surf = self._font_bold.render(f"KILLS  {total:04d}", True, (220, 50, 50))
        surface.blit(total_surf, (panel_x + 10, panel_y + 8))

        div_y = panel_y + 38
        pygame.draw.line(surface, (60, 60, 60),
                         (panel_x + 6, div_y), (panel_x + panel_w - 6, div_y))

        for i, (slot, name, kc, is_dead, respawn_t) in enumerate(rows):
            row_y = div_y + 6 + i * 38
            color = PLAYER_COLORS[slot % len(PLAYER_COLORS)]

            draw_color = tuple(max(30, c // 2) for c in color) if is_dead else color

            pygame.draw.rect(surface, draw_color,
                             pygame.Rect(panel_x + 6, row_y + 4, 5, 26),
                             border_radius=2)

            display_name = name[:10] if len(name) > 10 else name
            name_surf = self._font_score.render(display_name, True, draw_color)
            surface.blit(name_surf, (panel_x + 18, row_y + 4))

            kc_surf = self._font_score.render(f"{kc}", True, draw_color)
            surface.blit(kc_surf,
                         (panel_x + panel_w - kc_surf.get_width() - 10, row_y + 4))

            if is_dead and respawn_t >= 0:
                t_int = int(math.ceil(respawn_t))
                cd_str  = f"  respawn {t_int}s"
                cd_surf = self._font_tiny.render(cd_str, True, (255, 170, 50))
                surface.blit(cd_surf, (panel_x + 16, row_y + 22))

    def draw_menu(self, surface):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 210))
        surface.blit(overlay, (0, 0))

        title = self._font_large.render("CRIMSONLAND", True, RED)
        surface.blit(title, title.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 140)))

        sub = self._font_tiny.render("Survive as long as you can", True, (160, 160, 160))
        surface.blit(sub, sub.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 88)))

        cx = SCREEN_W // 2
        cy = SCREEN_H // 2
        bw, bh = 220, 52

        self._play_btn_rect = pygame.Rect(cx - bw // 2, cy - 30, bw, bh)
        self._lan_btn_rect  = pygame.Rect(cx - bw // 2, cy + 38, bw, bh)
        self._quit_btn_rect = pygame.Rect(cx - bw // 2, cy + 108, bw, bh)

        self._draw_button(surface, self.t("play"),     self._play_btn_rect,
                          self._font_medium, bg=(40, 120, 60),  fg=WHITE)
        self._draw_button(surface, self.t("play_lan"), self._lan_btn_rect,
                          self._font_medium, bg=(30, 70, 150),  fg=WHITE)
        self._draw_button(surface, self.t("quit"),     self._quit_btn_rect,
                          self._font_medium, bg=(100, 30, 30),  fg=WHITE)

        self._draw_button(surface, self.t("lang_btn"), self._lang_btn_rect,
                          self._font_tiny, bg=(30, 30, 30), fg=WHITE, border=(80, 80, 80))

        mouse   = pygame.mouse.get_pos()
        clicked = pygame.mouse.get_pressed()[0]
        if clicked:
            if self._play_btn_rect.collidepoint(mouse):  return "play_solo"
            if self._lan_btn_rect.collidepoint(mouse):   return "play_lan"
            if self._quit_btn_rect.collidepoint(mouse):  return "quit"
            if self._lang_btn_rect.collidepoint(mouse):  return "lang"
        return None

    # UPDATED draw_death with LAN ready table + countdown
    def draw_death(self, surface, elapsed: float, kill_counts: list,
                   players_info: list, is_lan=False, is_host=False,
                   ready_slots=None, post_countdown=-1):
        if ready_slots is None:
            ready_slots = []

        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        surface.blit(overlay, (0, 0))

        cx = SCREEN_W // 2
        cy = SCREEN_H // 2

        title = self._font_large.render(self.t("score_title"), True, RED)
        surface.blit(title, title.get_rect(center=(cx, cy - 200)))

        total_secs = max(1, int(elapsed))
        minutes    = total_secs // 60
        seconds    = total_secs % 60
        time_surf  = self._font_medium.render(
            f"{self.t('time_label')}:  {minutes:02d}:{seconds:02d}", True, WHITE)
        surface.blit(time_surf, time_surf.get_rect(center=(cx, cy - 140)))

        total      = sum(kill_counts)
        total_surf = self._font_bold.render(
            f"{self.t('kills_label')}:  {total}", True, (220, 50, 50))
        surface.blit(total_surf, total_surf.get_rect(center=(cx, cy - 95)))

        row_start_y  = cy - 55
        active_slots = [slot for slot in range(LAN_MAX_PLAYERS)
                        if (kill_counts[slot] if slot < len(kill_counts) else 0) > 0
                        or any(p["slot"] == slot for p in players_info)]
        for i, slot in enumerate(active_slots):
            kc    = kill_counts[slot] if slot < len(kill_counts) else 0
            p     = next((p for p in players_info if p["slot"] == slot), None)
            name  = p["username"] if p else f"P{slot + 1}"
            color = PLAYER_COLORS[slot % len(PLAYER_COLORS)]
            line  = f"P{slot + 1}  {name[:12]:<12}  {kc} kills"
            surf  = self._font_score.render(line, True, color)
            surface.blit(surf, surf.get_rect(center=(cx, row_start_y + i * 30)))

        n_players = max(1, len(players_info))
        avg       = total / n_players
        avg_surf  = self._font_small.render(
            f"{self.t('avg_label')}:  {avg:.1f}", True, (200, 200, 100))
        surface.blit(avg_surf,
                     avg_surf.get_rect(center=(cx, row_start_y + len(active_slots) * 30 + 16)))

        # LAN-only ready table + countdown
        if is_lan:
            ready_y = row_start_y + len(active_slots) * 30 + 70
            ready_title = self._font_medium.render("READY TO PLAY AGAIN", True, YELLOW)
            surface.blit(ready_title, ready_title.get_rect(center=(cx, ready_y)))

            panel_w, panel_h = 500, 30 + LAN_MAX_PLAYERS * 40
            panel_rect = pygame.Rect(cx - panel_w // 2, ready_y + 40, panel_w, panel_h)
            pygame.draw.rect(surface, (15, 15, 15), panel_rect, border_radius=8)
            pygame.draw.rect(surface, (60, 60, 60), panel_rect, width=1, border_radius=8)

            for slot in range(LAN_MAX_PLAYERS):
                row_y = panel_rect.y + 10 + slot * 40
                color = PLAYER_COLORS[slot]
                pygame.draw.rect(surface, color,
                                 pygame.Rect(panel_rect.x + 16, row_y + 8, 8, 24),
                                 border_radius=3)
                p = next((p for p in players_info if p["slot"] == slot), None)
                name = p["username"] if p else f"P{slot + 1}"
                is_ready = slot in ready_slots
                name_surf = self._font_score.render(name, True, color)
                surface.blit(name_surf, (panel_rect.x + 36, row_y + 10))
                if is_ready:
                    ready_surf = self._font_tiny.render("READY", True, (80, 220, 80))
                    surface.blit(ready_surf, (panel_rect.right - 100, row_y + 12))
                else:
                    empty_surf = self._font_tiny.render("WAITING...", True, (100, 100, 100))
                    surface.blit(empty_surf, (panel_rect.right - 120, row_y + 12))

            if post_countdown >= 0:
                cd_str = self.t("beginning_countdown", n=int(post_countdown))
                cd_surf = self._font_small.render(cd_str, True, (255, 200, 50))
                surface.blit(cd_surf, cd_surf.get_rect(center=(cx, SCREEN_H - 80)))

        # Buttons
        btn_y = cy + 260 if is_lan else cy + 100
        bw, bh = 220, 52

        self._retry_btn_rect = pygame.Rect(cx - bw - 10, btn_y, bw, bh)
        self._death_quit_rect = pygame.Rect(cx + 10, btn_y, bw, bh)

        self._draw_button(surface, self.t("retry"), self._retry_btn_rect,
                          self._font_medium, bg=(40, 120, 60), fg=WHITE)
        self._draw_button(surface, self.t("quit"), self._death_quit_rect,
                          self._font_medium, bg=(100, 30, 30), fg=WHITE)

        self._draw_button(surface, self.t("lang_btn"), self._lang_btn_rect,
                          self._font_tiny, bg=(30, 30, 30), fg=WHITE, border=(80, 80, 80))

        mouse   = pygame.mouse.get_pos()
        clicked = pygame.mouse.get_pressed()[0]
        if clicked:
            if self._retry_btn_rect and self._retry_btn_rect.collidepoint(mouse):
                return "play_again" if is_lan else "retry"
            if self._death_quit_rect and self._death_quit_rect.collidepoint(mouse):
                return "quit"
            if self._lang_btn_rect.collidepoint(mouse):
                return "lang"
        return None

    def draw_pause(self, surface, game_surface: pygame.Surface,
                   is_host: bool, is_lan: bool,
                   restart_countdown: int = -1) -> str | None:
        blurred = _blur_surface(game_surface, strength=5)
        surface.blit(blurred, (0, 0))

        tint = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        tint.fill((0, 0, 0, 120))
        surface.blit(tint, (0, 0))

        sidebar_w = 280
        sidebar_x = SCREEN_W - sidebar_w - 20
        sidebar_y = SCREEN_H // 2 - 200
        sidebar_h = 420

        sidebar_surf = pygame.Surface((sidebar_w, sidebar_h), pygame.SRCALPHA)
        sidebar_surf.fill((10, 10, 10, 160))
        pygame.draw.rect(sidebar_surf, (80, 80, 80, 200),
                         pygame.Rect(0, 0, sidebar_w, sidebar_h),
                         width=1, border_radius=10)
        surface.blit(sidebar_surf, (sidebar_x, sidebar_y))

        paused_surf = self._font_medium.render(self.t("paused"), True, YELLOW)
        surface.blit(paused_surf,
                     paused_surf.get_rect(center=(sidebar_x + sidebar_w // 2, sidebar_y + 40)))

        pygame.draw.line(surface, (80, 80, 80),
                         (sidebar_x + 20, sidebar_y + 68),
                         (sidebar_x + sidebar_w - 20, sidebar_y + 68))

        show_restart = (not is_lan) or is_host
        options = [
            ("resume",  self.t("pause_resume"),  (40, 120, 60),  True),
            ("restart", self.t("pause_restart"), (30, 70, 150),  show_restart),
            ("lang",    self.t("pause_lang"),    (60, 60, 120),  True),
            ("quit",    self.t("pause_quit"),    (100, 30, 30),  True),
        ]

        btn_w, btn_h = sidebar_w - 40, 50
        btn_start_y  = sidebar_y + 90
        gap          = 60
        self._pause_rects = {}
        visible_index = 0

        for key, label, color, visible in options:
            if not visible:
                continue
            bx   = sidebar_x + 20
            by   = btn_start_y + visible_index * gap
            rect = pygame.Rect(bx, by, btn_w, btn_h)
            self._draw_button(surface, label, rect, self._font_medium,
                              bg=color, fg=WHITE)
            self._pause_rects[key] = rect
            visible_index += 1

        if restart_countdown >= 0:
            msg_surf = self._font_small.render(
                self.t("restart_countdown", n=restart_countdown), True, (255, 200, 50))
            surface.blit(msg_surf,
                         msg_surf.get_rect(center=(SCREEN_W // 2, SCREEN_H - 60)))

        mouse   = pygame.mouse.get_pos()
        clicked = pygame.mouse.get_pressed()[0]
        if clicked:
            for key, rect in self._pause_rects.items():
                if rect.collidepoint(mouse):
                    return key
        return None

    def _draw_button(self, surface, text, rect, font,
                     bg=(40, 40, 40), fg=WHITE, border=(60, 60, 60)):
        mouse  = pygame.mouse.get_pos()
        hover  = rect.collidepoint(mouse)
        colour = tuple(min(255, c + 30) for c in bg) if hover else bg
        pygame.draw.rect(surface, colour, rect, border_radius=6)
        pygame.draw.rect(surface, border, rect, width=2, border_radius=6)
        label = font.render(text, True, fg)
        surface.blit(label, label.get_rect(center=rect.center))