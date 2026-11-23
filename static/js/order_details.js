/* global bootstrap */
const orderDetailConfig = window.OrderDetailConfig || {};
const orderId = orderDetailConfig.orderId || '';
const canEdit = Boolean(orderDetailConfig.canEdit);
const orderSeriesId = orderDetailConfig.orderSeriesId || '';
const orderFrontId = orderDetailConfig.orderFrontId || '';
const orderIsFramesToPaint = Boolean(orderDetailConfig.orderIsFramesToPaint);
const orderStatus = orderDetailConfig.orderStatus || '';
const csrfToken = orderDetailConfig.csrfToken || '';
const familyConfig = orderDetailConfig.familyConfig || {};
const orderUrls = orderDetailConfig.urls || {};

function setColorTBD(fieldId) {
    const el = document.getElementById(fieldId);
    if (el) {
        el.value = 'לפי בחירת לקוח';
        el.dispatchEvent(new Event('input', {bubbles: true}));
    }
}

function transferOrderToProduction(btn, url) {
    window.sbConfirm({
        title: 'העברה לייצור',
        message: 'האם להעביר את ההזמנה לתהליך ייצור?',
        variant: 'primary',
        okText: 'העבר לייצור',
        cancelText: 'ביטול'
    }).then(function (confirmed) {
        if (!confirmed) return;

        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>מעביר לייצור...';

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json'
            }
        })
            .then(function (response) {
                return response.json().then(function (data) {
                    if (response.ok && data['status'] === 'ok') {
                        window.open(data['master_report_url'], '_blank');
                        window.location.reload();
                    } else {
                        const errors = data['errors'] || [data['message'] || 'שגיאה בהעברה לייצור'];
                        window.sbAlert('לא ניתן להעביר לייצור:\n• ' + errors.join('\n• '), 'שגיאה בהעברה לייצור', 'danger');
                        btn.disabled = false;
                        btn.innerHTML = originalHtml;
                    }
                });
            })
            .catch(function (err) {
                console.error(err);
                window.sbAlert('שגיאת תקשורת עם השרת', 'שגיאת תקשורת', 'danger');
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            });
    });
}

window.setColorTBD = setColorTBD;
window.transferOrderToProduction = transferOrderToProduction;

