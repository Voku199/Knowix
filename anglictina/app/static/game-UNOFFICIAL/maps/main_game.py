import pygame
import os
import pytmx
from pytmx.util_pygame import load_pygame
from pygame.locals import *
import time
import xml.etree.ElementTree as ET


# Monkey patch pro opravu chyby v knihovně pytmx
def patched_cast_and_set_attributes(self, items):
    # Bezpečné získání atributu 'types' s fallback na prázdný slovník
    types = getattr(self.__class__, 'types', {})

    for key, value in items:
        if key in types:
            try:
                # Zkusíme převést na float a poté na int
                if types[key] is int:
                    try:
                        casted_value = int(float(value))
                    except (ValueError, TypeError):
                        casted_value = int(value)  # Fallback
                else:
                    casted_value = types[key](value)
            except (ValueError, TypeError):
                # Pokud selže, použijeme výchozí hodnotu
                if types[key] is int:
                    casted_value = 0
                elif types[key] is float:
                    casted_value = 0.0
                else:
                    casted_value = value
            setattr(self, key, casted_value)
        else:
            # Pokud klíč není v 'types', nastavíme hodnotu jako řetězec
            setattr(self, key, value)


# Aplikujeme patch
pytmx.pytmx.TiledElement._cast_and_set_attributes_from_node_items = patched_cast_and_set_attributes


# Další monkey patch pro opravu chyby s tileset atributy
def patched_tileset_init(self, parent, node):  # Opraveno: přidán parametr 'parent'
    # Nejprve zavoláme původní __init__ metodu
    pytmx.pytmx.TiledElement.__init__(self)

    # Načteme atributy a převedeme je na správné typy
    self.firstgid = int(node.attrib.get("firstgid", 0))
    self.source = node.attrib.get("source")

    # Pokud je tileset vestavěný (ne externí)
    if not self.source:
        self.name = node.attrib.get("name", "")
        self.tilewidth = int(node.attrib.get("tilewidth", 0))
        self.tileheight = int(node.attrib.get("tileheight", 0))
        self.spacing = int(node.attrib.get("spacing", 0))
        self.margin = int(node.attrib.get("margin", 0))
        self.tilecount = int(node.attrib.get("tilecount", 0))
        self.columns = int(node.attrib.get("columns", 0))

    # Zpracování vlastností
    self._set_properties(node)


# Nahradíme původní __init__ metodu pro TiledTileset
pytmx.pytmx.TiledTileset.__init__ = patched_tileset_init

# Monkey patch pro metodu reload_images v TiledMap
original_reload_images = pytmx.pytmx.TiledMap.reload_images


def patched_reload_images(self, *args, **kwargs):
    # Projdeme všechny tilesety a zajistíme, že atributy jsou číselné
    for ts in self.tilesets:
        # Pokud je některý atribut řetězec, převedeme ho na int
        if isinstance(ts.tilewidth, str):
            ts.tilewidth = int(ts.tilewidth)
        if isinstance(ts.tileheight, str):
            ts.tileheight = int(ts.tileheight)
        if isinstance(ts.spacing, str):
            ts.spacing = int(ts.spacing)
        if isinstance(ts.margin, str):
            ts.margin = int(ts.margin)

    # Zavoláme původní metodu
    return original_reload_images(self, *args, **kwargs)


# Aplikujeme patch
pytmx.pytmx.TiledMap.reload_images = patched_reload_images

# Constants
FPS = 60
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 600

