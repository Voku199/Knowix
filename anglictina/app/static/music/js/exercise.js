// Inicializace
document.addEventListener('DOMContentLoaded', () => {
    initWordMatching();
    setupValidation();
});

// Spojovačka - logika
function initWordMatching() {
    let selectedPairs = [];

    document.querySelectorAll('.word-box').forEach(box => {
        box.addEventListener('click', () => handleWordClick(box, selectedPairs));
    });
}

function handleWordClick(box, selectedPairs) {
    if (!box.classList.contains('selected')) {
        box.classList.add('selected');
        selectedPairs.push(box);

        if (selectedPairs.length === 2) {
            const [first, second] = selectedPairs;
            const isPairValid = validatePair(first, second);
            highlightPair(first, second, isPairValid);

            // Resetování výběru
            selectedPairs.splice(0); // Lepší než selectedPairs.length = 0
            first.classList.remove('selected');
            second.classList.remove('selected');
        }
    }
}

// In validatePair function
function validatePair(first, second) {
    const isEnCsPair = (
        (first.classList.contains('en-word') && second.classList.contains('cs-word')) ||
        (first.classList.contains('cs-word') && second.classList.contains('en-word'))
    );

    if (!isEnCsPair) return false;

    const enWord = first.classList.contains('en-word') ?
        first.dataset.word : second.dataset.word;
    const csWord = first.classList.contains('cs-word') ?
        first.dataset.word : second.dataset.word;

    return config.word_pairs[enWord] === csWord; // Corrected variable name
}

function handleWordClick(box, selectedPairs) {
    // Zamezí klikání na již správně spojené (locked) boxy
    if (box.classList.contains('locked')) return;

    if (!box.classList.contains('selected')) {
        box.classList.add('selected');
        selectedPairs.push(box);

        if (selectedPairs.length === 2) {
            const [first, second] = selectedPairs;
            const isValid = validatePair(first, second);
            highlightPair(first, second, isValid);

            // Pokud je správně, zamkne
            if (isValid) {
                first.classList.add('locked');
                second.classList.add('locked');
                first.style.pointerEvents = 'none';
                second.style.pointerEvents = 'none';
            }

            // Resetuj výběr i vybrané styly
            setTimeout(() => {
                first.classList.remove('selected');
                second.classList.remove('selected');

                if (!isValid) {
                    first.classList.remove('wrong');
                    second.classList.remove('wrong');
                }

                selectedPairs.splice(0);
            }, 400); // Počká 0.8 sekundy, ať máš čas vidět výsledek
        }
    }
}

function highlightPair(first, second, isValid) {
    first.classList.remove('correct', 'wrong');
    second.classList.remove('correct', 'wrong');

    const styleClass = isValid ? 'correct' : 'wrong';
    first.classList.add(styleClass);
    second.classList.add(styleClass);
}


function setupValidation() {
    document.querySelector('#checkButton').addEventListener('click', async (event) => {
        event.preventDefault();
        let missingValid = true;
        let translationValid = true;

        const user_missing = [];
        const correct_missing = [];

        config.missing_exercises.forEach((item, index) => {
            const input = document.querySelector(`input[name="missing_word_${index}"]`);
            const userAnswer = input.value.trim().toLowerCase();
            const correctAnswer = item.missing_word.trim().toLowerCase();
            user_missing.push(userAnswer);
            correct_missing.push(correctAnswer);

            if (userAnswer === correctAnswer) {
                input.style.borderColor = "green";
                input.classList.add("good-answer");
                input.classList.remove("bad-answer");
            } else {
                input.style.borderColor = "red";
                input.classList.add("bad-answer");
                input.classList.remove("good-answer");
                missingValid = false;
            }
        });

        const user_translations = [];
        const correct_translations = [];

        config.translation_exercises.forEach((item, index) => {
            const input = document.querySelector(`input[name="translation_${index}"]`);
            const userAnswer = input.value.trim().toLowerCase();
            const correctAnswer = item.translated.trim().toLowerCase();
            user_translations.push(userAnswer);
            correct_translations.push(correctAnswer);

            if (userAnswer === correctAnswer) {
                input.style.borderColor = "green";
                input.classList.add("good-answer");
                input.classList.remove("bad-answer");
            } else {
                input.style.borderColor = "red";
                input.classList.add("bad-answer");
                input.classList.remove("good-answer");
                translationValid = false;
            }
        });

        const selectedPairs = [];
        let pairsValid = true;

        for (const [en, cs] of Object.entries(config.word_pairs)) {
            const enEl = document.querySelector(`.en-word[data-word="${en}"]`);
            const csEl = document.querySelector(`.cs-word[data-word="${cs}"]`);

            if (enEl?.classList.contains('correct') && csEl?.classList.contains('correct')) {
                selectedPairs.push([en, cs]);
            } else {
                pairsValid = false;
            }
        }

        if (!missingValid || !translationValid || !pairsValid) return;

        const response = await fetch('/check-answer', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                user_missing: user_missing[0],
                missing_word: correct_missing[0],
                user_translation: user_translations[0],
                translation: correct_translations[0],
                pairs: selectedPairs
            })
        });

        const result = await response.json();

        if (result.correct.missing_word && result.correct.translation && result.correct.pairs) {
            window.location.href = "/results";
        } else {
            alert("Něco je špatně. Zkontroluj odpovědi.");
        }
    });
}


function validateMissingWord() {
    const userInput = document.getElementById('missingWordInput').value;
    return userInput.toLowerCase() === exerciseConfig.missing_word.toLowerCase();
}

function validateTranslation() {
    const userInput = document.getElementById('translationInput').value.trim().toLowerCase();
    const correctTranslation = exerciseConfig.translated_line.trim().toLowerCase();
    return userInput === correctTranslation;
}

// In the setupValidation function's fetch call:
body: JSON.stringify({
    user_missing: missingWord,
    missing_word: exerciseConfig.missing_word,
    user_translation: translation,
    translation: exerciseConfig.translated_line,  // Now correctly references the Czech translation
    pairs: selectedPairs,
})

function validateAllPairs() {
    return Object.entries(exerciseConfig.word_pairs).every(([en, cs]) => {
        const enElement = document.querySelector(`.en-word[data-word="${en}"]`);
        const csElement = document.querySelector(`.cs-word[data-word="${cs}"]`);
        return enElement?.classList.contains('correct') &&
            csElement?.classList.contains('correct');
    });
}

document.querySelector('.lyrics-toggle').addEventListener('click', function () {
    const container = document.querySelector('.lyrics-container');
    container.classList.toggle('collapsed'); // Přepíná mezi zkráceným a rozbaleným stavem
    container.style.display = 'block'; // Vždy zobrazíme
    this.textContent = container.classList.contains('collapsed') ? 'Zobrazit více' : 'Skrýt'; // Změna textu na tlačítku
});


// Přepínání mezi světlým a tmavým režimem
const themeToggle = document.getElementById("theme-toggle");
const body = document.body;

themeToggle.addEventListener("click", () => {
    body.classList.toggle("dark-mode");

    // Přepínání ikonky 🌙 / ☀️
    if (body.classList.contains("dark-mode")) {
        themeToggle.textContent = "☀️";
    } else {
        themeToggle.textContent = "🌙";
    }
});

