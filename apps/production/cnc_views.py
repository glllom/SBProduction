"""
Веб-интерфейс пересборки и выгрузки библиотек макросов ЧПУ (apps.production.cnc_views).

Назначение модуля:
    Доступен только сотрудникам с правами is_staff.
    Позволяет выбрать зарегистрированный станок с supports_library=True,
    опционально отфильтровать ветку (семьи / замки / петли / фасады),
    выполнить Dry-Run предпросмотр дерева путей или скачать готовый ZIP-архив.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import FileResponse
from django.shortcuts import render
from django.utils import timezone

from apps.catalog.models import Front, Hardware, ProductFamily
from apps.production.cnc import LibraryBuildScope, MachineLibraryService, MachineRegistry


def _parse_int_tuple(raw_values: List[str]) -> Optional[Tuple[int, ...]]:
    """Преобразует список строковых ID из POST-формы в кортеж int (или None)."""
    parsed: List[int] = []
    for val in raw_values:
        try:
            parsed.append(int(val))
        except (ValueError, TypeError):
            continue
    return tuple(parsed) if parsed else None


@login_required
@user_passes_test(lambda u: u.is_staff)
def cnc_library_builder_view(request):
    """Страница генерации и выгрузки библиотек макросов ЧПУ."""
    library_drivers = MachineRegistry.library_drivers()
    all_drivers = MachineRegistry.all_drivers()

    selected_machine = request.POST.get('machine_code') or (library_drivers[0].code if library_drivers else '')
    selected_families = request.POST.getlist('family_ids')
    selected_locks = request.POST.getlist('lock_ids')
    selected_hinges = request.POST.getlist('hinge_ids')
    selected_fronts = request.POST.getlist('front_ids')

    preview_result = None

    if request.method == 'POST':
        action = request.POST.get('action', 'preview')
        driver = MachineRegistry.get_or_none(selected_machine)

        if not driver or not driver.supports_library:
            messages.error(request, 'המכונה שנבחרה אינה תומכת בבניית ספריית מקרו.')
        else:
            scope = LibraryBuildScope(
                family_ids=_parse_int_tuple(selected_families),
                lock_ids=_parse_int_tuple(selected_locks),
                hinge_ids=_parse_int_tuple(selected_hinges),
                front_ids=_parse_int_tuple(selected_fronts),
            )
            try:
                if action == 'download_zip':
                    spooled_zip, result = MachineLibraryService.build_to_spooled_zip(driver, scope=scope)
                    stamp = timezone.localtime().strftime('%Y%m%d_%H%M')
                    suffix = '_partial' if scope.is_partial else '_full'
                    filename = f"cnc_library_{driver.code.lower()}{suffix}_{stamp}.zip"
                    return FileResponse(spooled_zip, as_attachment=True, filename=filename)

                preview_result = MachineLibraryService.preview(driver, scope=scope, max_samples=50)
            except Exception as exc:
                messages.error(request, f'שגיאה בבניית הספרייה: {exc}')

    context = {
        'library_drivers': library_drivers,
        'all_drivers': all_drivers,
        'selected_machine': selected_machine,
        'selected_families': {str(x) for x in selected_families},
        'selected_locks': {str(x) for x in selected_locks},
        'selected_hinges': {str(x) for x in selected_hinges},
        'selected_fronts': {str(x) for x in selected_fronts},
        'families': ProductFamily.objects.filter(active=True).order_by('name'),
        'locks': Hardware.objects.filter(active=True, role=Hardware.HardwareRole.LOCK).order_by('name'),
        'hinges': Hardware.objects.filter(active=True, role=Hardware.HardwareRole.HINGE).order_by('name'),
        'fronts': Front.objects.filter(active=True).select_related('series').order_by('series__name', 'name'),
        'preview_result': preview_result,
    }
    return render(request, 'production/cnc_library_builder.html', context)
