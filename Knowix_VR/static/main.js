import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
import {VRButton} from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/webxr/VRButton.js';
import {
    XRControllerModelFactory
} from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/webxr/XRControllerModelFactory.js';

// Rychlá diagnostika: když se nic nezobrazuje, ať je aspoň vidět, že se JS spustil.
console.log('[Knowix_VR] main.js loaded');
if (!('WebGLRenderingContext' in window)) {
    document.body.innerHTML = '<pre>WebGL není v tomto prohlížeči dostupné.</pre>';
}

let scene, camera, renderer;

// Controllers (levá + pravá ruka)
let controllerL, controllerR;
let gripL, gripR;

// --- App state ---
const AppState = Object.freeze({LOBBY: 'lobby', GAME: 'game'});
let state = AppState.LOBBY;

// --- Laser + raycast ---
const raycaster = new THREE.Raycaster();
const tempMatrix = new THREE.Matrix4();

// Laser má být krátký (teď cca 2m)
const LASER_LENGTH = 2.0;
let laserLineL, laserLineR;
let hovered = null;
let hoveredBy = null; // 'L' | 'R' | null

// --- Lobby UI ---
let lobbyGroup;
let interactables = [];

// --- Game ---
let gameGroup;
let wordCubes = [];
let score = 0;
let spawnAccumulator = 0;
let scoreSprite = null;

// Lanes (pruhy)
const LANE_COUNT = Math.min(6, 6);
const LANE_WIDTH = 0.35;
const LANE_GAP = 0.12;
const LANES_TOTAL_WIDTH = LANE_COUNT * LANE_WIDTH + (LANE_COUNT - 1) * LANE_GAP;
const LANE_START_X = -LANES_TOTAL_WIDTH / 2 + LANE_WIDTH / 2;

// Cube můžeš rozbít až když je blízko u hráče.
const BREAKABLE_Z_MIN = -1.5;
const BREAKABLE_Z_MAX = 0.9;

// --- Desktop fallback ---
const mouseNDC = new THREE.Vector2();
let lastPointerEvent = null;

// --- Songs / Audio / Lyrics ---
let songs = [];
let selectedSong = null; // {id,title,duration_seconds,logo_url,audio_url,lrc_url}
let audioEl = null;
let lyrics = null; // { wordEvents: Array<{t:number,w:string}>, duration:number|null }
let lyricSprite = null;
let currentLyricIndex = -1;

// --- Lyrics timing + cube sequence ---
// Pokud jsou lyrics "napřed" (zobrazují se moc brzy), nastav kladný offset.
// Defaultně dáváme ~1.2s, protože jsi psal, že to typicky ujíždí o 1-2s.
let lyricTimeOffsetSec = 1.2;
let lyricAutocalibrated = false;

let wordSequence = []; // pole slov v pořadí pro spawn kostek
let nextSpawnWordIndex = 0;
let currentLineIndex = 0;
let lineEvents = null; // { lineEvents: Array<{t:number, words:string[]}> }

init();
animate();

async function init() {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x101010);
    scene.fog = null;

    camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.set(0, 1.6, 3);

    renderer = new THREE.WebGLRenderer({antialias: true});
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.xr.enabled = true;
    document.body.appendChild(renderer.domElement);
    document.body.appendChild(VRButton.createButton(renderer));

    console.log('[Knowix_VR] renderer ready', renderer);

    // světlo
    const light = new THREE.HemisphereLight(0xffffff, 0x444444, 1.0);
    light.position.set(0, 1, 0);
    scene.add(light);

    // přednačti song metadata (logo/audio/lrc/délka) z backendu
    try {
        const res = await fetch('/api/vr/songs');
        const data = await res.json();
        songs = Array.isArray(data?.songs) ? data.songs : [];
    } catch (e) {
        console.warn('[Knowix_VR] failed to load songs list', e);
        songs = [];
    }

    setupControllers();

    // skupiny pro přehlednost
    lobbyGroup = new THREE.Group();
    lobbyGroup.name = 'lobbyGroup';
    scene.add(lobbyGroup);

    gameGroup = new THREE.Group();
    gameGroup.name = 'gameGroup';
    scene.add(gameGroup);

    enterLobby();

    // desktop fallback
    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('pointerdown', onPointerDown);

    window.addEventListener('resize', onWindowResize);
}

