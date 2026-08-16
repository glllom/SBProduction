/**
 * Order Measurements Management Script
 * Handles inline editing, AJAX updates, and exporting to Excel.
 * 
 * This script is designed to work with the order_measurements.html template.
 * It uses jQuery for DOM manipulation and AJAX calls.
 */

// Global configuration passed from Django template
const config = window.OrderMeasurementsConfig || {};

/**
 * Formats a number to 1 decimal place, removes .0
 * @param {number|string} val - Value to format
 * @returns {string} Formatted string
 */
const formatNum = (val) => {
    if (!val && val !== 0) return '';
    let n = parseFloat(val);
    if (isNaN(n)) return val;
    // Truncate to 1 decimal place
    n = Math.floor(n * 10) / 10;
    return n % 1 === 0 ? n.toString() : n.toFixed(1);
};

/**
 * Generates the HTML for a static (non-editing) row content.
 * @param {Object} data - Item data
 * @returns {string} HTML string
 */
function renderStaticRowContent(data) {
    const openingText = (data.opening === 'LEFT' ? 'L' : (data.opening === 'RIGHT' ? 'R' : ''));
    const directionText = (data.direction === 'IN' ? 'פנימה' : (data.direction === 'OUT' ? 'החוצה' : ''));
    let combinedText = '-';
    if (openingText || directionText) {
        combinedText = `${openingText} / ${directionText}`;
    }

    return `
        <td class="fw-bold bg-light">${data.mark || ''}</td>
        <td class="field-place small text-start">${data.place || ''}</td>
        <td class="field-width">${formatNum(data.width)}</td>
        <td class="field-height">${formatNum(data.height)}</td>
        <td class="field-wall">${formatNum(data.wall)}</td>
        <td class="field-opening small">${combinedText}</td>
        <td class="field-addition-cut small">${formatNum(data.additionCut)}</td>
        <td class="field-comment small text-start">${data.comment || ''}</td>
        <td class="no-print text-nowrap">
            ${data.sketchUrl ? `
                <a href="${data.sketchUrl}" target="_blank" class="btn btn-sm btn-primary py-0" data-bs-toggle="tooltip" title="צפה בשרטוט עבור פריט זה">
                    <i class="bi bi-file-earmark-image"></i>
                </a>
            ` : ''}
            ${config.canEdit ? '<i class="bi bi-pencil-square opacity-50 ms-2" data-bs-toggle="tooltip" title="עריכת פריט"></i>' : ''}
        </td>
    `;
}

/**
 * Generates the HTML for the custom heights display row.
 * @param {number} itemId - Item ID
 * @param {Object} data - Custom heights data
 * @returns {string} HTML string
 */
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

/**
 * Exports all measurement cards to a CSV file (compatible with Excel).
 * Uses BOM for UTF-8 support in Excel for Hebrew characters.
 */
