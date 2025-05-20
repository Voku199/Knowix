window.KnowixData = window.KnowixData || {};
KnowixData.exerciseConfig = KnowixData.exerciseConfig || {};


document.addEventListener('DOMContentLoaded', () => {
    initWordMatching();
    setupValidation();
    setupLyricsToggle();
});

function initWordMatching() {
    let selectedPairs = [];

    document.querySelectorAll('.word-box').forEach(box => {
        box.addEventListener('click', () => handleWordClick(box, selectedPairs));
    });
}

function handleWordClick(box, selectedPairs) {
    if (box.classList.contains('locked')) return;

    box.classList.toggle('selected');
    selectedPairs.includes(box)
        ? selectedPairs.splice(selectedPairs.indexOf(box), 1)
        : selectedPairs.push(box);

    if (selectedPairs.length === 2) {
        const [first, second] = selectedPairs;
        const isValid = validatePair(first, second);

        highlightPair(first, second, isValid);

        setTimeout(() => {
            first.classList.remove('selected', 'wrong');
            second.classList.remove('selected', 'wrong');

            if (isValid) {
                [first, second].forEach(el => {
                    el.classList.add('locked', 'correct');
                    el.style.pointerEvents = 'none';
                });
            }

            selectedPairs.length = 0;
        }, 1000);
    }
}

function validatePair(first, second) {
    // Detekce jazykové kombinace
    const languageCombination = [
        first.classList.contains('en-word') ? 'en' : 'cs',
        second.classList.contains('en-word') ? 'en' : 'cs'
    ].join('-');

    // Povolené kombinace
    const validCombinations = ['en-cs', 'cs-en'];
    if (!validCombinations.includes(languageCombination)) return false;

    // Normalizace vstupních hodnot
    const normalize = (text) => text.trim().toLowerCase();
    const word1 = normalize(first.dataset.word);
    const word2 = normalize(second.dataset.word);

    // Validace podle konfigurace - OPRAVA ZDE
    const wordPairs = window.exerciseConfig?.word_pairs || {};
    return Object.entries(wordPairs).some(([key, value]) => {
        const normalizedKey = normalize(key);
        const normalizedValue = normalize(value);

        // Kontrola obou směrů
        return (normalizedKey === word1 && normalizedValue === word2) ||
            (normalizedValue === word1 && normalizedKey === word2);
    });
}

function highlightPair(first, second, isValid) {
    const styleClass = isValid ? 'correct' : 'wrong';
    first.classList.add(styleClass);
    second.classList.add(styleClass);
}

function collectMatchedWordPairs() {
    const pairs = [];
    const used = new Set();
    const wordPairs = window.exerciseConfig?.word_pairs || {}; // OPRAVA ZDE

    const enWords = document.querySelectorAll('.en-word.correct.locked');
    const csWords = document.querySelectorAll('.cs-word.correct.locked');

    enWords.forEach(enEl => {
        const enWord = enEl.dataset.word;
        const match = Array.from(csWords).find(csEl => {
            const csWord = csEl.dataset.word;
            return !used.has(csEl) && wordPairs[enWord] === csWord; // OPRAVA ZDE
        });

        if (match) {
            pairs.push([enWord, match.dataset.word]);
            used.add(enEl);
            used.add(match);
        }
    });

    return pairs;
}

// Přidejte globální normalizační funkci
function normalizeAnswer(text) {
    return text
        .normalize('NFD')  // Rozložení diakritiky na základní znaky
        .replace(/[\u0300-\u036f]/g, '')  // Odstranění diakritických znaků
        .replace(/[^\w\s]/g, '')  // Odstranění interpunkce a speciálních znaků
        .trim()  // Oříznutí mezer
        .toLowerCase();  // Převod na malá písmena
}

function setupValidation() {
    document.getElementById('checkButton').addEventListener('click', async () => {
        // Zpracování odpovědí pro doplňovačky
        const missingAnswers = Array.from(document.querySelectorAll('.exercise-input:not(.translation-input)')).map(input => ({
            correct: normalizeAnswer(input.getAttribute('data-correct')),
            user: normalizeAnswer(input.value),
            original: input.getAttribute('data-original') || ''
        }));

        // Zpracování překladů
        const translationAnswers = Array.from(document.querySelectorAll('.translation-input')).map(input => ({
            correct: normalizeAnswer(input.getAttribute('data-correct')),
            user: normalizeAnswer(input.value),
            original: input.getAttribute('data-original') || ''
        }));

        // Zpracování slovních párů
        const wordPairs = collectMatchedWordPairs();

        // Odeslání na server
        const response = await fetch('/check-answer', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                missing: missingAnswers,
                translations: translationAnswers,
                pairs: wordPairs
            })
        });

        // Zobrazení výsledků
        const result = await response.json();
        renderResults(result);
    });
}

function renderResults(result) {
    const resultContainer = document.getElementById('result');
    let html = '<h2>Výsledky:</h2>';

    html += '<h3>Doplň chybějící slovo:</h3>' +
        result.results.missing.map((correct, i) => `<p>Úloha ${i + 1}: ${correct ? '✅ Správně' : '❌ Špatně'}</p>`).join('');
    
    html += `<h3>Slovní páry:</h3><p>${result.results.pairs ? '✅ Správně' : '❌ Špatně'}</p>`;

    html += result.success
        ? '<p class="success-msg">🎉 Všechny odpovědi jsou správně!</p>'
        : '<p class="error-msg">Některé odpovědi nejsou správně. Zkus to znovu! 🙈</p>';

    resultContainer.innerHTML = html;
}

function setupLyricsToggle() {
    const toggleBtn = document.querySelector('.lyrics-toggle');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', () => {
        const container = document.querySelector('.lyrics-container');
        container.classList.toggle('collapsed');
        container.style.display = 'block';
        toggleBtn.textContent = container.classList.contains('collapsed') ? 'Zobrazit více' : 'Skrýt';
    });
}