function setupControllers() {
    const controllerModelFactory = new XRControllerModelFactory();

    // Levá ruka (index 0)
    controllerL = renderer.xr.getController(0);
    controllerL.userData.hand = 'L';
    controllerL.addEventListener('selectstart', () => handleSelect('L'));
    scene.add(controllerL);

    gripL = renderer.xr.getControllerGrip(0);
    gripL.add(controllerModelFactory.createControllerModel(gripL));
    scene.add(gripL);

    // Pravá ruka (index 1)
    controllerR = renderer.xr.getController(1);
    controllerR.userData.hand = 'R';
    controllerR.addEventListener('selectstart', () => handleSelect('R'));
    scene.add(controllerR);

    gripR = renderer.xr.getControllerGrip(1);
    gripR.add(controllerModelFactory.createControllerModel(gripR));
    scene.add(gripR);

    // Lasery a "sabery" pro obě ruce
    laserLineL = createLaserLine(LASER_LENGTH, 0xff2244); // červená = levá
    controllerL.add(laserLineL);

    laserLineR = createLaserLine(LASER_LENGTH, 0x3388ff); // modrá = pravá
    controllerR.add(laserLineR);

    const saberL = createSaber(0xff2244); // červený pruh
    saberL.position.set(0, 0, -0.05);
    controllerL.add(saberL);

    const saberR = createSaber(0x3388ff); // modrý pruh
    saberR.position.set(0, 0, -0.05);
    controllerR.add(saberR);
}

function createLaserLine(length, color) {
    const points = [new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -length)];
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({color});
    const line = new THREE.Line(geometry, material);
    line.name = 'laserLine';
    return line;
}

function enterLobby() {
    state = AppState.LOBBY;
    score = 0;

    // zastavit případně běžící audio / lyrics
    stopSongPlayback();

    // hezčí "lobby" look
    scene.background = new THREE.Color(0x02030a);
    scene.fog = new THREE.Fog(0x02030a, 2, 22);

    // vyčistit scénu
    clearGroup(lobbyGroup);
    clearGroup(gameGroup);
    wordCubes = [];
    interactables = [];
    setHovered(null, null);

    // jemná gradient obloha
    const skyTex = createSkyGradientTexture({top: '#0b1a3a', mid: '#050616', bottom: '#000000'});
    scene.background = skyTex;

    // podlaha s jemným leskem
    const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(22, 22),
        new THREE.MeshStandardMaterial({color: 0x0f1426, metalness: 0.1, roughness: 0.9})
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0;
    lobbyGroup.add(floor);

    // titulky
    const title = createTextBillboard('KNOWIX VR', {
        bg: '#000000',
        fg: '#ffffff',
        fontSize: 68,
        width: 900,
        height: 240
    });
    title.position.set(0, 2.05, -2);
    title.scale.set(1.8, 0.6, 1);
    lobbyGroup.add(title);

    const hint = createTextBillboard('Vyber písničku.\nBude se zobrazovat 1 slovo podle LRC.', {
        bg: '#000000',
        fg: '#cfd6ff',
        fontSize: 30,
        width: 900,
        height: 220
    });
    hint.position.set(0, 1.62, -2);
    hint.scale.set(1.6, 0.55, 1);
    lobbyGroup.add(hint);

    // --- Song cards (2 písničky) ---
    const cards = createSongCards(songs);
    for (const c of cards) {
        interactables.push(c);
        lobbyGroup.add(c);
    }
}

