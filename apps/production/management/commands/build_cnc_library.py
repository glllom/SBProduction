"""
Management-команда пересборки библиотеки макросов/файлов ЧПУ.

Примеры использования:
    python manage.py build_cnc_library --list
    python manage.py build_cnc_library HOMAG --dry-run
    python manage.py build_cnc_library HOMAG --output C:\\CNC_Export\\HomagLib --clean
    python manage.py build_cnc_library HOMAG --zip C:\\CNC_Export\\homag_lib.zip --lock 5 8
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.production.cnc import LibraryBuildScope, MachineLibraryService, MachineRegistry


class Command(BaseCommand):
    help = "Генерирует библиотеку макросов/исполняемых файлов ЧПУ для выбранного драйвера станка."

    def add_arguments(self, parser):
        parser.add_argument(
            'machine',
            nargs='?',
            type=str,
            help="Код драйвера станка (например, ACCORD_STD, ESSEPIGI, HOMAG).",
        )
        parser.add_argument(
            '--list',
            action='store_true',
            dest='list_drivers',
            help="Показать все зарегистрированные драйверы ЧПУ и статус поддержки библиотеки.",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Только подсчёт файлов и вывод примеров путей без записи на диск.",
        )
        parser.add_argument(
            '--output',
            type=str,
            default='',
            help="Путь к папке назначения для записи дерева файлов библиотеки.",
        )
        parser.add_argument(
            '--zip',
            type=str,
            dest='zip_path',
            default='',
            help="Путь к итоговому ZIP-архиву библиотеки.",
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help="Очистить папку --output перед записью (используйте осторожно!).",
        )
        parser.add_argument('--family', nargs='*', type=int, help="Фильтр по ID ProductFamily.")
        parser.add_argument('--model', nargs='*', type=int, help="Фильтр по ID ProductModel.")
        parser.add_argument('--lock', nargs='*', type=int, help="Фильтр по ID замков (Hardware).")
        parser.add_argument('--hinge', nargs='*', type=int, help="Фильтр по ID петель (Hardware).")
        parser.add_argument('--front', nargs='*', type=int, help="Фильтр по ID фасадов (Front).")
        parser.add_argument('--customizer', nargs='*', type=int, help="Фильтр по ID Customizer.")

    def handle(self, *args, **options):
        if options['list_drivers']:
            self.stdout.write("Зарегистрированные драйверы ЧПУ:")
            for drv in MachineRegistry.all_drivers():
                status = "library: YES" if drv.supports_library else "library: NO"
                self.stdout.write(f"  - {drv.code:<16} | {drv.label:<28} | {status}")
            return

        machine_code = (options.get('machine') or '').strip()
        if not machine_code:
            raise CommandError("Укажите код станка или используйте флаг --list.")

        driver = MachineRegistry.get_or_none(machine_code)
        if driver is None:
            available = ", ".join(d.code for d in MachineRegistry.all_drivers())
            raise CommandError(f"Драйвер '{machine_code}' не найден. Доступны: {available}")

        if not driver.supports_library:
            raise CommandError(
                f"Драйвер '{driver.code}' ({driver.label}) пока не поддерживает генерацию библиотеки "
                f"(установите supports_library = True и реализуйте build_library())."
            )

        scope = LibraryBuildScope(
            family_ids=tuple(options['family']) if options.get('family') else None,
            model_ids=tuple(options['model']) if options.get('model') else None,
            lock_ids=tuple(options['lock']) if options.get('lock') else None,
            hinge_ids=tuple(options['hinge']) if options.get('hinge') else None,
            front_ids=tuple(options['front']) if options.get('front') else None,
            customizer_ids=tuple(options['customizer']) if options.get('customizer') else None,
        )

        dry_run = bool(options.get('dry_run'))
        output_dir = (options.get('output') or '').strip()
        zip_path = (options.get('zip_path') or '').strip()

        if not dry_run and not output_dir and not zip_path:
            raise CommandError("Укажите режим вывода: --dry-run, --output <папка> или --zip <файл.zip>.")

        if dry_run:
            res = MachineLibraryService.preview(driver, scope=scope)
            self.stdout.write(self.style.SUCCESS(
                f"[DRY-RUN] {res.machine_code}: файлов = {res.files_count}, "
                f"объём = {res.total_kb} КБ ({res.total_mb} МБ)"
            ))
        elif zip_path:
            res = MachineLibraryService.build_to_zip_file(driver, zip_path=zip_path, scope=scope)
            self.stdout.write(self.style.SUCCESS(
                f"[ZIP] {res.machine_code}: записано {res.files_count} файлов ({res.total_mb} МБ) -> {res.output_path}"
            ))
        else:
            res = MachineLibraryService.build_to_directory(
                driver,
                output_dir=output_dir,
                scope=scope,
                clean=bool(options.get('clean')),
            )
            self.stdout.write(self.style.SUCCESS(
                f"[DIR] {res.machine_code}: записано {res.files_count} файлов ({res.total_mb} МБ) -> {res.output_path}"
            ))

        if res.sample_paths:
            self.stdout.write("Примеры путей:")
            for path in res.sample_paths[:20]:
                self.stdout.write(f"  {path}")
