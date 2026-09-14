import csv
import os
import shutil
import string

from django.conf import settings
from django.db import transaction

from apps.orders.models import Order, OrderStatus

MARKER_FILE = ".sb_marker"
CSV_FILE_NAME = "completed_from_stations.csv"
USB_JOBS_SUBPATH = "jobs"
CSV_DELIMITER = ";"


def find_usb_drive() -> str | None:
    """Scan logical drives for the marker file."""
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive) and os.path.isfile(os.path.join(drive, MARKER_FILE)):
            return drive
    return None


def run_usb_sync() -> dict:
    """
    Execute full server-side synchronization:
    1. Ingest completed orders from USB CSV.
    2. Update Order statuses in DB.
    3. Delete completed orders from the server's cnc_files/mecal.
    4. Wipe USB jobs/ directory.
    5. Copy current cnc_files/mecal contents to USB jobs/.
    """
    usb_root = find_usb_drive()
    if not usb_root:
        return {"success": False, "message": "USB drive with .sb_marker not found."}

    csv_path = os.path.join(usb_root, CSV_FILE_NAME)
    mecal_dir = os.path.join(settings.BASE_DIR, "cnc_files", "mecal")
    usb_jobs_dir = os.path.join(usb_root, USB_JOBS_SUBPATH)

    os.makedirs(mecal_dir, exist_ok=True)
    os.makedirs(usb_jobs_dir, exist_ok=True)

    processed_orders = []

    # 1. Process completed orders from CSV
    if os.path.isfile(csv_path):
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=CSV_DELIMITER)
            with transaction.atomic():
                for row in reader:
                    order_num = row.get("Order_ID", "").strip()
                    if not order_num:
                        continue

                    order = Order.objects.filter(order_number=order_num).first()
                    if not order:
                        continue

                    # Update status based on current state
                    if order.status == OrderStatus.IN_PRODUCTION_PHASE1:
                        order.status = OrderStatus.PHASE1_READY
                        order.save(update_fields=["status"])
                        processed_orders.append(order_num)
                    elif order.status in (OrderStatus.IN_PRODUCTION, OrderStatus.IN_PRODUCTION_PHASE2):
                        order.status = OrderStatus.READY
                        order.save(update_fields=["status"])
                        processed_orders.append(order_num)

                    # Delete completed order folder from local CNC directory
                    order_folder = os.path.join(mecal_dir, order_num)
                    if os.path.isdir(order_folder):
                        shutil.rmtree(order_folder, ignore_errors=True)


    # 2. Clear USB jobs directory
    try:
        os.remove(csv_path)
    except OSError:
        pass

    for item in os.listdir(usb_jobs_dir):
        item_path = os.path.join(usb_jobs_dir, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path, ignore_errors=True)
        else:
            try:
                os.remove(item_path)
            except OSError:
                pass


    # 3. Copy remaining files from the server to USB jobs/
    copied_count = 0
    for item in os.listdir(mecal_dir):
        src_path = os.path.join(mecal_dir, item)
        dest_path = os.path.join(usb_jobs_dir, item)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dest_path)
            copied_count += 1
        elif os.path.isfile(src_path):
            shutil.copy2(src_path, dest_path)
            copied_count += 1

    return {
        "success": True,
        "message": f"Sync completed. Updated {len(processed_orders)} orders. Copied {copied_count} items to USB."
    }