function createSongCards(songList) {
    const items = (Array.isArray(songList) ? songList : []).slice(0, 2);

    // když se nepodaří načíst API, uděláme aspoň fallback UI
    const fallback = [
        {
            id: 'my_kind_of_woman',
            title: 'My Kind of Woman',
            duration_seconds: null,
            logo_url: '/static/music/My_kind_of_woman.jpeg'
        },
        {id: 'runaway', title: 'Runaway', duration_seconds: null, logo_url: '/static/music/Runaway.jpeg'},
    ];

    const list = items.length ? items : fallback;

    const out = [];
    const spacing = 0.95;
    const startX = -((list.length - 1) * spacing) / 2;

    for (let i = 0; i < list.length; i++) {
        const s = list[i];
        const card = createSongCard(s);
        card.position.set(startX + i * spacing, 1.35, -1.55);
        card.rotation.y = 0.0;

        card.userData.onSelect = () => {
            console.log('[Knowix_VR] selected song id=', s.id);
            selectedSong = s;
            startGameWithSong(s);
        };

        out.push(card);
    }

    return out;
}

function createSongCard(song) {
    const group = new THREE.Group();
    group.name = `song:${song?.id ?? 'unknown'}`;

    // panel (větší + zaoblený dojem přes barvy / highlight)
    const panel = new THREE.Mesh(
        new THREE.BoxGeometry(0.90, 0.70, 0.05),
        new THREE.MeshStandardMaterial({color: 0x121a33, roughness: 0.65, metalness: 0.15})
    );
    panel.userData.baseColor = panel.material.color.clone();
    panel.userData.hoverColor = new THREE.Color(0x243c7a);
    group.add(panel);

    // jemný "rámeček" (druhá deska)
    const frame = new THREE.Mesh(
        new THREE.BoxGeometry(0.92, 0.72, 0.01),
        new THREE.MeshStandardMaterial({color: 0x0a0f22, roughness: 0.9, metalness: 0.0})
    );
    frame.position.z = -0.03;
    group.add(frame);

    // logo
    const logoPlane = new THREE.Mesh(
        new THREE.PlaneGeometry(0.80, 0.44),
        new THREE.MeshBasicMaterial({color: 0x111111})
    );
    logoPlane.position.set(0, 0.10, 0.03);
    group.add(logoPlane);

    const loader = new THREE.TextureLoader();
    if (song?.logo_url) {
        loader.load(
            song.logo_url,
            (tex) => {
                tex.colorSpace = THREE.SRGBColorSpace;
                logoPlane.material.map = tex;
                logoPlane.material.needsUpdate = true;
            },
            undefined,
            (err) => console.warn('[Knowix_VR] logo load failed', song.logo_url, err)
        );
    }

    const title = createTextBillboard(song?.title ?? 'Unknown', {
        bg: '#000000',
        fg: '#ffffff',
        fontSize: 36,
        width: 700,
        height: 180
    });
    title.position.set(0, -0.21, 0.035);
    title.scale.set(1.15, 0.36, 1);
    group.add(title);

    const durLabel = createTextBillboard(formatDuration(song?.duration_seconds), {
        bg: '#000000',
        fg: '#b9c2ff',
        fontSize: 30,
        width: 700,
        height: 150
    });
    durLabel.position.set(0, -0.37, 0.035);
    durLabel.scale.set(1.05, 0.28, 1);
    group.add(durLabel);

    group.userData.hitTarget = panel;
    group.userData.onSelect = null;

    return group;
}

function formatDuration(seconds) {
    if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return 'Délka: ?';
    const s = Math.round(seconds);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `Délka: ${m}:${String(r).padStart(2, '0')}`;
}

function startGameWithSong(song) {
    // hezčí "vybráno" feedback: krátká animace scale
    try {
        if (hovered) {
            hovered.scale.set(1.12, 1.12, 1.12);
            setTimeout(() => {
                try {
                    hovered?.scale?.set?.(1, 1, 1);
                } catch (_) {
                }
            }, 180);
        }
    } catch (_) {
    }

    enterGame();
    startSongPlayback(song).catch((e) => console.warn('[Knowix_VR] startSongPlayback failed', e));
}

