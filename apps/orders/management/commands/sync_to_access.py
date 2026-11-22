import os
from datetime import datetime, timedelta

import pyodbc
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.orders.models import Order, OrderItem

DEFAULT_ACCESS_PATH = r"\\172.16.40.254\Public\MagicDoors\MagicDoors_3.1_Tables.accdb"
PLACEHOLDER_DOOR_TYPE_ID = 38


class Command(BaseCommand):
    help = "Копирует новые заказы из PostgreSQL в MS Access (пропускает уже существующие)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--order",
            type=str,
            help="Синхронизировать только один конкретный номер заказа (для теста)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="За сколько последних дней проверять заказы (по умолчанию 7)",
        )

    def handle(self, *args, **options):
        db_path = os.environ.get("ACCESS_DB_PATH", DEFAULT_ACCESS_PATH)
        conn_str = (
            r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
            f"DBQ={db_path};"
        )

        qs = Order.objects.all().order_by("id")
        if options["order"]:
            qs = qs.filter(order_number=options["order"].strip())
        else:
            since = timezone.now() - timedelta(days=options["days"])
            qs = qs.filter(created_at__gte=since)

        orders = list(qs)
        if not orders:
            self.stdout.write("Нет заказов для проверки.")
            return

        try:
            conn = pyodbc.connect(conn_str, autocommit=False)
        except pyodbc.Error as exc:
            self.stderr.write(f"Не удалось подключиться к Access (возможно, файл заблокирован): {exc}")
            return

        created_count = 0
        skipped_count = 0

        try:
            cur = conn.cursor()

            for order in orders:
                raw_num = (order.order_number or "").strip()
                if not raw_num.isdigit():
                    self.stdout.write(f"Пропуск заказа id={order.id}: нечисловой номер '{raw_num}'")
                    skipped_count += 1
                    continue

                access_order_id = int(raw_num)

                # Проверяем, есть ли уже такой заказ в Access
                exists = cur.execute(
                    "SELECT 1 FROM [Orders] WHERE [ID] = ?",
                    access_order_id,
                ).fetchone()

                if exists:
                    skipped_count += 1
                    continue

                items = list(
                    OrderItem.objects.filter(group__order=order).order_by("group__batch_number", "id")
                )
                num_of_doors = len(items)

                order_date = order.production_start_date or order.created_at.date()
                completion_date = order.completion_date  # может быть None

                try:
                    cur.execute(
                        """
                        INSERT INTO [Orders]
                        ([ID], [Customer], [NumOfDoors], [OrderDate], [ComplitionDate], [OrderComments])
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        access_order_id,
                        order.customer or "",
                        num_of_doors,
                        datetime.combine(order_date, datetime.min.time()),
                        datetime.combine(completion_date, datetime.min.time()) if completion_date else None,
                        "Заказ заведен через новую программу",
                    )

                    for idx, _item in enumerate(items, start=1):
                        cur.execute(
                            """
                            INSERT INTO [Doors]
                                ([Order], [DoorNumber], [TypeOfDoor])
                            VALUES (?, ?, ?)
                            """,
                            access_order_id,
                            idx,
                            PLACEHOLDER_DOOR_TYPE_ID,
                        )

                    conn.commit()
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Заказ {access_order_id} ({order.customer}) перенесён в Access ({num_of_doors} дв.)."
                        )
                    )
                except pyodbc.Error as exc:
                    conn.rollback()
                    self.stderr.write(f"Ошибка при записи заказа {access_order_id}: {exc}")

        finally:
            conn.close()

        self.stdout.write(f"Готово. Добавлено: {created_count}, пропущено (уже есть): {skipped_count}.")