$(document).ready(function () {
    const $saveSpecGroupName = $('#saveSpecGroupName');
    const $saveSpecGroupDetails = $('#saveSpecGroupDetails');
    const $saveSpecGroupQty = $('#saveSpecGroupQty');
    const $saveSpecNameInput = $('#saveSpecNameInput');
    const $saveSpecDescInput = $('#saveSpecDescInput');
    const $saveSpecForm = $('#saveSpecForm');
    const $loadSpecTargetGroupId = $('#loadSpecTargetGroupId');
    const $loadSpecTargetBadge = $('#loadSpecTargetBadge');
    const $specLoadingIndicator = $('#specLoadingIndicator');
    const $specCardsGrid = $('#specCardsGrid');
    const $specEmptyState = $('#specEmptyState');
    const $groupModal = $('#groupModal');

    function postFormAjax(url, paramsObj) {
        const payload = Object.assign({csrfmiddlewaretoken: csrfToken}, paramsObj || {});
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: new URLSearchParams(payload)
        }).then(function (res) {
            return res.json();
        });
    }

    // --- Раскрытие/скрытие строк позиций в карточке группы ---
    $('.btn-toggle-items').on('click', function () {
        const $btn = $(this);
        const groupId = $btn.data('group-id');
        const $allRows = $('.item-row-' + groupId);
        const $hiddenRows = $allRows.filter('.d-none');

        if ($hiddenRows.length) {
            $hiddenRows.removeClass('d-none');
            $btn.text('הצג פחות');
        } else {
            $allRows.each(function (index) {
                if (index >= 4) $(this).addClass('d-none');
            });
            $btn.text('הצג עוד... (' + ($allRows.length - 4) + ')');
        }
    });

    // --- Модалка быстрого редактирования отдельной двери ---
    $('.btn-edit-item').on('click', function () {
        const $btn = $(this);
        const itemId = $btn.data('item-id');
        const familyId = $btn.data('family-id');
        const mark = $btn.data('item-mark');
        const sketchUrl = $btn.data('sketch-url');

        $('#editItemForm').attr('action', '/orders/items/' + itemId + '/edit/');
        $('#modalItemMarkDisplay').text(mark);
        $('#id_item_mark').val(mark);
        $('#id_item_width').val($btn.data('width'));
        $('#id_item_height').val($btn.data('height'));
        $('#id_item_wall').val($btn.data('wall'));
        $('#id_item_direction').val($btn.data('direction'));
        $('#id_item_opening').val($btn.data('opening'));
        $('#id_item_addition_cut').val($btn.data('addition-cut'));
        $('#id_item_place').val($btn.data('place'));
        $('#id_item_comment').val($btn.data('comment'));
        $('#id_item_lock').val($btn.data('lock'));
        $('#id_item_h1').val($btn.data('h1'));
        $('#id_item_h2').val($btn.data('h2'));
        $('#id_item_h3').val($btn.data('h3'));
        $('#id_item_h4').val($btn.data('h4'));
        $('#id_item_h5').val($btn.data('h5'));

        if (sketchUrl) {
            $('#sketchLink').attr('href', sketchUrl);
            $('#currentSketchDisplay').removeClass('d-none');
        } else {
            $('#currentSketchDisplay').addClass('d-none');
        }

        const config = familyConfig[familyId] || {has_door: true, has_frame: true};
        const showDims = config.has_door || config.has_frame;
        $('.field-wall').toggle(config.has_frame);
        $('.field-door').toggle(config.has_door);
        $('.field-dims').toggle(showDims);
        $('.field-place').toggle(showDims);
    });

    // --- Модалка добавления / редактирования группы (#groupModal) ---
    $('#groupModal input, #groupModal select, #groupModal textarea').each(function () {
        const $el = $(this);
        if ($el.is(':checkbox') || $el.is(':radio')) {
            $el.addClass('form-check-input');
        } else if ($el.is('select')) {
            $el.addClass('form-select');
        } else {
            $el.addClass('form-control');
        }
    });

    function getGroupFormState($form) {
        const $disabled = $form.find(':disabled');
        $disabled.prop('disabled', false);
        const state = $form.serialize();
        $disabled.prop('disabled', true);
        return state;
    }

    $(document).on('click', '[data-bs-target="#groupModal"]', function () {
        const $btn = $(this);
        const isEdit = $btn.hasClass('btn-edit-group');
        const $form = $('#groupForm');
        const $label = $('#groupModalLabel');
        const $submitBtn = $('#groupModalSubmitBtn');
        const $customizeBtn = $('#groupModalCustomizeBtn');

        $groupModal.data('mode', isEdit ? 'edit' : 'add');
        $groupModal.data('force-close', false);

        if (isEdit) {
            $label.text('עריכת קבוצה');
            $submitBtn.text('שמור שינויים');
            $form.attr('action', $btn.attr('data-edit-url'));
            $form[0].reset();

            const canEditGroup = $btn.attr('data-can-edit') !== 'false';
            $customizeBtn.toggleClass('d-none', !canEditGroup).prop('disabled', !canEditGroup);

            $groupModal.find('input[name="quantity"]').val($btn.attr('data-quantity'));
            $groupModal.find('textarea[name="comments"]').val($btn.attr('data-comments'));
            $groupModal.find('input[name="is_split_installation"]').prop('checked', $btn.attr('data-is-split') === 'true');

            const panelPaint = $btn.attr('data-panel-paint-option') || 'MAIN_COLOR';
            $groupModal.find('select[name="panel_paint_option"]').val(panelPaint).trigger('change');

            const isDiffSides = $btn.attr('data-is-diff-sides') === 'true';
            $groupModal.find('input[name="is_door_inside_different_color"]').prop('checked', isDiffSides).trigger('change');

            $groupModal.find('input[name="color_panel_outside"]').val($btn.attr('data-color-panel-outside') || '');
            $groupModal.find('input[name="color_panel_inside"]').val($btn.attr('data-color-panel-inside') || '');

            const framePaint = $btn.attr('data-frame-paint-option') || 'NO_PAINT';
            $groupModal.find('select[name="frame_paint_option"]').val(framePaint).trigger('change');
            $groupModal.find('input[name="color_frames"]').val($btn.attr('data-color-frames') || '');

            const productId = $btn.attr('data-product-id');
            const productName = $btn.attr('data-product-name');
            const productCode = $btn.attr('data-product-code');
            if (productId) {
                const $productSelect = $groupModal.find('select[name="product"]');
                if ($productSelect.find('option[value="' + productId + '"]').length === 0) {
                    $productSelect.append('<option value="' + productId + '">' + productName + '</option>');
                }
                $productSelect.val(productId);
                $groupModal.find('.product-info-display').html(
                    '<span class="sb-product-found fw-semibold"><i class="bi bi-check-circle-fill me-1"></i>' +
                    productName + ' (' + productCode + ')</span>'
                );
            }

            $groupModal.find('select[name="product_family"]').attr('data-initial-value', $btn.attr('data-product-family'));
            $groupModal.find('select[name="product_type"]').val($btn.attr('data-product-type')).trigger('change');

            $groupModal.find('select[name="front"]').attr('data-initial-value', $btn.attr('data-front'));
            $groupModal.find('select[name="basic_color_frames"]').attr('data-initial-value', $btn.attr('data-basic-color-frames'));
            $groupModal.find('select[name="series"]').val($btn.attr('data-series')).trigger('change');

            const structuralSelectors =
                'select[name="product_type"], select[name="product_family"], select[name="series"], ' +
                'select[name="front"], select[name="basic_color_frames"], select[name="product"], ' +
                'input[name="quantity"], input[name="is_split_installation"]';

            if (!canEditGroup) {
                $groupModal.find(structuralSelectors).prop('disabled', true);
                $groupModal.find(
                    'select[name="panel_paint_option"], input[name="is_door_inside_different_color"], ' +
                    'input[name="color_panel_outside"], input[name="color_panel_inside"], ' +
                    'select[name="frame_paint_option"], input[name="color_frames"]'
                ).prop('disabled', false);

                if ($groupModal.find('.alert-grace-period').length === 0) {
                    $groupModal.find('.modal-body').prepend(
                        '<div class="alert alert-warning alert-grace-period mb-2 p-1" role="alert">' +
                        '<i class="bi bi-lock-fill me-2"></i> הקבוצה נעולה לעריכה כללית (עבר תאריך הייצור). ' +
                        'ניתן לערוך <strong>נתוני צביעה בלבד</strong>.</div>'
                    );
                }
            } else {
                $groupModal.find('input, select, textarea').prop('disabled', false);
                $groupModal.find('.alert-grace-period').remove();
            }
        } else {
            $label.text('הוספת קבוצת דלתות');
            $submitBtn.text('הוסף קבוצה');
            $customizeBtn.removeClass('d-none').prop('disabled', false);
            $form.attr('action', orderUrls.groupAdd || ('/orders/' + orderId + '/groups/add/'));
            $form[0].reset();

            $groupModal.find('input, select, textarea').prop('disabled', false);
            $groupModal.find('.alert-grace-period').remove();
            $groupModal.find('select').removeAttr('data-initial-value');
            $groupModal.find('.product-info-display').html('<small class="text-secondary">בחר סדרה ומשפחה לחיפוש מוצר...</small>');

            if (orderSeriesId) {
                $groupModal.find('select[name="series"]').val(orderSeriesId).trigger('change');
            }

            $groupModal.find('select[name="panel_paint_option"]').val('MAIN_COLOR').trigger('change');
            $groupModal.find('input[name="is_door_inside_different_color"]').prop('checked', false).trigger('change');
            $groupModal.find('input[name="color_panel_outside"]').val('');
            $groupModal.find('input[name="color_panel_inside"]').val('');

            $groupModal.find('select[name="frame_paint_option"]').val(
                orderIsFramesToPaint ? 'MAIN_COLOR' : 'NO_PAINT'
            ).trigger('change');
            $groupModal.find('input[name="color_frames"]').val('');
        }
    });

    $groupModal.on('show.bs.modal', function () {
        const $form = $(this).find('form');
        setTimeout(function () {
            $form.data('initial-state', getGroupFormState($form));
        }, 100);
    });

    $groupModal.on('hide.bs.modal', function (e) {
        if ($(this).data('force-close')) {
            return;
        }
        const $form = $(this).find('form');
        const initialState = $form.data('initial-state');
        const currentState = getGroupFormState($form);

        if (initialState !== currentState) {
            e.preventDefault();
            e.stopPropagation();

            if ($(this).data('confirming-close')) {
                return;
            }
            $(this).data('confirming-close', true);

            window.sbConfirm({
                title: 'סגירה ללא שמירה',
                message: 'יש שינויים שלא נשמרו. האם אתה בטוח שברצונך לסגור?',
                variant: 'warning',
                okText: 'סגור ללא שמירה',
                cancelText: 'המשך עריכה'
            }).then(function (confirmed) {
                $groupModal.data('confirming-close', false);
                if (confirmed) {
                    $groupModal.data('force-close', true);
                    bootstrap.Modal.getOrCreateInstance($groupModal[0]).hide();
                }
            });
        }
    });

    // Единый обработчик отправки #groupForm (валидация + подтверждение через sbConfirm + разблокировка полей)
    $('#groupForm').on('submit', function (e) {
        const $form = $(this);

        if ($form.data('confirmed-submit')) {
            $form.data('confirmed-submit', false);
            $groupModal.data('force-close', true);
            $form.find(':disabled').prop('disabled', false);
            return true;
        }

        const productType = $groupModal.find('select[name="product_type"]').val();
        const productFamily = $groupModal.find('select[name="product_family"]').val();
        const series = $groupModal.find('select[name="series"]').val();
        const front = $groupModal.find('select[name="front"]').val();
        const quantity = $groupModal.find('input[name="quantity"]').val();

        const missingFields = [];
        if (!productType) missingFields.push('סוג מוצר');
        if (!productFamily) missingFields.push('משפחת מוצר');
        if (!series) missingFields.push('סדרה');
        if (!front) missingFields.push('חזית');
        if (!quantity || parseInt(quantity, 10) <= 0) missingFields.push('כמות תקינה');

        if (missingFields.length > 0) {
            e.preventDefault();
            window.sbAlert(
                'אנא מלא את השדות חובה הבאים: ' + missingFields.join(', '),
                'שדות חובה חסרים',
                'warning'
            );
            return false;
        }

        const initialState = $form.data('initial-state');
        const currentState = getGroupFormState($form);
        if (initialState !== currentState) {
            e.preventDefault();
            const submitter = e.originalEvent ? e.originalEvent.submitter : null;
            const isCustomize = submitter && submitter.value === 'customize';

            window.sbConfirm({
                title: isCustomize ? 'שמירה ומעבר לשדרוגים' : 'שמירת שינויים',
                message: isCustomize
                    ? 'לשמור את הקבוצה ולעבור להגדרת שינויים ושדרוגים?'
                    : 'לשמור שינויים?',
                variant: 'primary',
                okText: 'שמור',
                cancelText: 'ביטול'
            }).then(function (confirmed) {
                if (!confirmed) return;
                $form.data('confirmed-submit', true);
                $groupModal.data('force-close', true);
                $form.find(':disabled').prop('disabled', false);
                if (typeof $form[0].requestSubmit === 'function') {
                    $form[0].requestSubmit(submitter || undefined);
                } else {
                    if (submitter && submitter.name) {
                        $('<input>').attr({
                            type: 'hidden',
                            name: submitter.name,
                            value: submitter.value
                        }).appendTo($form);
                    }
                    $form[0].submit();
                }
            });
            return false;
        }

        $groupModal.data('force-close', true);
        $form.find(':disabled').prop('disabled', false);
    });

    // --- Каскадные списки каталога (Тип -> Семейство -> Серия -> Модель / Фасад / Цвет коробки) ---
    function updateFronts($container, seriesId) {
        const $frontSelect = $container.find('select[name="front"]');
        if (!$frontSelect.length) return;

        if (!seriesId) {
            $frontSelect.html('<option value="">---------</option>').trigger('change');
            return;
        }

        const currentVal = $frontSelect.val();
        fetch('/catalog/api/fronts/?series=' + seriesId)
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                let options = '<option value="">---------</option>';
                const fronts = (Array.isArray(data) ? data : data['results']) || [];
                fronts.forEach(function (front) {
                    const desc = front['description'] || '';
                    const finishType = front['finish_type'] || 'PAINT';
                    options +=
                        '<option value="' + front['id'] + '" data-finish-type="' + finishType +
                        '" data-description="' + desc + '" title="' + desc + '">' + front['name'] + '</option>';
                });
                $frontSelect.html(options);

                const $modalEl = $container.closest('#groupModal');
                const isNew = $modalEl.length > 0 && $modalEl.data('mode') === 'add';
                const initialVal = $frontSelect.attr('data-initial-value');

                if (currentVal && fronts.some(function (f) {
                    return String(f['id']) === String(currentVal);
                })) {
                    $frontSelect.val(currentVal);
                } else if (!isNew && initialVal && fronts.some(function (f) {
                    return String(f['id']) === String(initialVal);
                })) {
                    $frontSelect.val(initialVal);
                } else if (isNew && seriesId === orderSeriesId && orderFrontId && fronts.some(function (f) {
                    return String(f['id']) === String(orderFrontId);
                })) {
                    $frontSelect.val(orderFrontId);
                }
                $frontSelect.trigger('change');
            })
            .catch(function (error) {
                console.error('Error fetching fronts:', error);
            });
    }

    function updateFrameColors($container, seriesId, familyId) {
        const $basicColorFramesSelect = $container.find('select[name="basic_color_frames"]');
        if (!$basicColorFramesSelect.length) return;

        const $modalEl = $container.closest('#groupModal');
        const isGroupLocked = $modalEl.length > 0 && $modalEl.find('input[name="quantity"]').is(':disabled');

        if (!seriesId || !familyId || isGroupLocked) {
            $basicColorFramesSelect.prop('disabled', true);
            if (isGroupLocked) {
                if (window.jQuery && $basicColorFramesSelect.data('select2')) {
                    $basicColorFramesSelect.trigger('change.select2');
                }
                return;
            }
            $basicColorFramesSelect.html('<option value="">---------</option>').val('').trigger('change');
            return;
        }

        const url = '/catalog/api/frame-colors/?series=' + seriesId + '&family=' + familyId;
        const currentVal = $basicColorFramesSelect.val();
        const initialVal = $basicColorFramesSelect.attr('data-initial-value');
        const isNew = $modalEl.length > 0 && $modalEl.data('mode') === 'add';

        fetch(url)
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                let options = '<option value="">---------</option>';
                const colors = (Array.isArray(data) ? data : data['results']) || [];

                if (colors.length === 0) {
                    $basicColorFramesSelect.prop('disabled', true).html(options).val('').trigger('change');
                } else {
                    $basicColorFramesSelect.prop('disabled', false);
                    colors.forEach(function (color) {
                        const desc = color['sku'] || color['description'] || '';
                        options += '<option value="' + color['id'] + '" data-description="' + desc + '" title="' + desc + '">' + color['name'] + '</option>';
                    });
                    $basicColorFramesSelect.html(options);

                    if (currentVal && colors.some(function (c) {
                        return String(c['id']) === String(currentVal);
                    })) {
                        $basicColorFramesSelect.val(currentVal);
                    } else if (!isNew && initialVal && colors.some(function (c) {
                        return String(c['id']) === String(initialVal);
                    })) {
                        $basicColorFramesSelect.val(initialVal);
                    } else {
                        $basicColorFramesSelect.val(colors[0]['id']);
                    }
                    $basicColorFramesSelect.trigger('change');
                }
            })
            .catch(function (error) {
                console.error('Error fetching frame colors:', error);
                $basicColorFramesSelect.prop('disabled', true);
            });
    }

    function updateProductModel($container) {
        const $seriesSelect = $container.find('select[name="series"]');
        const $familySelect = $container.find('select[name="product_family"]');
        const $productSelect = $container.find('select[name="product"]');
        const $splitCheckbox = $container.find('input[name="is_split_installation"]');
        const $display = $container.find('.product-info-display');
        const $submitBtn = $container.closest('form').find('button[type="submit"]');

        if (!$seriesSelect.length || !$familySelect.length || !$productSelect.length) return;

        const seriesId = $seriesSelect.val();
        const familyId = $familySelect.val();

        if (!seriesId || !familyId) {
            if ($display.length) {
                $display.html('<small class="text-muted">בחר סדרה ומשפחה לחיפוש מוצר...</small>');
            }
            if ($productSelect.val() !== '') {
                $productSelect.val('');
                if ($productSelect.hasClass('select2-hidden-accessible')) {
                    $productSelect.trigger('change.select2');
                }
            }
            if ($splitCheckbox.length) {
                $splitCheckbox.prop('disabled', true).prop('checked', false);
            }
            return;
        }

        fetch('/catalog/api/models/?series=' + seriesId + '&family=' + familyId)
            .then(function (response) {
                if (!response.ok) throw new Error('Network response was not ok');
                return response.json();
            })
            .then(function (data) {
                const models = (Array.isArray(data) ? data : data['results']) || [];

                if (models.length > 0) {
                    const model = models[0];
                    const desc = model['description'] || '';
                    const supportsSplit = Boolean(model['supports_split_installation']);

                    if ($display.length) {
                        $display.html(
                            '<span class="sb-product-found fw-semibold" data-bs-toggle="tooltip" title="' + (desc || model['name']) + '">' +
                            '<i class="bi bi-check-circle-fill me-1"></i>' + model['name'] + ' (' + model['code'] + ')</span>'
                        );
                        if (window['initTooltips']) window['initTooltips']($display[0]);
                    }

                    if ($productSelect.find('option[value="' + model['id'] + '"]').length === 0) {
                        $productSelect.append('<option value="' + model['id'] + '" data-description="' + desc + '">' + model['name'] + '</option>');
                    }

                    if (String($productSelect.val()) !== String(model['id'])) {
                        $productSelect.val(model['id']);
                        if ($productSelect.hasClass('select2-hidden-accessible')) {
                            $productSelect.trigger('change.select2');
                        }
                    }

                    if ($splitCheckbox.length) {
                        const canUseSplit = ['NEW', 'PHASE1_PRODUCTION'].includes(orderStatus);
                        if (canUseSplit && supportsSplit) {
                            $splitCheckbox.prop('disabled', false).prop('checked', true);
                        } else {
                            $splitCheckbox.prop('disabled', true).prop('checked', false);
                        }
                    }
                    $submitBtn.prop('disabled', false);
                } else {
                    if ($display.length) {
                        $display.html('<span class="text-danger"><i class="bi bi-exclamation-triangle-fill me-1"></i> מוצר לא נמצא לשילוב זה</span>');
                    }
                    if ($productSelect.val() !== '') {
                        $productSelect.val('');
                        if ($productSelect.hasClass('select2-hidden-accessible')) {
                            $productSelect.trigger('change.select2');
                        }
                    }
                    $submitBtn.prop('disabled', true);
                }
            })
            .catch(function (error) {
                console.error('Error fetching product model:', error);
                $submitBtn.prop('disabled', false);
            });
    }

    $(document).on('change', 'select[name="product_type"]', function () {
        const $typeSelect = $(this);
        const typeId = $typeSelect.val();
        const $container = $typeSelect.closest('.modal-body, form');
        const $familySelect = $container.find('select[name="product_family"]');

        if (!typeId) {
            $familySelect.html('<option value="">---------</option>').trigger('change');
            return;
        }

        const currentVal = $familySelect.val();
        const initialVal = $familySelect.attr('data-initial-value');

        fetch('/catalog/api/families/?type=' + typeId)
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                let options = '<option value="">---------</option>';
                const families = (Array.isArray(data) ? data : data['results']) || [];
                families.forEach(function (family) {
                    const desc = family['description'] || '';
                    options += '<option value="' + family['id'] + '" data-description="' + desc + '" title="' + desc + '">' + family['name'] + '</option>';
                });
                $familySelect.html(options);

                if (currentVal && families.some(function (f) {
                    return String(f['id']) === String(currentVal);
                })) {
                    $familySelect.val(currentVal);
                } else if (initialVal && families.some(function (f) {
                    return String(f['id']) === String(initialVal);
                })) {
                    $familySelect.val(initialVal);
                }

                $familySelect.trigger('change');
            })
            .catch(function (error) {
                console.error('Error fetching families:', error);
            });
    });

    $(document).on('change', 'select[name="series"]', function (e) {
        if (e.namespace === 'select2') return;
        const $container = $(this).closest('.modal-body, form, .card-body');
        if (!$container.length) return;

        const seriesId = $(this).val();
        const familyId = $container.find('select[name="product_family"]').val();

        updateFronts($container, seriesId);
        updateFrameColors($container, seriesId, familyId);
        updateProductModel($container);
    });

    $(document).on('change', 'select[name="product_family"]', function (e) {
        if (e.namespace === 'select2') return;
        const $container = $(this).closest('.modal-body, form, .card-body');
        if (!$container.length) return;

        const familyId = $(this).val();
        const seriesId = $container.find('select[name="series"]').val();

        updateFrameColors($container, seriesId, familyId);
        updateProductModel($container);
    });

    // --- Логика покраски полотна и коробки в модалке группы ---
    function setupGroupPaintingLogic($modal) {
        const $frameSelect = $modal.find('select[name="frame_paint_option"]');
        const $frameWrap = $modal.find('#group-frame-special-color-wrap');

        const $panelSelect = $modal.find('select[name="panel_paint_option"]');
        const $panelWrap = $modal.find('#group-panel-special-color-wrap');
        const $diffWrap = $modal.find('#group-diff-sides-switch-wrap');
        const $diffToggle = $modal.find('input[name="is_door_inside_different_color"]');
        const $insideWrap = $modal.find('#group-panel-inside-wrap');
        const $labelOut = $modal.find('#group-label-panel-out');
        const $labelIn = $modal.find('#group-panel-inside-wrap label');
        const $inputOut = $modal.find('input[name="color_panel_outside"]');
        const $inputIn = $modal.find('input[name="color_panel_inside"]');
        const $frontSelect = $modal.find('select[name="front"]');
        const $panelTitle = $panelSelect.closest('.col-md-6').find('.form-label').first();

        function syncColors() {
            $frameWrap.toggle($frameSelect.val() === 'SPECIAL_COLOR');

            const finishType = $frontSelect.find('option:selected').attr('data-finish-type') || 'PAINT';
            const isDiff = $diffToggle.is(':checked');

            $('#group-no-paint-notice').remove();

            if (finishType === 'NO_PAINT') {
                $panelTitle.html('גימור כנף: <i class="bi bi-info-circle help-hint-icon"></i>');
                $panelSelect.hide().val('NO_PAINT');
                $panelWrap.hide();
                $diffWrap.hide();
                $insideWrap.hide();
                $inputOut.val('');
                $inputIn.val('');
                $panelSelect.after('<div id="group-no-paint-notice" class="badge bg-secondary p-2 mt-1">ללא צבע (בסיס)</div>');
            } else {
                $panelSelect.show();

                if (finishType === 'FORMICA') {
                    $panelTitle.html('גימור פורמייקה: <i class="bi bi-info-circle help-hint-icon"></i>');
                    $inputOut.attr('placeholder', 'מספר פורמייקה');
                    $inputIn.attr('placeholder', 'מספר פורמייקה פנים');
                    $labelOut.text(isDiff ? 'מספר פורמייקה (חוץ):' : 'מספר פורמייקה:');
                    $labelIn.text('מספר פורמייקה (פנים):');
                } else {
                    $panelTitle.html('צביעת כנף: <i class="bi bi-info-circle help-hint-icon"></i>');
                    $inputOut.attr('placeholder', 'קוד צבע');
                    $inputIn.attr('placeholder', 'קוד צבע פנים');
                    $labelOut.text(isDiff ? 'גוון כנף חוץ:' : 'גוון כנף (דו-צדדי):');
                    $labelIn.text('גוון כנף צד פנים:');
                }

                if ($panelSelect.val() === 'SPECIAL_COLOR') {
                    $panelWrap.show();
                    $diffWrap.show();
                    $insideWrap.toggle(isDiff);
                } else {
                    $panelWrap.hide();
                    $diffWrap.hide();
                    $insideWrap.hide();
                }
            }
        }

        $frameSelect.off('change.groupPaint').on('change.groupPaint', syncColors);
        $panelSelect.off('change.groupPaint').on('change.groupPaint', syncColors);
        $diffToggle.off('change.groupPaint').on('change.groupPaint', syncColors);
        $frontSelect.off('change.groupPaint').on('change.groupPaint', syncColors);

        $modal.find('#btn-group-copy-door').off('click.groupCopy').on('click.groupCopy', function () {
            $modal.find('input[name="color_frames"]').val($modal.find('input[name="color_panel_outside"]').val());
        });

        syncColors();
    }

    if ($groupModal.length) {
        setupGroupPaintingLogic($groupModal);
    }

    // --- Управление кастомизаторами группы (#groupCustomizerModal) ---
    const $custModal = $('#groupCustomizerModal');
    const $custSearch = $('#customizerSearch');
    const $custResults = $('#customizerSearchResults');
    const $custTableBody = $('#groupCustomizersList');

    function updateMainListCustomizers(groupId) {
        fetch('/orders/api/group-customizers/?group_id=' + groupId)
            .then(function (r) {
                return r.json();
            })
            .then(function (data) {
                const items = Array.isArray(data) ? data : (data['results'] || []);
                const $tab = $('#custom-' + groupId);
                let $container = $tab.find('.row-cols-1');

                const manageBtnHtml = canEdit ? (
                    '<div class="mt-4 text-end">' +
                    '<button class="btn btn-sm btn-outline-primary px-3 open-customizer-btn" data-group-id="' + groupId + '">' +
                    '<i class="bi bi-gear me-1"></i> ניהול קסטומייזרים' +
                    '</button></div>'
                ) : '';

                if (items.length === 0) {
                    $tab.html(
                        '<div class="row row-cols-1 row-cols-md-2 g-3"></div>' +
                        '<div class="col-12 text-center text-muted py-4 small">' +
                        '<i class="bi bi-info-circle me-1"></i> לא יושמו קסטומייזרים לקבוצה זו' +
                        '</div>' + manageBtnHtml
                    );
                    return;
                }

                if ($container.length === 0) {
                    $tab.html('<div class="row row-cols-1 row-cols-md-2 g-3"></div>' + manageBtnHtml);
                    $container = $tab.find('.row-cols-1');
                }

                let html = '';
                items.forEach(function (cust) {
                    let paramsHtml = '';
                    for (let i = 1; i <= 5; i++) {
                        const label = cust['par' + i + '_label'];
                        const hint = cust['par' + i + '_hint'] || '';
                        const val = cust['par' + i];
                        const options = cust['par' + i + '_options'] || [];

                        if (label) {
                            let displayVal = val || '-';
                            if (val && options && options.length > 0) {
                                const opt = options.find(function (o) {
                                    return o['key'] === val;
                                });
                                if (opt) displayVal = opt['label'];
                            }

                            paramsHtml +=
                                '<div class="col-6 extra-small" ' + (hint ? 'data-bs-toggle="tooltip" title="' + hint + '"' : '') + '>' +
                                '<span class="text-muted">' + label + ':</span> ' +
                                '<span class="fw-medium">' + displayVal + '</span>' +
                                '</div>';
                        }
                    }

                    const reqBadge = (cust['customizer_is_required'] || cust['is_required']) ? '<span class="badge bg-danger-subtle text-danger me-1">חובה</span>' : '';
                    html +=
                        '<div class="col">' +
                        '<div class="p-3 border rounded-3 bg-body h-100" data-bs-toggle="tooltip" title="' + (cust['customizer_description'] || cust['customizer_name']) + '">' +
                        '<div class="d-flex align-items-center mb-2">' +
                        '<div class="flex-shrink-0 bg-primary-subtle text-primary px-2 py-1 rounded me-3">' +
                        '<i class="bi bi-check2-circle"></i>' +
                        '</div>' +
                        '<div>' +
                        '<div class="fw-bold small text-primary">' + cust['customizer_name'] + reqBadge + '</div>' +
                        '<div class="text-muted extra-small">' + cust['customizer_code'] + '</div>' +
                        '</div>' +
                        '</div>' +
                        '<div class="ps-5"><div class="row g-1">' + paramsHtml + '</div></div>' +
                        '</div></div>';
                });
                $container.html(html);
                $tab.find('.text-center.text-muted.py-4').remove();
                if (window['initTooltips']) window['initTooltips']($tab[0]);
            });
    }

    function updatePar2Visibility($row) {
        const $par1 = $row.find('.cust-param-input[data-param="par1"]');
        const $par2Col = $row.find('.col-md-6[data-param-index="2"]');
        const $par2Input = $par2Col.find('.cust-param-input');

        if ($par1.length && $par2Col.length) {
            const val = $par1.val() || '';
            if (val === 'defined' || val.indexOf('DEFINED=') === 0) {
                $par2Col.hide();
                if ($par2Input.val() !== '') {
                    $par2Input.val('').trigger('change');
                }
            } else {
                $par2Col.show();
            }
        }
    }

    function renderCustomizerRow(item) {
        let paramsHtml = '<div class="row g-2">';
        let hasParams = false;
        const custIsRequired = item['customizer_is_required'];

        for (let i = 1; i <= 5; i++) {
            const label = item['par' + i + '_label'];
            const hint = item['par' + i + '_hint'] || '';
            const options = item['par' + i + '_options'] || [];
            const currentValue = item['par' + i] || '';
            const defaultValue = item['par' + i + '_default_value'] || '';
            const isRequired = item['par' + i + '_required'];

            if (label) {
                hasParams = true;
                let inputHtml = '';
                if (options && options.length > 0) {
                    inputHtml = '<select class="form-select form-select-sm cust-param-input" data-id="' + item['id'] + '" data-param="par' + i + '">';
                    if (isRequired) {
                        inputHtml += '<option value="" ' + ((!currentValue && !defaultValue) ? 'selected' : '') + '>-- נא לבחור --</option>';
                    }
                    options.forEach(function (opt) {
                        const selected = (currentValue === opt['key'] || (!currentValue && defaultValue === opt['key'])) ? 'selected' : '';
                        inputHtml += '<option value="' + opt['key'] + '" ' + selected + '>' + opt['label'] + '</option>';
                    });
                    inputHtml += '</select>';
                } else {
                    const effectiveVal = (currentValue !== null && currentValue !== undefined && currentValue !== '') ? currentValue : (defaultValue || '');
                    inputHtml =
                        '<input type="text" class="form-control form-control-sm cust-param-input" data-id="' + item['id'] +
                        '" data-param="par' + i + '" value="' + effectiveVal + '" placeholder="' + (hint || (isRequired ? 'שדה חובה' : '')) +
                        '" ' + (hint ? 'data-bs-toggle="tooltip" title="' + hint + '"' : '') + '>';
                }

                paramsHtml +=
                    '<div class="col-md-6" data-param-index="' + i + '">' +
                    '<label class="extra-small text-muted mb-0 d-block" ' + (hint ? 'data-bs-toggle="tooltip" title="' + hint + '"' : '') + '>' +
                    label + ' ' + (isRequired ? '<span class="text-danger fw-bold" title="שדה חובה">*</span>' : '') + ' ' + (hint ? '<i class="bi bi-info-circle help-hint-icon"></i>' : '') +
                    '</label>' + inputHtml +
                    '</div>';
            }
        }
        if (!hasParams) paramsHtml += '<div class="col-12 text-muted extra-small">אין פרמטרים להגדרה</div>';
        paramsHtml += '</div>';

        const reqBadge = custIsRequired ? '<span class="badge bg-danger-subtle text-danger me-1">חובה</span>' : '';
        return '<tr data-item-id="' + item['id'] + '">' +
            '<td><div class="fw-bold text-primary" data-bs-toggle="tooltip" title="' + (item['customizer_description'] || item['customizer_name']) + '">' +
            item['customizer_name'] + reqBadge + '</div>' +
            '<div class="extra-small text-muted">' + item['customizer_code'] + '</div></td>' +
            '<td>' + paramsHtml + '</td>' +
            '<td class="text-end">' +
            '<button class="btn btn-sm btn-outline-danger remove-cust-btn" data-id="' + item['id'] + '" data-bs-toggle="tooltip" title="הסר קסטומייזר זה מהקבוצה">' +
            '<i class="bi bi-trash"></i></button></td></tr>';
    }

    function loadGroupCustomizers(groupId) {
        $custTableBody.html('<tr><td colspan="3" class="text-center py-4"><div class="spinner-border spinner-border-sm text-primary"></div></td></tr>');

        fetch('/orders/api/group-customizers/?group_id=' + groupId)
            .then(function (r) {
                return r.json();
            })
            .then(function (data) {
                const items = Array.isArray(data) ? data : (data['results'] || []);
                let html = items.map(renderCustomizerRow).join('');
                if (items.length === 0) {
                    html = '<tr><td colspan="3" class="text-center py-4 text-muted">לא נוספו קסטומייזרים לקבוצה זו</td></tr>';
                }
                $custTableBody.html(html);
                $custTableBody.find('tr').each(function () {
                    updatePar2Visibility($(this));
                });
                if (window['initTooltips']) window['initTooltips']($custTableBody[0]);
            })
            .catch(function (err) {
                console.error('Error loading group customizers:', err);
                $custTableBody.html('<tr><td colspan="3" class="text-center text-danger py-4">שגיאה בטעינת נתונים</td></tr>');
            });
    }

    function openCustomizerModal(groupId) {
        const $groupCard = $('.group-card[data-group-id="' + groupId + '"]');
        if (!$groupCard.length) {
            $('#custModalGroupName').text('קבוצה #' + groupId);
        } else {
            $('#custModalGroupName').text($groupCard.data('group-name'));
            $('#custModalGroupQty').text($groupCard.data('group-qty'));
            $('#custModalGroupDetails').text($groupCard.data('group-details'));

            $custModal.data('product-id', $groupCard.data('product-id'));
            $custModal.data('family-id', $groupCard.data('family-id'));
            $custModal.data('type-id', $groupCard.data('type-id'));
        }

        $custModal.data('group-id', groupId);
        loadGroupCustomizers(groupId);

        const modalInst = window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance($custModal[0]) : null;
        if (modalInst) modalInst.show();
    }

    let searchTimeout;
    $custSearch.on('input', function () {
        clearTimeout(searchTimeout);
        const query = $(this).val();
        if (query.length < 2) {
            $custResults.addClass('d-none');
            return;
        }

        searchTimeout = setTimeout(function () {
            const productId = $custModal.data('product-id') || '';
            const familyId = $custModal.data('family-id') || '';
            const typeId = $custModal.data('type-id') || '';

            let url = '/catalog/api/customizers/?search=' + encodeURIComponent(query);
            if (productId) url += '&product_model=' + productId;
            if (familyId) url += '&product_family=' + familyId;
            if (typeId) url += '&product_type=' + typeId;

            fetch(url)
                .then(function (r) {
                    return r.json();
                })
                .then(function (data) {
                    const results = Array.isArray(data) ? data : (data['results'] || []);
                    let html = '';
                    results.forEach(function (c) {
                        const desc = c['description'] || '';
                        const descHtml = desc ? '<div class="extra-small text-secondary mt-1">' + desc + '</div>' : '';
                        html +=
                            '<a href="#" class="list-group-item list-group-item-action add-customizer-item" data-id="' + c['id'] + '" data-bs-toggle="tooltip" title="' + (desc || c['name']) + '">' +
                            '<div class="d-flex justify-content-between align-items-center">' +
                            '<div><div class="fw-bold">' + c['name'] + '</div><small class="text-muted">' + c['code'] + '</small>' + descHtml + '</div>' +
                            '<i class="bi bi-plus-circle text-primary"></i></div></a>';
                    });
                    if (results.length === 0) {
                        html = '<div class="list-group-item text-muted">לא נמצאו תוצאות</div>';
                    }
                    $custResults.html(html).removeClass('d-none');
                    if (window['initTooltips']) window['initTooltips']($custResults[0]);
                });
        }, 300);
    });

    $(document).on('click', '.add-customizer-item', function (e) {
        e.preventDefault();
        const custId = $(this).data('id');
        const groupId = $custModal.data('group-id');

        fetch('/orders/api/group-customizers/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({group: groupId, customizer: custId})
        })
            .then(function (r) {
                return r.json();
            })
            .then(function () {
                $custSearch.val('');
                $custResults.addClass('d-none');
                loadGroupCustomizers(groupId);
                updateMainListCustomizers(groupId);
            });
    });

    $(document).on('click', '.remove-cust-btn', function () {
        const id = $(this).data('id');
        const groupId = $custModal.data('group-id');

        window.sbConfirm({
            title: 'הסרת קסטומייזר',
            message: 'להסיר קסטומייזר זה מהקבוצה?',
            variant: 'danger',
            okText: 'הסר',
            cancelText: 'ביטול'
        }).then(function (confirmed) {
            if (!confirmed) return;
            fetch('/orders/api/group-customizers/' + id + '/', {
                method: 'DELETE',
                headers: {'X-CSRFToken': csrfToken}
            }).then(function () {
                loadGroupCustomizers(groupId);
                updateMainListCustomizers(groupId);
            });
        });
    });

    let updateParamTimeout;
    $(document).on('input change', '.cust-param-input', function () {
        const $input = $(this);
        const id = $input.data('id');
        const paramName = $input.data('param');

        if (paramName === 'par1') {
            updatePar2Visibility($input.closest('tr'));
        }
        const value = $input.val();
        const groupId = $custModal.data('group-id');

        clearTimeout(updateParamTimeout);
        $input.addClass('border-warning');

        updateParamTimeout = setTimeout(function () {
            const payload = {};
            payload[paramName] = value;
            fetch('/orders/api/group-customizers/' + id + '/', {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(payload)
            }).then(function (r) {
                if (r.ok) {
                    $input.removeClass('border-warning').addClass('border-success');
                    setTimeout(function () {
                        $input.removeClass('border-success');
                    }, 1000);
                    updateMainListCustomizers(groupId);
                }
            });
        }, 1000);
    });

    $(document).on('click', function (e) {
        if (!$(e.target).closest('#customizerSearch, #customizerSearchResults').length) {
            $custResults.addClass('d-none');
        }
    });

    const urlParams = new URLSearchParams(window.location.search);
    const groupToCustomize = urlParams.get('open_customize');
    if (groupToCustomize) {
        openCustomizerModal(groupToCustomize);
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    $(document).on('click', '.open-customizer-btn, button:contains("ניהול קסטומייזרים")', function () {
        const groupId = $(this).data('group-id') || $(this).closest('.group-card').data('group-id');
        if (groupId) openCustomizerModal(groupId);
    });

    // --- Сохранение и загрузка шаблонов спецификаций ---
    function showSuccessNotification(message) {
        const toastHtml =
            '<div class="toast-container position-fixed bottom-0 end-0 p-3" style="z-index: 11000">' +
            '<div class="toast align-items-center text-bg-success border-0" role="alert" aria-live="assertive" aria-atomic="true">' +
            '<div class="d-flex">' +
            '<div class="toast-body"><i class="bi bi-check-circle-fill me-2"></i> ' + message + '</div>' +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
            '</div></div></div>';

        const $wrapper = $(toastHtml);
        $('body').append($wrapper);

        const toastEl = $wrapper.find('.toast')[0];
        if (window.bootstrap && window.bootstrap.Toast) {
            const toast = new window.bootstrap.Toast(toastEl, {delay: 3000});
            toast.show();
            toastEl.addEventListener('hidden.bs.toast', function () {
                $wrapper.remove();
            });
        } else {
            setTimeout(function () {
                $wrapper.remove();
            }, 3500);
        }
    }

    $(document).on('click', '.btn-open-save-spec', function (e) {
        e.preventDefault();
        const $btn = $(this);
        const groupId = $btn.data('group-id');
        const groupName = $btn.data('group-name') || '';

        $saveSpecGroupName.text(groupName);
        $saveSpecGroupDetails.text($btn.data('group-details') || '');
        $saveSpecGroupQty.text(($btn.data('group-qty') || 1) + ' דלתות');
        $saveSpecNameInput.val(groupName ? ('מפרט ' + groupName) : '');
        $saveSpecDescInput.val('');
        $saveSpecForm.attr('action', '/orders/groups/' + groupId + '/save-specification/');

        const modalEl = document.getElementById('saveSpecificationModal');
        const modal = window.bootstrap ? new window.bootstrap.Modal(modalEl) : null;
        if (modal) modal.show();
    });

    $saveSpecForm.on('submit', function (e) {
        e.preventDefault();
        const url = $(this).attr('action');
        const name = $saveSpecNameInput.val().trim();
        const description = $saveSpecDescInput.val().trim();

        if (!name) {
            window.sbAlert('נא להזין שם למפרט', 'שדה חובה', 'warning');
            return;
        }

        const $btn = $('#btnSubmitSaveSpec');
        $btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm me-1"></span> שומר...');

        postFormAjax(url, {name: name, description: description})
            .then(function (data) {
                $btn.prop('disabled', false).html('<i class="bi bi-check2-circle me-1"></i>שמור מפרט');
                if (data['status'] === 'ok') {
                    const modalEl = document.getElementById('saveSpecificationModal');
                    const modal = window.bootstrap ? (window.bootstrap.Modal.getInstance(modalEl) || new window.bootstrap.Modal(modalEl)) : null;
                    if (modal) modal.hide();
                    showSuccessNotification('המפרט נשמר בהצלחה!');
                } else {
                    window.sbAlert(data['message'] || 'שגיאה בשמירת המפרט', 'שגיאה', 'danger');
                }
            })
            .catch(function (err) {
                $btn.prop('disabled', false).html('<i class="bi bi-check2-circle me-1"></i>שמור מפרט');
                console.error('Error saving spec:', err);
                window.sbAlert('שגיאה בשמירת המפרט', 'שגיאה', 'danger');
            });
    });

    let currentSpecifications = [];

    function renderSpecificationCards(specs, targetGroupId) {
        $specCardsGrid.empty();

        if (!specs || specs.length === 0) {
            $specEmptyState.removeClass('d-none');
            return;
        }
        $specEmptyState.addClass('d-none');

        specs.forEach(function (spec) {
            let customizersHtml;
            if (spec['customizers'] && spec['customizers'].length > 0) {
                customizersHtml = spec['customizers'].map(function (c) {
                    const params = ['par1', 'par2', 'par3', 'par4'].map(function (k) {
                        return c[k];
                    }).filter(Boolean);
                    const paramsStr = params.length ? (' (' + params.join(', ') + ')') : '';
                    return '<span class="badge bg-secondary-subtle text-secondary border me-1 mb-1">' + c['customizer_name'] + paramsStr + '</span>';
                }).join(' ');
            } else {
                customizersHtml = '<span class="text-muted small">ללא שדרוגים מיוחדים</span>';
            }

            const isSplitBadge = spec['is_split_installation']
                ? '<span class="badge bg-info-subtle text-info me-2">התקנה מפוצלת</span>'
                : '';

            let actionButtons;
            if (targetGroupId) {
                actionButtons =
                    '<div class="d-flex flex-column gap-2 mt-3">' +
                    '<button type="button" class="btn btn-primary btn-sm btn-apply-spec" data-spec-id="' + spec['id'] + '" data-spec-name="' + spec['name'] + '">' +
                    '<i class="bi bi-arrow-repeat me-1"></i>החל על קבוצה זו</button>' +
                    '<div class="input-group input-group-sm">' +
                    '<input type="number" class="form-control spec-create-qty" value="' + (spec['quantity'] || 1) + '" min="1" placeholder="כמות">' +
                    '<button type="button" class="btn btn-outline-success btn-create-from-spec" data-spec-id="' + spec['id'] + '">' +
                    '<i class="bi bi-plus-circle me-1"></i>הוסף כקבוצה חדשה</button>' +
                    '</div></div>';
            } else {
                actionButtons =
                    '<div class="d-flex gap-2 mt-3"><div class="input-group input-group-sm">' +
                    '<span class="input-group-text">כמות</span>' +
                    '<input type="number" class="form-control spec-create-qty" value="' + (spec['quantity'] || 1) + '" min="1">' +
                    '<button type="button" class="btn btn-success btn-create-from-spec" data-spec-id="' + spec['id'] + '">' +
                    '<i class="bi bi-plus-circle me-1"></i>הוסף להזמנה</button>' +
                    '</div></div>';
            }

            const descHtml = spec['description'] ? ('<p class="small text-muted mb-2">' + spec['description'] + '</p>') : '';
            const panelColorHtml = spec['color_panels'] ? (' (' + spec['color_panels'] + ')') : '';
            const frameColorHtml = spec['color_frames'] ? (' (' + spec['color_frames'] + ')') : '';
            const createdByHtml = spec['created_by_name'] ? ('ע״י: ' + spec['created_by_name']) : '';

            const cardHtml =
                '<div class="col-md-6 col-xl-4 spec-card-item">' +
                '<div class="card h-100 bg-body-tertiary">' +
                '<div class="card-header bg-body border-bottom d-flex justify-content-between align-items-center py-2">' +
                '<div class="text-truncate me-2"><strong class="text-primary fs-6" title="' + spec['name'] + '">' + spec['name'] + '</strong> ' + isSplitBadge + '</div>' +
                '<button type="button" class="btn btn-outline-danger btn-sm p-1 py-0 btn-delete-spec" data-spec-id="' + spec['id'] + '" title="מחק מפרט זה"><i class="bi bi-trash"></i></button>' +
                '</div>' +
                '<div class="card-body py-2">' + descHtml +
                '<div class="small mb-2">' +
                '<div class="d-flex justify-content-between border-bottom py-1"><span class="text-muted">דגם מוצר:</span><span class="fw-bold">' + (spec['product_name'] || '-') + '</span></div>' +
                '<div class="d-flex justify-content-between border-bottom py-1"><span class="text-muted">סדרה / חזית:</span><span>' + (spec['series_name'] || '-') + ' / ' + (spec['front_name'] || '-') + '</span></div>' +
                '<div class="d-flex justify-content-between border-bottom py-1"><span class="text-muted">משקוף בסיסי:</span><span>' + (spec['basic_color_frames_name'] || 'סטנדרט') + '</span></div>' +
                '<div class="d-flex justify-content-between border-bottom py-1"><span class="text-muted">צביעת כנף:</span><span>' + (spec['panel_paint_option_display'] || '-') + panelColorHtml + '</span></div>' +
                '<div class="d-flex justify-content-between border-bottom py-1"><span class="text-muted">צביעת משקוף:</span><span>' + (spec['frame_paint_option_display'] || '-') + frameColorHtml + '</span></div>' +
                '</div>' +
                '<div class="mb-2"><div class="text-muted extra-small mb-1">שינויים ושדרוגים (קסטומייזרים):</div><div>' + customizersHtml + '</div></div>' +
                actionButtons +
                '</div>' +
                '<div class="card-footer bg-body border-top-0 py-1 text-muted extra-small d-flex justify-content-between">' +
                '<span>נוצר: ' + (spec['created_at_formatted'] || '') + '</span>' +
                '<span>' + createdByHtml + '</span>' +
                '</div></div></div>';

            $specCardsGrid.append(cardHtml);
        });
    }

    function loadSpecifications(targetGroupId) {
        $specLoadingIndicator.removeClass('d-none');
        $specCardsGrid.empty();
        $specEmptyState.addClass('d-none');

        fetch('/orders/api/specifications/')
            .then(function (res) {
                return res.json();
            })
            .then(function (data) {
                $specLoadingIndicator.addClass('d-none');
                currentSpecifications = Array.isArray(data) ? data : (data['results'] || []);
                renderSpecificationCards(currentSpecifications, targetGroupId);
            })
            .catch(function (err) {
                $specLoadingIndicator.addClass('d-none');
                console.error('Error fetching specifications:', err);
                $specEmptyState.removeClass('d-none');
            });
    }

    $(document).on('click', '.btn-open-load-spec', function (e) {
        e.preventDefault();
        const $btn = $(this);
        const targetGroupId = $btn.data('group-id') || '';
        const targetGroupName = $btn.data('group-name') || '';

        $loadSpecTargetGroupId.val(targetGroupId);
        if (targetGroupId) {
            $loadSpecTargetBadge
                .removeClass('bg-info-subtle text-info border-info')
                .addClass('bg-primary-subtle text-primary border-primary')
                .html('<i class="bi bi-layers me-1"></i>פעולה עבור קבוצה: <strong>' + (targetGroupName || ('#' + targetGroupId)) + '</strong>');
        } else {
            $loadSpecTargetBadge
                .removeClass('bg-primary-subtle text-primary border-primary')
                .addClass('bg-info-subtle text-info border-info')
                .html('<i class="bi bi-plus-circle me-1"></i>הוספת קבוצה חדשה להזמנה');
        }

        $('#specSearchInput').val('');
        loadSpecifications(targetGroupId);

        const modalEl = document.getElementById('loadSpecificationModal');
        const modal = window.bootstrap ? new window.bootstrap.Modal(modalEl) : null;
        if (modal) modal.show();
    });

    $(document).on('input', '#specSearchInput', function () {
        const q = $(this).val().trim().toLowerCase();
        const targetGroupId = $loadSpecTargetGroupId.val();
        if (!q) {
            renderSpecificationCards(currentSpecifications, targetGroupId);
            return;
        }
        const filtered = currentSpecifications.filter(function (spec) {
            const str = (
                spec['name'] + ' ' + (spec['description'] || '') + ' ' +
                (spec['product_name'] || '') + ' ' + (spec['series_name'] || '') + ' ' + (spec['front_name'] || '')
            ).toLowerCase();
            return str.indexOf(q) !== -1;
        });
        renderSpecificationCards(filtered, targetGroupId);
    });

    $(document).on('click', '.btn-apply-spec', function () {
        const $btn = $(this);
        const specId = $btn.data('spec-id');
        const specName = $btn.data('spec-name');
        const groupId = $loadSpecTargetGroupId.val();

        if (!groupId || !specId) return;

        window.sbConfirm({
            title: 'החלת מפרט שמור',
            message: 'האם להחיל את מפרט "' + specName + '" על הקבוצה? פעולה זו תעדכן את הגדרות הקבוצה והשדרוגים.',
            variant: 'warning',
            okText: 'החל מפרט',
            cancelText: 'ביטול'
        }).then(function (confirmed) {
            if (!confirmed) return;

            $btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm me-1"></span> מחיל...');

            postFormAjax('/orders/groups/' + groupId + '/apply-specification/' + specId + '/')
                .then(function (data) {
                    if (data['status'] === 'ok') {
                        window.location.reload();
                    } else {
                        window.sbAlert(data['message'] || 'שגיאה בהחלת המפרט', 'שגיאה', 'danger');
                        $btn.prop('disabled', false).html('<i class="bi bi-arrow-repeat me-1"></i>החל על קבוצה זו');
                    }
                })
                .catch(function (err) {
                    console.error('Error applying spec:', err);
                    window.sbAlert('שגיאה בהחלת המפרט', 'שגיאה', 'danger');
                    $btn.prop('disabled', false).html('<i class="bi bi-arrow-repeat me-1"></i>החל על קבוצה זו');
                });
        });
    });

    $(document).on('click', '.btn-create-from-spec', function () {
        const $btn = $(this);
        const specId = $btn.data('spec-id');
        const qty = $btn.closest('.card').find('.spec-create-qty').val() || 1;

        $btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm me-1"></span> מוסיף...');

        postFormAjax('/orders/' + orderId + '/groups/create-from-specification/' + specId + '/', {quantity: qty})
            .then(function (data) {
                if (data['status'] === 'ok') {
                    window.location.reload();
                } else {
                    window.sbAlert(data['message'] || 'שגיאה ביצירת קבוצה ממפרט', 'שגיאה', 'danger');
                    $btn.prop('disabled', false).html('<i class="bi bi-plus-circle me-1"></i>הוסף');
                }
            })
            .catch(function (err) {
                console.error('Error creating group from spec:', err);
                window.sbAlert('שגיאה ביצירת קבוצה ממפרט', 'שגיאה', 'danger');
                $btn.prop('disabled', false).html('<i class="bi bi-plus-circle me-1"></i>הוסף');
            });
    });

    $(document).on('click', '.btn-delete-spec', function () {
        const specId = $(this).data('spec-id');

        window.sbConfirm({
            title: 'מחיקת מפרט שמור',
            message: 'האם אתה בטוח שברצונך למחוק מפרט שמור זה לצמיתות?',
            variant: 'danger',
            okText: 'מחק לצמיתות',
            cancelText: 'ביטול'
        }).then(function (confirmed) {
            if (!confirmed) return;

            postFormAjax('/orders/specifications/' + specId + '/delete/')
                .then(function (data) {
                    if (data['status'] === 'ok') {
                        loadSpecifications($loadSpecTargetGroupId.val());
                    } else {
                        window.sbAlert(data['message'] || 'שגיאה במחיקת המפרט', 'שגיאה', 'danger');
                    }
                })
                .catch(function (err) {
                    console.error('Error deleting spec:', err);
                    window.sbAlert('שגיאה במחיקת המפרט', 'שגיאה', 'danger');
                });
        });
    });

    // --- Модалка печати отчётов и выбора партий (#reportsModal) ---
    function syncBatchesSelectionState() {
        const $allCheckboxes = $('#reportsModal .batch-checkbox');
        const checkedCount = $allCheckboxes.filter(':checked').length;
        const total = $allCheckboxes.length;
        const selectAllEl = document.getElementById('selectAllBatches');

        if (selectAllEl) {
            selectAllEl.checked = total > 0 && checkedCount === total;
            selectAllEl.indeterminate = checkedCount > 0 && checkedCount < total;
        }

        const $counter = $('#selectedBatchesCounter');
        if ($counter.length) {
            $counter.text('נבחרו ' + checkedCount + ' מתוך ' + total);
        }

        $allCheckboxes.each(function () {
            $(this).closest('tr').toggleClass('table-active', this.checked);
        });

        // Разблокируем только активные по текущей фазе кнопки (не трогаем заблокированные классом .disabled)
        $('#reportsModal .btn-generate-action:not(.disabled)').prop('disabled', checkedCount === 0);
    }

    $('#reportsModal').on('show.bs.modal', function () {
        $('#reportsModal .batch-checkbox').prop('checked', true);
        syncBatchesSelectionState();
    });

    $(document).on('change', '#selectAllBatches', function () {
        $('#reportsModal .batch-checkbox').prop('checked', this.checked);
        syncBatchesSelectionState();
    });

    $(document).on('change', '#reportsModal .batch-checkbox', function () {
        syncBatchesSelectionState();
    });

    $(document).on('click', '#reportsModal .batch-row', function (e) {
        if ($(e.target).is('input[type="checkbox"]')) return;
        const $cb = $(this).find('.batch-checkbox');
        $cb.prop('checked', !$cb.prop('checked')).trigger('change');
    });

    $(document).on('click', '.btn-generate-action', function (e) {
        e.preventDefault();
        if ($(this).prop('disabled')) return;

        const baseUrl = $(this).data('url');
        const target = $(this).data('target') || '_blank';

        const selectedBatches = [];
        $('#reportsModal .batch-checkbox:checked').each(function () {
            selectedBatches.push($(this).val());
        });

        if (selectedBatches.length === 0) {
            window.sbAlert('נא לבחור לפחות אצווה אחת להדפסה.', 'בחירת אצוות', 'warning');
            return;
        }

        const urlObj = new URL(baseUrl, window.location.origin);
        selectedBatches.forEach(function (batchNum) {
            urlObj.searchParams.append('batch', batchNum);
        });

        if (target === '_self') {
            window.location.href = urlObj.toString();
        } else {
            window.open(urlObj.toString(), target);
        }

        $('#reportsModal').modal('hide');
    });

    // --- Комментарии к отчётам станций (#stationNoteModal поверх #reportsModal) ---
    let activeStationNoteBtn = null;

    $(document).on('click', '.btn-edit-station-note', function () {
        activeStationNoteBtn = $(this);
        const stationId = activeStationNoteBtn.attr('data-station-id');
        const stationName = activeStationNoteBtn.attr('data-station-name');
        const currentNote = activeStationNoteBtn.attr('data-note') || '';

        $('#stationNoteStationId').val(stationId);
        $('#stationNoteModalTitle').text(stationName);
        $('#stationNoteTextarea').val(currentNote);

        const modalEl = document.getElementById('stationNoteModal');
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();

        // Поднимаем backdrop второго модального окна выше первого (#reportsModal = 1055)
        setTimeout(function () {
            $('.modal-backdrop').last().css('z-index', 1060);
            $('#stationNoteTextarea').trigger('focus');
        }, 50);
    });

    $('#btnSaveStationNote').on('click', function () {
        const $saveBtn = $(this);
        const stationId = $('#stationNoteStationId').val();
        const comment = $('#stationNoteTextarea').val();

        $saveBtn.prop('disabled', true);

        fetch(orderUrls.saveStationNote || ('/production/order/' + orderId + '/save-station-note/'), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                station_id: stationId,
                comment: comment
            })
        })
            .then(function (res) {
                return res.json();
            })
            .then(function (data) {
                $saveBtn.prop('disabled', false);
                if (data.status === 'ok') {
                    const savedText = data.comment || '';
                    if (activeStationNoteBtn) {
                        activeStationNoteBtn.attr('data-note', savedText);
                        if (savedText) {
                            activeStationNoteBtn
                                .removeClass('btn-outline-secondary')
                                .addClass('btn-warning')
                                .attr('title', 'הערה קיימת: ' + savedText);
                        } else {
                            activeStationNoteBtn
                                .removeClass('btn-warning')
                                .addClass('btn-outline-secondary')
                                .attr('title', 'הוסף הערה לדו"ח');
                        }
                    }
                    const modalEl = document.getElementById('stationNoteModal');
                    bootstrap.Modal.getInstance(modalEl).hide();
                } else {
                    window.sbAlert(data.message || 'שגיאה בשמירת ההערה', 'שגיאה', 'danger');
                }
            })
            .catch(function () {
                $saveBtn.prop('disabled', false);
                window.sbAlert('שגיאת תקשורת עם השרת', 'שגיאת תקשורת', 'danger');
            });
    });

    // --- Массовое сворачивание / разворачивание карточек групп ---
    const $collapseBodies = $('.group-collapse-body');

    $('#btnExpandAllGroups').on('click', function () {
        $collapseBodies.each(function () {
            bootstrap.Collapse.getOrCreateInstance(this, {toggle: false}).show();
        });
    });

    $('#btnCollapseAllGroups').on('click', function () {
        $collapseBodies.each(function () {
            bootstrap.Collapse.getOrCreateInstance(this, {toggle: false}).hide();
        });
    });
});