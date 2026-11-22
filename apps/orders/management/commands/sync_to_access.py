import os
from datetime import datetime, timedelta

import pyodbc
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.orders.models import Order, OrderItem, OrderItemsGroup, OrderStatus

DEFAULT_ACCESS_PATH = r"\\172.16.40.254\Public\MagicDoors\MagicDoors_3.1_Tables.accdb"
PLACEHOLDER_DOOR_TYPE_ID = 38


class Command(BaseCommand):
    help = "Copies launched orders from PostgreSQL to MS Access (skips NEW, CANCELED and existing ones)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--order",
            type=str,
            help="Sync only a specific order number (for testing)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=14,
            help="Number of past days to check for launched orders (default: 14)",
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
            # Берём только заказы, уже запущенные в работу (исключаем NEW и CANCELED)
            qs = qs.exclude(
                status__in=[OrderStatus.NEW, OrderStatus.CANCELED]
            ).filter(
                Q(production_start_date__gte=since.date()) | Q(created_at__gte=since)
            )

        orders = list(qs)
        if not orders:
            self.stdout.write("No orders to check.")
            return

        try:
            conn = pyodbc.connect(conn_str, autocommit=False)
        except pyodbc.Error as exc:
            self.stderr.write(f"Failed to connect to Access (file may be locked): {exc}")
            return

        created_count = 0
        skipped_count = 0

        try:
            cur = conn.cursor()

            for order in orders:
                raw_num = (order.order_number or "").strip()
                if not raw_num.isdigit():
                    self.stdout.write(f"Skipping order id={order.id}: non-numeric order_number '{raw_num}'")
                    skipped_count += 1
                    continue

                access_order_id = int(raw_num)

                exists = cur.execute(
                    "SELECT 1 FROM [Orders] WHERE [ID] = ?",
                    access_order_id,
                ).fetchone()

                if exists:
                    skipped_count += 1
                    continue

                items = list(
                    OrderItem.objects.filter(group__order=order)
                    .exclude(state=OrderItem.ItemState.CANCELED)
                    .exclude(group__production_state=OrderItemsGroup.ProductionState.CANCELED)
                    .order_by("group__id", "id")
                )
                num_of_doors = len(items)

                raw_start = order.production_start_date or order.created_at
                order_date = raw_start.date() if isinstance(raw_start, datetime) else raw_start
                completion_date = order.completion_date

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
                        "הזמנה נמצאת בתוכנה חדשה",
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
                            f"Order {access_order_id} ({order.customer}) synced to Access ({num_of_doors} doors)."
                        )
                    )
                except pyodbc.Error as exc:
                    conn.rollback()
                    self.stderr.write(f"Error writing order {access_order_id}: {exc}")

        finally:
            conn.close()

        self.stdout.write(f"Done. Added: {created_count}, skipped (already exists): {skipped_count}.")
