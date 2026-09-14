import csv
import ctypes
import datetime
import json
import os
import shutil
import string
import tkinter as tk
from functools import partial
from tkinter import messagebox, ttk

import winsound

CONFIG_FILE = "config.json"
PENDING_FILE = "pending.csv"
HISTORY_FILE = "history.csv"
CSV_DELIMITER = ";"
CSV_HEADER = ["Timestamp", "Station_ID", "Order_ID", "Phase_Status", "Operator_Name"]


def load_config() -> dict:
    """Load settings from the local config.json file."""
    if not os.path.exists(CONFIG_FILE):
        default_cfg = {
            "station_id": "CNC_ALU_01",
            "local_work_dir": "C:\\CNC_Jobs",
            "usb_marker_file": ".sb_marker",
            "usb_jobs_subpath": "jobs",
            "usb_output_file": "completed_from_stations.csv",
            "operators": [
                {"id": "superuser", "name": "Gleb", "pin": "8823"},
                {"id": "op_02", "name": "Alex Smith", "pin": "5678"}
            ]
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, indent=2, ensure_ascii=False)
        return default_cfg

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_usb_drive(marker_filename: str) -> str | None:
    """Scan available Windows drives for the USB marker file."""
    for letter in string.ascii_uppercase:
        drive_path = f"{letter}:\\"
        if os.path.exists(drive_path):
            marker_full_path = os.path.join(drive_path, marker_filename)
            if os.path.isfile(marker_full_path):
                return drive_path
    return None


class LoginDialog(tk.Toplevel):
    """Modal dialog for operator login with PIN verification."""

    def __init__(self, parent, operators: list[dict]):
        super().__init__(parent)
        self.parent = parent
        self.operators = operators
        self.authenticated_operator = None

        self.title("Operator Login")
        self.geometry("300x180")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Center dialog relative to parent
        x = parent.winfo_x() + (parent.winfo_width() - 300) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 180) // 2
        self.geometry(f"+{x}+{y}")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_ui(self):
        pad_opts = {"padx": 12, "pady": 6}

        ttk.Label(self, text="Select Operator:", font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad_opts)
        self.op_names = [op["name"] for op in self.operators]
        self.combo_op = ttk.Combobox(self, values=self.op_names, state="readonly", font=("Segoe UI", 9))
        if self.op_names:
            self.combo_op.current(0)
        self.combo_op.pack(fill="x", padx=12)

        ttk.Label(self, text="Enter PIN:", font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad_opts)
        self.entry_pin = ttk.Entry(self, show="*", font=("Segoe UI", 10))
        self.entry_pin.pack(fill="x", padx=12)
        self.entry_pin.focus_set()
        self.entry_pin.bind("<Return>", lambda e: self._on_submit())

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=12, pady=12)
        ttk.Button(btn_frame, text="Login", command=self._on_submit).pack(side="right", padx=(4, 0))
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="right")

    def _on_submit(self):
        selected_name = self.combo_op.get()
        entered_pin = self.entry_pin.get().strip()

        matched = next((op for op in self.operators if op["name"] == selected_name), None)
        if matched and matched.get("pin") == entered_pin:
            self.authenticated_operator = matched["name"]
            self.destroy()
        else:
            winsound.MessageBeep(winsound.MB_ICONHAND)
            messagebox.showerror("Login Failed", "Invalid PIN. Please try again.", parent=self)
            self.entry_pin.delete(0, tk.END)
            self.entry_pin.focus_set()

    def _on_cancel(self):
        self.destroy()


