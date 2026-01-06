# main.py  (REPLACEMENT)
# Mobile-friendly main loop, menu, difficulty, timer, pause, settings, and mobile controller overlay.
# Integrates with your game modules: settings, map, player, raycasting, object_renderer, sprite_object,
# object_handler, weapon, sound, pathfinding, npc, etc.

import pygame as pg
import sys
import json
import os
import math
from settings import *
from map import Map
from player import Player
from raycasting import RayCasting
from object_renderer import ObjectRenderer
from sprite_object import *
from object_handler import ObjectHandler
from weapon import Weapon
from sound import Sound
from pathfinding import PathFinding
from npc import *
# keep imports above consistent with your project file names

# ---------------------------
# Utility: persistent settings
# ---------------------------
DEFAULT_UI_SETTINGS = {
    "width": WIDTH,
    "height": HEIGHT,
    "fullscreen": False,
    "volume": 0.8,
    "sensitivity": MOUSE_SENSITIVITY
}
SETTINGS_FILE = "settings.json"


def load_ui_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                s = json.load(f)
            for k in DEFAULT_UI_SETTINGS:
                if k not in s:
                    s[k] = DEFAULT_UI_SETTINGS[k]
            return s
        except Exception:
            return DEFAULT_UI_SETTINGS.copy()
    return DEFAULT_UI_SETTINGS.copy()


def save_ui_settings(s):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except Exception as e:
        print("Failed save settings:", e)


# ---------------------------
# UI primitives
# ---------------------------
class Button:
    def __init__(self, rect, text, fn=None, font=None, bg=(40, 40, 40), fg=(255, 255, 255)):
        self.rect = pg.Rect(rect)
        self.text = text
        self.fn = fn
        self.bg = bg
        self.fg = fg
        self.font = font or pg.font.Font(None, 36)

    def draw(self, surf):
        pg.draw.rect(surf, self.bg, self.rect, border_radius=8)
        txt = self.font.render(self.text, True, self.fg)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def handle_event(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos):
                if self.fn:
                    self.fn()


class Label:
    def __init__(self, pos, text, font=None, fg=(255, 255, 255)):
        self.pos = pos
        self.text = text
        self.font = font or pg.font.Font(None, 28)
        self.fg = fg

    def draw(self, surf):
        txt = self.font.render(self.text, True, self.fg)
        surf.blit(txt, self.pos)


# ---------------------------
# Virtual joystick (left) and shoot button (right)
# ---------------------------
class VirtualJoystick:
    def __init__(self, center, outer_radius=80, inner_radius=34):
        self.center = pg.Vector2(center)
        self.outer_radius = outer_radius
        self.inner_radius = inner_radius
        self.active = False
        self.pointer = pg.Vector2(center)

    def draw(self, surf):
        # outer
        pg.draw.circle(surf, (80, 80, 80, 140), (int(self.center.x), int(self.center.y)), self.outer_radius)
        # inner
        pg.draw.circle(surf, (160, 160, 160, 180), (int(self.pointer.x), int(self.pointer.y)), self.inner_radius)

    def start(self, pos):
        self.active = True
        self.pointer = pg.Vector2(pos)

    def move(self, pos):
        v = pg.Vector2(pos) - self.center
        if v.length() > self.outer_radius:
            v.scale_to_length(self.outer_radius)
        self.pointer = self.center + v

    def end(self):
        self.active = False
        self.pointer = pg.Vector2(self.center)

    def get_vector(self):
        if not self.active:
            return pg.Vector2(0, 0)
        v = self.pointer - self.center
        # normalized - y axis inverted for screen coords => up is negative y
        return pg.Vector2(v.x / self.outer_radius, v.y / self.outer_radius)


class TouchButton:
    def __init__(self, rect, label=""):
        self.rect = pg.Rect(rect)
        self.label = label
        self.pressed = False

    def draw(self, surf, font=None):
        color = (180, 70, 70) if self.pressed else (120, 40, 40)
        pg.draw.ellipse(surf, color, self.rect)
        if self.label and font:
            txt = font.render(self.label, True, (255, 255, 255))
            surf.blit(txt, txt.get_rect(center=self.rect.center))

    def contains(self, pos):
        return self.rect.collidepoint(pos)


# ---------------------------
# Leaderboard basic storage
# ---------------------------
LEADERBOARD_FILE = "leaderboard.json"