async function startSongPlayback(song) {
    stopSongPlayback();

    // reset timing/sequence
    lyricAutocalibrated = false;
    currentLyricIndex = -1;
    currentLineIndex = 0;
    wordSequence = [];
    nextSpawnWordIndex = 0;
    lineEvents = null;

    if (!song?.audio_url) {
        console.warn('[Knowix_VR] song missing audio_url');
        return;
    }

    audioEl = new Audio(song.audio_url);
    audioEl.preload = 'auto';
    audioEl.crossOrigin = 'anonymous';

    // LRC načteme dopředu
    lyrics = null;

    if (song?.lrc_url) {
        try {
            const lrcText = await fetch(song.lrc_url).then(r => r.text());
            const parsed = parseLrcToWordEvents(lrcText);
            lyrics = parsed;
            lineEvents = parseLrcToLineEvents(lrcText);

            // sekvence slov pro kostky = všechna slova v pořadí výskytu
            wordSequence = (lyrics.wordEvents || []).map(e => e.w).filter(Boolean);
            nextSpawnWordIndex = 0;

            console.log('[Knowix_VR] lyrics words=', lyrics.wordEvents.length);
        } catch (e) {
            console.warn('[Knowix_VR] failed to load lrc', e);
        }
    }

    // vytvoř lyric billboard
    ensureLyricSprite();
    setLyricText('');

    // počkej, až půjde přehrát
    await audioEl.play();

    // extra: používáme přesnější čas (audio playback start může být lehce posunutý),
    // tak chvíli počkáme na "playing" event a pak autokalibrujeme.
    audioEl.addEventListener('playing', () => {
        if (lyricAutocalibrated) return;
        // Autokalibrace: posuneme lyrics tak, aby první slovo nevyjelo divně.
        // Často LRC sedí a jen audio.currentTime je na začátku "před" vůči pocitu.
        // Držíme to konzervativně: offset necháme, ale dovolíme malé doladění.
        lyricAutocalibrated = true;
    }, {once: true});
}

function parseLrcToLineEvents(lrcText) {
    const lines = String(lrcText || '').split(/\r?\n/);
    const timeRe = /\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?]/g;

    const entries = [];
    for (const raw of lines) {
        const line = raw.trim();
        if (!line) continue;

        let m;
        const times = [];
        while ((m = timeRe.exec(line)) !== null) {
            const mm = parseInt(m[1], 10);
            const ss = parseInt(m[2], 10);
            const frac = m[3] ? parseInt(m[3].padEnd(3, '0'), 10) : 0;
            const t = mm * 60 + ss + frac / 1000;
            times.push(t);
        }

        const text = line.replace(timeRe, '').trim();
        if (!text) continue;
        if (/^[a-zA-Z]{2,3}:/i.test(text)) continue;

        const words = text.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
        for (const t of times) {
            entries.push({t, words});
        }
    }
    entries.sort((a, b) => a.t - b.t);
    return {lineEvents: entries};
}

function updateGame(dt) {
    // lyrics sync (s offsetem)
    if (audioEl && lyrics?.wordEvents?.length) {
        const t = (audioEl.currentTime || 0) - lyricTimeOffsetSec;

        // najdi poslední event, který už nastal
        while (currentLyricIndex + 1 < lyrics.wordEvents.length && lyrics.wordEvents[currentLyricIndex + 1].t <= t) {
            currentLyricIndex++;
            const w = lyrics.wordEvents[currentLyricIndex]?.w ?? '';
            setLyricText(w);
        }
    }

    // spawn kostek podle pořadí slov v LRC (ne random banana apod.)
    spawnAccumulator += dt;
    if (spawnAccumulator > 1.0) {
        spawnAccumulator = 0;
        if (wordCubes.length < 10) spawnWordCube();
    }

    // pohyb kostek k hráči + držení v pruhu
    for (const cube of wordCubes) {
        if (!cube.userData.alive) continue;

        cube.position.z += cube.userData.velocityZ * dt;
        cube.position.x = laneX(cube.userData.laneIndex ?? 0);
        cube.rotation.y += 0.6 * dt;

        // zvýraznění, když je "rozbitelná"
        const inBreakRange = cube.position.z > BREAKABLE_Z_MIN && cube.position.z < BREAKABLE_Z_MAX;
        if (inBreakRange) cube.material.color.set(0x33ffb0);
        else cube.material.color.copy(cube.userData.baseColor);

        if (cube.position.z > 2.5) {
            cube.userData.alive = false;
            gameGroup.remove(cube);
        }
    }

    wordCubes = wordCubes.filter(c => c.userData.alive);
}