class CNCStationApp(tk.Tk):
    """Main client application for the CNC terminal."""

    def __init__(self):
        super().__init__()
        self.config_data = load_config()
        self.current_operator = None

        # Window configuration
        self.title("SBProduction - CNC Sync")
        self.geometry("420x520")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        # Prevent accidental closing via standard close button
        # self.protocol("WM_DELETE_WINDOW", lambda: None)
        # Emergency exit hotkey for supervisors: Ctrl+Shift+Q
        self.bind("<Control-Shift-Q>", lambda e: self.destroy())

        # Ensure directories and files exist
        os.makedirs(self.config_data["local_work_dir"], exist_ok=True)
        self._init_csv_files()

        self._build_ui()
        self._update_auth_ui()
        self._refresh_history_ui()

        # Automatic focus handling
        self.bind("<FocusIn>", lambda e: self._refocus_scanner())

    @staticmethod
    def _init_csv_files():
        """Create pending and history CSV files with headers if missing."""
        for file_path in [PENDING_FILE, HISTORY_FILE]:
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f, delimiter=CSV_DELIMITER)
                    writer.writerow(CSV_HEADER)

    def _build_ui(self):
        """Construct the visual components."""
        # Top panel: Header & Auth status
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=10, pady=(8, 4))

        self.lbl_station = ttk.Label(
            header_frame,
            text=f"Station: {self.config_data.get('station_id', 'CNC')}",
            font=("Segoe UI", 8, "italic"),
            foreground="#555555"
        )
        self.lbl_station.pack(side="left")

        self.btn_auth = tk.Label(
            header_frame,
            text="Login",
            font=("Segoe UI", 8, "underline"),
            fg="#0055cc",
            cursor="hand2"
        )
        self.btn_auth.pack(side="right")
        self.btn_auth.bind("<Button-1>", lambda e: self._toggle_auth())

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=10, pady=4)

        # Barcode input and LED section
        scan_frame = ttk.LabelFrame(self, text=" Barcode Scanner / Manual Input ")
        scan_frame.pack(fill="x", padx=10, pady=4)

        input_row = ttk.Frame(scan_frame)
        input_row.pack(fill="x", padx=8, pady=8)

        # Visual LED indicator
        self.canvas_led = tk.Canvas(input_row, width=20, height=20, highlightthickness=0)
        self.canvas_led.pack(side="left", padx=(0, 8))
        self.led_circle = self.canvas_led.create_oval(3, 3, 18, 18, fill="#999999", outline="#666666")

        self.entry_barcode = ttk.Entry(input_row, font=("Segoe UI", 12, "bold"))
        self.entry_barcode.pack(side="left", fill="x", expand=True)
        self.entry_barcode.bind("<Return>", lambda e: self._on_barcode_submitted())

        # Rolling history section
        history_frame = ttk.LabelFrame(self, text=" Pending Queue (Last 3 Scans) ")
        history_frame.pack(fill="x", padx=10, pady=6)

        self.history_slots = []
        for i in range(3):
            row_frame = ttk.Frame(history_frame)
            row_frame.pack(fill="x", padx=6, pady=3)

            lbl_text = ttk.Label(row_frame, text="---", font=("Segoe UI", 8))
            lbl_text.pack(side="left", fill="x", expand=True)

            btn_cancel = tk.Button(
                row_frame,
                text="✕",
                font=("Segoe UI", 7, "bold"),
                fg="red",
                relief="groove",
                state="disabled",
                width=3
            )
            btn_cancel.pack(side="right")

            self.history_slots.append({
                "frame": row_frame,
                "label": lbl_text,
                "button": btn_cancel,
                "record_index": None
            })

        # Sync button
        self.btn_sync = tk.Button(
            self,
            text="Sync with USB Drive",
            font=("Segoe UI", 11, "bold"),
            bg="#2e7d32",
            fg="white",
            activebackground="#1b5e20",
            activeforeground="white",
            relief="raised",
            cursor="hand2",
            height=2,
            command=self._execute_sync
        )
        self.btn_sync.pack(fill="x", padx=10, pady=(8, 4))

        # Bottom status bar
        status_frame = ttk.Frame(self, relief="sunken", borderwidth=1)
        status_frame.pack(side="bottom", fill="x")

        self.lbl_status = ttk.Label(
            status_frame,
            text="Status: Ready",
            font=("Segoe UI", 8),
            foreground="#333333",
            anchor="w"
        )
        self.lbl_status.pack(fill="x", padx=6, pady=3)

    # --- Authentication Handling ---

    def _toggle_auth(self):
        """Handle login or logout action."""
        if self.current_operator:
            self.current_operator = None
            self._update_auth_ui()
            self._set_status("Operator logged out.")
        else:
            dialog = LoginDialog(self, self.config_data.get("operators", []))
            self.wait_window(dialog)
            if dialog.authenticated_operator:
                self.current_operator = dialog.authenticated_operator
                self._update_auth_ui()
                self._set_status(f"Logged in as {self.current_operator}")

    def _update_auth_ui(self):
        """Update the interface state based on operator login status."""
        if self.current_operator:
            self.btn_auth.config(text=f"{self.current_operator} / Logout", fg="#b71c1c")
            self.entry_barcode.config(state="normal")
            self._refocus_scanner()
        else:
            self.btn_auth.config(text="Login", fg="#0055cc")
            self.entry_barcode.delete(0, tk.END)
            self.entry_barcode.config(state="disabled")

    def _refocus_scanner(self):
        """Ensure focus returns to the scanner field when logged in."""
        if self.current_operator and str(self.entry_barcode.cget("state")) == "normal":
            self.entry_barcode.focus_set()

    # --- LED Indicator ---

    def _set_led(self, color: str):
        """Set LED color: gray (#999999), green (#00c853), red (#d50000)."""
        color_map = {
            "gray": "#999999",
            "green": "#00c853",
            "red": "#d50000"
        }
        self.canvas_led.itemconfig(self.led_circle, fill=color_map.get(color, "#999999"))

    def _flash_led_green(self):
        """Briefly flash LED green on success, then reset to gray."""
        self._set_led("green")
        self.after(1500, lambda: self._set_led("gray"))

    # --- Barcode Processing & Validation ---

    def _on_barcode_submitted(self):
        """Process barcode input from a scanner or keyboard."""
        raw_val = self.entry_barcode.get().strip()
        if not raw_val:
            return

        if not self.current_operator:
            self._trigger_validation_error("Authentication Required", "Please log in before scanning.")
            return

        # Barcode format: ORDER_ID:PHASE_STATUS
        if ":" not in raw_val:
            self._trigger_validation_error(
                "Invalid Barcode",
                f"Invalid barcode format '{raw_val}'.\nExpected format: ORDER_ID:PHASE"
            )
            return

        parts = raw_val.split(":", 1)
        order_id = parts[0].strip()
        phase_status = parts[1].strip()

        if not order_id or not phase_status:
            self._trigger_validation_error("Invalid Barcode", "Order ID or Phase is empty.")
            return

        # Validate order directory presence in local CNC folder
        local_work_dir = self.config_data.get("local_work_dir", "C:\\CNC_Jobs")
        order_dir_path = os.path.join(local_work_dir, order_id)
        if not os.path.isdir(order_dir_path):
            self._trigger_validation_error(
                "Order Error",
                f"Order directory '{order_id}' not found on this machine.\n"
                "Please verify the job sheet or sync programs from USB."
            )
            return

        # Prevent immediate duplicates in pending queue
        pending_rows = self._read_pending_rows()
        for r in pending_rows:
            if len(r) >= 4 and r[2] == order_id and r[3] == phase_status:
                self._trigger_validation_error(
                    "Duplicate Entry",
                    f"Order '{order_id}' (Phase: {phase_status}) is already in pending queue."
                )
                return

        # Record success
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        station_id = self.config_data.get("station_id", "CNC_ALU_01")
        new_row = [timestamp, station_id, order_id, phase_status, self.current_operator]

        self._append_pending_row(new_row)
        self._flash_led_green()
        winsound.MessageBeep(winsound.MB_OK)

        self.entry_barcode.delete(0, tk.END)
        self._refresh_history_ui()
        self._set_status(f"Logged order {order_id} ({phase_status}) successfully.")
        self._refocus_scanner()

    def _trigger_validation_error(self, title: str, message: str):
        """Signal failure via red LED, audio alert, and modal messagebox."""
        self._set_led("red")
        winsound.MessageBeep(winsound.MB_ICONHAND)
        messagebox.showerror(title, message, parent=self)
        self.entry_barcode.delete(0, tk.END)
        self._set_led("gray")
        self._refocus_scanner()

    # --- Pending Queue & History UI ---

    @staticmethod
    def _read_pending_rows() -> list[list[str]]:
        """Read all data rows from pending.csv, skipping headers and blank lines."""
        if not os.path.exists(PENDING_FILE):
            return []
        rows = []
        with open(PENDING_FILE, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f, delimiter=CSV_DELIMITER)
            header = next(reader, None)  # Skip the header row
            for row in reader:
                # Ignore empty rows or accidental duplicate headers
                if row and row != CSV_HEADER and row[0] != "Timestamp":
                    rows.append(row)
        return rows

    @staticmethod
    def _append_pending_row(row: list[str]):
        """Append a single record to pending.csv."""
        with open(PENDING_FILE, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=CSV_DELIMITER)
            writer.writerow(row)

    @staticmethod
    def _write_all_pending_rows(rows: list[list[str]]):
        """Overwrite pending.csv with the given list of rows."""
        with open(PENDING_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=CSV_DELIMITER)
            writer.writerow(CSV_HEADER)
            writer.writerows(rows)

    def _refresh_history_ui(self):
        """Render the last 3 items in the pending queue."""
        rows = self._read_pending_rows()
        # Display the 3 most recent records (newest on top)
        recent = list(reversed(rows))[:3]

        for i in range(3):
            slot = self.history_slots[i]
            if i < len(recent):
                record = recent[i]
                timestamp_str = record[0]
                # Format to HH:MM if standard timestamp
                try:
                    t_part = timestamp_str.split(" ")[1][:5]
                except IndexError:
                    t_part = timestamp_str

                order_id = record[2]
                phase = record[3]
                op_name = record[4]

                slot["label"].config(text=f"[{t_part}] #{order_id} ({phase}) - {op_name}")
                slot["button"].config(
                    state="normal",
                    command=partial(self._confirm_cancellation, record)
                )
            else:
                slot["label"].config(text="---")
                slot["button"].config(state="disabled", command=lambda: None)

    def _confirm_cancellation(self, record: list[str]):
        """Ask for confirmation before removing a record from the pending queue."""
        order_id = record[2]
        phase = record[3]

        confirm = messagebox.askyesno(
            "Confirm Cancellation",
            f"Cancel registration for Order #{order_id} (Phase: {phase})?",
            parent=self
        )
        if confirm:
            rows = self._read_pending_rows()
            # Remove matching row
            updated_rows = [r for r in rows if r != record]
            self._write_all_pending_rows(updated_rows)
            self._refresh_history_ui()
            self._set_status(f"Cancelled order {order_id} ({phase}).")
            self._refocus_scanner()

    # --- USB Synchronization ---

    def _execute_sync(self):
        """Execute full USB synchronization: export logs and mirror CNC files."""
        self._set_status("Scanning for USB drive...")
        self.update_idletasks()

        marker = self.config_data.get("usb_marker_file", ".sb_marker")
        usb_root = find_usb_drive(marker)

        if not usb_root:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            self._trigger_validation_error(
                "USB Not Found",
                f"Marker file '{marker}' was not detected on any removable drive.\n"
                "Please insert the authorized SBProduction USB drive."
            )
            self._set_status("Error: USB drive not detected.")
            return

        # 1. Export pending completed jobs to USB and local history
        pending_rows = self._read_pending_rows()
        orders_exported_count = len(pending_rows)

        if orders_exported_count > 0:
            usb_out_name = self.config_data.get("usb_output_file", "completed_from_stations.csv")
            usb_out_path = os.path.join(usb_root, usb_out_name)

            try:
                # Check if the file already exists and has content
                has_existing_data = os.path.isfile(usb_out_path) and os.path.getsize(usb_out_path) > 0

                with open(usb_out_path, "a", encoding="utf-8-sig", newline="") as f_usb:
                    writer_usb = csv.writer(f_usb, delimiter=CSV_DELIMITER)
                    # Write header only if file is new or empty (fresh from server)
                    if not has_existing_data:
                        writer_usb.writerow(CSV_HEADER)
                    writer_usb.writerows(pending_rows)

                # Append to permanent local terminal history (history.csv always has a header)
                with open(HISTORY_FILE, "a", encoding="utf-8-sig", newline="") as f_hist:
                    writer_hist = csv.writer(f_hist, delimiter=CSV_DELIMITER)
                    writer_hist.writerows(pending_rows)

                # Clear pending queue only after successful write
                self._write_all_pending_rows([])
                self._refresh_history_ui()

            except (IOError, OSError) as e:
                self._trigger_validation_error("Export Error", f"Failed writing to USB: {e}")
                self._set_status("Error: Failed writing logs to USB.")
                return

        # 2. Mirror sync jobs directory: USB -> Local WorkDir
        usb_subpath = self.config_data.get("usb_jobs_subpath", "jobs")
        src_jobs_dir = os.path.join(usb_root, usb_subpath)
        dest_jobs_dir = self.config_data.get("local_work_dir", "C:\\CNC_Jobs")

        if not os.path.isdir(src_jobs_dir):
            self._flash_led_green()
            msg = f"Orders exported: {orders_exported_count}. USB jobs path '{usb_subpath}' not found."
            self._set_status(msg)
            messagebox.showinfo("Sync Info", msg, parent=self)
            return

        copied_count, deleted_count, skipped_locked_count = self._mirror_directories(src_jobs_dir, dest_jobs_dir)

        # Finalize and report
        self._flash_led_green()
        winsound.MessageBeep(winsound.MB_OK)
        result_msg = (
            f"Sync complete. Exported: {orders_exported_count} orders. "
            f"Copied: {copied_count}, Deleted: {deleted_count}, Locked/Skipped: {skipped_locked_count}."
        )
        self._set_status(result_msg)
        messagebox.showinfo("Sync Completed", result_msg, parent=self)
        self._refocus_scanner()

    @staticmethod
    def _mirror_directories(src_root: str, dest_root: str) -> tuple[int, int, int]:
        """
        Mirror src_root into dest_root.
        Delete obsolete files/directories in dest that do not exist in src.
        Safely catch locked files without crashing.
        """
        copied_files = 0
        deleted_files = 0
        skipped_locked = 0

        # Step A: Delete obsolete items in dest_root (bottom-up walk)
        for root, dirs, files in os.walk(dest_root, topdown=False):
            rel_dir = os.path.relpath(root, dest_root)
            src_corresponding_dir = os.path.join(src_root, rel_dir)

            # Check files
            for file_name in files:
                dest_file_path = os.path.join(root, file_name)
                src_file_path = os.path.join(src_corresponding_dir, file_name)

                if not os.path.exists(src_file_path):
                    try:
                        os.remove(dest_file_path)
                        deleted_files += 1
                    except (PermissionError, OSError):
                        # File is locked by CNC controller software; skip safely
                        skipped_locked += 1

            # Check directories
            for dir_name in dirs:
                dest_sub_dir = os.path.join(root, dir_name)
                src_sub_dir = os.path.join(src_corresponding_dir, dir_name)

                if not os.path.exists(src_sub_dir):
                    try:
                        os.rmdir(dest_sub_dir)
                    except (PermissionError, OSError):
                        # Not empty (e.g., contains locked file) or access denied
                        skipped_locked += 1

        # Step B: Copy new/modified files from src_root to dest_root
        for root, dirs, files in os.walk(src_root):
            rel_dir = os.path.relpath(root, src_root)
            dest_current_dir = os.path.join(dest_root, rel_dir)
            os.makedirs(dest_current_dir, exist_ok=True)

            for file_name in files:
                src_file_path = os.path.join(root, file_name)
                dest_file_path = os.path.join(dest_current_dir, file_name)

                needs_copy = False
                if not os.path.exists(dest_file_path):
                    needs_copy = True
                else:
                    try:
                        src_stat = os.stat(src_file_path)
                        dest_stat = os.stat(dest_file_path)
                        if src_stat.st_mtime > dest_stat.st_mtime or src_stat.st_size != dest_stat.st_size:
                            needs_copy = True
                    except OSError:
                        needs_copy = True

                if needs_copy:
                    try:
                        shutil.copy2(src_file_path, dest_file_path)
                        copied_files += 1
                    except (PermissionError, OSError):
                        skipped_locked += 1

        return copied_files, deleted_files, skipped_locked

    def _set_status(self, text: str):
        """Update bottom status line text."""
        self.lbl_status.config(text=f"Status: {text}")


if __name__ == "__main__":
    # Optimize DPI awareness for Windows 10 high-DPI screens
    try:
        shcore = getattr(ctypes.windll, "shcore", None)
        if shcore:
            shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass

    app = CNCStationApp()
    app.mainloop()