# Map definitions - s absolutními cestami
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_CHUNKS = {
    "chill": {"filename": os.path.join(BASE_DIR, "chill.tmx"), "boundary": (0, 0, 480, 320)},
    "chill2": {"filename": os.path.join(BASE_DIR, "chill2.tmx"), "boundary": (480, 0, 480, 320)},
    "chill3": {"filename": os.path.join(BASE_DIR, "chill3.tmx"), "boundary": (960, 0, 480, 320)},
    "chill4": {"filename": os.path.join(BASE_DIR, "chill4.tmx"), "boundary": (1440, 0, 480, 320)},
    "chill5": {"filename": os.path.join(BASE_DIR, "chill5.tmx"), "boundary": (1920, 0, 480, 320)},
    "chill6": {"filename": os.path.join(BASE_DIR, "chill6.tmx"), "boundary": (2400, 0, 480, 320)},
    "obrovky_kamen_1": {"filename": os.path.join(BASE_DIR, "obrovky_kamen_1.tmx"), "boundary": (0, 320, 480, 320)},
    "obrovky_kamen_2": {"filename": os.path.join(BASE_DIR, "obrovky_kamen_2.tmx"), "boundary": (480, 320, 480, 320)},
    "skakat_1": {"filename": os.path.join(BASE_DIR, "skakat_1.tmx"), "boundary": (0, 640, 480, 320)},
    "skakat_2": {"filename": os.path.join(BASE_DIR, "skakat_2.tmx"), "boundary": (480, 640, 480, 320)},
    "skakat_3": {"filename": os.path.join(BASE_DIR, "skakat_3.tmx"), "boundary": (960, 640, 480, 320)},
    "skakat_4": {"filename": os.path.join(BASE_DIR, "skakat_4.tmx"), "boundary": (1440, 640, 480, 320)}
}


class MapRenderer:
    def __init__(self, filename):
        self.tmx_data = None
        self.map_surface = None
        self.width = 0
        self.height = 0
        self.filename = filename
        self.load_map(filename)

    def load_map(self, filename):
        try:
            print(f"Loading map: {filename}")
            # Zkontrolujeme existenci souboru
            if not os.path.exists(filename):
                print(f"Map file not found: {filename}")
                # Vytvoříme náhradní plochu s chybovou zprávou
                self.map_surface = pygame.Surface((480, 320), pygame.SRCALPHA)
                self.map_surface.fill((255, 0, 0, 128))
                font = pygame.font.Font(None, 24)
                text = font.render(f"File not found: {os.path.basename(filename)}", True, (255, 255, 255))
                self.map_surface.blit(text, (10, 150))
                self.width = 480
                self.height = 320
                return True

            # Načtení mapy
            self.tmx_data = load_pygame(filename)

            # Kontrola platnosti rozměrů
            map_width = max(30, int(self.tmx_data.width))
            map_height = max(20, int(self.tmx_data.height))
            tile_width = max(16, int(self.tmx_data.tilewidth))
            tile_height = max(16, int(self.tmx_data.tileheight))

            self.width = map_width * tile_width
            self.height = map_height * tile_height

            # Vytvoření plochy pro mapu
            self.map_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

            # Vykreslení všech vrstev
            for layer in self.tmx_data.visible_layers:
                if isinstance(layer, pytmx.TiledTileLayer):
                    for x, y, gid in layer:
                        tile = self.tmx_data.get_tile_image_by_gid(gid)
                        if tile:
                            # Pro animované dlaždice vezmeme první snímek
                            tile_surface = tile[0] if isinstance(tile, tuple) else tile

                            if not isinstance(tile_surface, pygame.Surface):
                                # Vytvoření náhradního dlaždice pro chybějící obrázek
                                tile_surface = pygame.Surface((tile_width, tile_height))
                                tile_surface.fill((255, 0, 255))
                                pygame.draw.rect(tile_surface, (0, 0, 0), (0, 0, tile_width, tile_height), 1)

                            self.map_surface.blit(
                                tile_surface,
                                (x * tile_width, y * tile_height)
                            )

            print(f"Map successfully loaded: {os.path.basename(filename)}")
            return True
        except Exception as e:
            print(f"Critical error loading map: {e}")
            import traceback
            traceback.print_exc()
            # Vytvoření chybové plochy
            self.map_surface = pygame.Surface((480, 320), pygame.SRCALPHA)
            self.map_surface.fill((255, 0, 0, 200))
            font = pygame.font.Font(None, 24)
            text = font.render(f"Error: {str(e)}", True, (255, 255, 255))
            self.map_surface.blit(text, (10, 150))
            self.width = 480
            self.height = 320
            return True

    def render(self, screen, offset_x=0, offset_y=0):
        if self.map_surface:
            # Pro debug: vykreslíme modrý obdélník kolem mapy
            pygame.draw.rect(screen, (0, 0, 255), (offset_x, offset_y, self.width, self.height), 2)
            screen.blit(self.map_surface, (offset_x, offset_y))
        else:
            # Červené pozadí pro chybu
            pygame.draw.rect(screen, (255, 0, 0), (offset_x, offset_y, self.width, self.height))
            # Zelený rámeček pro viditelnost
            pygame.draw.rect(screen, (0, 255, 0), (offset_x, offset_y, self.width, self.height), 3)


