class ShadowingApp {
    constructor() {
        this.DEBUG = true;
        this.userLevel = window.userEnglishLevel;
        this.currentLevel = this.userLevel;
        this.currentSentence = '';
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.isRecording = false;
        // Countdown state
        this.countdownIntervalId = null;
        this.countdownEndsAt = null;

        this.initElements();
        this.initSpeechRecognition();
        this.bindEvents();
    }

    initElements() {
        this.elements = {
            sentenceDisplay: document.getElementById('sentenceDisplay'),
            newSentenceBtn: document.getElementById('newSentenceBtn'),
            playBtn: document.getElementById('playBtn'),
            recordBtn: document.getElementById('recordBtn'),
            stopBtn: document.getElementById('stopBtn'),
            recordingIndicator: document.getElementById('recordingIndicator'),
            loading: document.getElementById('loading'),
            resultArea: document.getElementById('resultArea'),
            accuracyBar: document.getElementById('accuracyBar'),
            accuracyText: document.getElementById('accuracyText'),
            resultTitle: document.getElementById('resultTitle'),
            comparison: document.getElementById('comparison'),
            originalText: document.getElementById('originalText'),
            spokenText: document.getElementById('spokenText'),
            feedback: document.getElementById('feedback'),
            countdownTimer: document.getElementById('countdownTimer')
        };
    }

    initSpeechRecognition() {
        if ('webkitSpeechRecognition' in window) {
            this.recognition = new webkitSpeechRecognition();
        } else if ('SpeechRecognition' in window) {
            this.recognition = new SpeechRecognition();
        } else {
            alert('Váš prohlížeč nepodporuje rozpoznávání řeči. Zkuste Google Chrome.');
            return;
        }

        this.recognition.continuous = false;
        this.recognition.interimResults = false;
        this.recognition.lang = 'en-US';

        this.recognition.onstart = () => {
            this.elements.recordingIndicator.classList.add('active');
            this.elements.recordBtn.style.display = 'none';
            this.elements.stopBtn.style.display = 'inline-flex';
            this.elements.stopBtn.disabled = false;
            this.isRecording = true;
        };

        this.recognition.onresult = (event) => {
            const userSpeech = event.results[0][0].transcript;
            if (this.DEBUG) {
                console.log('[Shadowing] onresult transcript:', userSpeech);
            }
            this.processResult(userSpeech);
        };

        this.recognition.onerror = (event) => {
            console.error('Chyba rozpoznávání:', event.error);
            this.stopRecording();
            alert('Chyba při rozpoznávání řeči. Zkuste to znovu.');
        };

        this.recognition.onend = () => {
            this.stopRecording();
        };
    }

    bindEvents() {
        this.elements.newSentenceBtn.addEventListener('click', () => this.getNewSentence());
        this.elements.playBtn.addEventListener('click', () => this.playSentence());
        this.elements.recordBtn.addEventListener('click', () => this.startRecording());
        this.elements.stopBtn.addEventListener('click', () => this.recognition.stop());
    }