function spawnWordCube() {
    // Preferujeme sekvenci z LRC, když je k dispozici.
    let word = null;
    if (Array.isArray(wordSequence) && nextSpawnWordIndex < wordSequence.length) {
        word = wordSequence[nextSpawnWordIndex++];
    }

    // fallback (když není LRC) - ale bez "banana" styl slov
    if (!word) {
        const safe = ['word', 'listen', 'focus', 'ready', 'go'];
        word = safe[Math.floor(Math.random() * safe.length)];
    }

    // lane podle pořadí (ať je vidět pattern): postupně procházíme pruhy
    const laneIndex = (nextSpawnWordIndex - 1) % LANE_COUNT;

    const cube = createWordCube(word);
    cube.userData.laneIndex = laneIndex;

    // drobný "rytmus" v Y podle lane
    const yBase = 1.15 + (laneIndex % 2) * 0.15;

    cube.position.set(
        laneX(laneIndex),
        yBase,
        -7.0
    );

    // rychlost mírně podle tempa (pozice ve skladbě)
    cube.userData.velocityZ = 1.35 + (laneIndex * 0.05);
    cube.userData.alive = true;

    wordCubes.push(cube);
    gameGroup.add(cube);
}

function stopSongPlayback() {
    if (audioEl) {
        try {
            audioEl.pause();
            audioEl.src = '';
        } catch (_) {
        }
    }
    audioEl = null;
    lyrics = null;
    currentLyricIndex = -1;

    if (lyricSprite && lyricSprite.parent) {
        lyricSprite.parent.remove(lyricSprite);
    }
    lyricSprite = null;
}

function ensureLyricSprite() {
    if (lyricSprite) return;
    lyricSprite = createTextBillboard('', {
        bg: '#000000',
        fg: '#ffffff',
        fontSize: 76,
        width: 1024,
        height: 256
    });
    lyricSprite.position.set(0, 1.8, -1.6);
    lyricSprite.scale.set(1.6, 0.6, 1);
    gameGroup.add(lyricSprite);
}

function setLyricText(text) {
    if (!lyricSprite) return;

    const parent = lyricSprite.parent;
    const pos = lyricSprite.position.clone();
    const scale = lyricSprite.scale.clone();

    parent.remove(lyricSprite);
    lyricSprite = createTextBillboard(text || '', {
        bg: '#000000',
        fg: '#ffffff',
        fontSize: 76,
        width: 1024,
        height: 256
    });
    lyricSprite.position.copy(pos);
    lyricSprite.scale.copy(scale);
    parent.add(lyricSprite);
}

