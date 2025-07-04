document.addEventListener('DOMContentLoaded', function () {
    // --- SpeechRecognition ---
    let recognition;
    let isListening = false;
    let noSpeechTimeout = null;

    // --- Vylepšená spojovačka slov ---
    function showMatchingExercise(pairs) {
        inputArea.innerHTML = `
            <div style="font-size:1.2em;margin-bottom:10px;">Spoj anglická slova/věty s českými:</div>
            <div id="matchingExercise" style="display:flex;gap:40px;justify-content:center;">
                <div id="enCol"></div>
                <div id="czCol"></div>
            </div>
            <button class="submit-btn" id="checkMatchingBtn" style="margin-top:20px;">Zkontrolovat</button>
            <div id="matchingResult" style="margin-top:15px;font-size:1.1em;"></div>
        `;

        function shuffle(arr) {
            for (let i = arr.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [arr[i], arr[j]] = [arr[j], arr[i]];
            }
        }

        const enArr = pairs.map(p => p.en);
        const czArr = pairs.map(p => p.cz);
        shuffle(enArr);
        shuffle(czArr);

        const enCol = document.getElementById('enCol');
        const czCol = document.getElementById('czCol');

        enArr.forEach((en) => {
            const div = document.createElement('div');
            div.className = 'matching-item';
            div.textContent = en;
            div.draggable = true;
            div.dataset.en = en;
            div.style.padding = '10px 18px';
            div.style.margin = '8px 0';
            div.style.background = '#e3eafc';
            div.style.borderRadius = '8px';
            div.style.cursor = 'grab';
            div.style.border = '1px solid #b3c6e7';
            enCol.appendChild(div);
        });

        czArr.forEach((cz) => {
            const drop = document.createElement('div');
            drop.className = 'matching-drop';
            drop.textContent = cz;
            drop.dataset.cz = cz;
            drop.style.padding = '10px 18px';
            drop.style.margin = '8px 0';
            drop.style.background = '#f8f9fa';
            drop.style.borderRadius = '8px';
            drop.style.minHeight = '40px';
            drop.style.border = '2px dashed #b3c6e7';
            drop.style.position = 'relative';
            drop.style.transition = 'background 0.2s';
            czCol.appendChild(drop);
        });

        // Drag & drop logic
        let dragged = null;
        enCol.querySelectorAll('.matching-item').forEach(item => {
            item.addEventListener('dragstart', function () {
                dragged = item;
                setTimeout(() => item.style.opacity = '0.5', 0);
            });
            item.addEventListener('dragend', function () {
                item.style.opacity = '1';
            });
        });
        czCol.querySelectorAll('.matching-drop').forEach(drop => {
            drop.addEventListener('dragover', function (e) {
                e.preventDefault();
                drop.style.background = '#d4edda';
            });
            drop.addEventListener('dragleave', function () {
                drop.style.background = '#f8f9fa';
            });
            drop.addEventListener('drop', function (e) {
                e.preventDefault();
                drop.style.background = '#f8f9fa';
                if (dragged) {
                    // Remove previous if exists
                    if (drop.querySelector('.matching-item')) {
                        enCol.appendChild(drop.querySelector('.matching-item'));
                    }
                    drop.appendChild(dragged);
                    dragged.style.margin = '0';
                    dragged = null;
                }
            });
        });

        // Kontrola výsledku
        document.getElementById('checkMatchingBtn').onclick = function () {
            let correct = 0;
            let userMatches = [];
            czCol.querySelectorAll('.matching-drop').forEach(drop => {
                const cz = drop.dataset.cz;
                const item = drop.querySelector('.matching-item');
                if (item) {
                    const en = item.dataset.en;
                    const pair = pairs.find(p => p.en === en && p.cz === cz);
                    userMatches.push({en, cz, correct: !!pair});
                    if (pair) correct++;
                }
            });
            const resultDiv = document.getElementById('matchingResult');
            if (correct === pairs.length) {
                resultDiv.innerHTML = `<span style="color:#27ae60;">🎉 Vše správně! Výborně!</span>`;
                setTimeout(() => showCongratsPopout(pairs, userMatches), 1200);
            } else {
                resultDiv.innerHTML = `<span style="color:#e74c3c;">Některé dvojice nesedí, zkus to znovu.</span>`;
            }
        };
    }

    // --- Vylepšený popout po spojovačce ---
    function showCongratsPopout(matchingPairs, userMatches) {
        // matchingPairs: [{en, cz}, ...]
        // userMatches: [{en, cz, correct: true/false}]
        let answersHtml = '';
        if (userMatches && userMatches.length) {
            answersHtml = `
                <div class="matching-summary">
                    <h3 style="margin-bottom:10px;">Tvoje spojení:</h3>
                    <table class="matching-table" style="margin:auto;">
                        <thead>
                            <tr>
                                <th>Anglicky</th>
                                <th>Česky</th>
                                <th>Správně?</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${userMatches.map(pair => `
                                <tr>
                                    <td>${pair.en}</td>
                                    <td>${pair.cz}</td>
                                    <td>${pair.correct ? '✔️' : '❌'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }

        const pop = document.createElement('div');
        pop.id = 'congratsPopout';
        pop.className = 'popup-container';
        pop.innerHTML = `
            <div class="popup-content" style="max-width:420px;text-align:center;">
                <div style="font-size:2.2em;margin-bottom:10px;">🎉 Skvělá práce!</div>
                <div style="font-size:1.15em;margin-bottom:18px;">Dokončil(a) jsi konverzaci i spojovačku.</div>
                <div style="margin-bottom:18px;">
                    <button id="showAnswersBtn" class="submit-btn" style="margin:0 8px 0 0;">Zobrazit odpovědi</button>
                    <button id="nextLessonBtn" class="next-btn" style="margin:0 0 0 8px;">Další lekce &rarr;</button>
                </div>
                <div id="matchingAnswersDetail" style="display:none;">${answersHtml}</div>
            </div>
        `;
        document.body.appendChild(pop);

        document.getElementById('showAnswersBtn').onclick = function () {
            const detail = document.getElementById('matchingAnswersDetail');
            if (detail) {
                detail.style.display = 'block';
                this.style.display = 'none';
            }
        };

        document.getElementById('nextLessonBtn').onclick = function () {
            window.location.href = '/roleplaying';
        };
    }

    // --- Ostatní původní logika zůstává beze změny ---

    function initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'en-US';
            recognition.onstart = function () {
                isListening = true;
                if (micButton) micButton.classList.add('listening');
                if (prekladInput) prekladInput.placeholder = "Poslouchám...";
                noSpeechTimeout = setTimeout(() => {
                    stopListening();
                    showNoSpeechWarning();
                }, 6000);
            };
            recognition.onresult = function (event) {
                clearTimeout(noSpeechTimeout);
                const transcript = event.results[0][0].transcript;
                if (prekladInput) prekladInput.value = transcript;
                stopListening();
            };
            recognition.onerror = function (event) {
                clearTimeout(noSpeechTimeout);
                if (event.error === "no-speech") {
                    showNoSpeechWarning();
                } else {
                    showResult('Chyba: ' + event.error, false);
                }
                stopListening();
            };
            recognition.onend = function () {
                clearTimeout(noSpeechTimeout);
                stopListening();
            };
        } else {
            if (micButton) micButton.disabled = true;
            if (micButton) micButton.title = "Váš prohlížeč nepodporuje rozpoznávání řeči";
            if (prekladInput) prekladInput.placeholder = "Napište překlad...";
        }
    }

    function startListening() {
        if (recognition) recognition.start();
    }

    function stopListening() {
        if (recognition && isListening) {
            recognition.stop();
            isListening = false;
            if (micButton) micButton.classList.remove('listening');
            if (prekladInput) prekladInput.placeholder = "Zkuste to anglicky...";
        }
        clearTimeout(noSpeechTimeout);
    }

    function showTypeWarning() {
        let warn = document.getElementById('typeWarning');
        if (!warn) {
            warn = document.createElement('div');
            warn.id = 'typeWarning';
            warn.style.position = 'fixed';
            warn.style.bottom = '40px';
            warn.style.left = '50%';
            warn.style.transform = 'translateX(-50%)';
            warn.style.background = '#fffbe6';
            warn.style.border = '2px solid #ff9800';
            warn.style.borderRadius = '12px';
            warn.style.padding = '14px 28px';
            warn.style.fontSize = '1.1em';
            warn.style.boxShadow = '0 4px 16px rgba(0,0,0,0.12)';
            warn.style.zIndex = 9999;
            warn.style.color = '#b26a00';
            warn.innerHTML = 'Používej mikrofon 🎤 pokud můžeš! Piš jen když opravdu nemůžeš mluvit.';
            document.body.appendChild(warn);
            setTimeout(() => {
                warn.style.opacity = '0';
                setTimeout(() => {
                    if (warn) warn.remove();
                }, 600);
            }, 3200);
        }
    }

    function showNoSpeechWarning() {
        let warn = document.getElementById('noSpeechWarning');
        if (!warn) {
            warn = document.createElement('div');
            warn.id = 'noSpeechWarning';
            warn.style.position = 'fixed';
            warn.style.bottom = '40px';
            warn.style.left = '50%';
            warn.style.transform = 'translateX(-50%)';
            warn.style.background = '#ffeaea';
            warn.style.border = '2px solid #e74c3c';
            warn.style.borderRadius = '12px';
            warn.style.padding = '14px 28px';
            warn.style.fontSize = '1.1em';
            warn.style.boxShadow = '0 4px 16px rgba(0,0,0,0.12)';
            warn.style.zIndex = 9999;
            warn.style.color = '#c0392b';
            warn.innerHTML = 'Nebyla rozpoznána žádná řeč. Zkuste to znovu a mluvte zřetelněji!';
            document.body.appendChild(warn);
            setTimeout(() => {
                warn.style.opacity = '0';
                setTimeout(() => {
                    if (warn) warn.remove();
                }, 600);
            }, 3200);
        }
    }

    function showStreakToast(message) {
        const toast = document.getElementById('streakToast');
        const toastText = document.getElementById('streakToastText');
        toastText.textContent = message;
        toast.style.display = 'flex';
        setTimeout(() => {
            toast.style.display = 'none';
        }, 2200);
    }

    const conversationHistory = document.getElementById('conversationHistory');
    const inputArea = document.getElementById('inputArea');
    const resultContainer = document.getElementById('resultContainer');
    let prekladInput, micButton, submitBtn, nextBtn;

    function playAlexAudio(text) {
        const topic = "{{ topic|e }}".replace('.json', '');
        const index = window.currentAlexIndex || 0;
        const audioUrl = `/static/speaking/roleplaying/mp3/${topic}_${index}.mp3`;
        const audio = new Audio(audioUrl);
        audio.play().catch(() => {
        });
        window.currentAlexIndex = index + 2;
    }

    function addToHistory(speaker, cz, en = null, userInput = null, correct = null, isAlex = false) {
        const row = document.createElement('div');
        row.className = 'chat-row ' + (speaker.toLowerCase() === 'uživatel' ? 'user' : 'ai');
        const avatar = document.createElement('img');
        avatar.className = 'chat-avatar';
        avatar.src = speaker.toLowerCase() === 'uživatel'
            ? '/static/profile_pics/{{ session.get("profile_pic", "default.webp") }}'
            : '/static/pic/danndas.png';
        avatar.alt = speaker;
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble ' + (speaker.toLowerCase() === 'uživatel' ? 'bubble-user' : 'bubble-ai');
        let text = speaker.toLowerCase() === 'alex' ? (en || cz) : cz;
        bubble.innerHTML = `<span class="speaker-label">${speaker === 'Uživatel' ? 'Vy' : speaker}:</span> ${text}`;
        if (userInput !== null) {
            bubble.innerHTML += `<span class="answer-feedback">Vaše odpověď: <b>${userInput}</b></span>`;
            if (correct !== null) {
                bubble.innerHTML += correct
                    ? `<span class="answer-feedback correct">✔️ Správně!</span>`
                    : `<span class="answer-feedback incorrect">❌ Nesprávně.<br>Správně: <b>${en}</b></span>`;
            }
        }
        if (speaker.toLowerCase() === 'uživatel') {
            row.appendChild(bubble);
            row.appendChild(avatar);
        } else {
            row.appendChild(avatar);
            row.appendChild(bubble);
        }
        conversationHistory.appendChild(row);
        conversationHistory.scrollTop = conversationHistory.scrollHeight;
        if (isAlex) {
            playAlexAudio(text);
        }
    }

    function handleUserSubmit() {
        const translation = prekladInput.value.trim();
        if (!translation) {
            showResult("Zadejte nebo řekněte překlad", false);
            return;
        }
        submitBtn.disabled = true;
        fetch(window.ROLEPLAYING_NEXT_URL, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({preklad: translation})
        })
            .then(response => response.json())
            .then(data => {
                addToHistory('Uživatel', document.getElementById('czText').textContent, data.correct_answer, translation, data.correct, false);
                if (data.correct) {
                    showResult("Správně! ✅", true);
                    if (data.xp_awarded && data.xp_awarded > 0) showStreakToast(`+${data.xp_awarded} XP!`);
                    if (data.streak_info && data.streak_info.streak) showStreakToast(`🔥 Streak: ${data.streak_info.streak} dní!`);
                } else {
                    showResult(`Nesprávně. Správná odpověď: "${data.correct_answer}"`, false);
                }
                setTimeout(() => {
                    showNextTurn(data);
                }, 1200);
            });
    }

    function showNextTurn(data) {
        resultContainer.textContent = '';
        inputArea.innerHTML = '';
        if (data.end) {
            if (data.matching_pairs && Array.isArray(data.matching_pairs) && data.matching_pairs.length > 0) {
                showMatchingExercise(data.matching_pairs);
            } else {
                inputArea.innerHTML = `<div style="font-size:1.3em;margin:30px 0;">🎉 Konverzace dokončena!</div>`;
            }
            return;
        }
        if (data.speaker.toLowerCase() === 'uživatel') {
            inputArea.innerHTML = `
                <div style="margin-bottom:10px; color:#888;">Co říct: <b id="czText">${data.cz}</b></div>
                <input type="text" class="translation-input" id="prekladInput" placeholder="Zkuste to anglicky...">
                <button class="mic-btn" id="micButton"><span>🎤</span></button>
                <button class="submit-btn" id="submitBtn">Odeslat</button>
            `;
            prekladInput = document.getElementById('prekladInput');
            micButton = document.getElementById('micButton');
            submitBtn = document.getElementById('submitBtn');
            if (micButton) {
                micButton.addEventListener('click', function () {
                    if (isListening) stopListening();
                    else startListening();
                });
            }
            if (submitBtn) submitBtn.addEventListener('click', handleUserSubmit);
            prekladInput.addEventListener('input', function () {
                if (prekladInput.value.length > 0) showTypeWarning();
            });
        } else {
            addToHistory(data.speaker, data.cz, null, null, null, true);
            inputArea.innerHTML = `
                <div style="margin-bottom:10px; color:#888;">Poslouchej a pokračuj</div>
                <button class="next-btn" id="nextBtn" style="display:block;">Pokračovat &rarr;</button>
            `;
            nextBtn = document.getElementById('nextBtn');
            if (nextBtn) nextBtn.addEventListener('click', function () {
                fetch(window.ROLEPLAYING_NEXT_URL, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                })
                    .then(response => response.json())
                    .then(showNextTurn);
            });
        }
    }

    function showResult(message, isCorrect) {
        resultContainer.textContent = message;
        resultContainer.className = 'result ' + (isCorrect ? 'correct' : 'incorrect');
    }

    window.ROLEPLAYING_NEXT_URL = window.ROLEPLAYING_NEXT_URL || '{{ url_for("roleplaying.roleplaying_next") }}';
    initSpeechRecognition();

    const firstSpeaker = '{{ speaker }}';
    const firstCz = `{{ cz }}`;
    window.currentAlexIndex = 0;
    if (firstSpeaker && firstCz) {
        addToHistory(firstSpeaker, firstCz, null, null, null, firstSpeaker.toLowerCase() === 'alex');
    }

    if (firstSpeaker.toLowerCase() === 'uživatel') {
        inputArea.innerHTML = `
            <div style="margin-bottom:10px; color:#888;">Co říct: <b id="czText">${firstCz}</b></div>
            <input type="text" class="translation-input" id="prekladInput" placeholder="Zkuste to anglicky...">
            <button class="mic-btn" id="micButton"><span>🎤</span></button>
            <button class="submit-btn" id="submitBtn">Odeslat</button>
        `;
        prekladInput = document.getElementById('prekladInput');
        micButton = document.getElementById('micButton');
        submitBtn = document.getElementById('submitBtn');
        if (micButton) {
            micButton.addEventListener('click', function () {
                if (isListening) stopListening();
                else startListening();
            });
        }
        if (submitBtn) submitBtn.addEventListener('click', handleUserSubmit);
        prekladInput.addEventListener('input', function () {
            if (prekladInput.value.length > 0) showTypeWarning();
        });
    } else {
        inputArea.innerHTML = `
            <div style="margin-bottom:10px; color:#888;">Poslouchej a pokračuj</div>
            <button class="next-btn" id="nextBtn" style="display:block;">Pokračovat &rarr;</button>
        `;
        nextBtn = document.getElementById('nextBtn');
        if (nextBtn) nextBtn.addEventListener('click', function () {
            fetch(window.ROLEPLAYING_NEXT_URL, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({})
            })
                .then(response => response.json())
                .then(showNextTurn);
        });
    }
});