class ChunkManager:
    def __init__(self):
        self.loaded_chunks = {}
        self.active_chunk = "chill"
        # Načteme chill.tmx jako první mapu
        self.load_chunk(self.active_chunk, initial=True)

    def load_chunk(self, chunk_name, initial=False):
        if chunk_name in self.loaded_chunks:
            return

        map_info = MAP_CHUNKS.get(chunk_name)
        if not map_info:
            print(f"Chunk {chunk_name} not defined!")
            return

        try:
            renderer = MapRenderer(map_info["filename"])
            if renderer.map_surface:
                self.loaded_chunks[chunk_name] = {
                    "renderer": renderer,
                    "boundary": map_info["boundary"]
                }
                print(f"Loaded chunk: {chunk_name}")
                print(f"  Boundary: {map_info['boundary']}")
                print(f"  Map size: {renderer.width}x{renderer.height}")

                # Pokud je to počáteční načítání, nastavíme i aktivní chunk
                if initial:
                    self.active_chunk = chunk_name
        except Exception as e:
            print(f"Failed to load chunk {chunk_name}: {e}")

    def unload_chunk(self, chunk_name):
        if chunk_name in self.loaded_chunks:
            del self.loaded_chunks[chunk_name]
            print(f"Unloaded chunk: {chunk_name}")

    def get_current_chunk(self):
        return self.active_chunk

    def get_chunk_boundary(self, chunk_name):
        if chunk_name in self.loaded_chunks:
            return self.loaded_chunks[chunk_name]["boundary"]
        return None

    def check_chunk_transition(self, player_pos):
        current_boundary = self.get_chunk_boundary(self.active_chunk)
        if not current_boundary:
            return

        x, y, w, h = current_boundary
        px, py = player_pos

        # Kontrola přechodu do nového chunku
        for chunk_name, chunk_data in MAP_CHUNKS.items():
            # Přeskočit aktuální chunk
            if chunk_name == self.active_chunk:
                continue

            cx, cy, cw, ch = chunk_data["boundary"]

            # Kontrola, zda je hráč uvnitř tohoto chunku
            if (cx <= px <= cx + cw) and (cy <= py <= cy + ch):
                print(f"Player moved to {chunk_name}")
                self.active_chunk = chunk_name
                self.load_chunk(chunk_name)
                return

    def unload_distant_chunks(self, player_pos):
        keep_distance = 2000  # Vzdálenost pro udržení chunku

        chunks_to_unload = []
        for chunk_name in list(self.loaded_chunks.keys()):
            if chunk_name == self.active_chunk:
                continue

            boundary = self.get_chunk_boundary(chunk_name)
            if not boundary:
                continue

            cx, cy, cw, ch = boundary
            chunk_center = (cx + cw / 2, cy + ch / 2)
            distance = ((player_pos[0] - chunk_center[0]) ** 2 +
                        (player_pos[1] - chunk_center[1]) ** 2) ** 0.5

            if distance > keep_distance:
                chunks_to_unload.append(chunk_name)

        for chunk_name in chunks_to_unload:
            self.unload_chunk(chunk_name)

    def render_chunks(self, screen, camera_offset):
        # Nejprve vykreslit aktivní chunk
        if self.active_chunk in self.loaded_chunks:
            chunk_data = self.loaded_chunks[self.active_chunk]
            boundary = chunk_data["boundary"]
            renderer = chunk_data["renderer"]

            render_x = boundary[0] - camera_offset[0]
            render_y = boundary[1] - camera_offset[1]

            # Vykreslit s zvýrazněním
            renderer.render(screen, render_x, render_y)
            pygame.draw.rect(screen, (0, 255, 255),
                             (render_x, render_y, boundary[2], boundary[3]), 3)

            # Text s označením aktivního chunku
            font = pygame.font.Font(None, 28)
            text = font.render(f"ACTIVE: {self.active_chunk}", True, (0, 255, 255))
            screen.blit(text, (render_x + 10, render_y + 10))

        # Pak vykreslit ostatní načtené chunky
        for chunk_name, chunk_data in self.loaded_chunks.items():
            if chunk_name == self.active_chunk:
                continue

            boundary = chunk_data["boundary"]
            renderer = chunk_data["renderer"]

            render_x = boundary[0] - camera_offset[0]
            render_y = boundary[1] - camera_offset[1]

            if (render_x + boundary[2] > 0 and render_x < SCREEN_WIDTH and
                    render_y + boundary[3] > 0 and render_y < SCREEN_HEIGHT):
                renderer.render(screen, render_x, render_y)

                # Rámeček a text pro neaktivní chunky
                pygame.draw.rect(screen, (0, 200, 0),
                                 (render_x, render_y, boundary[2], boundary[3]), 1)

                font = pygame.font.Font(None, 24)
                text = font.render(chunk_name, True, (150, 150, 150))
                screen.blit(text, (render_x + 10, render_y + 10))


