/**
 * Pexeso main.js – upraveno pro správné zobrazování slov a otazníků
 */
const socket = io();

let playerNum = null;
let myTurn = false;
let roomId = null;
let selected = [];
let lockBoard = false;
let scores = [0, 0];
let cards = [];
let cardElements = [];
let gameEnded = false;

const lobbyDiv = document.getElementById('lobby');
const gameArea = document.getElementById('game-area');
const board = document.getElementById('board');
const playerInfo = document.getElementById('player-info');
const turnInfo = document.getElementById('turn-info');
const score1 = document.getElementById('score-1');
const score2 = document.getElementById('score-2');
const resultDiv = document.getElementById('result');
const newGameBtn = document.getElementById('new-game-btn');
const roomStatus = document.getElementById('room-status');

const flipSound = document.getElementById('flip-sound');
const successSound = document.getElementById('success-sound');
const failSound = document.getElementById('fail-sound');

document.getElementById('join-btn').onclick = () => {
    const id = document.getElementById('room-id').value.trim();
    if (id.length < 2) {
        roomStatus.textContent = "Kód místnosti musí mít alespoň 2 znaky.";
        return;
    }
    socket.emit('join_room', id);
    roomStatus.textContent = "Připojuji se...";
};

document.getElementById('create-btn').onclick = () => {
    fetch('/pexeso/create_room', {method: 'POST'})
        .then(res => res.json())
        .then(data => {
            document.getElementById('room-id').value = data.room_id;
            roomStatus.textContent = "Místnost vytvořena! Kód: " + data.room_id;
        })
        .catch(() => {
            roomStatus.textContent = "Chyba při vytváření místnosti.";
        });
};

newGameBtn.onclick = () => {
    socket.emit('new_game', roomId);
};

/**
 * Vykreslí herní desku. Na začátku jsou všechny karty otočené (zobrazen otazník).
 * Po otočení karty se zobrazí správné slovo (anglicky nebo česky).
 */
function renderBoard(cardsData) {
    board.innerHTML = '';
    cardElements = [];
    cards = cardsData.map(card => ({
        ...card,
        flipped: false,
        matched: false
    }));

    cards.forEach((card, idx) => {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card';
        cardDiv.dataset.idx = idx;

        // Create card elements manually to ensure proper structure
        const innerDiv = document.createElement('div');
        innerDiv.className = 'card-inner';

        const frontDiv = document.createElement('div');
        frontDiv.className = 'card-front';
        frontDiv.textContent = card.text;  // Always show ? on front

        const backDiv = document.createElement('div');
        backDiv.className = 'card-back';
        backDiv.textContent = '?';  // Show word on back

        innerDiv.appendChild(frontDiv);
        innerDiv.appendChild(backDiv);
        cardDiv.appendChild(innerDiv);

        cardDiv.onclick = () => onCardClick(idx);
        board.appendChild(cardDiv);
        cardElements.push(cardDiv);
    });
}

/**
 * Otočí kartu a zobrazí na ní správné slovo.
 */
function flipCard(idx, force = true) {
    const card = cards[idx];
    const cardDiv = cardElements[idx];

    // Ensure card has the correct structure
    let front = cardDiv.querySelector('.card-front');
    let back = cardDiv.querySelector('.card-back');
    let inner = cardDiv.querySelector('.card-inner');

    if (!inner) {
        inner = document.createElement('div');
        inner.className = 'card-inner';
        cardDiv.appendChild(inner);
    }

    if (!front) {
        front = document.createElement('div');
        front.className = 'card-front';
        front.textContent = card.text;
        inner.appendChild(front);
    } else {
        front.textContent = card.text;
    }

    if (!back) {
        back = document.createElement('div');
        back.className = 'card-back';
        back.textContent = '?';
        inner.appendChild(back);
    } else {
        back.textContent = '?';
    }

    // Flip the card
    cardDiv.classList.add('flipped');
    if (force) card.flipped = true;
}

/**
 * Otočí zpět karty na otazník.
 */
function unflipCards(idxs) {
    idxs.forEach(idx => {
        const cardDiv = cardElements[idx];
        cardDiv.classList.remove('flipped');
        cards[idx].flipped = false;
    });
}

function setMatched(idxs) {
    idxs.forEach(idx => {
        cardElements[idx].classList.add('matched');
        cards[idx].matched = true;
    });
}

function updateScores(s1, s2) {
    score1.textContent = `Hráč 1: ${s1}`;
    score2.textContent = `Hráč 2: ${s2}`;
}

function createCards(wordsList) {
    // wordsList: [{cz: "...", en: "..."}, ...]
    // Výstup: pole karet [{text: "...", pair: "en", lang: "en"|"cz"}, ...]
    let cards = [];
    wordsList.forEach(pair => {
        // Anglická karta
        cards.push({
            text: pair.en,
            pair: pair.en,
            lang: "en"
        });
        // Česká karta
        cards.push({
            text: pair.cz,
            pair: pair.en,
            lang: "cz"
        });
    });
    // Zamíchat karty
    for (let i = cards.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [cards[i], cards[j]] = [cards[j], cards[i]];
    }
    return cards;
}

