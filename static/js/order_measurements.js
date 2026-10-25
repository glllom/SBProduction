/**
 * Order Measurements Management Script
 * Controlled row editing with Checkmark Submit button, Enter navigation,
 * single active row limit, and click-away/next-row save functionality.
 */

const config = window.OrderMeasurementsConfig || {};

const formatNum = (val) => {
    if (!val && val !== 0) return '';
    let n = parseFloat(val);
    if (isNaN(n)) return val;
    n = Math.floor(n * 10) / 10;
    return n % 1 === 0 ? n.toString() : n.toFixed(1);
};

function renderStaticRowContent(data) {
    const openingText = (data.opening === 'IN' ? 'פנימה' : (data.opening === 'OUT' ? 'החוצה' : ''));
    const directionText = (data.direction === 'L' ? 'L' : (data.direction === 'R' ? 'R' : ''));
    let combinedText = '-';
    if (openingText || directionText) {
        combinedText = `${directionText} | ${openingText}`;
    }

    return `
        <td class="fw-bold bg-light">${data.mark || ''}</td>
        <td class="field-place small text-start">${data.place || ''}</td>
        <td class="field-width">${formatNum(data.width)}</td>
        <td class="field-height">${formatNum(data.height)}</td>
        <td class="field-wall">${formatNum(data.wall)}</td>
        <td class="field-opening small">${combinedText}</td>
        <td class="field-bottom-correction small">${formatNum(data.bottomCorrection)}</td>
        <td class="field-comment small text-start">${data.comment || ''}</td>
        <td class="no-print text-nowrap">
            ${data.sketchUrl ? `
                <a href="${data.sketchUrl}" target="_blank" class="btn btn-sm btn-primary py-0" data-bs-toggle="tooltip" title="צפה בשרטוט">
                    <i class="bi bi-file-earmark-image"></i>
                </a>
            ` : ''}
            ${data.canEdit ? '<i class="bi bi-pencil-square opacity-50 ms-2" data-bs-toggle="tooltip" title="עריכת פריט"></i>' : ''}
        </td>
    `;
}

function renderCustomDisplayRow(itemId, data) {
    const cLock = formatNum(data.customLockHeight);
    const cH1 = formatNum(data.customHinge1);
    const cH2 = formatNum(data.customHinge2);
    const cH3 = formatNum(data.customHinge3);
    const cH4 = formatNum(data.customHinge4);
    const cH5 = formatNum(data.customHinge5);

    if (cLock || cH1 || cH2 || cH3 || cH4 || cH5) {
        return `
            <tr id="display-custom-${itemId}" class="custom-heights-display-row text-muted">
                <td></td>
                <td colspan="7" class="text-start">
                    <span class="ps-4">
                        ${cLock ? `<span class="custom-label">מנעול:</span><span class="custom-value">${cLock}</span>` : ''}
                        ${cH1 ? `<span class="custom-label">ציר 1:</span><span class="custom-value">${cH1}</span>` : ''}
                        ${cH2 ? `<span class="custom-label">ציר 2:</span><span class="custom-value">${cH2}</span>` : ''}
                        ${cH3 ? `<span class="custom-label">ציר 3:</span><span class="custom-value">${cH3}</span>` : ''}
                        ${cH4 ? `<span class="custom-label">ציר 4:</span><span class="custom-value">${cH4}</span>` : ''}
                        ${cH5 ? `<span class="custom-label">ציר 5:</span><span class="custom-value">${cH5}</span>` : ''}
                    </span>
                </td>
                <td class="no-print"></td>
            </tr>
        `;
    }
    return '';
}