# Inicializace Pygame
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("2D Platformer Game - Chunk System")
clock = pygame.time.Clock()

# Vytvoření správce chunku
chunk_manager = ChunkManager()

# Startovní pozice hráče
# Startovní pozice hráče - uprostřed první mapy
start_x, start_y = 240, 160  # 480/2 = 240, 320/2 = 160


# Třída hráče s animacemi (zvětšená postavička)
class Player(pygame.sprite.Sprite):
    def __init__(self, x, y, chunk_manager):
        super().__init__()
        self.chunk_manager = chunk_manager

        # Vlastnosti animací
        self.animations = {}
        self.current_animation = "idle"
        self.frame_index = 0
        self.frame_timer = 0
        self.animation_speed = 0.1  # sekundy mezi snímky
        self.facing_right = True
        self.character_scale = 2.0  # Zvětšení postavičky na dvojnásobnou velikost

        # Načtení animací
        self.load_animations()

        # Nastavení počátečního obrázku
        if self.animations.get(self.current_animation):
            self.image = self.animations[self.current_animation][0]
            self.rect = self.image.get_rect(center=(x, y))
        else:
            # Záložní obrázek, pokud se animace nenačtou
            self.image = pygame.Surface((60, 100))  # Zvětšený základní obdélník
            self.image.fill((0, 255, 0))
            self.rect = self.image.get_rect(center=(x, y))

        # Vlastnosti pohybu
        self.velocity_x = 0
        self.velocity_y = 0
        self.speed = 300
        self.jump_strength = -500
        self.gravity = 1500
        self.on_ground = False
        self.world_pos = [x, y]

    def load_animations(self):
        scale = self.character_scale
        animation_base_path = os.path.join(BASE_DIR, "Samurai")

        # Funkce pro načítání a škálování obrázků
        def load_image(path):
            try:
                img = pygame.image.load(path).convert_alpha()
                new_width = int(img.get_width() * scale)
                new_height = int(img.get_height() * scale)
                return pygame.transform.scale(img, (new_width, new_height))
            except pygame.error as e:
                print(f"Error loading {path}: {e}")
                # Záložní obdélník
                surf = pygame.Surface((int(64 * scale), int(64 * scale)), pygame.SRCALPHA)
                pygame.draw.rect(surf, (255, 0, 0), (0, 0, 64 * scale, 64 * scale), 1)
                return surf

        # Načtení animací
        try:
            self.animations["idle"] = [
                load_image(os.path.join(animation_base_path, "Idle", "idle_01.png")),
                load_image(os.path.join(animation_base_path, "Idle", "idle_02.png")),
                load_image(os.path.join(animation_base_path, "Idle", "idle_03.png")),
            ]
        except Exception:
            self.animations["idle"] = [pygame.Surface((100, 100))]  # Zvětšený fallback

        try:
            self.animations["run"] = [
                load_image(os.path.join(animation_base_path, "Run", "run_01.png")),
                load_image(os.path.join(animation_base_path, "Run", "run_02.png")),
                load_image(os.path.join(animation_base_path, "Run", "run_03.png")),
                load_image(os.path.join(animation_base_path, "Run", "run_04.png")),
                load_image(os.path.join(animation_base_path, "Run", "run_05.png")),
                load_image(os.path.join(animation_base_path, "Run", "run_06.png")),
            ]
        except Exception:
            self.animations["run"] = self.animations["idle"]

        try:
            self.animations["jump"] = [
                load_image(os.path.join(animation_base_path, "Jump", "jump_01.png")),
                load_image(os.path.join(animation_base_path, "Jump", "jump_02.png")),
                load_image(os.path.join(animation_base_path, "Jump", "jump_03.png")),
                load_image(os.path.join(animation_base_path, "Jump", "jump_04.png")),
                load_image(os.path.join(animation_base_path, "Jump", "jump_05.png")),
            ]
        except Exception:
            self.animations["jump"] = self.animations["idle"]

    def update_animation(self, dt):
        # Kontrola, zda máme animace pro aktuální stav
        if self.current_animation not in self.animations:
            return

        frames = self.animations[self.current_animation]
        if not frames:
            return

        # Aktualizace časovače
        self.frame_timer += dt

        # Změna snímku, pokud uplynul dostatečný čas
        if self.frame_timer >= self.animation_speed:
            self.frame_timer = 0
            self.frame_index = (self.frame_index + 1) % len(frames)

        # Získání aktuálního snímku
        frame = frames[self.frame_index]

        # Otočení podle směru
        if not self.facing_right:
            frame = pygame.transform.flip(frame, True, False)

        # Uložení staré pozice pro obnovení
        old_center = self.rect.center

        # Aktualizace obrázku
        self.image = frame
        self.rect = self.image.get_rect()
        self.rect.center = old_center

    def handle_input(self, keys):
        self.velocity_x = 0

        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.velocity_x = -self.speed
            self.facing_right = False
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.velocity_x = self.speed
            self.facing_right = True

        if (keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]) and self.on_ground:
            self.velocity_y = self.jump_strength
            self.on_ground = False
            self.current_animation = "jump"
            self.frame_index = 0
            self.frame_timer = 0

    def update(self, dt):
        keys = pygame.key.get_pressed()
        self.handle_input(keys)

        # Aplikace gravitace
        self.velocity_y += self.gravity * dt

        # Aktualizace pozice v globálním světě
        self.world_pos[0] += self.velocity_x * dt
        self.world_pos[1] += self.velocity_y * dt

        # Aktualizace rect pro vykreslování
        self.rect.x = self.world_pos[0]
        self.rect.y = self.world_pos[1]

        # Dynamické určení země na základě aktuálního chunku
        current_chunk = self.chunk_manager.get_chunk_boundary(self.chunk_manager.active_chunk)
        if current_chunk:
            # Zem je na spodku aktuálního chunku
            ground_level = current_chunk[1] + current_chunk[3] - 10  # 10 pixelů nad spodkem

            if self.world_pos[1] >= ground_level:
                self.world_pos[1] = ground_level
                self.rect.y = ground_level
                self.velocity_y = 0
                self.on_ground = True
            else:
                self.on_ground = False
        else:
            # Fallback pro případ, že chunk není načten
            if self.world_pos[1] >= 550:
                self.world_pos[1] = 550
                self.rect.y = 550
                self.velocity_y = 0
                self.on_ground = True
            else:
                self.on_ground = False

        # Aktualizace animace podle pohybu
        if not self.on_ground:
            if self.current_animation != "jump":
                self.current_animation = "jump"
                self.frame_index = 0
                self.frame_timer = 0
        elif abs(self.velocity_x) > 1:
            if self.current_animation != "run":
                self.current_animation = "run"
                self.frame_index = 0
                self.frame_timer = 0
        else:
            if self.current_animation != "idle":
                self.current_animation = "idle"
                self.frame_index = 0
                self.frame_timer = 0

        # Aktualizace animace
        self.update_animation(dt)

        # Omezení pohybu ve světě (volitelné)
        # self.world_pos[0] = max(0, min(self.world_pos[0], 6000))
        # self.world_pos[1] = max(0, min(self.world_pos[1], 1800))