def load_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_leaderboard(board):
    try:
        with open(LEADERBOARD_FILE, "w") as f:
            json.dump(board, f, indent=2)
    except Exception as e:
        print("Failed save leaderboard:", e)


# ---------------------------
# Game wrapper (keeps your Game structure but adds UI/game states)
# ---------------------------
class Game:
    def __init__(self):
        pg.init()
        pg.font.init()
        self.ui_settings = load_ui_settings()
        self.width = int(self.ui_settings["width"])
        self.height = int(self.ui_settings["height"])
        self.screen = pg.display.set_mode((self.width, self.height))
        pg.display.set_caption("Mobile FPS")
        pg.mouse.set_visible(True)
        pg.event.set_grab(False)

        self.clock = pg.time.Clock()
        self.delta_time = 1
        self.global_trigger = False
        self.global_event = pg.USEREVENT + 1
        pg.time.set_timer(self.global_event, 40)

        # game internals
        self.game_state = "menu"  # menu, difficulty, playing, paused, settings, leaderboard
        self.difficulty = "medium"
        self.start_time = 0
        self.elapsed_seconds = 0

        # joystick and touch controls
        # positions relative to screen
        left_center = (int(self.width * 0.16), int(self.height * 0.78))
        self.joystick = VirtualJoystick(left_center, outer_radius=int(self.height * 0.13),
                                       inner_radius=int(self.height * 0.055))
        shoot_rect = (self.width - int(self.width * 0.20), int(self.height * 0.72), int(self.width * 0.15),
                      int(self.width * 0.15))
        self.shoot_button = TouchButton(shoot_rect, label="SHOOT")
        self.font = pg.font.Font(None, int(self.height * 0.04))

        # UI Buttons (menu)
        b_w, b_h = int(self.width * 0.45), int(self.height * 0.10)
        cx = (self.width - b_w) // 2
        sy = int(self.height * 0.28)
        gap = int(self.height * 0.03)
        self.btn_start = Button((cx, sy, b_w, b_h), "Start New Game", fn=self.open_difficulty, font=self.font)
        self.btn_leader = Button((cx, sy + (b_h + gap), b_w, b_h), "Leaderboard", fn=self.open_leaderboard, font=self.font)
        self.btn_settings = Button((cx, sy + 2 * (b_h + gap), b_w, b_h), "Settings", fn=self.open_settings, font=self.font)
        self.btn_exit = Button((cx, sy + 3 * (b_h + gap), b_w, b_h), "Exit", fn=self.exit_game, font=self.font)

        # difficulty buttons
        db_w, db_h = int(self.width * 0.28), int(self.height * 0.10)
        dbx = (self.width - db_w) // 2
        dsy = int(self.height * 0.3)
        self.btn_easy = Button((dbx, dsy, db_w, db_h), "Easy", fn=lambda: self.start_new_game("easy"), font=self.font)
        self.btn_medium = Button((dbx, dsy + db_h + 12, db_w, db_h), "Medium", fn=lambda: self.start_new_game("medium"), font=self.font)
        self.btn_hard = Button((dbx, dsy + 2 * (db_h + 12), db_w, db_h), "Hard", fn=lambda: self.start_new_game("hard"), font=self.font)

        # in-game pause/settings
        pbw, pbh = int(self.width * 0.24), int(self.height * 0.10)
        px = (self.width - pbw) // 2
        py = int(self.height * 0.28)
        self.btn_resume = Button((px, py, pbw, pbh), "Resume", fn=self.resume_game, font=self.font)
        self.btn_gsettings = Button((px, py + pbh + 12, pbw, pbh), "Settings", fn=self.open_settings, font=self.font)
        self.btn_mainmenu = Button((px, py + 2 * (pbh + 12), pbw, pbh), "Main Menu", fn=self.back_to_menu, font=self.font)

        # settings UI (simple)
        self.volume = self.ui_settings.get("volume", 0.8)
        self.sensitivity = self.ui_settings.get("sensitivity", MOUSE_SENSITIVITY)

        # leaderboard memory
        self.leaderboard = load_leaderboard()

        # placeholder: will be set when starting gameplay
        self.map = None
        self.player = None
        self.object_renderer = None
        self.raycasting = None
        self.object_handler = None
        self.weapon = None
        self.sound = None
        self.pathfinding = None

        # small HUD
        self.hud_font = pg.font.Font(None, int(self.height * 0.035))

    # ---------------------------
    # Menu actions
    # ---------------------------
    def open_difficulty(self):
        self.game_state = "difficulty"

    def open_leaderboard(self):
        self.game_state = "leaderboard"

    def open_settings(self):
        self.game_state = "settings"

    def exit_game(self):
        pg.quit()
        sys.exit()

    def back_to_menu(self):
        # stop gameplay, go to menu
        self.game_state = "menu"

    def resume_game(self):
        if self.game_state == "paused":
            self.game_state = "playing"
            # resume timer (keep start_time unchanged)

    # ---------------------------
    # Start game & difficulty setup
    # ---------------------------
    def start_new_game(self, level):
        # apply difficulty
        self.difficulty = level
        if level == "easy":
            enemy_count = 8
        elif level == "medium":
            enemy_count = 20
        else:
            enemy_count = 32
        # initialize game world
        self.map = Map(self)
        self.player = Player(self)
        self.object_renderer = ObjectRenderer(self)
        self.raycasting = RayCasting(self)
        self.object_handler = ObjectHandler(self)
        self.object_handler.enemies = enemy_count
        # re-spawn NPCs with the new count
        self.object_handler.spawn_npc()
        self.weapon = Weapon(self)
        self.sound = Sound(self)
        self.pathfinding = PathFinding(self)
        # audio volume
        pg.mixer.music.set_volume(self.volume)
        # start timer
        self.start_time = pg.time.get_ticks()
        self.game_state = "playing"
        # ensure mouse/grab disabled for mobile
        pg.event.set_grab(False)
        pg.mouse.set_visible(True)

    # ---------------------------
    # Core loop pieces
    # ---------------------------
    def check_events(self):
        # handle events based on current game state
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.exit_game()
            if event.type == pg.KEYDOWN:
                # universal shortcuts
                if event.key == pg.K_ESCAPE:
                    if self.game_state == "playing":
                        self.game_state = "paused"
                    elif self.game_state == "paused":
                        self.game_state = "playing"
                    elif self.game_state in ("menu", "settings", "leaderboard", "difficulty"):
                        self.exit_game()

            # distribute to UI buttons in menu-like states
            if self.game_state == "menu":
                self.btn_start.handle_event(event)
                self.btn_leader.handle_event(event)
                self.btn_settings.handle_event(event)
                self.btn_exit.handle_event(event)
            elif self.game_state == "difficulty":
                self.btn_easy.handle_event(event)
                self.btn_medium.handle_event(event)
                self.btn_hard.handle_event(event)
            elif self.game_state == "leaderboard":
                # clicking anywhere returns to menu
                if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                    self.game_state = "menu"
            elif self.game_state == "settings":
                # simple settings: click left/right on top/bottom areas to change volume/sensitivity (quick)
                if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                    x, y = event.pos
                    # volume area: top-left quarter
                    if x < self.width * 0.5 and y < self.height * 0.5:
                        self.volume = min(1.0, self.volume + 0.1)
                        pg.mixer.music.set_volume(self.volume)
                    # sensitivity area: top-right quarter
                    elif x >= self.width * 0.5 and y < self.height * 0.5:
                        self.sensitivity = min(0.02, self.sensitivity + 0.0005)
                    # save quickly
                    self.ui_settings["volume"] = self.volume
                    self.ui_settings["sensitivity"] = self.sensitivity
                    save_ui_settings(self.ui_settings)

            elif self.game_state == "playing":
                # gameplay events: forward to game systems
                if event.type == self.global_event:
                    self.global_trigger = True
                # mouse/touch input for joystick/shoot button
                if event.type == pg.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        pos = event.pos
                        # joystick area
                        if self.joystick.center.distance_to(pos) < self.joystick.outer_radius * 1.2:
                            self.joystick.start(pos)
                        # shoot
                        if self.shoot_button.contains(pos):
                            self.shoot_button.pressed = True
                            # immediate shot
                            self.trigger_shoot()
                if event.type == pg.MOUSEBUTTONUP:
                    if event.button == 1:
                        pos = event.pos
                        # release joystick if it was active
                        if self.joystick.active:
                            self.joystick.end()
                        # release shoot
                        if self.shoot_button.pressed:
                            self.shoot_button.pressed = False
                if event.type == pg.MOUSEMOTION:
                    pos = event.pos
                    if self.joystick.active:
                        self.joystick.move(pos)

            elif self.game_state == "paused":
                self.btn_resume.handle_event(event)
                self.btn_gsettings.handle_event(event)
                self.btn_mainmenu.handle_event(event)

    def trigger_shoot(self):
        # map to your Player single fire behavior
        if self.player and not self.player.shot and not self.weapon.reloading:
            # play the sound and set shot/reloading flags
            try:
                self.sound.shotgun.play()
            except Exception:
                pass
            self.player.shot = True
            self.weapon.reloading = True

    def update_gameplay(self):
        # dt in seconds
        self.delta_time = max(1, self.clock.tick(FPS))
        dt_seconds = self.delta_time / 1000.0

        # joystick vector maps to movement and angle
        v = self.joystick.get_vector()
        # left/right X controls strafing and forward/back: we will map as:
        # joystick up/down => forward/back, left/right => strafe
        # also small X turns the camera slightly
        if self.player:
            # simulate key presses by adjusting player.x/y directly via movement algorithm:
            # We'll create a small temporary override: if joystick is active, change player.x/y using player's movement logic
            # use player's speed variable (PLAYER_SPEED uses delta_time within Player.movement),
            # so to avoid duplicating code we'll set synthetic pressed keys via a small wrapper:
            # Simpler: directly modify player.x/y with normalized vector and speed
            speed = PLAYER_SPEED * self.delta_time
            # note: joystick.get_vector() returns -1..1 for x and y (y positive down)
            jx = v.x
            jy = -v.y  # invert so up is positive
            # movement relative to player angle (forward/back and strafe)
            sin_a = math.sin(self.player.angle)
            cos_a = math.cos(self.player.angle)
            dx = (cos_a * jy - sin_a * jx) * speed
            dy = (sin_a * jy + cos_a * jx) * speed
            # perform collision-safe move
            self.player.check_wall_collision(dx, dy)
            # small look rotation from horizontal joystick movement
            self.player.angle += jx * 0.05 * self.sensitivity * self.delta_time
            self.player.angle %= math.tau

        # feed player single fire to NPC hit check in same tick (player.shot used by NPCs)
        # update game systems (reuse existing update flows)
        if self.player:
            self.player.recover_health()
            # call raycasting, objects, etc.
        if self.raycasting:
            self.raycasting.update()
        if self.object_handler:
            self.object_handler.update()
        if self.weapon:
            self.weapon.update()
        # note: object_renderer.draw will be called in draw()

        # update timer
        if self.start_time:
            self.elapsed_seconds = (pg.time.get_ticks() - self.start_time) // 1000

    def draw_gameplay(self):
        # draw via your existing renderer functions
        if self.object_renderer:
            self.object_renderer.draw()
        if self.weapon:
            self.weapon.draw()

        # overlay HUD: health and timer
        if self.player:
            health_txt = self.hud_font.render(f"HP: {self.player.health}", True, (255, 200, 200))
            self.screen.blit(health_txt, (12, 12))
        # timer center top
        mm = int(self.elapsed_seconds // 60)
        ss = int(self.elapsed_seconds % 60)
        timer_txt = self.hud_font.render(f"{mm:02d}:{ss:02d}", True, (230, 230, 230))
        self.screen.blit(timer_txt, (self.width // 2 - timer_txt.get_width() // 2, 12))

        # draw joystick and shoot button
        # translucent overlay for mobile control
        overlay = pg.Surface((self.width, self.height), flags=pg.SRCALPHA)
        self.joystick.draw(overlay)
        self.shoot_button.draw(overlay, font=self.font)
        self.screen.blit(overlay, (0, 0))

    # ---------------------------
    # Main loop
    # ---------------------------
    def run(self):
        while True:
            # event processing
            self.check_events()

            # clear screen for each state
            if self.game_state in ("menu", "difficulty", "settings", "leaderboard"):
                self.screen.fill((20, 20, 25))
            elif self.game_state in ("playing", "paused"):
                # gameplay rendering will clear inside object_renderer
                # but we will fill a background to avoid artifacts before renderer loads textures
                self.screen.fill((0, 0, 0))

            # state drawings and updates
            if self.game_state == "menu":
                # draw title and menu buttons
                title_font = pg.font.Font(None, int(self.height * 0.08))
                title = title_font.render("MY FPS MOBILE", True, (255, 215, 80))
                self.screen.blit(title, (self.width // 2 - title.get_width() // 2, int(self.height * 0.12)))
                self.btn_start.draw(self.screen)
                self.btn_leader.draw(self.screen)
                self.btn_settings.draw(self.screen)
                self.btn_exit.draw(self.screen)

            elif 