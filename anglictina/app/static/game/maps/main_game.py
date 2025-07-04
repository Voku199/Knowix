import pygame
import pyscroll
import os
from pytmx.util_pygame import load_pygame
from pygame.locals import *
import time

# Constants
FPS = 60
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 600


class Animation:
    def __init__(self, frames, speed=0.1, loop=True):
        self.frames = frames
        self.speed = speed
        self.loop = loop
        self.current_frame = 0
        self.done = False
        self.last_update = 0

    def update(self, dt):
        now = pygame.time.get_ticks() / 1000
        if now - self.last_update > self.speed:
            self.last_update = now
            self.current_frame = (self.current_frame + 1) % len(self.frames)
            if not self.loop and self.current_frame == 0:
                self.done = True
                self.current_frame = len(self.frames) - 1
        return self.frames[int(self.current_frame)]

    def reset(self):
        self.current_frame = 0
        self.done = False

    @property
    def current_image(self):
        return self.frames[int(self.current_frame)]


class MapRenderer:
    def __init__(self, filename):
        self.tmx_data = None
        self.map_surface = None
        self.load_map(filename)

    def load_map(self, filename):
        try:
            self.tmx_data = load_pygame(filename)
            print(f"Map loaded: {filename}")
            print(f"Size: {self.tmx_data.width}x{self.tmx_data.height} tiles")
            print(f"Tile size: {self.tmx_data.tilewidth}x{self.tmx_data.tileheight}")

            # Vytvoříme povrch pro mapu
            self.map_surface = pygame.Surface(
                (self.tmx_data.width * self.tmx_data.tilewidth,
                 self.tmx_data.height * self.tmx_data.tileheight)
            )

            # Vykreslíme všechny vrstvy na povrch mapy
            for layer in self.tmx_data.visible_layers:
                if hasattr(layer, 'data'):
                    for x, y, gid in layer:
                        tile = self.tmx_data.get_tile_image_by_gid(gid)
                        if tile:
                            self.map_surface.blit(
                                tile,
                                (x * self.tmx_data.tilewidth,
                                 y * self.tmx_data.tileheight)
                            )
            return True

        except Exception as e:
            print(f"Error loading map: {e}")
            import traceback
            traceback.print_exc()
            return False

    def render(self, screen, camera_offset=(0, 0)):
        if self.map_surface:
            # Získáme rozměry obrazovky a mapy
            screen_width, screen_height = screen.get_size()
            map_width = self.map_surface.get_width()
            map_height = self.map_surface.get_height()

            # Vypočítáme poměr škálování
            scale_x = screen_width / map_width
            scale_y = screen_height / map_height
            scale = max(scale_x, scale_y)  # Použijeme větší škálu, aby mapa vyplnila celou obrazovku

            # Vytvoříme škálovaný povrch
            scaled_surface = pygame.transform.scale(
                self.map_surface,
                (int(map_width * scale), int(map_height * scale))
            )

            # Vykreslíme vycentrovanou mapu
            screen.blit(
                scaled_surface,
                (screen_width // 2 - scaled_surface.get_width() // 2,
                 screen_height // 2 - scaled_surface.get_height() // 2)
            )


# Inicializace Pygame a vytvoření okna
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("2D Platformer Game")

# Načtení mapy
map_path = "chill.tmx"
print(f"Loading map: {os.path.abspath(map_path)}")
map_renderer = MapRenderer(map_path)

# Výchozí pozice hráče
start_x, start_y = 15.8182, 287.0

# Pokud máme načtenou mapu, zkusíme najít spawn bod
if map_renderer.tmx_data:
    for obj in map_renderer.tmx_data.objects:
        if obj.name == "spawn":
            start_x, start_y = obj.x, obj.y
            print(f"Found spawn point at: {start_x}, {start_y}")
            break

# Vytvoříme skupinu pro objekty ve hře
game_objects = pygame.sprite.Group()
clock = pygame.time.Clock()


# Simple falling image class
class FallingImage(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()

        # Animation properties
        self.animations = {}
        self.current_animation = "idle"
        self.frame_index = 0
        self.frame_timer = 0
        self.animation_direction = 1  # 1 = forward, -1 = backward
        self.frame_speed = 0.1  # ms per frame (1000ms = 1 FPS)
        self.facing_right = True
        self.character_scale = 3.0  # Scale factor for the character

        # Create a transparent surface for the character
        # self.image = pygame.Surface((64, 64), pygame.SRCALPHA)
        # self.rect = self.image.get_rect()
        # self.rect.midbottom = (x, y)

        # Load all animations
        self.load_animations()

        # Set initial frame
        if self.animations and self.animations.get("idle"):
            self.image = self.animations["idle"][0]
            self.rect = self.image.get_rect(midbottom=(x, y))

        # Movement properties
        self.velocity_x = 0
        self.velocity_y = 0
        self.speed = 150
        self.jump_strength = -400
        self.gravity = 800
        self.on_ground = False
        # Set ground level to a very high value to prevent pushing character down
        self.ground_level = 575  # Large value to effectively disable ground pushing

    def load_animations(self):
        # Scale factor for the character
        scale = self.character_scale

        # Load and scale your custom images
        def load_and_scale_image(path):
            try:
                img = pygame.image.load(path).convert_alpha()
                # Scale the image while maintaining aspect ratio
                new_width = int(img.get_width() * scale)
                new_height = int(img.get_height() * scale)
                return pygame.transform.scale(img, (new_width, new_height))
            except pygame.error as e:
                print(f"Error loading {path}: {e}")
                # Create a placeholder if image loading fails
                surf = pygame.Surface((int(64 * scale), int(64 * scale)), pygame.SRCALPHA)
                pygame.draw.rect(surf, (255, 0, 0), (0, 0, 64 * scale, 64 * scale), 1)
                return surf

        # Load idle frames
        self.animations["idle"] = [
            load_and_scale_image("./Samurai/Idle/idle_01.png"),
            load_and_scale_image("./Samurai/Idle/idle_02.png"),
            load_and_scale_image("./Samurai/Idle/idle_03.png"),
        ]

        # Load run frames (if available)
        try:
            self.animations["run"] = [
                load_and_scale_image("./Samurai/Run/run_01.png"),
                load_and_scale_image("./Samurai/Run/run_02.png"),
                load_and_scale_image("./Samurai/Run/run_03.png"),
                load_and_scale_image("./Samurai/Run/run_04.png"),
                load_and_scale_image("./Samurai/Run/run_05.png"),
                load_and_scale_image("./Samurai/Run/run_06.png"),
            ]
        except:
            self.animations["run"] = self.animations["idle"]  # Fallback to idle if run frames not found

        # Create a simple jump frame (or load if available)
        try:
            self.animations["jump"] = [
                load_and_scale_image("./Samurai/Jump/jump_01.png"),
                load_and_scale_image("./Samurai/Jump/jump_02.png"),
                load_and_scale_image("./Samurai/Jump/jump_03.png"),
                load_and_scale_image("./Samurai/Jump/jump_04.png"),
                load_and_scale_image("./Samurai/Jump/jump_05.png"),
                load_and_scale_image("./Samurai/Jump/jump_06.png"),
                load_and_scale_image("./Samurai/Jump/jump_07.png"),
            ]
        except:
            # Create a simple jump placeholder
            jump_surf = pygame.Surface((int(64 * scale), int(64 * scale)), pygame.SRCALPHA)
            pygame.draw.rect(jump_surf, (255, 100, 100), (20 * scale, 10 * scale, 24 * scale, 50 * scale))
            pygame.draw.circle(jump_surf, (255, 100, 100), (32 * scale, 8 * scale), 12 * scale)
            self.animations["jump"] = [jump_surf]

    def scale_frame(self, frame, target_width, target_height):
        """Scale frame to target size while maintaining aspect ratio"""
        # Get original dimensions
        original_width = frame.get_width()
        original_height = frame.get_height()

        # Calculate aspect ratio
        aspect_ratio = original_width / original_height

        # Calculate new dimensions
        if original_width > original_height:
            new_width = target_width
            new_height = int(target_width / aspect_ratio)
        else:
            new_height = target_height
            new_width = int(target_height * aspect_ratio)

        # Scale the frame
        scaled_frame = pygame.transform.scale(frame, (new_width, new_height))

        # Create a transparent surface of the target size
        result = pygame.Surface((target_width, target_height), pygame.SRCALPHA)

        # Center the scaled frame on the result surface
        x = (target_width - new_width) // 2
        y = target_height - new_height  # Align to bottom

        # Blit the scaled frame onto the result
        result.blit(scaled_frame, (x, y))
        return result

    def update_animation(self, dt):
        """Aktualizuje animaci podle času s ping-pong efektem (0→1→2→1→0)"""
        frames = self.animations.get(self.current_animation, [])
        if not frames:
            print(f"No frames for animation: {self.current_animation}")
            return

        # Přidání uplynulého času k časovači
        self.frame_timer += dt * 1000  # převod na milisekundy

        # Kontrola, zda je čas na další snímek
        if self.frame_timer >= self.frame_speed:
            self.frame_timer = 0

            # Pokud jsme na konci animace, začneme se vracet
            if self.frame_index >= len(frames) - 1:
                self.animation_direction = -1  # Jdeme zpět
            # Pokud jsme na začátku animace, jdeme zase dopředu
            elif self.frame_index <= 0:
                self.animation_direction = 1  # Jdeme dopředu

            # Aktualizace indexu
            self.frame_index += self.animation_direction
            # print(f"Updating frame to {self.frame_index} for {self.current_animation}")

        # Vždy aktualizovat aktuální snímek
        frame = frames[self.frame_index].copy()

        # Otočení obrázku podle směru
        if not self.facing_right:
            frame = pygame.transform.flip(frame, True, False)

        # Uložení aktuální pozice
        old_bottom = self.rect.bottom if hasattr(self, 'rect') else 0
        old_centerx = self.rect.centerx if hasattr(self, 'rect') else 0

        # Aktualizace obrázku
        self.image = frame
        self.rect = self.image.get_rect()

        # Obnovení pozice
        if hasattr(self, 'rect'):
            self.rect.bottom = old_bottom
            self.rect.centerx = old_centerx

    def handle_input(self, keys):
        # Reset horizontal movement
        self.velocity_x = 0

        # Handle left/right movement
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.velocity_x = -self.speed
            self.facing_right = False
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.velocity_x = self.speed
            self.facing_right = True

        # Handle jump
        if (keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]) and self.on_ground:
            self.velocity_y = self.jump_strength
            self.on_ground = False

    def update(self, dt):
        # Zpracování vstupu
        keys = pygame.key.get_pressed()
        self.handle_input(keys)

        # Aplikace gravitace a pohybu
        self.velocity_y += self.gravity * dt
        self.rect.x += self.velocity_x * dt
        self.rect.y += self.velocity_y * dt

        # Nastavení rychlosti animace (v sekundách mezi snímky)
        if not self.on_ground:
            self.frame_speed = 140  # 5 FPS pro skok (1/5 = 0.2s)
        elif abs(self.velocity_x) > 1:
            self.frame_speed = 85  # ~12.5 FPS pro běh (1/12.5 = 0.08s)
        else:
            self.frame_speed = 130  # ~3.3 FPS pro idle (1/3.3 ≈ 0.3s)

        # Kolize se zemí
        was_on_ground = self.on_ground
        if self.rect.bottom >= self.ground_level:
            self.rect.bottom = self.ground_level
            self.velocity_y = 0
            self.on_ground = True
            # Reset jump state only when landing, not every frame
            if not was_on_ground and self.current_animation == "jump":
                self.current_animation = "idle"
                self.frame_index = 0
                self.frame_timer = 0
        else:
            self.on_ground = False

        # Aktualizace stavu animace
        if not self.on_ground:
            new_animation = "jump" if "jump" in self.animations else "idle"
        elif abs(self.velocity_x) > 1:
            new_animation = "run"
        else:
            new_animation = "idle"

        # Pokud se změnila animace, resetuj čítače
        if new_animation != self.current_animation:
            self.current_animation = new_animation
            self.frame_index = 0
            self.frame_timer = 0
            print(f"Animation changed to: {self.current_animation}")

        # Update the animation frames
        self.update_animation(dt)

        # Keep on screen
        if self.rect.left < 0:
            self.rect.left = 0
        elif self.rect.right > screen.get_width():
            self.rect.right = screen.get_width()

        if self.rect.top < 0:
            self.rect.top = 0
            self.velocity_y = 0

        # Debug info
        print(
            f"Pos Y: {self.rect.bottom}, Vel Y: {self.velocity_y:.1f}, On ground: {self.on_ground}, Frame: {self.frame_index}, Anim: {self.current_animation}",
            end='\r')


# Create player and add to game objects
player = FallingImage(start_x, start_y)
game_objects = pygame.sprite.Group()
game_objects.add(player)

# Hlavní smyčka
running = True
last_time = pygame.time.get_ticks() / 1000

# Camera offset for following the player
camera_offset = [5, 5]

while running:
    current_time = pygame.time.get_ticks() / 1000
    dt = current_time - last_time
    last_time = current_time

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == KEYDOWN:
            if event.key == K_ESCAPE:
                running = False

    # Update all game objects
    game_objects.update(dt)

    # Vykreslení
    screen.fill((0, 0, 0))  # Černé pozadí

    # Vykreslíme mapu s offsetem kamery
    camera_offset = [0, 0]
    if map_renderer.tmx_data:
        camera_offset = [
            player.rect.centerx - SCREEN_WIDTH // 2,
            player.rect.centery - SCREEN_HEIGHT // 2
        ]

        # Omezení kamery na hranice mapy
        map_width = map_renderer.tmx_data.width * map_renderer.tmx_data.tilewidth
        map_height = map_renderer.tmx_data.height * map_renderer.tmx_data.tileheight

        camera_offset[0] = max(0, min(camera_offset[0], map_width - SCREEN_WIDTH))
        camera_offset[1] = max(0, min(camera_offset[1], map_height - SCREEN_HEIGHT))

        map_renderer.render(screen, camera_offset)

    # Vykreslíme všechny objekty s přihlédnutím k offsetu kamery
    for obj in game_objects:
        screen.blit(obj.image, (obj.rect.x - camera_offset[0], obj.rect.y - camera_offset[1]))

    # Debug info
    font = pygame.font.Font(None, 24)
    debug_text = f"Pozice: {player.rect.x:.1f}, {player.rect.y:.1f} | FPS: {clock.get_fps():.1f}"
    debug_surface = font.render(debug_text, True, (255, 255, 255), (0, 0, 0))
    screen.blit(debug_surface, (10, 10))

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