# Vytvoření hráče
player = Player(start_x, start_y, chunk_manager)
game_objects = pygame.sprite.Group()
game_objects.add(player)

# Hlavní herní smyčka
running = True
last_time = pygame.time.get_ticks() / 1000

while running:
    current_time = pygame.time.get_ticks() / 1000
    dt = current_time - last_time
    last_time = current_time
    dt = min(dt, 0.033)  # Omezení dt pro stabilitu

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == KEYDOWN:
            if event.key == K_ESCAPE:
                running = False

    # Aktualizace herních objektů
    game_objects.update(dt)

    # Kontrola přechodu mezi chunky
    chunk_manager.check_chunk_transition(player.world_pos)

    # Uvolnění vzdálených chunků
    chunk_manager.unload_distant_chunks(player.world_pos)

    # Vyčištění obrazovky
    screen.fill((50, 50, 100))  # Tmavě modré pozadí

    # Výpočet pozice kamery
    camera_offset = [
        player.world_pos[0] - SCREEN_WIDTH // 2,
        player.world_pos[1] - SCREEN_HEIGHT // 2
    ]

    # Pro debug: dočasně fixní kamera
    # camera_offset = [0, 0]

    # Vykreslení chunků
    chunk_manager.render_chunks(screen, camera_offset)

    # Vykreslení objektů s korekcí kamery
    for obj in game_objects:
        # Nakreslíme postavu s červeným rámečkem pro lepší viditelnost
        screen.blit(
            obj.image,
            (obj.rect.x - camera_offset[0], obj.rect.y - camera_offset[1])
        )
        # Červený rámeček kolem postavy
        pygame.draw.rect(
            screen,
            (255, 0, 0),
            (obj.rect.x - camera_offset[0],
             obj.rect.y - camera_offset[1],
             obj.rect.width,
             obj.rect.height),
            2
        )

    # Vykreslení debug informací
    font = pygame.font.Font(None, 24)
    debug_text = [
        f"Position: {player.world_pos[0]:.1f}, {player.world_pos[1]:.1f}",
        f"Chunk: {chunk_manager.get_current_chunk()}",
        f"Loaded chunks: {len(chunk_manager.loaded_chunks)}",
        f"FPS: {clock.get_fps():.1f}",
        f"Animation: {player.current_animation}",
        f"Frame: {player.frame_index}",
        f"Camera: {camera_offset[0]:.1f}, {camera_offset[1]:.1f}"
    ]

    for i, text in enumerate(debug_text):
        text_surface = font.render(text, True, (255, 255, 255))
        screen.blit(text_surface, (10, 10 + i * 25))

    # Vykreslit osu X a Y pro lepší orientaci
    pygame.draw.line(screen, (255, 0, 0), (0, SCREEN_HEIGHT // 2), (SCREEN_WIDTH, SCREEN_HEIGHT // 2), 1)
    pygame.draw.line(screen, (0, 255, 0), (SCREEN_WIDTH // 2, 0), (SCREEN_WIDTH // 2, SCREEN_HEIGHT), 1)

    # Vykreslit střed obrazovky
    pygame.draw.circle(screen, (255, 255, 0), (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2), 5)

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