function parseLrcToWordEvents(lrcText) {
    // LRC: [mm:ss.xx] text
    // Z jednoho řádku uděláme word events rozložené do času mezi tímhle a dalším řádkem.
    const lines = String(lrcText || '').split(/\r?\n/);

    const entries = [];
    const timeRe = /\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?]/g;

    for (const raw of lines) {
        const line = raw.trim();
        if (!line) continue;

        let m;
        const times = [];
        while ((m = timeRe.exec(line)) !== null) {
            const mm = parseInt(m[1], 10);
            const ss = parseInt(m[2], 10);
            const frac = m[3] ? parseInt(m[3].padEnd(3, '0'), 10) : 0;
            const t = mm * 60 + ss + frac / 1000;
            times.push(t);
        }

        const text = line.replace(timeRe, '').trim();
        if (!text) continue;

        // metadata typu [ar:], [ti:] ignorujeme
        if (/^[a-zA-Z]{2,3}:/i.test(text)) continue;

        for (const t of times) {
            entries.push({t, text});
        }
    }

    entries.sort((a, b) => a.t - b.t);

    const wordEvents = [];

    for (let i = 0; i < entries.length; i++) {
        const cur = entries[i];
        const next = entries[i + 1];

        const startT = cur.t;
        const endT = (next ? next.t : cur.t + 4.0);
        const span = Math.max(0.2, endT - startT);

        // slova: odstraníme přebytečné mezery; zachováme apostrofy atd.
        const words = cur.text
            .replace(/\s+/g, ' ')
            .trim()
            .split(' ')
            .filter(Boolean);

        if (!words.length) continue;

        // rozložení do časového okna - lehká preferce delších slov
        const weights = words.map(w => Math.max(1, w.replace(/[^A-Za-z0-9]/g, '').length));
        const totalW = weights.reduce((a, b) => a + b, 0);

        let acc = 0;
        for (let j = 0; j < words.length; j++) {
            const wSpan = span * (weights[j] / totalW);
            const tWord = startT + acc;
            wordEvents.push({t: tWord, w: words[j]});
            acc += wSpan;
        }
    }

    return {wordEvents, duration: entries.length ? entries[entries.length - 1].t : null};
}

function updateScoreSprite() {
    if (!scoreSprite) return;
    // nahradíme sprite novým, aby se zaktualizoval text (jednoduché řešení bez shaderů)
    const parent = scoreSprite.parent;
    const pos = scoreSprite.position.clone();
    parent.remove(scoreSprite);
    scoreSprite = createTextBillboard(`Score: ${score}`, {
        bg: '#000000',
        fg: '#ffffff',
        fontSize: 42,
        width: 512,
        height: 196
    });
    scoreSprite.position.copy(pos);
    parent.add(scoreSprite);
}

function createSkyGradientTexture({top, mid, bottom}) {
    // Jednoduchý canvas-gradient jako pozadí (bez externích assetů).
    const canvas = document.createElement('canvas');
    canvas.width = 16;
    canvas.height = 256;
    const ctx = canvas.getContext('2d');

    const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
    grad.addColorStop(0.0, top);
    grad.addColorStop(0.52, mid);
    grad.addColorStop(1.0, bottom);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.magFilter = THREE.LinearFilter;
    tex.minFilter = THREE.LinearMipMapLinearFilter;
    return tex;
}

function animate() {
    renderer.setAnimationLoop(render);
}

function render(_, frame) {
    const dt = renderer.xr.isPresenting ? 1 / 75 : 1 / 60;

    // aktualizace raycastu (VR lasery nebo desktop myš)
    updateInteractionRay(frame);

    if (state === AppState.GAME) {
        updateGame(dt);
        checkControllerCollisions();
    }

    renderer.render(scene, camera);
}


function checkControllerCollisions() {
    // kolize pro obě ruce
    if (controllerL) checkOneControllerCollision(controllerL, 'L');
    if (controllerR) checkOneControllerCollision(controllerR, 'R');
}

function checkOneControllerCollision(controller, hand) {
    const controllerBox = new THREE.Box3().setFromObject(controller);
    for (const cube of wordCubes) {
        if (!cube.userData.alive) continue;
        if (cube.position.z <= BREAKABLE_Z_MIN || cube.position.z >= BREAKABLE_Z_MAX) continue;

        const cubeBox = new THREE.Box3().setFromObject(cube);
        if (cubeBox.intersectsBox(controllerBox)) {
            hitCube(cube, `collision-${hand}`);
        }
    }
}