    async getNewSentence() {
        try {
            // Pokud náhodou běží nahrávání, zastav ho
            if (this.isRecording && this.recognition) {
                try {
                    this.recognition.stop();
                } catch {
                }
                this.stopRecording();
            }

            const response = await fetch(`/shadow/get_sentence?level=${this.currentLevel}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.currentSentence = data.sentence;
            this.elements.sentenceDisplay.textContent = data.sentence;
            this.elements.sentenceDisplay.style.visibility = 'visible';
            this.elements.playBtn.disabled = false;
            // Během zobrazení věty zakázat nahrávání
            this.elements.recordBtn.disabled = true;
            this.hideResult();

            // Start a fresh countdown based on sentence length
            this.startCountdown(this.computeVisibleSeconds(this.currentSentence));

        } catch (error) {
            console.error('Chyba při načítání věty:', error);
            alert('Nepodařilo se načíst větu. Zkuste to znovu.');
        }
    }

    playSentence() {
        if (!this.currentSentence) return;
        // Block play if sentence visibility expired
        if (!this.isSentenceVisible()) {
            this.elements.playBtn.disabled = true;
            return;
        }

        // Zastavit všechny předchozí syntézy
        this.synthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(this.currentSentence);
        utterance.lang = 'en-US';
        utterance.rate = 0.8; // Pomalejší řeč pro lepší pochopení
        utterance.pitch = 1;

        this.synthesis.speak(utterance);
    }

    startRecording() {
        if (!this.recognition || this.isRecording) return;
        // Pokud je věta stále viditelná, nahrávání nepovol
        if (this.isSentenceVisible()) {
            return;
        }
        this.hideResult();
        this.recognition.start();
    }

    stopRecording() {
        this.elements.recordingIndicator.classList.remove('active');
        this.elements.recordBtn.style.display = 'inline-flex';
        this.elements.stopBtn.style.display = 'none';
        this.elements.stopBtn.disabled = true;
        this.isRecording = false;
    }

    async processResult(userSpeech) {
        this.elements.loading.classList.add('show');

        try {
            if (!this.currentSentence || typeof userSpeech !== 'string') {
                if (this.DEBUG) {
                    console.warn('[Shadowing] Missing data for accuracy', {
                        currentSentence: this.currentSentence,
                        userSpeech
                    });
                }
                this.showResult(userSpeech || '', 0);
                return;
            }

            let accuracy = this.calculateAccuracy(this.currentSentence, userSpeech);
            if (!Number.isFinite(accuracy) || Number.isNaN(accuracy)) {
                if (this.DEBUG) {
                    console.warn('[Shadowing] Computed accuracy is invalid, coercing to 0', {accuracy});
                }
                accuracy = 0;
            }
            accuracy = Math.max(0, Math.min(100, Math.round(accuracy)));
            if (this.DEBUG) {
                console.log('[Shadowing] Calculated accuracy:', accuracy);
            }

            await this.saveResult(userSpeech, accuracy);
            this.showResult(userSpeech, accuracy);

        } catch (error) {
            console.error('Chyba při zpracování výsledku:', error);
        } finally {
            this.elements.loading.classList.remove('show');
        }
    }

    calculateAccuracy(original, spoken) {
        // Ošetření vstupů
        if (typeof original !== 'string' || typeof spoken !== 'string') return 0;
        const o = original.trim();
        const s = spoken.trim();
        if (!o && !s) return 0;

        // Jednoduchý algoritmus pro porovnání podobnosti
        const originalWords = o.toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/).filter(Boolean);
        const spokenWords = s.toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/).filter(Boolean);
        const maxLength = Math.max(originalWords.length, spokenWords.length);
        if (this.DEBUG) {
            console.log('[Shadowing] Accuracy inputs:', {
                original: o,
                spoken: s,
                originalWords,
                spokenWords,
                maxLength
            });
        }
        if (maxLength === 0) return 0;

        let matches = 0;
        for (let i = 0; i < Math.min(originalWords.length, spokenWords.length); i++) {
            if (originalWords[i] === spokenWords[i]) {
                matches++;
            } else if (this.areSimilar(originalWords[i], spokenWords[i])) {
                matches += 0.7; // Částečná shoda
            }
        }

        const percent = (matches / maxLength) * 100;
        if (this.DEBUG) {
            console.log('[Shadowing] Accuracy calc matches:', {matches, percent});
        }
        return percent;
    }

    areSimilar(word1, word2) {
        // Jednoduché porovnání podobnosti slov
        if (!word1 || !word2) return false;
        if (Math.abs(word1.length - word2.length) > 2) return false;

        let differences = 0;
        const maxLength = Math.max(word1.length, word2.length);

        for (let i = 0; i < maxLength; i++) {
            if (word1[i] !== word2[i]) differences++;
        }

        return differences <= Math.ceil(maxLength * 0.3);
    }

    async saveResult(userSpeech, accuracy) {
        try {
            const safeAccuracy = (Number.isFinite(accuracy) && !Number.isNaN(accuracy)) ? accuracy : 0;
            const payload = {
                sentence: this.currentSentence || '',
                user_speech: typeof userSpeech === 'string' ? userSpeech : '',
                accuracy: safeAccuracy,
                level: this.currentLevel,
                csrf_token: window.CSRF_TOKEN || (document.querySelector('meta[name="csrf-token"]')?.content || '')
            };
            if (this.DEBUG) {
                console.log('[Shadowing] Sending /shadow/save_result payload:', payload);
            }
            const response = await fetch('/shadow/save_result', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN || (document.querySelector('meta[name="csrf-token"]')?.content || '')
                },
                body: JSON.stringify(payload)
            });

            let data;
            const isJson = response.headers.get('content-type')?.includes('application/json');
            if (!response.ok) {
                const text = isJson ? JSON.stringify(await response.json()) : await response.text();
                console.error(`[Shadowing] Save result failed: ${response.status} ${response.statusText}`, text);
                this.elements.feedback.textContent = `Chyba ukládání (${response.status}): ${text}`;
                return;
            }

            data = isJson ? await response.json() : {};
            if (this.DEBUG) {
                console.log('[Shadowing] Save result response:', data);
            }

            if (data && data.xp_gained) {
                this.showXPGain(data.xp_gained);
            }

        } catch (error) {
            console.error('Chyba při ukládání výsledku:', error);
        }
    }

    showResult(userSpeech, accuracy) {
        this.elements.resultArea.classList.add('show');

        // Nastavení barvy a třídy podle přesnosti
        let resultClass, title, feedback;

        if (accuracy >= 85) {
            resultClass = 'result-excellent';
            title = '🎉 Výborně!';
            feedback = 'Vaše výslovnost je skvělá! Pokračujte v dobré práci.';
        } else if (accuracy >= 70) {
            resultClass = 'result-good';
            title = '👍 Dobře!';
            feedback = 'Dobrá práce! Zkuste si větu přečíst ještě jednou a zaměřte se na přesnost.';
        } else {
            resultClass = 'result-poor';
            title = '💪 Zkuste znovu!';
            feedback = 'Nebojte se, procvičování pomáhá! Poslouchejte pozorně a zkuste to znovu.';
        }

        this.elements.resultArea.className = `result-area show ${resultClass}`;
        this.elements.resultTitle.textContent = title;
        this.elements.accuracyBar.style.width = `${accuracy}%`;
        this.elements.accuracyText.textContent = `Přesnost: ${accuracy}%`;
        this.elements.feedback.textContent = feedback;

        // Zobrazení porovnání
        this.elements.comparison.style.display = 'grid';
        this.elements.originalText.textContent = this.currentSentence || '';
        this.elements.spokenText.textContent = userSpeech || '';
    }

    showXPGain(xp) {
        // Jednoduchá notifikace o získaných XP
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #28a745;
            color: white;
            padding: 15px 20px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            z-index: 1000;
            font-weight: bold;
        `;
        notification.textContent = `+${xp} XP!`;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    hideResult() {
        this.elements.resultArea.classList.remove('show');
    }

    // ===== Countdown logic =====
    computeVisibleSeconds(sentence) {
        try {
            const words = String(sentence || '').trim().split(/\s+/).filter(Boolean).length;
            // 5s base + 0.5s per word, clamped 4-14s
            const secs = 5 + words * 0.5;
            return Math.max(4, Math.min(14, Math.round(secs)));
        } catch {
            return 7;
        }
    }

    startCountdown(seconds) {
        // Clear any previous countdown
        if (this.countdownIntervalId) {
            clearInterval(this.countdownIntervalId);
            this.countdownIntervalId = null;
        }
        const now = Date.now();
        this.countdownEndsAt = now + seconds * 1000;

        // Ensure sentence is visible and UI reset
        this.elements.sentenceDisplay.style.visibility = 'visible';
        this.elements.playBtn.disabled = false;
        this.updateCountdown();
        this.elements.countdownTimer.style.display = 'block';

        this.countdownIntervalId = setInterval(() => {
            this.updateCountdown();
        }, 250);
    }

    updateCountdown() {
        if (!this.countdownEndsAt) return;
        const remainingMs = Math.max(0, this.countdownEndsAt - Date.now());
        const remainingSec = Math.ceil(remainingMs / 1000);
        // Update label
        this.elements.countdownTimer.textContent = `Věta zmizí za ${remainingSec}s`;

        if (remainingMs <= 0) {
            this.expireSentence();
        }
    }

    isSentenceVisible() {
        return this.countdownEndsAt && Date.now() < this.countdownEndsAt;
    }

    expireSentence() {
        if (this.countdownIntervalId) {
            clearInterval(this.countdownIntervalId);
            this.countdownIntervalId = null;
        }
        this.countdownEndsAt = null;
        // Po vypršení zobrazit výzvu k řeči
        this.elements.sentenceDisplay.textContent = 'And now, say the sentence!';
        this.elements.sentenceDisplay.style.visibility = 'visible';
        // Disable play and stop any ongoing TTS
        this.synthesis.cancel();
        this.elements.playBtn.disabled = true;
        // Povolit nahrávání až po vypršení
        this.elements.recordBtn.disabled = false;
        // Hide timer
        this.elements.countdownTimer.style.display = 'none';
    }
}

// Inicializace aplikace po načtení stránky
document.addEventListener('DOMContentLoaded', () => {
    new ShadowingApp();
});