function onCardClick(idx) {
    if (!myTurn || lockBoard || gameEnded) return;
    if (selected.includes(idx) || cards[idx].matched) return;
    if (selected.length === 1 && selected[0] === idx) return; // zabrání opakovanému výběru stejné karty
    flipCard(idx);
    selected.push(idx);
    cardElements[idx].classList.add('selected');
    socket.emit('flip_card', {room: roomId, idx: idx});
    flipSound.currentTime = 0;
    flipSound.play();

    if (selected.length === 2) {
        lockBoard = true;
        setTimeout(() => {
            socket.emit('check_pair', {room: roomId, idxs: selected});
            selected.forEach(i => cardElements[i].classList.remove('selected'));
            selected = [];
        }, 800);
    }
}

// Socket.IO events
socket.on('room_joined', data => {
    playerNum = data.player;
    roomId = data.room;
    lobbyDiv.style.display = 'none';
    gameArea.style.display = '';
    playerInfo.textContent = `Jsi hráč ${playerNum}${data.is_host ? ' (zakladatel místnosti)' : ''}`;

    if (playerNum === 1) {
        turnInfo.textContent = 'Čekám na druhého hráče...';
    } else {
        turnInfo.textContent = 'Připojeno! Čekám na začátek hry...';
    }

    resultDiv.style.display = 'none';
    newGameBtn.style.display = 'none';
    updateScores(0, 0);
});

socket.on('start_game', data => {
    console.log('start_game received:', data);
    renderBoard(data.cards);
    scores = [0, 0];
    updateScores(0, 0);

    // Store player info
    playerNum = data.player_num;
    myTurn = data.your_turn;

    // Update UI based on turn
    if (myTurn) {
        turnInfo.textContent = "Jsi na tahu!";
        lockBoard = false;
    } else {
        const currentPlayer = data.player_turn || 1;
        turnInfo.textContent = `Hra začíná! První je na řadě Hráč ${currentPlayer}.`;
        lockBoard = true;
    }

    gameEnded = false;
    resultDiv.style.display = 'none';
    newGameBtn.style.display = 'none';

    console.log(`Game started. I am player ${playerNum}, my turn: ${myTurn}`);
});

socket.on('turn_update', data => {
    myTurn = (data.player_turn === playerNum);
    if (myTurn) {
        turnInfo.textContent = "Jsi na tahu!";
    } else {
        turnInfo.textContent = `Na tahu je hráč ${data.player_turn === 1 ? '1' : '2'}.`;
    }
    lockBoard = !myTurn;
});

socket.on('flip_card', idx => {
    flipCard(idx, false);
});

socket.on('unflip_cards', idxs => {
    setTimeout(() => {
        unflipCards(idxs);
        lockBoard = false;
        if (!failSound.paused) {
            failSound.pause();
            failSound.currentTime = 0;
        }
        failSound.play();
    }, 700);
});

socket.on('set_matched', idxs => {
    setMatched(idxs);
    successSound.currentTime = 0;
    successSound.play();
});

// Nová práce s výběrem slov podle nové struktury
// Předpokládáme, že proměnná slova je načtená z JSONu ve formátu { "A1": [...], "A2": [...], ... }
function getRandomWords(level, count) {
    const words = slova[level];
    // Ochrana proti nedostatku slov
    if (!words || words.length < count) {
        return words ? words.slice() : [];
    }
    // Zamíchat a vybrat count slov
    const shuffled = words.slice().sort(() => 0.5 - Math.random());
    return shuffled.slice(0, count);
}

// Příklad použití (musí být až po načtení slova.json!):
// const selectedLevel = document.getElementById('level-select').value;
// const gameWords = getRandomWords(selectedLevel, 8); // 8 dvojic pro hru

socket.on('update_scores', data => {
    scores = data.scores;
    updateScores(scores[0], scores[1]);
});

socket.on('turn', data => {
    myTurn = data.turn === playerNum;
    turnInfo.textContent = myTurn ? "Jsi na tahu!" : "Na tahu je soupeř.";
    lockBoard = false;
});

socket.on('game_over', data => {
    gameEnded = true;
    let msg = '';
    if (data.winner === 0) msg = "Remíza!";
    else if (data.winner === playerNum) msg = "Vyhrál jsi! 🎉";
    else msg = "Prohrál jsi!";
    resultDiv.textContent = msg;
    resultDiv.style.display = '';
    newGameBtn.style.display = '';
});

socket.on('opponent_left', () => {
    turnInfo.textContent = "Soupeř opustil hru.";
    lockBoard = true;
    resultDiv.textContent = "Soupeř opustil hru.";
    resultDiv.style.display = '';
    newGameBtn.style.display = '';
});