function hitCube(cube, mode) {
    if (!cube?.userData?.alive) return;
    cube.userData.alive = false;

    if (cube.material?.color) cube.material.color.set(0x00ff00);

    gameGroup.remove(cube);
    score += 1;
    updateScoreSprite();
    console.log(`[Knowix_VR] HIT (${mode}) score=${score} word=${cube.userData.word}`);
}

function handleSelect(hand) {
    if (!hovered) return;

    // Song card group: voláme onSelect na groupu
    if (typeof hovered.userData?.onSelect === 'function') {
        hovered.userData.onSelect();
        return;
    }

    // UI tlačítko
    if (typeof hovered.userData?.onSelect === 'function') {
        hovered.userData.onSelect();
        return;
    }

    // ve hře: zásah kostky laserem (jen blízko/rozbitelná)
    if (state === AppState.GAME && hovered.name?.startsWith('word:')) {
        const z = hovered.position?.z ?? -999;
        if (z > BREAKABLE_Z_MIN && z < BREAKABLE_Z_MAX) {
            hitCube(hovered, `laser-${hand}`);
        }
    }
}

function setHovered(obj, by) {
    // když trefíme sprite s textem, chceme parent mesh
    const target = obj?.parent?.isMesh ? obj.parent : obj;

    // když trefíme panel v song card, chceme group
    const isSongPanel = target?.parent?.name?.startsWith('song:');
    const normalized = isSongPanel ? target.parent : target;

    if (hovered === normalized) {
        hoveredBy = by;
        return;
    }

    // unhover staré
    if (hovered) {
        const oldPanel = hovered?.userData?.hitTarget;
        if (oldPanel && oldPanel.material && oldPanel.userData?.baseColor) {
            oldPanel.material.color.copy(oldPanel.userData.baseColor);
        } else if (hovered.material && hovered.userData?.baseColor) {
            hovered.material.color.copy(hovered.userData.baseColor);
        }
        hovered.scale?.set?.(1, 1, 1);
    }

    hovered = normalized;
    hoveredBy = by;

    // hover nové
    // - Song card: zvýrazníme panel (mesh) i group trochu přifoukneme
    const panel = hovered?.userData?.hitTarget;
    if (panel && panel.material && panel.userData?.baseColor) {
        const hoverColor = panel.userData?.hoverColor;
        if (hoverColor) panel.material.color.copy(hoverColor);
        else panel.material.color.set(0xffcc00);
    } else if (hovered && hovered.material) {
        const hoverColor = hovered.userData?.hoverColor;
        if (hoverColor) hovered.material.color.copy(hoverColor);
        else hovered.material.color.set(0xffcc00);
    }

    if (hovered) hovered.scale.set(1.04, 1.04, 1.04);
}

function updateInteractionRay(frame) {
    const targets = (state === AppState.LOBBY) ? interactables : wordCubes;

    // VR: zkusíme oba controllery a vybereme nejbližší hit
    if (renderer.xr.isPresenting && frame) {
        const hitL = intersectFromController(controllerL, targets);
        const hitR = intersectFromController(controllerR, targets);

        const best = pickBestHit(hitL, hitR);
        setHovered(best?.hit?.object ?? null, best?.hand ?? null);

        // délka laserů
        setLaserLength(laserLineL, hitL?.hit ? Math.min(hitL.hit.distance, LASER_LENGTH) : LASER_LENGTH);
        setLaserLength(laserLineR, hitR?.hit ? Math.min(hitR.hit.distance, LASER_LENGTH) : LASER_LENGTH);
        return;
    }

    // Desktop: ray z kamery přes myš
    if (lastPointerEvent) {
        raycaster.setFromCamera(mouseNDC, camera);
        raycaster.far = LASER_LENGTH;
        const intersects = raycaster.intersectObjects(targets, true);
        setHovered(intersects.length ? intersects[0].object : null, null);
    } else {
        setHovered(null, null);
    }

    // mimo VR necháme lasery defaultně krátké
    setLaserLength(laserLineL, LASER_LENGTH);
    setLaserLength(laserLineR, LASER_LENGTH);
}