function exportToExcel() {
    let csv = ["\uFEFF", `טופס מידות הזמנה: ${config.orderNumber || ''}`, `לקוח: ${config.customer || ''}`, ""];

    document.querySelectorAll('.card').forEach(card => {
        const header = card.querySelector('h5');
        if (!header) return;
        csv.push(header.innerText.trim());

        const table = card.querySelector('table');
        if (!table) return;

        table.querySelectorAll('tr').forEach(row => {
            const cols = row.querySelectorAll('th, td');
            let rowData = [];
            cols.forEach((col) => {
                if (!col.classList.contains('no-print')) {
                    rowData.push('"' + col.innerText.trim().replace(/"/g, '""') + '"');
                }
            });
            if (rowData.length > 0) csv.push(rowData.join(","));
        });
        csv.push("");
    });

    const blob = new Blob([csv.join("\n")], {type: 'text/csv;charset=utf-8;'});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `מידות_הזמנה_${config.orderNumber || 'export'}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

window.exportToExcel = exportToExcel;

// Сворачивание строки в статический вид
function renderRowStatic($row) {
    if (!$row || !$row.length) return;
    const itemId = $row.attr('data-item-id');

    $row.find('[data-bs-toggle="tooltip"]').each(function () {
        const bs = window.bootstrap;
        if (bs && bs.Tooltip) {
            const inst = bs.Tooltip.getInstance(this);
            if (inst) inst.dispose();
        }
    });

    const rowData = {
        mark: $row.attr('data-mark'),
        place: $row.attr('data-place'),
        width: $row.attr('data-width'),
        height: $row.attr('data-height'),
        wall: $row.attr('data-wall'),
        opening: $row.attr('data-opening'),
        direction: $row.attr('data-direction'),
        bottomCorrection: $row.attr('data-bottom-correction'),
        comment: $row.attr('data-comment'),
        sketchUrl: $row.attr('data-sketch-url'),
        canEdit: $row.attr('data-can-edit') === 'true',
        customLockHeight: $row.attr('data-custom-lock-height'),
        customHinge1: $row.attr('data-custom-hinge1'),
        customHinge2: $row.attr('data-custom-hinge2'),
        customHinge3: $row.attr('data-custom-hinge3'),
        customHinge4: $row.attr('data-custom-hinge4'),
        customHinge5: $row.attr('data-custom-hinge5')
    };

    $row.html(renderStaticRowContent(rowData)).removeClass('edit-mode');
    $(`#custom-row-${itemId}`).remove();
    $(`#display-custom-${itemId}`).remove();

    const customHtml = renderCustomDisplayRow(itemId, rowData);
    if (customHtml) $row.after(customHtml);

    if (window.initTooltips) window.initTooltips($row[0]);
}

// Открытие строки для редактирования
function openEditMode($row) {
    if (!$row || !$row.length || $row.hasClass('edit-mode')) return;

    const canEdit = $row.attr('data-can-edit') === 'true';
    if (!canEdit || $row.hasClass('row-locked')) return;

    const itemId = $row.attr('data-item-id');
    const mark = $row.attr('data-mark') || '';
    const place = $row.attr('data-place') || '';
    const width = $row.attr('data-width') || '';
    const height = $row.attr('data-height') || '';
    const wall = $row.attr('data-wall') || '';
    const opening = $row.attr('data-opening') || '';
    const direction = $row.attr('data-direction') || '';
    const allowedDirection = ($row.attr('data-allowed-direction') || 'BOTH').toUpperCase();
    const bottomCorrection = $row.attr('data-bottom-correction') || '';
    const comment = $row.attr('data-comment') || '';
    const sketchUrl = $row.attr('data-sketch-url') || '';
    const hasFrame = $row.attr('data-has-frame') === 'true';
    const hasDoor = $row.attr('data-has-door') === 'true';

    const customLockHeight = $row.attr('data-custom-lock-height') || '';
    const customHinge1 = $row.attr('data-custom-hinge1') || '';
    const customHinge2 = $row.attr('data-custom-hinge2') || '';
    const customHinge3 = $row.attr('data-custom-hinge3') || '';
    const customHinge4 = $row.attr('data-custom-hinge4') || '';
    const customHinge5 = $row.attr('data-custom-hinge5') || '';

    $row.addClass('edit-mode').attr('data-opened-at', Date.now());
    $(`#display-custom-${itemId}`).addClass('d-none');

    let openingOptions;
    if (allowedDirection === 'IN_ONLY') {
        openingOptions = '<option value="IN" selected>פ</option>';
    } else if (allowedDirection === 'OUT_ONLY') {
        openingOptions = '<option value="OUT" selected>ח</option>';
    } else {
        const activeOpening = opening || 'IN';
        openingOptions = `
            <option value="IN" ${activeOpening === 'IN' ? 'selected' : ''}>פ</option>
            <option value="OUT" ${activeOpening === 'OUT' ? 'selected' : ''}>ח</option>
        `;
    }

    const directionOptions = `
        <option value="">-</option>
        <option value="L" ${direction === 'L' ? 'selected' : ''}>L</option>
        <option value="R" ${direction === 'R' ? 'selected' : ''}>R</option>
    `;

    const sketchBtnClass = sketchUrl ? 'btn-primary' : 'btn-outline-primary';

    const html = `
        <td class="fw-bold bg-light">${mark}</td>
        <td><input type="text" class="form-control form-control-sm" name="place" value="${place}" placeholder="מיקום"></td>
        <td><input type="text" class="form-control form-control-sm numeric-input" name="width" value="${width}" placeholder="רוחב"></td>
        <td><input type="text" class="form-control form-control-sm numeric-input" name="height" value="${height}" placeholder="גובה"></td>
        <td><input type="text" class="form-control form-control-sm numeric-input" name="wall" value="${wall}" ${hasFrame ? '' : 'disabled'} placeholder="משקוף"></td>
        <td>
            <div class="d-flex gap-1">
                <select class="form-select form-select-sm" name="direction" ${hasDoor ? '' : 'disabled'}>${directionOptions}</select>
                <select class="form-select form-select-sm" name="opening" ${hasDoor ? '' : 'disabled'} ${allowedDirection !== 'BOTH' ? 'tabindex="-1"' : ''}>${openingOptions}</select>
            </div>
        </td>
        <td><input type="text" class="form-control form-control-sm numeric-input" name="bottom_correction" value="${bottomCorrection}" placeholder="רווח נוסף"></td>
        <td><input type="text" class="form-control form-control-sm" name="comment" value="${comment}" placeholder="הערה" style="width: 100%; min-width: 100px;"></td>
        <td class="no-print text-nowrap">
            <!-- Кнопка-галочка подтверждения/сохранения -->
            <button type="button" class="btn btn-sm btn-success btn-save-row px-2" data-bs-toggle="tooltip" title="שמור (Enter)">
                <i class="bi bi-check-lg"></i>
            </button>
            <button type="button" class="btn btn-sm btn-outline-primary btn-duplicate" data-bs-toggle="tooltip" title="שכפל מידות לשאר הפריטים">
                <i class="bi bi-files"></i>
            </button>
            <button type="button" class="btn btn-sm btn-outline-info btn-toggle-custom" data-bs-toggle="tooltip" title="גבהים חריגים">
                <i class="bi bi-sliders"></i>
            </button>
            <div class="d-inline-block position-relative">
                <button type="button" class="btn btn-sm ${sketchBtnClass} btn-sketch-upload" data-bs-toggle="tooltip" title="שרטוט">
                    <i class="bi bi-file-earmark-image"></i>
                </button>
                ${sketchUrl ? '<button type="button" class="btn btn-sm btn-danger py-0 px-1 position-absolute top-0 start-0 translate-middle rounded-circle btn-sketch-delete" style="font-size: 8px; z-index: 5;"><i class="bi bi-x"></i></button>' : ''}
                <input type="file" class="d-none sketch-file-input" accept="image/*,application/pdf" name="sketch">
                <input type="hidden" name="delete_sketch" value="false" class="delete-sketch-input">
            </div>
        </td>
    `;

    $row.html(html);

    const customHtml = `
        <tr id="custom-row-${itemId}" class="edit-mode custom-heights-row d-none">
            <td class="bg-light fw-bold small text-center">גובה מותאם</td>
            <td colspan="7">
                <div class="d-flex gap-2 p-1 align-items-center">
                    <div class="input-group input-group-sm"><span class="input-group-text">מנעול</span><input type="text" class="form-control numeric-input" name="custom_lock_height" value="${customLockHeight}"></div>
                    <div class="input-group input-group-sm"><span class="input-group-text">ציר 1</span><input type="text" class="form-control numeric-input" name="custom_hinge1" value="${customHinge1}"></div>
                    <div class="input-group input-group-sm"><span class="input-group-text">ציר 2</span><input type="text" class="form-control numeric-input" name="custom_hinge2" value="${customHinge2}"></div>
                    <div class="input-group input-group-sm"><span class="input-group-text">ציר 3</span><input type="text" class="form-control numeric-input" name="custom_hinge3" value="${customHinge3}"></div>
                    <div class="input-group input-group-sm"><span class="input-group-text">ציר 4</span><input type="text" class="form-control numeric-input" name="custom_hinge4" value="${customHinge4}"></div>
                    <div class="input-group input-group-sm"><span class="input-group-text">ציר 5</span><input type="text" class="form-control numeric-input" name="custom_hinge5" value="${customHinge5}"></div>
                </div>
            </td>
            <td class="no-print"></td>
        </tr>
    `;
    $row.after(customHtml);

    if (window.initTooltips) window.initTooltips($row[0]);
    $row.find('input[name="width"]').focus();
}

// Сохранение строки и переход к следующему действию
function saveRowAndClose($row, onComplete) {
    if (!$row || !$row.length || !$row.hasClass('edit-mode')) {
        if (typeof onComplete === 'function') onComplete();
        return;
    }

    const itemId = $row.attr('data-item-id');
    const $customRow = $(`#custom-row-${itemId}`);
    const formData = new FormData();

    $row.find('input, select').each(function () {
        const curInput = this;
        if (curInput.type === 'file') {
            if (curInput.files[0]) formData.append('sketch', curInput.files[0]);
        } else if (curInput.className && curInput.className.includes('delete-sketch-input')) {
            formData.append('delete_sketch', $(curInput).val());
        } else if (curInput.name) {
            formData.append(curInput.name, $(curInput).val());
        }
    });

    if ($customRow.length) {
        $customRow.find('input').each(function () {
            if (this.name) formData.append(this.name, $(this).val());
        });
    }

    // Блокируем кнопку на время отправки
    const $btnSave = $row.find('.btn-save-row');
    $btnSave.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

    $.ajax({
        url: `/orders/items/${itemId}/update-measurements/`,
        method: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        headers: {'X-CSRFToken': config.csrfToken},
        success: function (response) {
            if (response.status === 'ok') {
                // Обновляем HTML data-атрибуты строки
                $row.attr('data-width', formatNum(formData.get('width')));
                $row.attr('data-height', formatNum(formData.get('height')));
                $row.attr('data-wall', formatNum(formData.get('wall')));
                $row.attr('data-opening', formData.get('opening') || '');
                $row.attr('data-direction', formData.get('direction') || '');
                $row.attr('data-place', formData.get('place') || '');
                $row.attr('data-bottom-correction', formatNum(formData.get('bottom_correction')));
                $row.attr('data-comment', formData.get('comment') || '');

                if (response.sketch_url) {
                    $row.attr('data-sketch-url', response.sketch_url);
                } else if (formData.get('delete_sketch') === 'true') {
                    $row.attr('data-sketch-url', '');
                }

                const customFields = ['custom_lock_height', 'custom_hinge1', 'custom_hinge2', 'custom_hinge3', 'custom_hinge4', 'custom_hinge5'];
                customFields.forEach(f => {
                    $row.attr(`data-${f.replace(/_/g, '-')}`, formatNum(formData.get(f)));
                });

                renderRowStatic($row);
            } else {
                alert(response.message || 'שגיאה בשמירת הנתונים');
                renderRowStatic($row);
            }
        },
        error: function () {
            alert('שגיאת תקשורת עם השרת');
            renderRowStatic($row);
        },
        complete: function () {
            if (typeof onComplete === 'function') {
                onComplete();
            }
        }
    });
}

$(document).ready(function () {

    // Ограничение ввода только числами и точкой
    $(document).on('input', '.numeric-input', function () {
        this.value = this.value.replace(/[^0-9.]/g, '');
        if ((this.value.match(/\./g) || []).length > 1) {
            this.value = this.value.replace(/\.$/, '');
        }
    });

    // 1 & 2. Клик по кнопке с галочкой: сохранение текущей строки
    $(document).on('click', '.btn-save-row', function (e) {
        e.stopPropagation();
        const $row = $(this).closest('tr');
        saveRowAndClose($row);
    });

    // 2 & 3. Клик по строке таблицы
    $(document).on('click', '.clickable-row', function (e) {
        e.stopPropagation();
        const $clickedRow = $(this);

        // Игнорируем внутренние клики по интерактивным элементам редактируемой строки
        if ($(e.target).closest('a, button, input, select, label').length) {
            return;
        }

        // Если строка уже в режиме редактирования — ничего не делаем
        if ($clickedRow.hasClass('edit-mode')) {
            return;
        }

        const $activeRow = $('.item-row.edit-mode');

        if ($activeRow.length) {
            // Если была активна другая строка: сохраняем её, перерисовываем и открываем нажатую
            saveRowAndClose($activeRow, function () {
                openEditMode($clickedRow);
            });
        } else {
            // Если активных строк не было: сразу открываем
            openEditMode($clickedRow);
        }
    });

    // 4. Нажатие клавиши Enter внутри полей ввода
    $(document).on('keydown', '.edit-mode input, .edit-mode select', function (e) {
        if (e.which === 13) {
            e.preventDefault();
            const $currentInput = $(this);
            const $row = $currentInput.closest('tr').hasClass('custom-heights-row')
                ? $currentInput.closest('tr').prev('tr.item-row')
                : $currentInput.closest('tr.item-row');

            // Поиск следующей строки таблицы
            const $allRows = $('.item-row');
            const currentIndex = $allRows.index($row);
            const $nextRow = (currentIndex >= 0 && currentIndex + 1 < $allRows.length)
                ? $allRows.eq(currentIndex + 1)
                : null;

            saveRowAndClose($row, function () {
                if ($nextRow && $nextRow.length && $nextRow.attr('data-can-edit') === 'true' && !$nextRow.hasClass('row-locked')) {
                    openEditMode($nextRow);
                }
            });
        }
    });

    // Клик мимо записей: сохраняем и сворачиваем редактируемую строку
    $(document).on('click', function (e) {
        const $activeRow = $('.item-row.edit-mode');
        if (!$activeRow.length) return;

        // Защита от закрытия при клике внутри активной строки, выпадающих окон, дропдаунов и пикеров
        if ($(e.target).closest('.edit-mode, .custom-heights-row, .tooltip, .modal').length === 0) {
            saveRowAndClose($activeRow);
        }
    });

    // Переключение строки нестандартных высот (замки/петли)
    $(document).on('click', '.btn-toggle-custom', function (e) {
        e.stopPropagation();
        const itemId = $(this).closest('tr').attr('data-item-id');
        $(`#custom-row-${itemId}`).toggleClass('d-none');
    });

    // Загрузка чертежа
    $(document).on('click', '.btn-sketch-upload', function (e) {
        e.stopPropagation();
        $(this).closest('div').find('.sketch-file-input').click();
    });

    $(document).on('change', '.sketch-file-input', function () {
        if (this.files && this.files[0]) {
            $(this).prevAll('.btn-sketch-upload').removeClass('btn-outline-primary').addClass('btn-primary');
        }
    });

    // Удаление чертежа
    $(document).on('click', '.btn-sketch-delete', function (e) {
        e.stopPropagation();
        const $container = $(this).closest('div');
        $container.find('.delete-sketch-input').val('true');
        $container.find('.btn-sketch-upload').removeClass('btn-primary').addClass('btn-outline-primary');
        $(this).remove();
    });

    // Дублирование данных на остальные строки группы
    $(document).on('click', '.btn-duplicate', function (e) {
        e.stopPropagation();
        const $row = $(this).closest('tr');
        const itemId = $row.attr('data-item-id');
        const $customRow = $(`#custom-row-${itemId}`);
        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', config.csrfToken);

        $row.find('input, select').each(function () {
            const curInput = this;
            if (curInput.name && curInput.type !== 'file' && !curInput.className.includes('delete-sketch-input')) {
                formData.append(curInput.name, $(curInput).val());
            }
        });

        if ($customRow.length) {
            $customRow.find('input').each(function () {
                if (this.name) formData.append(this.name, $(this).val());
            });
        }

        if (!confirm('האם להעתיק את הנתונים לכל שאר השורות בקבוצה זו?')) return;

        const $btnDup = $(this);
        $btnDup.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        $.ajax({
            url: `/orders/items/${itemId}/duplicate-measurements/`,
            method: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            headers: {'X-CSRFToken': config.csrfToken},
            success: function (response) {
                if (response.status === 'ok') {
                    location.reload();
                } else {
                    alert(response.message || 'שגיאה בשכפול הנתונים');
                    $btnDup.prop('disabled', false).html('<i class="bi bi-files"></i>');
                }
            },
            error: function () {
                alert('שגיאת תקשורת עם השרת');
                $btnDup.prop('disabled', false).html('<i class="bi bi-files"></i>');
            }
        });
    });

});