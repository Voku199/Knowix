document.addEventListener('DOMContentLoaded', () => {
    // Matching UI
    const root = document.getElementById('matching-root');
    const statusEl = document.getElementById('match-status');
    const enList = Array.from(document.querySelectorAll('#match-en .match-en'));
    const csList = Array.from(document.querySelectorAll('#match-cs .match-cs'));

    // DEBUG: print correct answers (initial)
    try {
        const missingInputs = Array.from(document.querySelectorAll('input[name^="missing_word_"]'));
        if (missingInputs.length) {
            console.groupCollapsed('[DEBUG] Missing – correct answers');
            missingInputs.forEach((inp, i) => {
                console.log(`#${i + 1}:`, inp.getAttribute('data-correct') || '');
            });
            console.groupEnd();
        }

        const translationInputs = Array.from(document.querySelectorAll('input[name^="translation_"]'));
        if (translationInputs.length) {
            console.groupCollapsed('[DEBUG] Translations – original => correct CS');
            translationInputs.forEach((inp, i) => {
                const original = inp.getAttribute('data-original') || '';
                const correct = inp.getAttribute('data-correct') || '';
                console.log(`#${i + 1}:`, original, '=>', correct);
            });
            console.groupEnd();
        }

        const enButtons = Array.from(document.querySelectorAll('#match-en .match-en'));
        if (enButtons.length) {
            console.groupCollapsed('[DEBUG] Matching pairs EN -> CS');
            enButtons.forEach((btn, i) => {
                console.log(`#${i + 1}:`, btn.getAttribute('data-en') || '', '=>', btn.getAttribute('data-cs') || '');
            });
            console.groupEnd();
        }
    } catch (e) {
        console.warn('[DEBUG] Initial logging failed:', e);
    }

    let selectedEn = null;
    let selectedCs = null;
    let solved = 0;

    function setStatus(msg, type = 'info') {
        if (!statusEl) return;
        statusEl.textContent = msg;
        statusEl.style.color = type === 'ok' ? '#0a7' : type === 'err' ? '#c33' : '#444';
    }

    function clearSelectionStyles() {
        enList.forEach(b => b.classList.remove('selected'));
        csList.forEach(b => b.classList.remove('selected'));
    }

    function finalizeIfDone() {
        const total = Math.min(enList.length, csList.length);
        if (solved >= total && total > 0) {
            setStatus('Hotovo! Vše správně spárováno.', 'ok');
            enList.forEach(b => (b.disabled = true));
            csList.forEach(b => (b.disabled = true));
        }
    }

    function handleMatchAttempt() {
        if (!selectedEn || !selectedCs) return;
        const correctCs = selectedEn.getAttribute('data-cs') || '';
        const chosenCs = selectedCs.getAttribute('data-cs') || '';
        if (correctCs === chosenCs) {
            selectedEn.classList.add('matched');
            selectedCs.classList.add('matched');
            selectedEn.disabled = true;
            selectedCs.disabled = true;
            solved++;
        } else {
            selectedEn.classList.add('wrong');
            selectedCs.classList.add('wrong');
            setTimeout(() => {
                selectedEn.classList.remove('wrong');
                selectedCs.classList.remove('wrong');
            }, 500);
        }
        selectedEn.classList.remove('selected');
        selectedCs.classList.remove('selected');
        selectedEn = null;
        selectedCs = null;

        finalizeIfDone();
    }

    if (root) {
        enList.forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.disabled) return;
                if (selectedEn === btn) {
                    btn.classList.remove('selected');
                    selectedEn = null;
                    return;
                }
                clearSelectionStyles();
                selectedEn = btn;
                btn.classList.add('selected');
                if (selectedCs) handleMatchAttempt();
            });
        });

        csList.forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.disabled) return;
                if (selectedCs === btn) {
                    btn.classList.remove('selected');
                    selectedCs = null;
                    return;
                }
                csList.forEach(b => b.classList.remove('selected'));
                selectedCs = btn;
                btn.classList.add('selected');
                if (selectedEn) handleMatchAttempt();
            });
        });
    }

    // Submit to backend: gather all answers and POST JSON
    async function submitToBackend() {
        const submitBtn = document.getElementById('submit-answers');
        const endpoint = submitBtn ? submitBtn.getAttribute('data-endpoint') : null;
        if (!endpoint) {
            alert('Endpoint pro kontrolu odpovědí nebyl nalezen.');
            return;
        }

        // Missing answers (doplňovačky)
        const missingPayload = [];
        const missingInputs = Array.from(document.querySelectorAll('input[name^="missing_word_"]'));
        missingInputs.forEach((inp) => {
            missingPayload.push({user: (inp.value || '').toString()});
        });

        // Translations
        const translationsPayload = [];
        const translationInputs = Array.from(document.querySelectorAll('input[name^="translation_"]'));
        translationInputs.forEach((inp) => {
            translationsPayload.push({user: (inp.value || '').toString()});
        });

        // Pairs - from matched EN buttons (each matched EN implies its CS pair via data-cs)
        const pairsPayload = [];
        const matchedEn = enList.filter(b => b.classList.contains('matched'));
        matchedEn.forEach(enBtn => {
            const en = enBtn.getAttribute('data-en') || '';
            const cs = enBtn.getAttribute('data-cs') || '';
            if (en && cs) pairsPayload.push([en, cs]);
        });

        const payload = {missing: missingPayload, translations: translationsPayload, pairs: pairsPayload};

        try {
            submitBtn && (submitBtn.disabled = true);
            // DEBUG: log payload before sending
            console.groupCollapsed('[DEBUG] Payload sent to backend');
            console.log(JSON.stringify(payload, null, 2));
            console.groupEnd();

            const res = await fetch(endpoint, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                cache: 'no-store',
                body: JSON.stringify(payload)
            });
            if (!res.ok) {
                const text = await res.text();
                console.error('[DEBUG] Backend error response:', text);
                throw new Error('Chyba při volání backendu');
            }
            const data = await res.json();
            renderFeedback(data);
        } catch (e) {
            console.error(e);
            alert('Nepodařilo se zkontrolovat odpovědi. Zkus to znovu.');
        } finally {
            submitBtn && (submitBtn.disabled = false);
        }
    }

    function renderFeedback(data) {
        // DEBUG: server evaluation details
        try {
            console.groupCollapsed('[DEBUG] Server evaluation result');
            console.log('Success flag:', data && data.success, 'Score:', data && data.score);
            if (data && data.details) {
                console.groupCollapsed('Missing details');
                (data.details.missing || []).forEach((d, i) => console.log(`#${i + 1}:`, d));
                console.groupEnd();

                console.groupCollapsed('Translations details');
                (data.details.translations || []).forEach((d, i) => console.log(`#${i + 1}:`, d));
                console.groupEnd();

                console.groupCollapsed('Pairs details (bools)');
                (data.details.pairs || []).forEach((ok, i) => console.log(`#${i + 1}:`, ok));
                console.groupEnd();
            }
            console.groupEnd();
        } catch (e) {
            console.warn('[DEBUG] Failed to log server result:', e);
        }

        // Missing feedback
        const missingDetails = (data && data.details && data.details.missing) || [];
        const missingInputs = Array.from(document.querySelectorAll('input[name^="missing_word_"]'));
        missingInputs.forEach((inp, idx) => {
            const card = inp.closest('.exercise-card');
            const feedback = (card && card.querySelector('.feedback')) || null;
            const d = missingDetails[idx] || {};
            const okFlag = data && Array.isArray(data.missing) ? data.missing[idx] : undefined;
            if (card) {
                card.classList.remove('ok', 'err');
            }
            if (feedback) {
                if (okFlag === true) {
                    feedback.textContent = 'Správně';
                    feedback.style.color = '#0a7';
                    card && card.classList.add('ok');
                } else if (okFlag === 'almost') {
                    feedback.textContent = `Skoro. Správně: ${d.correct || ''}`;
                    feedback.style.color = '#c90';
                    card && card.classList.add('err');
                } else {
                    feedback.textContent = `Špatně. Správně: ${d.correct || ''}`;
                    feedback.style.color = '#c33';
                    card && card.classList.add('err');
                }
            }
        });

        // Translations feedback
        const transDetails = (data && data.details && data.details.translations) || [];
        const translationInputs = Array.from(document.querySelectorAll('input[name^="translation_"]'));
        translationInputs.forEach((inp, idx) => {
            const card = inp.closest('.exercise-card');
            const feedback = (card && card.querySelector('.feedback')) || null;
            const d = transDetails[idx] || {};
            const okFlag = data && Array.isArray(data.translations) ? data.translations[idx] : undefined;
            if (card) {
                card.classList.remove('ok', 'err');
            }
            if (feedback) {
                if (okFlag === true) {
                    feedback.textContent = 'Správně';
                    feedback.style.color = '#0a7';
                    card && card.classList.add('ok');
                } else if (okFlag === 'almost') {
                    feedback.textContent = d.feedback || `Skoro. Správně: ${d.correct || ''}`;
                    feedback.style.color = '#c90';
                    card && card.classList.add('err');
                } else {
                    feedback.textContent = `Špatně. Správně: ${d.correct || ''}`;
                    feedback.style.color = '#c33';
                    card && card.classList.add('err');
                }
            }
        });

        // Pairs overall feedback
        if (statusEl) {
            if (data && data.pairs) {
                setStatus('Spojovačka: správně', 'ok');
            } else {
                setStatus('Spojovačka: špatně nebo nedokončeno', 'err');
            }
        }

        // Summary, XP, streak
        const resultBox = document.getElementById('result');
        if (resultBox) {
            const okMissing = (data.missing || []).filter(x => x === true).length;
            const okTrans = (data.translations || []).filter(x => x === true).length;
            const totalMissing = (data.missing || []).length;
            const totalTrans = (data.translations || []).length;
            const pairsOk = data.pairs ? 1 : 0;
            const total = totalMissing + totalTrans + 1; // +1 pairs block
            const correct = okMissing + okTrans + pairsOk;
            const score = typeof data.score === 'number' ? data.score : (total ? correct / total : 0);
            let txt = `Výsledek: ${correct} / ${total} (${Math.round(score * 100)}%)`;
            if (data.success) {
                if (score === 1) {
                    txt += ' | Perfektní!';
                } else if (score >= 0.8) {
                    txt += ' | Skoro správně! Nevadí';
                }
            }
            if (data.xp_awarded && data.xp_awarded > 0) txt += ` | +${data.xp_awarded} XP`;
            if (data.streak_message) txt += ` | ${data.streak_message}`;
            if (data.xp_error) txt += ` | XP chyba: ${data.xp_error}`;
            resultBox.textContent = txt;
        }

        // === POPUP LOGIKA pro vlastni_music ===
        if (data && (data.success || data.all_correct)) {
            const score = typeof data.score === 'number' ? data.score : null;
            const perfect = (score !== null && score === 1) || (
                Array.isArray(data.missing) && data.missing.every(x => x === true) &&
                Array.isArray(data.translations) && data.translations.every(x => x === true) &&
                data.pairs === true
            );
            if (typeof window._vm_showSuccess === 'function') {
                window._vm_showSuccess(score !== null ? score : 1, perfect);
            }
        }
    }

    const submitBtn = document.getElementById('submit-answers');
    if (submitBtn) submitBtn.addEventListener('click', submitToBackend);

    // Přidání listeneru i pro tlačítko A1 varianty (checkButton), pokud existuje
    const legacyBtn = document.getElementById('checkButton');
    if (legacyBtn && !legacyBtn.dataset._vmBound) {
        legacyBtn.dataset._vmBound = '1';
        legacyBtn.addEventListener('click', submitToBackend);
    }
});
