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
    const wTop = formatNum(data.width);
    const wBottom = formatNum(data.widthBottom);
    const widthHtml = wBottom
        ? `<span title="רוחב עליון">${wTop}</span><span class="text-muted mx-1">/</span><span class="text-accent" title="רוחב תחתון">${wBottom}</span>`
        : wTop;
    let combinedText = '-';
    if (openingText || directionText) {
        combinedText = `${directionText} | ${openingText}`;
    }

    return `
        <td class="fw-bold meas-mark-cell">${data.mark || ''}</td>
        <td class="field-place small text-start">${data.place || ''}</td>
        <td class="field-width fw-semibold">${widthHtml}</td>
        <td class="field-height fw-semibold">${formatNum(data.height)}</td>
        <td class="field-wall">${formatNum(data.wall)}</td>
        <td class="field-opening small">${combinedText}</td>
        <td class="field-bottom-correction small">${formatNum(data.bottomCorrection)}</td>
        <td class="field-comment small text-start">${data.comment || ''}</td>
        <td class="no-print text-nowrap">
            <div class="d-inline-flex align-items-center justify-content-center gap-1">
                ${data.sketchUrl ? `
                    <a href="${data.sketchUrl}" target="_blank" class="btn btn-sm btn-outline-primary meas-action-btn" data-bs-toggle="tooltip" title="צפה בשרטוט">
                        <i class="bi bi-file-earmark-image"></i>
                    </a>
                ` : ''}
                ${data.canEdit ? `
                    <span class="btn btn-sm btn-light border-0 meas-action-btn text-muted" data-bs-toggle="tooltip" title="לחץ לעריכת שורה">
                        <i class="bi bi-pencil-square"></i>
                    </span>
                ` : ''}
            </div>
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
                <td class="meas-mark-cell"></td>
                <td colspan="7" class="text-start">
                    <span class="ps-3" dir="rtl">
                        ${cLock ? `<span class="custom-label">מנעול:</span><span class="custom-value ms-1 me-3">${cLock}</span>` : ''}
                        ${cH1 ? `<span class="custom-label">ציר 1:</span><span class="custom-value ms-1 me-3">${cH1}</span>` : ''}
                        ${cH2 ? `<span class="custom-label">ציר 2:</span><span class="custom-value ms-1 me-3">${cH2}</span>` : ''}
                        ${cH3 ? `<span class="custom-label">ציר 3:</span><span class="custom-value ms-1 me-3">${cH3}</span>` : ''}
                        ${cH4 ? `<span class="custom-label">ציר 4:</span><span class="custom-value ms-1 me-3">${cH4}</span>` : ''}
                        ${cH5 ? `<span class="custom-label">ציר 5:</span><span class="custom-value ms-1 me-3">${cH5}</span>` : ''}
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

    const blocks = document.querySelectorAll('.meas-group-block');
    const containers = blocks.length ? blocks : document.querySelectorAll('.card');

    containers.forEach(block => {
        const header = block.querySelector('h5');
        if (!header) return;
        csv.push(header.innerText.trim());

        const table = block.querySelector('table');
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
        widthBottom: $row.attr('data-width-bottom'),
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
    const widthBottom = $row.attr('data-width-bottom') || '';
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

    const hasTrapezoid = hasDoor && Boolean(widthBottom);
    const widthCellHtml = hasTrapezoid
        ? `<div class="meas-split-width">
               <input type="text" class="meas-excel-input fw-semibold numeric-input" name="width" value="${width}" placeholder="עליון" title="רוחב עליון">
               <input type="text" class="meas-excel-input fw-semibold numeric-input" name="width_bottom" value="${widthBottom}" placeholder="תחתון" title="רוחב תחתון">
           </div>`
        : `<input type="text" class="meas-excel-input fw-semibold numeric-input" name="width" value="${width}" placeholder="רוחב">`;

    const trapezoidBtnHtml = hasDoor
        ? `<button type="button" class="btn btn-sm ${hasTrapezoid ? 'btn-outline-accent' : 'btn-outline-secondary'} meas-action-btn btn-toggle-trapezoid" data-bs-toggle="tooltip" title="רוחב תחתון (דלת טרפז)">
               <i class="bi bi-distribute-horizontal"></i>
           </button>`
        : '';

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

    const sketchBtnClass = sketchUrl ? 'btn-accent' : 'btn-outline-secondary';

    const html = `
        <td class="fw-bold meas-mark-cell">${mark}</td>
        <td class="meas-edit-td"><input type="text" class="meas-excel-input text-start" name="place" value="${place}" placeholder="מיקום"></td>
        <td class="meas-edit-td">${widthCellHtml}</td>
        <td class="meas-edit-td"><input type="text" class="meas-excel-input fw-semibold numeric-input" name="height" value="${height}" placeholder="גובה"></td>
        <td class="meas-edit-td"><input type="text" class="meas-excel-input numeric-input" name="wall" value="${wall}" ${hasFrame ? '' : 'disabled'} placeholder="משקוף"></td>
        <td class="meas-edit-td">
            <div class="meas-split-select">
                <select class="form-select form-select-sm no-select2 meas-excel-select" name="direction" ${hasDoor ? '' : 'disabled'}>${directionOptions}</select>
                <select class="form-select form-select-sm no-select2 meas-excel-select" name="opening" ${hasDoor ? '' : 'disabled'} ${allowedDirection !== 'BOTH' ? 'tabindex="-1"' : ''}>${openingOptions}</select>
            </div>
        </td>
        <td class="meas-edit-td"><input type="text" class="meas-excel-input numeric-input" name="bottom_correction" value="${bottomCorrection}" placeholder="רווח"></td>
        <td class="meas-edit-td"><input type="text" class="meas-excel-input text-start" name="comment" value="${comment}" placeholder="הערה לשורה..."></td>
        <td class="no-print text-nowrap py-1 px-2">
            <div class="d-inline-flex align-items-center justify-content-center gap-1 meas-actions-wrap">
                <button type="button" class="btn btn-sm btn-primary meas-action-btn btn-save-row" data-bs-toggle="tooltip" title="שמור (Enter)">
                    <i class="bi bi-check-lg"></i>
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary meas-action-btn btn-duplicate" data-bs-toggle="tooltip" title="שכפל מידות לשאר הפריטים">
                    <i class="bi bi-files"></i>
                </button>
                ${trapezoidBtnHtml}
                <button type="button" class="btn btn-sm btn-outline-secondary meas-action-btn btn-toggle-custom" data-bs-toggle="tooltip" title="גבהים חריגים">
                    <i class="bi bi-sliders"></i>
                </button>
                <button type="button" class="btn btn-sm ${sketchBtnClass} meas-action-btn btn-sketch-upload" data-bs-toggle="tooltip" title="העלאת שרטוט">
                    <i class="bi bi-file-earmark-image"></i>
                </button>
                <button type="button" class="btn btn-sm btn-outline-danger meas-action-btn btn-sketch-delete ${sketchUrl ? '' : 'd-none'}" data-bs-toggle="tooltip" title="הסר שרטוט">
                    <i class="bi bi-trash3"></i>
                </button>
                <input type="file" class="d-none sketch-file-input" accept="image/*,application/pdf" name="sketch">
                <input type="hidden" name="delete_sketch" value="false" class="delete-sketch-input">
            </div>
        </td>
    `;

    $row.html(html);

    const customHtml = `
        <tr id="custom-row-${itemId}" class="edit-mode custom-heights-row d-none">
            <td class="meas-mark-cell fw-bold small text-center">גובה מותאם</td>
            <td colspan="7">
                <div class="d-flex gap-2 align-items-center">
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

    if (!formData.has('width_bottom')) {
        formData.append('width_bottom', '');
    }

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
                $row.attr('data-width', formatNum(formData.get('width')));
                $row.attr('data-width-bottom', formatNum(formData.get('width_bottom')));
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

    // Клик по кнопке с галочкой: сохранение текущей строки
    $(document).on('click', '.btn-save-row', function (e) {
        e.stopPropagation();
        const $row = $(this).closest('tr');
        saveRowAndClose($row);
    });

    // Клик по строке таблицы
    $(document).on('click', '.clickable-row', function (e) {
        e.stopPropagation();
        const $clickedRow = $(this);

        if ($(e.target).closest('a, button, input, select, label').length) {
            return;
        }

        if ($clickedRow.hasClass('edit-mode')) {
            return;
        }

        const $activeRow = $('.item-row.edit-mode');

        if ($activeRow.length) {
            saveRowAndClose($activeRow, function () {
                openEditMode($clickedRow);
            });
        } else {
            openEditMode($clickedRow);
        }
    });

    // Нажатие клавиши Enter внутри полей ввода
    $(document).on('keydown', '.edit-mode input, .edit-mode select', function (e) {
        if (e.which === 13) {
            e.preventDefault();
            const $currentInput = $(this);
            const $row = $currentInput.closest('tr').hasClass('custom-heights-row')
                ? $currentInput.closest('tr').prev('tr.item-row')
                : $currentInput.closest('tr.item-row');

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

        if ($(e.target).closest('.edit-mode, .custom-heights-row, .tooltip, .modal').length === 0) {
            saveRowAndClose($activeRow);
        }
    });

    // Переключение строки нестандартных высот (замки/петли)
    $(document).on('click', '.btn-toggle-custom', function (e) {
        e.stopPropagation();
        const itemId = $(this).closest('tr').attr('data-item-id');
        $(`#custom-row-${itemId}`).toggleClass('d-none');
        $(this).toggleClass('btn-outline-secondary btn-outline-accent');
    });

    // Загрузка чертежа
    $(document).on('click', '.btn-sketch-upload', function (e) {
        e.stopPropagation();
        $(this).closest('.meas-actions-wrap').find('.sketch-file-input').click();
    });

    $(document).on('change', '.sketch-file-input', function () {
        if (this.files && this.files[0]) {
            const $wrap = $(this).closest('.meas-actions-wrap');
            $wrap.find('.btn-sketch-upload').removeClass('btn-outline-secondary').addClass('btn-accent');
            $wrap.find('.delete-sketch-input').val('false');
            $wrap.find('.btn-sketch-delete').removeClass('d-none');
        }
    });

    // Удаление / сброс чертежа
    $(document).on('click', '.btn-sketch-delete', function (e) {
        e.stopPropagation();
        const bs = window.bootstrap;
        if (bs && bs.Tooltip) {
            const inst = bs.Tooltip.getInstance(this);
            if (inst) inst.hide();
        }
        const $wrap = $(this).closest('.meas-actions-wrap');
        $wrap.find('.delete-sketch-input').val('true');
        $wrap.find('.sketch-file-input').val('');
        $wrap.find('.btn-sketch-upload').removeClass('btn-accent').addClass('btn-outline-secondary');
        $(this).addClass('d-none');
    });

    // Дублирование данных на остальные строки группы
    $(document).on('click', '.btn-duplicate', async function (e) {
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

        if (!formData.has('width_bottom')) {
            formData.append('width_bottom', '');
        }

        if ($customRow.length) {
            $customRow.find('input').each(function () {
                if (this.name) formData.append(this.name, $(this).val());
            });
        }

        const confirmed = await window.sbConfirm({
            title: 'שכפול מידות לקבוצה',
            message: 'האם להעתיק את המידות והפרמטרים לכל שאר השורות בקבוצה זו? הנתונים הקיימים בשאר השורות יידרסו.',
            variant: 'warning',
            okText: 'שכפל נתונים'
        });
        if (!confirmed) return;

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

    // Переключение второй ширины (трапеция: верх / низ)
    $(document).on('click', '.btn-toggle-trapezoid', function (e) {
        e.stopPropagation();
        const $btn = $(this);
        const $row = $btn.closest('tr');
        const $widthTd = $row.find('input[name="width"]').closest('td');
        const currentTop = $row.find('input[name="width"]').val() || '';
        const $bottomInput = $row.find('input[name="width_bottom"]');

        if ($bottomInput.length) {
            // Сворачиваем обратно в одну ширину
            $widthTd.html(`<input type="text" class="meas-excel-input fw-semibold numeric-input" name="width" value="${currentTop}" placeholder="רוחב">`);
            $btn.removeClass('btn-outline-accent').addClass('btn-outline-secondary');
            $widthTd.find('input[name="width"]').focus();
        } else {
            // Разделяем ячейку на верх и низ
            const savedBottom = $row.attr('data-width-bottom') || '';
            $widthTd.html(`
             <div class="meas-split-width">
                 <input type="text" class="meas-excel-input fw-semibold numeric-input" name="width" value="${currentTop}" placeholder="עליון" title="רוחב עליון">
                 <input type="text" class="meas-excel-input fw-semibold numeric-input" name="width_bottom" value="${savedBottom}" placeholder="תחתון" title="רוחב תחתון">
             </div>
         `);
            $btn.removeClass('btn-outline-secondary').addClass('btn-outline-accent');
            $widthTd.find('input[name="width_bottom"]').focus();
        }
    });


});