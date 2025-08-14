document.addEventListener('DOMContentLoaded', function () {
    const canvas = document.getElementById('drawing-canvas');
    const ctx = canvas.getContext('2d');
    const panelBtn = document.getElementById('btn-panel');
    const drawBtn = document.getElementById('btn-draw');
    const lineBtn = document.getElementById('btn-line');
    const textBtn = document.getElementById('btn-text');
    const clearBtn = document.getElementById('btn-clear');
    const saveBtn = document.getElementById('btn-save');
    const bgColorPicker = document.getElementById('bg-color-picker');
    const bgImageInput = document.getElementById('bg-image-input');
    const bgImageControls = document.querySelector('.bg-image-controls');
    const applyBgBtn = document.getElementById('btn-apply-bg');
    const cancelBgBtn = document.getElementById('btn-cancel-bg');
    const colorOptions = document.querySelectorAll('.color-option');
    const canvasContainer = document.querySelector('.canvas-container');

    // Stav aplikace
    let currentMode = 'panel';
    let isDrawing = false;
    let startX = 0;
    let startY = 0;
    let panels = [];
    let contentPaths = [];
    let currentPath = {points: [], color: '', lineWidth: 3};
    let lines = [];
    let currentLine = null;
    let texts = [];
    let textStartX = 0;
    let textStartY = 0;
    let currentColor = '#000000';
    let bgColor = '#ffffff';
    let bgImage = null;
    let bgImageObj = null;
    let bgImageX = 0;
    let bgImageY = 0;
    let bgImageWidth = 0;
    let bgImageHeight = 0;
    let isPlacingBgImage = false;
    let isDraggingBg = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let selectedObject = null;
    let selectionType = null;
    let isMoving = false;
    let offsetX = 0;
    let offsetY = 0;
    let isResizing = false;
    let resizeHandle = null;

    const MAX_CANVAS_HEIGHT = 800; // Maximální výška plátna

    function initCanvas() {
        // Dynamický výpočet velikosti plátna
        const containerWidth = canvasContainer.clientWidth;
        const aspectRatio = A4_WIDTH / A4_HEIGHT;

        // Výpočet výšky na základě šířky kontejneru a poměru stran
        let canvasHeight = containerWidth / aspectRatio;

        // Omezení maximální výšky
        if (canvasHeight > MAX_CANVAS_HEIGHT) {
            canvasHeight = MAX_CANVAS_HEIGHT;
        }

        canvas.width = containerWidth;
        canvas.height = canvasHeight;

        // Responzivní styly
        canvas.style.width = '100%';
        canvas.style.height = 'auto';
        canvas.style.maxHeight = MAX_CANVAS_HEIGHT + 'px';

        redrawScene();
    }

    // Přidání resize listeneru
    window.addEventListener('resize', () => {
        initCanvas();
        redrawScene();
    });

    // Funkce pro změnu režimu
    function setMode(mode) {
        currentMode = mode;
        document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));

        if (mode === 'panel') panelBtn.classList.add('active');
        else if (mode === 'draw') drawBtn.classList.add('active');
        else if (mode === 'line') lineBtn.classList.add('active');
        else if (mode === 'text') textBtn.classList.add('active');

        if (mode === 'draw' || mode === 'line') {
            canvas.style.cursor = 'crosshair';
        } else if (mode === 'text') {
            canvas.style.cursor = 'text';
        } else {
            canvas.style.cursor = 'default';
        }

        selectedObject = null;
        selectionType = null;
        redrawScene();
    }

    // Překreslení celé scény
    function redrawScene() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        if (bgImage) {
            ctx.drawImage(bgImage, bgImageX, bgImageY, bgImageWidth, bgImageHeight);
        }

        panels.forEach(panel => {
            ctx.strokeStyle = panel.color;
            ctx.lineWidth = panel.lineWidth || 3;
            ctx.strokeRect(panel.x, panel.y, panel.width, panel.height);
        });

        lines.forEach(line => {
            ctx.strokeStyle = line.color;
            ctx.lineWidth = line.lineWidth || 3;
            ctx.beginPath();
            ctx.moveTo(line.startX, line.startY);
            ctx.lineTo(line.endX, line.endY);
            ctx.stroke();
        });

        contentPaths.forEach(path => {
            if (path.points.length > 0) {
                ctx.strokeStyle = path.color;
                ctx.lineWidth = path.lineWidth || 3;
                ctx.beginPath();
                ctx.moveTo(path.points[0].x, path.points[0].y);
                for (let i = 1; i < path.points.length; i++) {
                    ctx.lineTo(path.points[i].x, path.points[i].y);
                }
                ctx.stroke();
            }
        });

        ctx.textBaseline = 'top';
        ctx.font = '20px Arial';
        texts.forEach(text => {
            ctx.fillStyle = text.color;
            ctx.fillText(text.content, text.x, text.y);
        });

        if (selectedObject && selectionType) {
            ctx.strokeStyle = '#ff0000';
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 3]);

            if (selectionType === 'panel') {
                ctx.strokeRect(selectedObject.x, selectedObject.y, selectedObject.width, selectedObject.height);
            } else if (selectionType === 'text') {
                const textWidth = ctx.measureText(selectedObject.content).width;
                ctx.strokeRect(selectedObject.x, selectedObject.y - 5, textWidth, 25);
            } else if (selectionType === 'image' && bgImage) {
                ctx.strokeRect(bgImageX, bgImageY, bgImageWidth, bgImageHeight);
            } else if (selectionType === 'path') {
                let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
                selectedObject.points.forEach(point => {
                    minX = Math.min(minX, point.x);
                    minY = Math.min(minY, point.y);
                    maxX = Math.max(maxX, point.x);
                    maxY = Math.max(maxY, point.y);
                });
                ctx.strokeRect(minX, minY, maxX - minX, maxY - minY);
            } else if (selectionType === 'line') {
                ctx.strokeRect(
                    Math.min(selectedObject.startX, selectedObject.endX),
                    Math.min(selectedObject.startY, selectedObject.endY),
                    Math.abs(selectedObject.startX - selectedObject.endX),
                    Math.abs(selectedObject.startY - selectedObject.endY)
                );
            }

            ctx.setLineDash([]);

            if (selectionType === 'image' && bgImage) {
                ctx.fillStyle = '#ff0000';
                const handleSize = 8;
                const handles = [
                    {x: bgImageX, y: bgImageY},
                    {x: bgImageX + bgImageWidth, y: bgImageY},
                    {x: bgImageX, y: bgImageY + bgImageHeight},
                    {x: bgImageX + bgImageWidth, y: bgImageY + bgImageHeight}
                ];

                handles.forEach(pos => {
                    ctx.fillRect(pos.x - handleSize / 2, pos.y - handleSize / 2, handleSize, handleSize);
                });
            }
        }
    }

    // Funkce pro smazání vybraného objektu
    function deleteSelectedObject() {
        if (!selectedObject || !selectionType) return;

        if (selectionType === 'panel') {
            const index = panels.indexOf(selectedObject);
            if (index !== -1) {
                panels.splice(index, 1);
            }
        } else if (selectionType === 'text') {
            const index = texts.indexOf(selectedObject);
            if (index !== -1) {
                texts.splice(index, 1);
            }
        } else if (selectionType === 'line') {
            const index = lines.indexOf(selectedObject);
            if (index !== -1) {
                lines.splice(index, 1);
            }
        } else if (selectionType === 'path') {
            const index = contentPaths.indexOf(selectedObject);
            if (index !== -1) {
                contentPaths.splice(index, 1);
            }
        } else if (selectionType === 'image') {
            bgImage = null;
            bgImageObj = null;
        }

        selectedObject = null;
        selectionType = null;
        redrawScene();
    }

    // Event listener pro klávesu Delete
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Delete' || e.key === 'Del') {
            deleteSelectedObject();
        }
    });

    // Event listeners pro tlačítka
    panelBtn.addEventListener('click', () => setMode('panel'));
    drawBtn.addEventListener('click', () => setMode('draw'));
    lineBtn.addEventListener('click', () => setMode('line'));
    textBtn.addEventListener('click', () => setMode('text'));

    clearBtn.addEventListener('click', () => {
        if (confirm('Opravdu chcete vymazat celý komiks?')) {
            panels = [];
            contentPaths = [];
            lines = [];
            texts = [];
            bgImage = null;
            bgImageObj = null;
            selectedObject = null;
            selectionType = null;
            initCanvas();
        }
    });

    saveBtn.addEventListener('click', () => {
        const dataUrl = canvas.toDataURL('image/png');
        const link = document.createElement('a');
        link.download = 'knowix-komiks.png';
        link.href = dataUrl;
        link.click();
    });

    // Výběr barvy
    colorOptions.forEach(option => {
        option.addEventListener('click', () => {
            document.querySelectorAll('.color-option').forEach(opt => opt.classList.remove('active'));
            option.classList.add('active');
            currentColor = option.dataset.color;
            ctx.strokeStyle = currentColor;
            ctx.fillStyle = currentColor;

            if (selectedObject && selectionType !== 'image') {
                selectedObject.color = currentColor;
                redrawScene();
            }
        });
    });

    // Změna barvy pozadí
    bgColorPicker.addEventListener('input', (e) => {
        bgColor = e.target.value;
        redrawScene();
    });

    // Nahrání obrázku na pozadí
    bgImageInput.addEventListener('change', function (e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = function (event) {
            const img = new Image();
            img.onload = function () {
                bgImageObj = img;
                bgImageWidth = img.width;
                bgImageHeight = img.height;

                bgImageX = (canvas.width - img.width) / 2;
                bgImageY = (canvas.height - img.height) / 2;

                isPlacingBgImage = true;
                bgImageControls.style.display = 'block';
                canvas.style.cursor = 'move';
                redrawScene();
                ctx.drawImage(img, bgImageX, bgImageY, bgImageWidth, bgImageHeight);
            };
            img.src = event.target.result;
        };
        reader.readAsDataURL(file);
    });

    // Použít pozadí
    applyBgBtn.addEventListener('click', () => {
        bgImage = bgImageObj;
        isPlacingBgImage = false;
        bgImageControls.style.display = 'none';
        canvas.style.cursor = 'default';
        redrawScene();
    });

    // Zrušit pozadí
    cancelBgBtn.addEventListener('click', () => {
        bgImageObj = null;
        isPlacingBgImage = false;
        bgImageControls.style.display = 'none';
        canvas.style.cursor = 'default';
        redrawScene();
    });

    // Event listeners pro plátno
    canvas.addEventListener('mousedown', (e) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const mouseX = (e.clientX - rect.left) * scaleX;
        const mouseY = (e.clientY - rect.top) * scaleY;

        // Kontrola výběru existujícího objektu
        const clicked = findClickedObject(mouseX, mouseY);
        if (clicked) {
            selectedObject = clicked.object;
            selectionType = clicked.type;

            if (selectionType === 'image' && bgImage) {
                resizeHandle = getResizeHandle(mouseX, mouseY);
                if (resizeHandle) {
                    isResizing = true;
                    return;
                }
            }

            isMoving = true;

            if (selectionType === 'panel' || selectionType === 'text') {
                offsetX = mouseX - selectedObject.x;
                offsetY = mouseY - selectedObject.y;
            } else if (selectionType === 'image') {
                offsetX = mouseX - bgImageX;
                offsetY = mouseY - bgImageY;
            } else if (selectionType === 'path') {
                let sumX = 0, sumY = 0;
                selectedObject.points.forEach(point => {
                    sumX += point.x;
                    sumY += point.y;
                });
                const centerX = sumX / selectedObject.points.length;
                const centerY = sumY / selectedObject.points.length;
                offsetX = mouseX - centerX;
                offsetY = mouseY - centerY;
            } else if (selectionType === 'line') {
                const centerX = (selectedObject.startX + selectedObject.endX) / 2;
                const centerY = (selectedObject.startY + selectedObject.endY) / 2;
                offsetX = mouseX - centerX;
                offsetY = mouseY - centerY;
            }

            redrawScene();
            return;
        }

        if (isPlacingBgImage) {
            isDraggingBg = true;
            dragStartX = mouseX - bgImageX;
            dragStartY = mouseY - bgImageY;
            return;
        }

        if (currentMode === 'panel') {
            isDrawing = true;
            startX = mouseX;
            startY = mouseY;
        } else if (currentMode === 'draw') {
            isDrawing = true;
            currentPath = {
                points: [{x: mouseX, y: mouseY}],
                color: currentColor,
                lineWidth: 3
            };
        } else if (currentMode === 'line') {
            isDrawing = true;
            startX = mouseX;
            startY = mouseY;
            currentLine = {
                startX: startX,
                startY: startY,
                endX: startX,
                endY: startY,
                color: currentColor,
                lineWidth: 3
            };
        } else if (currentMode === 'text') {
            textStartX = mouseX;
            textStartY = mouseY;
            const text = prompt('Zadejte text:');
            if (text) {
                texts.push({
                    x: textStartX,
                    y: textStartY,
                    content: text,
                    color: currentColor
                });
                redrawScene();
            }
        }
    });

    canvas.addEventListener('mousemove', (e) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const mouseX = (e.clientX - rect.left) * scaleX;
        const mouseY = (e.clientY - rect.top) * scaleY;

        if (isPlacingBgImage && isDraggingBg) {
            bgImageX = mouseX - dragStartX;
            bgImageY = mouseY - dragStartY;
            redrawScene();
            ctx.drawImage(bgImageObj, bgImageX, bgImageY, bgImageWidth, bgImageHeight);
            return;
        }

        if (isResizing && bgImage) {
            switch (resizeHandle) {
                case 'nw':
                    bgImageWidth += bgImageX - mouseX;
                    bgImageHeight += bgImageY - mouseY;
                    bgImageX = mouseX;
                    bgImageY = mouseY;
                    break;
                case 'ne':
                    bgImageWidth = mouseX - bgImageX;
                    bgImageHeight += bgImageY - mouseY;
                    bgImageY = mouseY;
                    break;
                case 'sw':
                    bgImageWidth += bgImageX - mouseX;
                    bgImageHeight = mouseY - bgImageY;
                    bgImageX = mouseX;
                    break;
                case 'se':
                    bgImageWidth = mouseX - bgImageX;
                    bgImageHeight = mouseY - bgImageY;
                    break;
            }

            bgImageWidth = Math.max(50, bgImageWidth);
            bgImageHeight = Math.max(50, bgImageHeight);

            redrawScene();
            return;
        }

        if (isMoving && selectedObject !== null && selectionType) {
            if (selectionType === 'panel') {
                selectedObject.x = mouseX - offsetX;
                selectedObject.y = mouseY - offsetY;
            } else if (selectionType === 'text') {
                selectedObject.x = mouseX - offsetX;
                selectedObject.y = mouseY - offsetY;
            } else if (selectionType === 'image') {
                bgImageX = mouseX - offsetX;
                bgImageY = mouseY - offsetY;
            } else if (selectionType === 'path') {
                const deltaX = mouseX - offsetX - (selectedObject.centerX || 0);
                const deltaY = mouseY - offsetY - (selectedObject.centerY || 0);

                selectedObject.points.forEach(point => {
                    point.x += deltaX;
                    point.y += deltaY;
                });

                let sumX = 0, sumY = 0;
                selectedObject.points.forEach(point => {
                    sumX += point.x;
                    sumY += point.y;
                });
                selectedObject.centerX = sumX / selectedObject.points.length;
                selectedObject.centerY = sumY / selectedObject.points.length;
            } else if (selectionType === 'line') {
                const deltaX = mouseX - offsetX - (selectedObject.centerX || 0);
                const deltaY = mouseY - offsetY - (selectedObject.centerY || 0);

                selectedObject.startX += deltaX;
                selectedObject.startY += deltaY;
                selectedObject.endX += deltaX;
                selectedObject.endY += deltaY;

                selectedObject.centerX = (selectedObject.startX + selectedObject.endX) / 2;
                selectedObject.centerY = (selectedObject.startY + selectedObject.endY) / 2;
            }

            redrawScene();
            return;
        }

        if (!isDrawing) return;

        if (currentMode === 'panel') {
            redrawScene();
            const width = mouseX - startX;
            const height = mouseY - startY;
            ctx.strokeStyle = currentColor;
            ctx.strokeRect(startX, startY, width, height);
        } else if (currentMode === 'draw') {
            currentPath.points.push({x: mouseX, y: mouseY});
            redrawScene();

            ctx.beginPath();
            ctx.strokeStyle = currentPath.color;
            ctx.lineWidth = currentPath.lineWidth;
            ctx.moveTo(currentPath.points[0].x, currentPath.points[0].y);
            for (let i = 1; i < currentPath.points.length; i++) {
                ctx.lineTo(currentPath.points[i].x, currentPath.points[i].y);
            }
            ctx.stroke();
        } else if (currentMode === 'line') {
            currentLine.endX = mouseX;
            currentLine.endY = mouseY;
            redrawScene();

            ctx.beginPath();
            ctx.strokeStyle = currentLine.color;
            ctx.lineWidth = currentLine.lineWidth;
            ctx.moveTo(currentLine.startX, currentLine.startY);
            ctx.lineTo(currentLine.endX, currentLine.endY);
            ctx.stroke();
        }
    });

    canvas.addEventListener('mouseup', (e) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const mouseX = (e.clientX - rect.left) * scaleX;
        const mouseY = (e.clientY - rect.top) * scaleY;

        if (isPlacingBgImage) {
            isDraggingBg = false;
            return;
        }

        if (isResizing) {
            isResizing = false;
            return;
        }

        if (isMoving) {
            isMoving = false;
            return;
        }

        if (!isDrawing) return;
        isDrawing = false;

        if (currentMode === 'panel') {
            const width = mouseX - startX;
            const height = mouseY - startY;

            if (Math.abs(width) > 10 && Math.abs(height) > 10) {
                panels.push({
                    x: startX,
                    y: startY,
                    width: width,
                    height: height,
                    color: currentColor
                });
            }
            redrawScene();
        } else if (currentMode === 'draw') {
            if (currentPath.points.length > 1) {
                let sumX = 0, sumY = 0;
                currentPath.points.forEach(point => {
                    sumX += point.x;
                    sumY += point.y;
                });
                currentPath.centerX = sumX / currentPath.points.length;
                currentPath.centerY = sumY / currentPath.points.length;

                contentPaths.push({...currentPath});
            }
            currentPath = {points: [], color: currentColor};
            redrawScene();
        } else if (currentMode === 'line') {
            const dx = mouseX - startX;
            const dy = mouseY - startY;
            const length = Math.sqrt(dx * dx + dy * dy);
            if (length > 10) {
                currentLine.centerX = (startX + mouseX) / 2;
                currentLine.centerY = (startY + mouseY) / 2;
                lines.push({...currentLine});
            }
            currentLine = null;
            redrawScene();
        }
    });

    canvas.addEventListener('mouseout', () => {
        isDrawing = false;
        if (isPlacingBgImage) {
            isDraggingBg = false;
        }
        if (isResizing) {
            isResizing = false;
        }
        if (isMoving) {
            isMoving = false;
        }
    });

    // Dvojklik pro zrušení výběru
    canvas.addEventListener('dblclick', () => {
        selectedObject = null;
        selectionType = null;
        redrawScene();
    });

    // Pomocné funkce
    function findClickedObject(x, y) {
        ctx.font = '20px Arial';

        // Kontrola textů
        for (let i = texts.length - 1; i >= 0; i--) {
            const text = texts[i];
            const textWidth = ctx.measureText(text.content).width;
            if (x > text.x && x < text.x + textWidth &&
                y > text.y && y < text.y + 20) {
                return {object: text, type: 'text'};
            }
        }

        // Kontrola panelů
        for (let i = panels.length - 1; i >= 0; i--) {
            const panel = panels[i];
            if (x > panel.x && x < panel.x + panel.width &&
                y > panel.y && y < panel.y + panel.height) {
                return {object: panel, type: 'panel'};
            }
        }

        // Kontrola čar
        for (let i = lines.length - 1; i >= 0; i--) {
            const line = lines[i];
            const dx = line.endX - line.startX;
            const dy = line.endY - line.startY;
            const length = Math.sqrt(dx * dx + dy * dy);
            const t = Math.max(0, Math.min(1, ((x - line.startX) * dx + (y - line.startY) * dy) / (length * length)));
            const projX = line.startX + t * dx;
            const projY = line.startY + t * dy;
            const distance = Math.sqrt((x - projX) * (x - projX) + (y - projY) * (y - projY));

            if (distance < 10) {
                return {object: line, type: 'line'};
            }
        }

        // Kontrola kreseb
        for (let i = contentPaths.length - 1; i >= 0; i--) {
            const path = contentPaths[i];
            for (let j = 0; j < path.points.length; j++) {
                const point = path.points[j];
                const distance = Math.sqrt((x - point.x) * (x - point.x) + (y - point.y) * (y - point.y));
                if (distance < 10) {
                    return {object: path, type: 'path'};
                }
            }
        }

        // Kontrola obrázku na pozadí
        if (bgImage && x > bgImageX && x < bgImageX + bgImageWidth &&
            y > bgImageY && y < bgImageY + bgImageHeight) {
            return {object: null, type: 'image'};
        }

        return null;
    }

    function getResizeHandle(x, y) {
        if (!bgImage) return null;

        const handles = [
            {pos: 'nw', x: bgImageX, y: bgImageY},
            {pos: 'ne', x: bgImageX + bgImageWidth, y: bgImageY},
            {pos: 'sw', x: bgImageX, y: bgImageY + bgImageHeight},
            {pos: 'se', x: bgImageX + bgImageWidth, y: bgImageY + bgImageHeight}
        ];

        const handleSize = 10;
        for (const handle of handles) {
            if (Math.abs(x - handle.x) < handleSize && Math.abs(y - handle.y) < handleSize) {
                return handle.pos;
            }
        }

        return null;
    }

    // Inicializace
    initCanvas();
    setMode('panel');

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            document.body.classList.toggle('dark-mode');
            themeToggle.textContent = document.body.classList.contains('dark-mode') ? '☀️' : '🌙';
        });
    }
});