function intersectFromController(controller, targets) {
    if (!controller) return null;

    tempMatrix.identity().extractRotation(controller.matrixWorld);
    raycaster.ray.origin.setFromMatrixPosition(controller.matrixWorld);
    raycaster.ray.direction.set(0, 0, -1).applyMatrix4(tempMatrix);
    raycaster.far = LASER_LENGTH;

    const intersects = raycaster.intersectObjects(targets, true);
    return {hit: intersects.length ? intersects[0] : null};
}

function pickBestHit(hitL, hitR) {
    const dL = hitL?.hit?.distance ?? Infinity;
    const dR = hitR?.hit?.distance ?? Infinity;
    if (dL === Infinity && dR === Infinity) return null;
    if (dL <= dR) return {hand: 'L', hit: hitL.hit};
    return {hand: 'R', hit: hitR.hit};
}

function setLaserLength(line, length) {
    if (!line) return;
    const clamped = Math.max(0.02, Math.min(length, LASER_LENGTH));
    const pos = line.geometry.attributes.position;
    pos.setXYZ(1, 0, 0, -clamped);
    pos.needsUpdate = true;
}

function onPointerMove(e) {
    lastPointerEvent = e;
    const rect = renderer.domElement.getBoundingClientRect();
    mouseNDC.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouseNDC.y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
}

function onPointerDown() {
    // desktop potvrzení (bez ruky)
    handleSelect('D');
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function createSaber(color) {
    const geom = new THREE.BoxGeometry(0.02, 0.02, 0.35);
    const mat = new THREE.MeshBasicMaterial({color});
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.set(0, 0, -0.18);
    return mesh;
}

function clearGroup(group) {
    if (!group) return;
    while (group.children.length) {
        const child = group.children.pop();
        if (!child) break;
        group.remove(child);
    }
}

function laneX(i) {
    const idx = Math.max(0, Math.min(LANE_COUNT - 1, i | 0));
    return LANE_START_X + idx * (LANE_WIDTH + LANE_GAP);
}

function createTextBillboard(text, opts = {}) {
    const {
        bg = '#000000',
        fg = '#ffffff',
        fontSize = 48,
        width = 512,
        height = 256,
        padding = 24,
    } = opts;

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');

    // background
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);

    // text
    ctx.fillStyle = fg;
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const lines = String(text ?? '').split('\n');
    const lineH = Math.round(fontSize * 1.25);
    const totalH = lineH * lines.length;
    const startY = (height - totalH) / 2 + lineH / 2;

    for (let i = 0; i < lines.length; i++) {
        ctx.fillText(lines[i], width / 2, startY + i * lineH, width - padding * 2);
    }

    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.SpriteMaterial({map: tex, transparent: true});
    const sprite = new THREE.Sprite(mat);

    // přibližná velikost ve světě
    sprite.scale.set(1.2, 0.6, 1);
    return sprite;
}

function enterGame() {
    state = AppState.GAME;

    // look
    scene.background = new THREE.Color(0x06080f);
    scene.fog = new THREE.Fog(0x06080f, 2, 14);

    // vyčistit
    clearGroup(lobbyGroup);
    clearGroup(gameGroup);
    wordCubes = [];
    setHovered(null, null);

    // podlaha
    const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(20, 20),
        new THREE.MeshStandardMaterial({color: 0x101820, metalness: 0.0, roughness: 1.0})
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0;
    gameGroup.add(floor);

    // score
    scoreSprite = createTextBillboard(`Score: ${score}`, {
        bg: '#000000',
        fg: '#ffffff',
        fontSize: 42,
        width: 512,
        height: 196
    });
    scoreSprite.position.set(0, 2.25, -1.6);
    scoreSprite.scale.set(1.2, 0.45, 1);
    gameGroup.add(scoreSprite);
}