function exportToExcel() {
    let csv = [];
    csv.push("\uFEFF"); // BOM for Hebrew/UTF-8 support in Excel
    csv.push(`טופס מידות הזמנה: ${config.orderNumber || ''}`);
    csv.push(`לקוח: ${config.customer || ''}`);
    csv.push("");

    document.querySelectorAll('.card').forEach(card => {
        const header = card.querySelector('h5');
        if (!header) return;
        
        csv.push(header.innerText.trim());
        
        const table = card.querySelector('table');
        if (!table) return;
        
        const rows = table.querySelectorAll('tr');
        
        rows.forEach(row => {
            const cols = row.querySelectorAll('th, td');
            let rowData = [];
            cols.forEach((col) => {
                // Skip columns marked as no-print (actions, icons)
                if (!col.classList.contains('no-print')) {
                    rowData.push('"' + col.innerText.trim().replace(/"/g, '""') + '"');
                }
            });
            if (rowData.length > 0) {
                csv.push(rowData.join(","));
            }
        });
        csv.push("");
    });

    const csvContent = csv.join("\n");
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", `מידות_הזמנה_${config.orderNumber || 'export'}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Attach exportToExcel to window so it can be called from onclick in HTML
window.exportToExcel = exportToExcel;

$(document).ready(function() {
    /**
     * Filters input to allow only numbers and a single decimal point.
     * Prevents invalid numeric entry in measurement fields.
     */
    $(document).on('input', '.numeric-input', function() {
        this.value = this.value.replace(/[^0-9.]/g, '');
        if ((this.value.match(/\./g) || []).length > 1) {
            this.value = this.value.replace(/\.$/, '');
        }
    });

    /**
     * Enters edit mode when clicking a row.
     * Replaces static cells with input fields.
     */
    $('.clickable-row').on('click', function(e) {
        if (!config.canEdit) return;
        if ($(this).hasClass('edit-mode')) return;
        // Do not enter edit mode if click was on a link, button, or file input
        if ($(e.target).closest('a, button, input, select').length) return;
        
        const $row = $(this);
        const itemId = $row.data('item-id');
        const data = $row.data();
        
        // Save current HTML to restore if canceled
        $row.data('old-html', $row.html());
        $row.addClass('edit-mode');
        // Hide the static custom heights row while editing
        $(`#display-custom-${itemId}`).addClass('d-none');
        
        const openingOptions = `
            <option value="">-</option>
            <option value="LEFT" ${data.opening === 'LEFT' ? 'selected' : ''}>L</option>
            <option value="RIGHT" ${data.opening === 'RIGHT' ? 'selected' : ''}>R</option>
        `;
        
        const directionOptions = `
            <option value="">-</option>
            <option value="IN" ${data.direction === 'IN' ? 'selected' : ''}>פנימה</option>
            <option value="OUT" ${data.direction === 'OUT' ? 'selected' : ''}>החוצה</option>
        `;
        
        const sketchBtnClass = data.sketchUrl ? 'btn-primary' : 'btn-outline-primary';

        let html = `
            <td class="fw-bold bg-light">${data.mark}</td>
            <td><input type="text" class="form-control form-control-sm" name="place" value="${data.place || ''}" placeholder="מיקום" data-bs-toggle="tooltip" title="מיקום ההתקנה (חדר, קומה, דירה)"></td>
            <td><input type="text" class="form-control form-control-sm numeric-input" name="width" value="${data.width}" placeholder="רוחב" data-bs-toggle="tooltip" title="רוחב פתח אור / כנף במילימטרים"></td>
            <td><input type="text" class="form-control form-control-sm numeric-input" name="height" value="${data.height}" placeholder="גובה" data-bs-toggle="tooltip" title="גובה פתח אור / כנף במילימטרים"></td>
            <td><input type="text" class="form-control form-control-sm numeric-input" name="wall" value="${data.wall}" ${data.hasFrame ? '' : 'disabled'} placeholder="משקוף" data-bs-toggle="tooltip" title="עובי קיר עבור המשקוף במילימטרים"></td>
            <td>
                <div class="d-flex gap-1">
                    <select class="form-select form-select-sm" name="opening" ${data.hasDoor ? '' : 'disabled'}>${openingOptions}</select>
                    <select class="form-select form-select-sm" name="direction" ${data.hasDoor ? '' : 'disabled'}>${directionOptions}</select>
                </div>
            </td>
            <td><input type="text" class="form-control form-control-sm numeric-input" name="addition_cut" value="${data.additionCut || ''}" placeholder="רווח נוסף" data-bs-toggle="tooltip" title="חיתוך תחתון נוסף במילימטרים (לריצוף או שטיח)"></td>
            <td><input type="text" class="form-control form-control-sm" name="comment" value="${data.comment || ''}" placeholder="הערה" style="width: 100%; min-width: 100px;" data-bs-toggle="tooltip" title="הערה ספציפית לפריט זה"></td>
            <td class="text-nowrap">
                <button class="btn btn-sm btn-success btn-save" data-bs-toggle="tooltip" title="שמור שינויים בפריט"><i class="bi bi-check-lg"></i></button>
                <button class="btn btn-sm btn-outline-primary btn-duplicate" data-bs-toggle="tooltip" title="שכפל מידות לשאר הפריטים בקבוצה"><i class="bi bi-files"></i></button>
                <button class="btn btn-sm btn-outline-info btn-toggle-custom" data-bs-toggle="tooltip" title="שינוי גבהי צירים ומנעול חריגים"><i class="bi bi-sliders"></i></button>
                
                <div class="d-inline-block position-relative">
                    <button class="btn btn-sm ${sketchBtnClass} btn-sketch-upload" data-bs-toggle="tooltip" title="העלאת קובץ שרטוט">
                        <i class="bi bi-file-earmark-image"></i>
                    </button>
                    ${data.sketchUrl ? '<button type="button" class="btn btn-sm btn-danger py-0 px-1 position-absolute top-0 start-0 translate-middle rounded-circle btn-sketch-delete" style="font-size: 8px; z-index: 5;" data-bs-toggle="tooltip" title="מחק שרטוט קיים"><i class="bi bi-x"></i></button>' : ''}
                    <input type="file" class="d-none sketch-file-input" accept="image/*,application/pdf">
                    <input type="hidden" name="delete_sketch" value="false" class="delete-sketch-input">
                </div>

                <button class="btn btn-sm btn-outline-secondary btn-cancel" data-bs-toggle="tooltip" title="ביטול שינויים"><i class="bi bi-x-lg"></i></button>
            </td>
        `;
        
        $row.html(html);

        // Add custom heights row for engineering adjustments
        let customHtml = `
            <tr id="custom-row-${itemId}" class="edit-mode custom-heights-row d-none">
                <td class="bg-light fw-bold small text-center" data-bs-toggle="tooltip" title="הגדרת גבהים חריגים של מנעול וצירים">גובה מותאם</td>
                <td colspan="7">
                    <div class="d-flex gap-2 p-1 align-items-center">
                        <div class="input-group input-group-sm" data-bs-toggle="tooltip" title="גובה מרכז מנעול חריג מהרצפה (מ''מ)">
                            <span class="input-group-text">מנעול</span>
                            <input type="text" class="form-control numeric-input" name="custom_lock_height" value="${data.customLockHeight || ''}" placeholder="מנעול (מ''מ)">
                        </div>
                        <div class="input-group input-group-sm" data-bs-toggle="tooltip" title="גובה ציר 1 חריג מהרצפה (מ''מ)">
                            <span class="input-group-text">ציר 1</span>
                            <input type="text" class="form-control numeric-input" name="custom_hinge1" value="${data.customHinge1 || ''}" placeholder="ציר 1">
                        </div>
                        <div class="input-group input-group-sm" data-bs-toggle="tooltip" title="גובה ציר 2 חריג מהרצפה (מ''מ)">
                            <span class="input-group-text">ציר 2</span>
                            <input type="text" class="form-control numeric-input" name="custom_hinge2" value="${data.customHinge2 || ''}" placeholder="ציר 2">
                        </div>
                        <div class="input-group input-group-sm" data-bs-toggle="tooltip" title="גובה ציר 3 חריג מהרצפה (מ''מ)">
                            <span class="input-group-text">ציר 3</span>
                            <input type="text" class="form-control numeric-input" name="custom_hinge3" value="${data.customHinge3 || ''}" placeholder="ציר 3">
                        </div>
                        <div class="input-group input-group-sm" data-bs-toggle="tooltip" title="גובה ציר 4 חריג מהרצפה (מ''מ)">
                            <span class="input-group-text">ציר 4</span>
                            <input type="text" class="form-control numeric-input" name="custom_hinge4" value="${data.customHinge4 || ''}" placeholder="ציר 4">
                        </div>
                        <div class="input-group input-group-sm" data-bs-toggle="tooltip" title="גובה ציר 5 חריג מהרצפה (מ''מ)">
                            <span class="input-group-text">ציר 5</span>
                            <input type="text" class="form-control numeric-input" name="custom_hinge5" value="${data.customHinge5 || ''}" placeholder="ציר 5">
                        </div>
                    </div>
                </td>
                <td class="no-print"></td>
            </tr>
        `;
        $row.after(customHtml);
        
        if (window.initTooltips) {
            window.initTooltips($row[0]);
            window.initTooltips($(`#custom-row-${itemId}`)[0]);
        }
        
        // Auto-focus the first field for faster entry
        $row.find('input[name="place"]').focus();
    });

    /**
     * Toggles the display of the engineering custom heights row.
     */
    $(document).on('click', '.btn-toggle-custom', function(e) {
        e.stopPropagation();
        const itemId = $(this).closest('tr').data('item-id');
        $(`#custom-row-${itemId}`).toggleClass('d-none');
    });

    /**
     * Proxies click to hidden file input for sketch upload.
     */
    $(document).on('click', '.btn-sketch-upload', function(e) {
        e.stopPropagation();
        $(this).closest('div').find('.sketch-file-input').click();
    });

    /**
     * Marks a sketch for deletion in the form data.
     */
    $(document).on('click', '.btn-sketch-delete', function(e) {
        e.stopPropagation();
        const $container = $(this).closest('div');
        $container.find('.delete-sketch-input').val('true');
        $container.find('.btn-sketch-upload').removeClass('btn-primary').addClass('btn-outline-primary');
        $(this).remove();
    });

    /**
     * Changes upload button style when a file is staged for upload.
     */
    $(document).on('change', '.sketch-file-input', function() {
        const file = this.files[0];
        const $btn = $(this).prev('.btn-sketch-upload');
        if (file) {
            $btn.removeClass('btn-outline-primary').addClass('btn-primary');
        }
    });

    /**
     * Cancels editing mode and restores the original row state.
     */
    $(document).on('click', '.btn-cancel', function(e) {
        e.stopPropagation();
        const $row = $(this).closest('tr');
        const itemId = $row.data('item-id');
        
        // Dispose active tooltips before replacing HTML
        $row.find('[data-bs-toggle="tooltip"]').each(function() {
            const inst = bootstrap.Tooltip.getInstance(this);
            if (inst) inst.dispose();
        });
        $(`#custom-row-${itemId}`).find('[data-bs-toggle="tooltip"]').each(function() {
            const inst = bootstrap.Tooltip.getInstance(this);
            if (inst) inst.dispose();
        });

        $row.html($row.data('old-html')).removeClass('edit-mode');
        $(`#custom-row-${itemId}`).remove();
        $(`#display-custom-${itemId}`).removeClass('d-none');
        if (window.initTooltips) window.initTooltips($row[0]);
    });

    /**
     * Validates and saves measurement data via AJAX.
     * On success, updates data attributes and re-renders the static view.
     */
    $(document).on('click', '.btn-save', function(e) {
        e.stopPropagation();
        const $row = $(this).closest('tr');
        const itemId = $row.data('item-id');
        const $customRow = $(`#custom-row-${itemId}`);
        const formData = new FormData();
        
        // Collect data from the main row
        $row.find('input, select').each(function() {
            if (this.type === 'file') {
                if (this.files[0]) formData.append('sketch', this.files[0]);
            } else if (this.className.includes('delete-sketch-input')) {
                formData.append('delete_sketch', $(this).val());
            } else if (this.name) {
                formData.append(this.name, $(this).val());
            }
        });

        // Collect data from the custom heights row if it exists
        if ($customRow.length) {
            $customRow.find('input').each(function() {
                if (this.name) formData.append(this.name, $(this).val());
            });
        }

        const $btnSave = $(this);
        $btnSave.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        $.ajax({
            url: `/orders/items/${itemId}/update-measurements/`,
            method: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            headers: {'X-CSRFToken': config.csrfToken},
            success: function(response) {
                if (response.status === 'ok') {
                    // Dispose tooltips before replacing HTML
                    $row.find('[data-bs-toggle="tooltip"]').each(function() {
                        const inst = bootstrap.Tooltip.getInstance(this);
                        if (inst) inst.dispose();
                    });
                    $customRow.find('[data-bs-toggle="tooltip"]').each(function() {
                        const inst = bootstrap.Tooltip.getInstance(this);
                        if (inst) inst.dispose();
                    });

                    // Update all data attributes for future edits
                    $row.data('width', formatNum(formData.get('width')));
                    $row.data('height', formatNum(formData.get('height')));
                    $row.data('wall', formatNum(formData.get('wall')));
                    $row.data('opening', formData.get('opening'));
                    $row.data('direction', formData.get('direction'));
                    $row.data('place', formData.get('place'));
                    $row.data('addition-cut', formatNum(formData.get('addition_cut')));
                    $row.data('comment', formData.get('comment'));
                    $row.data('sketch-url', response.sketch_url);
                    
                    const customFields = ['custom_lock_height', 'custom_hinge1', 'custom_hinge2', 'custom_hinge3', 'custom_hinge4', 'custom_hinge5'];
                    customFields.forEach(f => {
                        $row.data(f.replace(/_/g, '-'), formatNum(formData.get(f)));
                    });

                    // Update UI
                    const updatedData = $row.data();
                    $row.html(renderStaticRowContent(updatedData)).removeClass('edit-mode');
                    $customRow.remove();
                    $(`#display-custom-${itemId}`).remove();

                    // Render custom heights summary row if any values are set
                    const customHtml = renderCustomDisplayRow(itemId, updatedData);
                    if (customHtml) $row.after(customHtml);
                    if (window.initTooltips) window.initTooltips($row[0]);

                    // Auto-advance: Click the next row to enter edit mode immediately
                    const $allRows = $('.clickable-row');
                    const currentIndex = $allRows.index($row);
                    if (currentIndex < $allRows.length - 1) {
                        $allRows.eq(currentIndex + 1).click();
                    }
                } else {
                    alert('שגיאה בשמירה');
                    $btnSave.prop('disabled', false).html('<i class="bi bi-check-lg"></i>');
                }
            },
            error: function() {
                alert('שגיאת תקשורת עם השרת');
                $btnSave.prop('disabled', false).html('<i class="bi bi-check-lg"></i>');
            }
        });
    });

    /**
     * Copies measurements from current row to all other items in the same product group.
     */
    $(document).on('click', '.btn-duplicate', function(e) {
        e.stopPropagation();
        const $row = $(this).closest('tr');
        const itemId = $row.data('item-id');
        const formData = {};
        
        $row.find('input, select').each(function() {
            if (this.name && this.type !== 'file') {
                formData[this.name] = $(this).val();
            }
        });

        if (!confirm('האם להעתיק את הנתונים לכל שאר השורות בקבוצה זו?')) return;

        const $btnDup = $(this);
        $btnDup.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        $.ajax({
            url: `/orders/items/${itemId}/duplicate-measurements/`,
            method: 'POST',
            data: formData,
            headers: {'X-CSRFToken': config.csrfToken},
            success: function(response) {
                if (response.status === 'ok') {
                    // Reloading is the most reliable way to sync labels, data attributes, and marks.
                    location.reload();
                } else {
                    alert('Ошибка при дублировании');
                    $btnDup.prop('disabled', false).html('<i class="bi bi-files"></i>');
                }
            },
            error: function() {
                alert('Ошибка связи с сервером');
                $btnDup.prop('disabled', false).html('<i class="bi bi-files"></i>');
            }
        });
    });
    
    /**
     * Prevents row click events when interacting with form controls inside a row.
     */
    $(document).on('click', 'input, select', function(e) {
        e.stopPropagation();
    });
    
    /**
     * Allows submitting the current row by pressing the Enter key.
     */
    $(document).on('keypress', 'input', function(e) {
        if (e.which === 13) {
            $(this).closest('tr').find('.btn-save').click();
        }
    });
});
