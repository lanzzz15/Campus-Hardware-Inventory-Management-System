import sqlite3
import os
import csv
import logging
import re
import time
from datetime import datetime
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    TKINTER_AVAILABLE = True
except ImportError:
    tk = None
    messagebox = None
    ttk = None
    TKINTER_AVAILABLE = False


from pydantic import BaseModel, Field, field_validator, ValidationError
import bcrypt


# ==========================================
# 1. CENTRAL LOGGING SETUP
# ==========================================

def setup_logger():
    log_dir = "app_logging"

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        filename=os.path.join(log_dir, "app.log"),
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    return logging.getLogger("CampusHardwareLogger")


logger = setup_logger()


# ==========================================
# 2. UI COLOR PALETTE (Gold / Navy Blue / Cream White)
# ==========================================
# A calm, low-glare palette: warm cream backgrounds instead of
# stark white, deep navy for structural chrome (headers, tab
# bars, table headings), and a muted gold reserved for primary
# actions and highlights so it doesn't fight for attention.

COLOR_BG = "#FAF7F0"            # app background - warm off-white
COLOR_PANEL_BG = "#FFFFFF"      # card / form background
COLOR_HEADER_BG = "#14355B"     # deep navy - header bar, table headings
COLOR_HEADER_FG = "#F4E9CB"     # soft gold-cream text on navy

COLOR_GOLD = "#C9A227"          # primary action accent
COLOR_GOLD_DARK = "#9C7D1D"
COLOR_GOLD_TEXT = "#14355B"     # navy text on gold buttons

COLOR_BLUE = "#2E5C8A"          # secondary / neutral actions
COLOR_BLUE_TEXT = "#FFFFFF"

COLOR_SLATE = "#4B5D77"         # muted slate-blue for destructive actions
COLOR_SLATE_TEXT = "#FFFFFF"

COLOR_TEXT_DARK = "#1F2937"
COLOR_TEXT_MUTED = "#5B6472"
COLOR_BORDER = "#D8CBA0"

# Status legend / row-highlight colors are left exactly as the
# original design (green/amber/red) - these are a functional
# signal (stock level at a glance), not part of the gold/navy
# decorative palette, so they are intentionally not restyled.
COLOR_IN_STOCK_BG = "#d4edda"
COLOR_IN_STOCK_FG = "#155724"
COLOR_LOW_STOCK_BG = "#fff3cd"
COLOR_LOW_STOCK_FG = "#856404"
COLOR_OUT_STOCK_BG = "#f8d7da"
COLOR_OUT_STOCK_FG = "#721c24"

FONT_BASE = ("Segoe UI", 10)
FONT_LABEL = ("Segoe UI", 10)
FONT_HEADING = ("Segoe UI", 12, "bold")


def configure_app_styles():
    """Configures ttk widget styles (Notebook, Treeview, Combobox) to
    match the gold / navy / cream palette. Safe to call once at startup."""

    style = ttk.Style()

    # NOTE: the "clam" theme has a known bug where it ignores
    # per-row Treeview.tag_configure() background/foreground colors
    # (used here for the In Stock / Low Stock / Out of Stock status
    # highlighting), silently flattening every row to one color.
    # "default" applies our navy/gold styling to headings, tabs,
    # etc. just as well while still honoring per-row tag colors.
    try:
        style.theme_use("default")
    except tk.TclError:
        pass

    style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=COLOR_BLUE,
        foreground="white",
        padding=(16, 9),
        font=("Segoe UI", 10, "bold")
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", COLOR_GOLD)],
        foreground=[("selected", COLOR_GOLD_TEXT)]
    )

    style.configure(
        "Treeview",
        background=COLOR_PANEL_BG,
        fieldbackground=COLOR_PANEL_BG,
        foreground=COLOR_TEXT_DARK,
        rowheight=26,
        font=("Segoe UI", 9)
    )
    style.configure(
        "Treeview.Heading",
        background=COLOR_HEADER_BG,
        foreground=COLOR_HEADER_FG,
        font=("Segoe UI", 9, "bold"),
        relief="flat"
    )
    style.map(
        "Treeview.Heading",
        background=[("active", COLOR_HEADER_BG)]
    )
    style.map(
        "Treeview",
        background=[("selected", COLOR_GOLD)],
        foreground=[("selected", COLOR_GOLD_TEXT)]
    )

    style.configure("TCombobox", fieldbackground="white", background="white")
    style.configure("TScrollbar", background=COLOR_BLUE, troughcolor=COLOR_BG)


def make_button(parent, text, command, kind="primary", width=None, height=None, padx=8):
    """Creates a tk.Button styled to the gold / navy / cream palette.

    kind: "primary" (gold - main call-to-action, e.g. Save/Submit/Approve),
          "secondary" (navy blue - neutral actions, e.g. Update/Refresh/Export),
          "danger" (muted slate - destructive/negative actions, e.g. Delete/Reject/Logout)
    """

    if kind == "primary":
        bg, fg, active_bg = COLOR_GOLD, COLOR_GOLD_TEXT, COLOR_GOLD_DARK
    elif kind == "danger":
        bg, fg, active_bg = COLOR_SLATE, COLOR_SLATE_TEXT, COLOR_HEADER_BG
    else:
        bg, fg, active_bg = COLOR_BLUE, COLOR_BLUE_TEXT, COLOR_HEADER_BG

    btn_kwargs = dict(
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=fg,
        relief="flat",
        bd=0,
        font=("Segoe UI", 9, "bold"),
        padx=padx,
        pady=4,
        cursor="hand2"
    )

    if width is not None:
        btn_kwargs["width"] = width
    if height is not None:
        btn_kwargs["height"] = height

    return tk.Button(parent, **btn_kwargs)


# ==========================================
# 3. DATABASE INITIALIZATION
# ==========================================

DB_NAME = "hardware_inventory.db"

ROLE_USER = "User"
ROLE_ADMIN = "Admin"
ROLE_SUPER_ADMIN = "SuperAdmin"
SUPER_ADMIN_USERNAME = "Lance1015"
SUPER_ADMIN_PASSWORD = "Lance@1015"
VALID_ROLES = (ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN)
PRIVILEGED_ROLES = (ROLE_ADMIN, ROLE_SUPER_ADMIN)

BORROW_STATUS_PENDING = "pending"
BORROW_STATUS_APPROVED = "approved"
BORROW_STATUS_REJECTED = "rejected"
BORROW_STATUS_RETURNED = "returned"


def init_db(db_name=DB_NAME):
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # ------------------------------------------
        # Users Table
        # ------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                password_hash TEXT NOT NULL,
                failed_attempts INTEGER DEFAULT 0,
                locked_until REAL DEFAULT 0
            )
        """)

        # ------------------------------------------
        # Database Migration
        # ------------------------------------------
        # This allows older databases to work even if
        # they were created using the original schema.

        cursor.execute("PRAGMA table_info(users)")
        existing_columns = [column[1] for column in cursor.fetchall()]

        if "email" not in existing_columns:
            cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
            logger.info("Database migration: Added email column.")

        if "failed_attempts" not in existing_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN failed_attempts INTEGER DEFAULT 0"
            )
            logger.info("Database migration: Added failed_attempts column.")

        if "locked_until" not in existing_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN locked_until REAL DEFAULT 0"
            )
            logger.info("Database migration: Added locked_until column.")

        if "role" not in existing_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'User'"
            )
            logger.info("Database migration: Added role column.")

        if "locked" not in existing_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN locked INTEGER DEFAULT 0"
            )
            logger.info("Database migration: Added locked column.")

        # ------------------------------------------
        # Hardware Inventory Table
        # ------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hardware (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                status TEXT NOT NULL
            )
        """)

        # ------------------------------------------
        # Account Creation Requests Table
        # ------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)

        # ------------------------------------------
        # Borrow Requests Table
        # ------------------------------------------
        # Each row is a single line-item (one hardware item).
        # Multiple items submitted together from the borrow cart
        # share the same batch_id so they can be tracked/approved
        # as a set if needed, while still being individually
        # trackable for return purposes.

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS borrow_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                batch_id TEXT,
                FOREIGN KEY (item_id) REFERENCES hardware(item_id)
            )
        """)

        cursor.execute("PRAGMA table_info(borrow_requests)")
        existing_borrow_columns = [column[1] for column in cursor.fetchall()]

        if "batch_id" not in existing_borrow_columns:
            cursor.execute("ALTER TABLE borrow_requests ADD COLUMN batch_id TEXT")
            logger.info("Database migration: Added batch_id column to borrow_requests.")

        # ------------------------------------------
        # Password Reset / Unlock Requests Table
        # ------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reset_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                new_password_hash TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)

        # ------------------------------------------
        # Ensure the permanent SuperAdmin account exists
        # ------------------------------------------

        super_hash = bcrypt.hashpw(
            SUPER_ADMIN_PASSWORD.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        cursor.execute("SELECT id FROM users WHERE username = ?", (SUPER_ADMIN_USERNAME,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO users
                (username, email, password_hash, failed_attempts, locked_until, role, locked)
                VALUES (?, ?, ?, 0, 0, ?, 0)
            """, (
                SUPER_ADMIN_USERNAME,
                "superadmin@campushardware.local",
                super_hash,
                ROLE_SUPER_ADMIN
            ))
            logger.info("Permanent SuperAdmin account created.")
        else:
            cursor.execute(
                "UPDATE users SET role = ?, password_hash = ?, locked = 0, failed_attempts = 0 WHERE username = ?",
                (ROLE_SUPER_ADMIN, super_hash, SUPER_ADMIN_USERNAME)
            )

        conn.commit()
        conn.close()

        logger.info("Database initialized successfully.")

    except sqlite3.Error as e:
        logger.error(f"Database setup error: {e}")


# ==========================================
# 4. PYDANTIC SCHEMAS & VALIDATION
# ==========================================

def validate_password_rules(v):
    """Shared password rule validator used by every schema that collects
    a new password (registration and password reset/update)."""

    if len(v) < 8:
        raise ValueError(
            "Password must contain at least 8 characters."
        )

    if not re.search(r"[A-Z]", v):
        raise ValueError(
            "Password must contain at least one uppercase letter."
        )

    if not re.search(r"[0-9]", v):
        raise ValueError(
            "Password must contain at least one number."
        )

    if not re.search(r"[@#$%^&*]", v):
        raise ValueError(
            "Password must contain at least one special character (@#$%^&*)."
        )

    return v


class UserRegisterSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str
    password: str
    role: str

    # ------------------------------------------
    # Username Validation
    # ------------------------------------------

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v):
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError(
                "Username must contain only letters, numbers, and underscores."
            )

        return v

    # ------------------------------------------
    # Email Validation
    # ------------------------------------------

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip().lower()

        if not re.match(
            r"^[a-zA-Z0-9._%+-]+@(gmail\.com|yahoo\.com)$",
            v
        ):
            raise ValueError(
                "Email must be a valid @gmail.com or @yahoo.com address."
            )

        return v

    # ------------------------------------------
    # Password Validation
    # ------------------------------------------

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return validate_password_rules(v)

    # ------------------------------------------
    # Role Validation
    # ------------------------------------------

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in VALID_ROLES:
            raise ValueError(
                f"Role must be one of: {', '.join(VALID_ROLES)}."
            )

        return v


class PasswordResetSchema(BaseModel):
    username: str = Field(..., min_length=1)
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip().lower()

        if not re.match(
            r"^[a-zA-Z0-9._%+-]+@(gmail\.com|yahoo\.com)$",
            v
        ):
            raise ValueError(
                "Email must be a valid @gmail.com or @yahoo.com address."
            )

        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return validate_password_rules(v)


class HardwareSchema(BaseModel):
    item_name: str = Field(..., min_length=2, max_length=100)
    category: str = Field(..., min_length=2, max_length=50)
    quantity: int = Field(..., ge=0)
    unit_price: float = Field(..., ge=0.0)


def calculate_status(quantity: int) -> str:

    if quantity > 5:
        return "In Stock"

    elif 1 <= quantity <= 5:
        return "Low Stock"

    else:
        return "Out of Stock"


# ==========================================
# 5. PASSWORD REQUIREMENT CHECKER
# ==========================================

def get_password_requirements(password):
    """
    Returns a list containing the password requirements
    that have not yet been satisfied.
    """

    missing = []

    if len(password) < 8:
        missing.append("at least 8 characters")

    if not re.search(r"[A-Z]", password):
        missing.append("one uppercase letter")

    if not re.search(r"[0-9]", password):
        missing.append("one number")

    if not re.search(r"[@#$%^&*]", password):
        missing.append("one special character (@#$%^&*)")

    return missing


PASSWORD_REQUIREMENTS_TEXT = (
    "Password requirements:\n"
    "• At least 8 characters\n"
    "• One uppercase letter\n"
    "• One number\n"
    "• One special character (@#$%^&*)"
)


# ==========================================
# 6. CONTROLLER / BACKEND LOGIC
# ==========================================

class InventoryController:

    MAX_FAILED_ATTEMPTS = 3

    def __init__(self, db_name=DB_NAME):
        self.db_name = db_name

    # ==========================================
    # ACCOUNT CREATION REQUEST
    # ==========================================

    def submit_registration_request(self, username, email, password, role):
        try:
            validated = UserRegisterSchema(
                username=username,
                email=email,
                password=password,
                role=role
            )
        except ValidationError as e:
            err_msg = e.errors()[0]["msg"]
            logger.warning(f"Registration validation failure: {err_msg}")
            return False, f"Validation Error: {err_msg}"

        if validated.username == SUPER_ADMIN_USERNAME or validated.role == ROLE_SUPER_ADMIN:
            return False, "SuperAdmin accounts cannot be created through registration."

        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT username, email FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
                (validated.username, validated.email)
            )
            if cursor.fetchone():
                return False, "Username or email already registered. Please use different details."

            cursor.execute(
                "SELECT request_id FROM account_requests WHERE status = 'pending' AND (LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?))",
                (validated.username, validated.email)
            )
            if cursor.fetchone():
                return False, "An account request with this username or email is already pending."

            hashed_pw = bcrypt.hashpw(validated.password.encode("utf-8"), bcrypt.gensalt())
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                INSERT INTO account_requests
                (username, email, password_hash, role, timestamp, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (
                validated.username,
                validated.email,
                hashed_pw.decode("utf-8"),
                validated.role,
                timestamp
            ))

            conn.commit()
            logger.info(f"Account creation request submitted for '{validated.username}'.")
            return True, "Account request submitted. A SuperAdmin must approve it before you can log in."

        except sqlite3.IntegrityError:
            return False, "An account request for this username already exists."
        except sqlite3.Error as e:
            logger.error(f"Account request database error: {e}")
            return False, "Database error occurred while submitting the account request."
        finally:
            if conn is not None:
                conn.close()

    def get_pending_account_requests(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT request_id, username, email, role, timestamp
            FROM account_requests
            WHERE status = 'pending'
            ORDER BY request_id ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows

    def approve_account_request(self, request_id):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT username, email, password_hash, role, status
                FROM account_requests WHERE request_id = ?
            """, (request_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Account request not found."

            username, email, password_hash, role, status = row
            if status != "pending":
                return False, "This account request has already been processed."

            cursor.execute(
                "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
                (username, email)
            )
            if cursor.fetchone():
                cursor.execute("UPDATE account_requests SET status = 'rejected' WHERE request_id = ?", (request_id,))
                conn.commit()
                return False, "Username or email is already registered. The request was rejected."

            cursor.execute("""
                INSERT INTO users
                (username, email, password_hash, failed_attempts, locked_until, role, locked)
                VALUES (?, ?, ?, 0, 0, ?, 0)
            """, (username, email, password_hash, role))

            cursor.execute("UPDATE account_requests SET status = 'approved' WHERE request_id = ?", (request_id,))
            conn.commit()
            logger.info(f"Account request #{request_id} for '{username}' approved.")
            return True, f"Account '{username}' approved successfully."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Account approval error: {e}")
            return False, "Database error occurred while approving the account."
        finally:
            conn.close()

    def reject_account_request(self, request_id):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT username, status FROM account_requests WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Account request not found."
            username, status = row
            if status != "pending":
                return False, "This account request has already been processed."
            cursor.execute("UPDATE account_requests SET status = 'rejected' WHERE request_id = ?", (request_id,))
            conn.commit()
            logger.info(f"Account request #{request_id} for '{username}' rejected.")
            return True, f"Account request for '{username}' rejected."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Account rejection error: {e}")
            return False, "Database error occurred while rejecting the account."
        finally:
            conn.close()

    # ==========================================
    # ACCOUNT MANAGEMENT (SUPERADMIN)
    # ==========================================

    def get_all_accounts(self):
        """Returns every account except the permanent SuperAdmin account,
        which can never be removed or listed for removal."""

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, email, role, locked
            FROM users
            WHERE username != ?
            ORDER BY role ASC, username ASC
        """, (SUPER_ADMIN_USERNAME,))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def remove_account(self, username):
        if username == SUPER_ADMIN_USERNAME:
            return False, "The permanent SuperAdmin account cannot be removed."

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if not row:
                return False, "Account not found."

            cursor.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            logger.info(f"Account '{username}' removed by a SuperAdmin.")
            return True, f"Account '{username}' has been removed."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Remove account error: {e}")
            return False, "Database error occurred while removing the account."
        finally:
            conn.close()

    # ==========================================
    # BORROW REQUESTS (CART-BASED)
    # ==========================================

    def submit_borrow_cart(self, username, cart_items):
        """
        cart_items: list of (item_id, quantity) tuples representing
        everything the user has added to their borrow cart.
        All items are validated together and submitted as one batch.
        """

        if not cart_items:
            return False, "Your borrow cart is empty. Add at least one item before submitting."

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            validated_items = []

            for item_id, quantity in cart_items:
                try:
                    quantity = int(quantity)
                    if quantity <= 0:
                        return False, "Borrow quantity must be at least 1 for every item in the cart."
                except (ValueError, TypeError):
                    return False, "Borrow quantity must be a valid whole number for every item in the cart."

                cursor.execute("SELECT item_name, quantity FROM hardware WHERE item_id = ?", (item_id,))
                item = cursor.fetchone()
                if not item:
                    return False, "One of the items in your cart could not be found."

                item_name, available = item
                if quantity > available:
                    return False, f"Only {available} unit(s) of '{item_name}' are currently available."

                cursor.execute("""
                    SELECT request_id FROM borrow_requests
                    WHERE username = ? AND item_id = ? AND status = 'pending'
                """, (username, item_id))
                if cursor.fetchone():
                    return False, f"You already have a pending request for '{item_name}'."

                validated_items.append((item_id, quantity, item_name))

            batch_id = f"{username}-{int(time.time() * 1000)}"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for item_id, quantity, item_name in validated_items:
                cursor.execute("""
                    INSERT INTO borrow_requests (username, item_id, quantity, timestamp, status, batch_id)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                """, (username, item_id, quantity, timestamp, batch_id))

            conn.commit()

            item_summary = ", ".join(f"{q} x '{n}'" for _, q, n in validated_items)
            logger.info(f"Borrow cart submitted by '{username}': {item_summary} (batch {batch_id}).")
            return True, f"Borrow request submitted for approval: {item_summary}."

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Borrow cart submission error: {e}")
            return False, "Database error occurred while submitting the borrow request."
        finally:
            conn.close()

    def get_pending_borrow_requests(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT br.request_id, br.username, h.item_name, br.quantity, br.timestamp
            FROM borrow_requests br
            JOIN hardware h ON h.item_id = br.item_id
            WHERE br.status = 'pending'
            ORDER BY br.request_id ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows

    def approve_borrow_request(self, request_id):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT br.username, br.item_id, br.quantity, br.status, h.item_name, h.quantity
                FROM borrow_requests br
                JOIN hardware h ON h.item_id = br.item_id
                WHERE br.request_id = ?
            """, (request_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Borrow request not found."
            username, item_id, qty, status, item_name, available = row
            if status != "pending":
                return False, "This borrow request has already been processed."
            if qty > available:
                return False, f"Not enough inventory remains for '{item_name}'."

            new_qty = available - qty
            cursor.execute("UPDATE hardware SET quantity = ?, status = ? WHERE item_id = ?",
                           (new_qty, calculate_status(new_qty), item_id))
            cursor.execute("UPDATE borrow_requests SET status = 'approved' WHERE request_id = ?", (request_id,))
            conn.commit()
            logger.info(f"Borrow request #{request_id} for '{username}' approved.")
            return True, f"Borrow request approved. {qty} unit(s) of '{item_name}' released to {username}."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Borrow approval error: {e}")
            return False, "Database error occurred while approving the borrow request."
        finally:
            conn.close()

    def reject_borrow_request(self, request_id):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT username, status FROM borrow_requests WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Borrow request not found."
            username, status = row
            if status != "pending":
                return False, "This borrow request has already been processed."
            cursor.execute("UPDATE borrow_requests SET status = 'rejected' WHERE request_id = ?", (request_id,))
            conn.commit()
            logger.info(f"Borrow request #{request_id} for '{username}' rejected.")
            return True, f"Borrow request for '{username}' rejected."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Borrow rejection error: {e}")
            return False, "Database error occurred while rejecting the borrow request."
        finally:
            conn.close()

    # ==========================================
    # BORROWED ITEMS / RETURNS
    # ==========================================

    def get_active_borrows(self):
        """Approved borrow requests that have not yet been marked as returned."""

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT br.request_id, br.username, h.item_name, br.quantity, br.timestamp
            FROM borrow_requests br
            JOIN hardware h ON h.item_id = br.item_id
            WHERE br.status = 'approved'
            ORDER BY br.request_id ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows

    def mark_borrow_returned(self, request_id):
        """Marks a borrowed item as returned and restocks it back into inventory."""

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT br.username, br.item_id, br.quantity, br.status, h.item_name, h.quantity
                FROM borrow_requests br
                JOIN hardware h ON h.item_id = br.item_id
                WHERE br.request_id = ?
            """, (request_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Borrow record not found."

            username, item_id, qty, status, item_name, current_qty = row
            if status != "approved":
                return False, "This borrow record is not currently active."

            new_qty = current_qty + qty
            cursor.execute("UPDATE hardware SET quantity = ?, status = ? WHERE item_id = ?",
                           (new_qty, calculate_status(new_qty), item_id))
            cursor.execute("UPDATE borrow_requests SET status = 'returned' WHERE request_id = ?", (request_id,))
            conn.commit()
            logger.info(f"Borrow request #{request_id} for '{username}' marked as returned. "
                        f"{qty} x '{item_name}' restocked.")
            return True, f"'{item_name}' ({qty} unit(s)) marked as returned by {username} and restocked."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Mark returned error: {e}")
            return False, "Database error occurred while marking the item as returned."
        finally:
            conn.close()

    # ==========================================
    # LOGIN
    # ==========================================

    def login_user(self, username, password):
        """
        Returns a tuple of (status, message, role).

        status is one of:
            "success" - credentials are correct
            "locked"  - account is locked and needs a password reset
            "fail"    - invalid credentials / unknown user

        Admin and SuperAdmin accounts are exempt from the lockout
        feature: repeated failed attempts never lock them out.
        """

        if not username or not password:

            return "fail", "Please enter both username and password.", None

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                password_hash,
                failed_attempts,
                role,
                locked
            FROM users
            WHERE username = ?
        """, (username,))

        row = cursor.fetchone()

        # ------------------------------------------
        # User Does Not Exist
        # ------------------------------------------

        if not row:

            conn.close()

            logger.warning(
                f"Failed login attempt for unknown user '{username}'"
            )

            return "fail", "Invalid username or password.", None

        password_hash = row[0]
        failed_attempts = row[1] or 0
        role = row[2] or ROLE_USER
        locked = row[3] or 0
        is_privileged = role in PRIVILEGED_ROLES

        # ==========================================
        # ACCOUNT LOCKED - NEEDS RESET / UNLOCK
        # ==========================================
        # Admin/SuperAdmin accounts never get locked, so this branch
        # only ever applies to regular User accounts.

        if locked and not is_privileged:

            conn.close()

            logger.warning(
                f"Login blocked for locked account '{username}'."
            )

            return (
                "locked",
                "Your account is locked due to too many failed login "
                "attempts.\nPlease reset your password to unlock it.",
                None
            )

        # ==========================================
        # CHECK PASSWORD
        # ==========================================

        password_correct = bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8")
        )

        # ==========================================
        # SUCCESSFUL LOGIN
        # ==========================================

        if password_correct:

            cursor.execute("""
                UPDATE users
                SET failed_attempts = 0
                WHERE username = ?
            """, (username,))

            conn.commit()
            conn.close()

            logger.info(
                f"User '{username}' logged in successfully as '{role}'."
            )

            return "success", "Login successful!", role

        # ==========================================
        # FAILED LOGIN
        # ==========================================

        failed_attempts += 1

        # Admin and SuperAdmin accounts are exempt from lockout:
        # track the failed attempt for logging/auditing purposes
        # only, but never lock the account.

        if is_privileged:

            cursor.execute("""
                UPDATE users
                SET failed_attempts = ?
                WHERE username = ?
            """, (
                failed_attempts,
                username
            ))

            conn.commit()
            conn.close()

            logger.warning(
                f"Failed login attempt for privileged account '{username}' "
                f"(role: {role}). Lockout does not apply to this role."
            )

            return "fail", "Invalid username or password.", None

        if failed_attempts >= self.MAX_FAILED_ATTEMPTS:

            cursor.execute("""
                UPDATE users
                SET failed_attempts = ?,
                    locked = 1
                WHERE username = ?
            """, (
                failed_attempts,
                username
            ))

            conn.commit()
            conn.close()

            logger.warning(
                f"Account '{username}' locked after "
                f"{failed_attempts} failed attempts."
            )

            return (
                "locked",
                "Too many failed login attempts.\n"
                "Your account has been locked. Please reset your "
                "password to unlock it.",
                None
            )

        else:

            cursor.execute("""
                UPDATE users
                SET failed_attempts = ?
                WHERE username = ?
            """, (
                failed_attempts,
                username
            ))

            conn.commit()
            conn.close()

            remaining_attempts = (
                self.MAX_FAILED_ATTEMPTS - failed_attempts
            )

            logger.warning(
                f"Failed login attempt for '{username}'. "
                f"Attempts: {failed_attempts}"
            )

            return (
                "fail",
                "Invalid username or password.\n"
                f"Attempts remaining before lockout: "
                f"{remaining_attempts}",
                None
            )

    # ==========================================
    # PASSWORD RESET / UNLOCK REQUEST
    # ==========================================

    def submit_reset_request(self, username, email, new_password, confirm_password):

        username = (username or "").strip()
        email_input = (email or "").strip()

        if not username:
            return False, "Please enter the account username."

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT email FROM users WHERE username = ?",
            (username,)
        )

        row = cursor.fetchone()

        # Username must exist first - highest priority error.

        if not row:
            conn.close()
            logger.warning(
                f"Reset request failed: unknown username '{username}'"
            )
            return False, "No account found with that username."

        registered_email = (row[0] or "").strip().lower()

        # Email must match the registered email - second priority error.
        # Basic email format check before comparing to the record.

        if not re.match(
            r"^[a-zA-Z0-9._%+-]+@(gmail\.com|yahoo\.com)$",
            email_input.strip().lower()
        ):
            conn.close()
            return False, "Email must be a valid @gmail.com or @yahoo.com address."

        if email_input.strip().lower() != registered_email:
            conn.close()
            logger.warning(
                f"Reset request failed: email mismatch for '{username}'"
            )
            return False, "The email does not match our records for this username."

        # Password requirements - third priority.

        try:
            validated = PasswordResetSchema(
                username=username,
                email=email_input,
                password=new_password
            )
        except ValidationError as e:
            conn.close()
            err_msg = e.errors()[0]["msg"]
            return False, f"Validation Error: {err_msg}"

        # Confirm password match - final check.

        if new_password != confirm_password:
            conn.close()
            return False, "New password and confirmation do not match."

        hashed_pw = bcrypt.hashpw(
            validated.password.encode("utf-8"),
            bcrypt.gensalt()
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO reset_requests
            (
                username,
                email,
                new_password_hash,
                timestamp,
                status
            )
            VALUES (?, ?, ?, ?, 'pending')
        """, (
            username,
            registered_email,
            hashed_pw.decode("utf-8"),
            timestamp
        ))

        conn.commit()
        conn.close()

        logger.info(
            f"Password reset/unlock request submitted for '{username}'."
        )

        return True, (
            "Your reset request has been submitted.\n"
            "An administrator must approve it before you can log in again."
        )

    def get_pending_reset_requests(self):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT request_id, username, email, timestamp
            FROM reset_requests
            WHERE status = 'pending'
            ORDER BY request_id ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        return rows

    def approve_reset_request(self, request_id):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT username, new_password_hash, status
            FROM reset_requests
            WHERE request_id = ?
        """, (request_id,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            return False, "Request not found."

        username, new_password_hash, status = row

        if status != "pending":
            conn.close()
            return False, "This request has already been processed."

        cursor.execute("""
            UPDATE users
            SET password_hash = ?,
                failed_attempts = 0,
                locked = 0
            WHERE username = ?
        """, (new_password_hash, username))

        cursor.execute("""
            UPDATE reset_requests
            SET status = 'approved'
            WHERE request_id = ?
        """, (request_id,))

        conn.commit()
        conn.close()

        logger.info(
            f"Reset request #{request_id} for '{username}' approved. Account unlocked."
        )

        return True, f"Reset request for '{username}' approved. Account unlocked."

    def reject_reset_request(self, request_id):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT username, status
            FROM reset_requests
            WHERE request_id = ?
        """, (request_id,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            return False, "Request not found."

        username, status = row

        if status != "pending":
            conn.close()
            return False, "This request has already been processed."

        cursor.execute("""
            UPDATE reset_requests
            SET status = 'rejected'
            WHERE request_id = ?
        """, (request_id,))

        conn.commit()
        conn.close()

        logger.info(
            f"Reset request #{request_id} for '{username}' rejected."
        )

        return True, f"Reset request for '{username}' rejected. Account remains locked."

    # ==========================================
    # DIRECT PASSWORD UPDATE (LOGGED-IN USER)
    # ==========================================

    def update_password_direct(self, username, new_password, confirm_password):

        if new_password != confirm_password:
            return False, "New password and confirmation do not match."

        missing = get_password_requirements(new_password)

        if missing:
            return False, "Password is missing: " + ", ".join(missing) + "."

        hashed_pw = bcrypt.hashpw(
            new_password.encode("utf-8"),
            bcrypt.gensalt()
        )

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE users
            SET password_hash = ?
            WHERE username = ?
        """, (hashed_pw.decode("utf-8"), username))

        conn.commit()
        conn.close()

        logger.info(f"User '{username}' updated their password directly.")

        return True, "Password updated successfully!"

    # ==========================================
    # ACCOUNT / PROFILE INFO
    # ==========================================

    def get_user_profile(self, username):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT username, email, role
            FROM users
            WHERE username = ?
        """, (username,))

        row = cursor.fetchone()
        conn.close()

        return row

    # ==========================================
    # FETCH HARDWARE
    # ==========================================

    def fetch_all_hardware(self):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                item_id,
                item_name,
                category,
                quantity,
                unit_price,
                status
            FROM hardware
        """)

        rows = cursor.fetchall()

        conn.close()

        return rows

    # ==========================================
    # FETCH / FILTER HARDWARE (CATEGORY + SEARCH)
    # ==========================================

    def fetch_filtered_hardware(self, category="All Categories", search_text=""):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        query = """
            SELECT
                item_id,
                item_name,
                category,
                quantity,
                unit_price,
                status
            FROM hardware
            WHERE 1 = 1
        """

        params = []

        if category and category != "All Categories":
            query += " AND category = ?"
            params.append(category)

        if search_text:
            query += " AND LOWER(item_name) LIKE ?"
            params.append(f"%{search_text.strip().lower()}%")

        query += " ORDER BY item_name ASC"

        cursor.execute(query, params)

        rows = cursor.fetchall()

        conn.close()

        return rows

    def get_distinct_categories(self):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT category
            FROM hardware
            ORDER BY category ASC
        """)

        rows = [r[0] for r in cursor.fetchall()]

        conn.close()

        return rows

    # ==========================================
    # TOTAL ASSET VALUE
    # ==========================================

    def get_total_asset_value(self):

        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT SUM(quantity * unit_price)
            FROM hardware
        """)

        total = cursor.fetchone()[0]

        conn.close()

        return total if total is not None else 0.0

    # ==========================================
    # ADD HARDWARE
    # ==========================================

    def add_hardware(
        self,
        item_name,
        category,
        quantity_str,
        unit_price_str
    ):

        try:

            qty = int(quantity_str)
            price = float(unit_price_str)

            validated = HardwareSchema(
                item_name=item_name,
                category=category,
                quantity=qty,
                unit_price=price
            )

        except (ValueError, ValidationError) as e:

            if isinstance(e, ValidationError):
                err_msg = e.errors()[0]["msg"]
            else:
                err_msg = "Invalid numbers."

            logger.warning(
                f"Hardware validation failed: {err_msg}"
            )

            return False, f"Validation Error: {err_msg}"

        status = calculate_status(validated.quantity)

        conn = None

        try:

            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()

            # Case-insensitive duplicate check

            cursor.execute("""
                SELECT item_id
                FROM hardware
                WHERE LOWER(item_name) = LOWER(?)
            """, (
                validated.item_name.strip(),
            ))

            if cursor.fetchone():

                logger.warning(
                    f"Duplicate entry attempt: "
                    f"'{validated.item_name}'"
                )

                return False, (
                    f"An item named '{validated.item_name}' "
                    f"already exists in inventory."
                )

            cursor.execute("""
                INSERT INTO hardware
                (
                    item_name,
                    category,
                    quantity,
                    unit_price,
                    status
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                validated.item_name.strip(),
                validated.category.strip(),
                validated.quantity,
                validated.unit_price,
                status
            ))

            conn.commit()

            logger.info(
                f"New equipment added: '{validated.item_name}'"
            )

            return True, "Equipment added successfully!"

        except sqlite3.IntegrityError:

            logger.warning(
                f"Integrity violation adding hardware: "
                f"'{validated.item_name}'"
            )

            return False, (
                f"An item named '{validated.item_name}' "
                f"already exists!"
            )

        except sqlite3.Error as e:

            logger.error(
                f"Database error on adding hardware: {e}"
            )

            return False, f"Database Error: {e}"

        finally:

            if conn:
                conn.close()

    # ==========================================
    # UPDATE HARDWARE
    # ==========================================

    def update_hardware(
        self,
        item_id,
        quantity_str,
        unit_price_str
    ):

        conn = None

        try:

            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT quantity, unit_price
                FROM hardware
                WHERE item_id = ?
            """, (item_id,))

            current_record = cursor.fetchone()

            if not current_record:

                return False, (
                    "Selected record could not be found."
                )

            current_qty, current_price = current_record

            new_qty = (
                int(quantity_str)
                if quantity_str.strip()
                else current_qty
            )

            new_price = (
                float(unit_price_str)
                if unit_price_str.strip()
                else current_price
            )

            if new_qty < 0 or new_price < 0:

                raise ValueError(
                    "Quantity and price must be non-negative."
                )

            new_status = calculate_status(new_qty)

            cursor.execute("""
                UPDATE hardware
                SET
                    quantity = ?,
                    unit_price = ?,
                    status = ?
                WHERE item_id = ?
            """, (
                new_qty,
                new_price,
                new_status,
                item_id
            ))

            conn.commit()

            logger.info(
                f"Hardware ID {item_id} updated. "
                f"New Qty: {new_qty}, "
                f"New Price: {new_price}"
            )

            return True, "Record updated successfully!"

        except ValueError:

            logger.warning(
                f"Update failed for item ID {item_id}: "
                f"Invalid numeric input."
            )

            return False, (
                "Quantity must be a valid non-negative "
                "integer and price a valid number."
            )

        except sqlite3.Error as e:

            logger.error(
                f"Database update error for ID {item_id}: {e}"
            )

            return False, "Database update failed."

        finally:

            if conn:
                conn.close()

    # ==========================================
    # DELETE HARDWARE
    # ==========================================

    def delete_hardware(self, item_id):

        conn = None

        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT item_name FROM hardware WHERE item_id = ?",
                (item_id,)
            )

            record = cursor.fetchone()

            if not record:
                return False, "Selected record could not be found."

            cursor.execute(
                "DELETE FROM hardware WHERE item_id = ?",
                (item_id,)
            )

            conn.commit()

            logger.info(
                f"Hardware ID {item_id} ('{record[0]}') deleted."
            )

            return True, f"'{record[0]}' was deleted successfully."

        except sqlite3.Error as e:

            logger.error(f"Database delete error for ID {item_id}: {e}")

            return False, "Database delete failed."

        finally:

            if conn:
                conn.close()

    # ==========================================
    # CSV EXPORT
    # ==========================================

    def export_to_csv(
        self,
        filename="inventory_report.csv"
    ):

        try:

            rows = self.fetch_all_hardware()

            timestamp = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            total_valuation = 0.0
            formatted_rows = []

            for r in rows:

                (
                    item_id,
                    item_name,
                    category,
                    qty,
                    unit_price,
                    status
                ) = r

                item_total = qty * unit_price

                total_valuation += item_total

                formatted_rows.append([
                    item_id,
                    item_name,
                    category,
                    qty,
                    f"${unit_price:,.2f}",
                    f"${item_total:,.2f}",
                    status
                ])

            with open(
                filename,
                mode="w",
                newline="",
                encoding="utf-8"
            ) as file:

                writer = csv.writer(file)

                writer.writerow([
                    "=================================================="
                ])

                writer.writerow([
                    "CAMPUS HARDWARE INVENTORY MANAGEMENT REPORT"
                ])

                writer.writerow([
                    f"Generated On: {timestamp}"
                ])

                writer.writerow([
                    f"Total Recorded Items: {len(rows)}"
                ])

                writer.writerow([
                    "=================================================="
                ])

                writer.writerow([])

                writer.writerow([
                    "Item ID",
                    "Item Name",
                    "Category",
                    "Quantity",
                    "Unit Price",
                    "Total Price",
                    "Status"
                ])

                writer.writerows(formatted_rows)

                writer.writerow([])

                writer.writerow([
                    "",
                    "",
                    "",
                    "",
                    "GRAND TOTAL ASSET VALUE:",
                    f"${total_valuation:,.2f}",
                    ""
                ])

            logger.info(
                f"CSV Export generated: {filename}. "
                f"Total Value: ${total_valuation:,.2f}"
            )

            return True, (
                f"Report successfully exported to "
                f"{filename}!"
            )

        except Exception as e:

            logger.error(
                f"CSV Export failed: {e}"
            )

            return False, f"Export failed: {e}"


# ==========================================
# 7. LOGIN / REGISTER / RESET WINDOW
# ==========================================

class LoginWindow:

    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success
        self.controller = InventoryController()
        self.root.title("Campus Hardware Inventory - Authentication")
        self.root.geometry("520x680")
        self.root.resizable(False, False)
        self.root.configure(bg=COLOR_BG)

        header = tk.Frame(root, bg=COLOR_HEADER_BG)
        header.pack(fill="x")
        tk.Label(header, text="Campus Hardware Inventory", font=("Segoe UI", 18, "bold"),
                 bg=COLOR_HEADER_BG, fg=COLOR_HEADER_FG, pady=14).pack()
        tk.Label(header, text="User Authentication", font=("Segoe UI", 11),
                 bg=COLOR_HEADER_BG, fg="white").pack(pady=(0, 12))

        self.notebook = ttk.Notebook(root)
        self.login_frame = tk.Frame(self.notebook, bg=COLOR_BG)
        self.register_frame = tk.Frame(self.notebook, bg=COLOR_BG)
        self.reset_frame = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.login_frame, text="  Login  ")
        self.notebook.add(self.register_frame, text="  Register  ")
        self.notebook.add(self.reset_frame, text="  Reset / Unlock Password  ")
        self.notebook.pack(fill="both", expand=True, padx=25, pady=15)

        self.create_login_pane()
        self.create_register_pane()
        self.create_reset_pane()

    def create_login_pane(self):
        frame = self.login_frame
        tk.Label(frame, text="Username:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(30, 5))
        self.login_username = tk.Entry(frame, width=38, relief="solid", bd=1)
        self.login_username.pack(padx=40, pady=(0, 15))
        tk.Label(frame, text="Password:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.login_password = tk.Entry(frame, show="*", width=38, relief="solid", bd=1)
        self.login_password.pack(padx=40)
        self.login_show_password = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Show Password", variable=self.login_show_password, command=self.toggle_login_password,
                       bg=COLOR_BG, fg=COLOR_TEXT_MUTED, selectcolor=COLOR_BG).pack(anchor="w", padx=40, pady=(0, 15))
        make_button(frame, "Login", self.handle_login, kind="primary", width=18, height=2).pack(pady=10)

    def create_register_pane(self):
        frame = self.register_frame
        tk.Label(frame, text="Username:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(20, 5))
        self.register_username = tk.Entry(frame, width=38, relief="solid", bd=1)
        self.register_username.pack(padx=40, pady=(0, 10))
        tk.Label(frame, text="Email Address:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.register_email = tk.Entry(frame, width=38, relief="solid", bd=1)
        self.register_email.pack(padx=40, pady=(0, 3))
        tk.Label(frame, text="Only @gmail.com or @yahoo.com addresses are accepted.", fg=COLOR_TEXT_MUTED, bg=COLOR_BG, font=("Segoe UI", 8)).pack(anchor="w", padx=40, pady=(0, 10))
        tk.Label(frame, text="Account Role:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.register_role = ttk.Combobox(frame, values=[ROLE_USER, ROLE_ADMIN], state="readonly", width=35)
        self.register_role.current(0)
        self.register_role.pack(padx=40, pady=(0, 10))
        tk.Label(frame, text="Password:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.register_password = tk.Entry(frame, show="*", width=38, relief="solid", bd=1)
        self.register_password.pack(padx=40)
        self.register_password_note = tk.Label(frame, text=PASSWORD_REQUIREMENTS_TEXT, fg="#B3413E", bg=COLOR_BG, font=("Segoe UI", 9), wraplength=360, justify="left")
        self.register_password_note.pack(anchor="w", padx=40, pady=(5, 5))
        self.register_password.bind("<KeyRelease>", self.update_register_password_note)
        self.register_show_password = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Show Password", variable=self.register_show_password, command=self.toggle_register_password,
                       bg=COLOR_BG, fg=COLOR_TEXT_MUTED, selectcolor=COLOR_BG).pack(anchor="w", padx=40, pady=(0, 10))
        tk.Label(frame, text="New accounts require SuperAdmin approval before login.", fg=COLOR_GOLD_DARK, bg=COLOR_BG, font=("Segoe UI", 9, "italic"), wraplength=360, justify="left").pack(anchor="w", padx=40, pady=(0, 5))
        make_button(frame, "Request Account", self.handle_register, kind="secondary", width=18, height=2).pack(pady=10)

    def create_reset_pane(self):
        frame = self.reset_frame
        tk.Label(frame, text="Reset / Unlock your account by submitting a new\npassword. An administrator must approve this\nrequest before you can log in again.", font=("Segoe UI", 9), fg=COLOR_TEXT_MUTED, bg=COLOR_BG, justify="left").pack(anchor="w", padx=40, pady=(20, 15))
        tk.Label(frame, text="Account Username:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.reset_username = tk.Entry(frame, width=38, relief="solid", bd=1); self.reset_username.pack(padx=40, pady=(0, 10))
        tk.Label(frame, text="Registered Email:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.reset_email = tk.Entry(frame, width=38, relief="solid", bd=1); self.reset_email.pack(padx=40, pady=(0, 10))
        tk.Label(frame, text="Desired New Password:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.reset_new_password = tk.Entry(frame, show="*", width=38, relief="solid", bd=1); self.reset_new_password.pack(padx=40)
        self.reset_password_note = tk.Label(frame, text=PASSWORD_REQUIREMENTS_TEXT, fg="#B3413E", bg=COLOR_BG, font=("Segoe UI", 9), wraplength=360, justify="left")
        self.reset_password_note.pack(anchor="w", padx=40, pady=(5, 10))
        self.reset_new_password.bind("<KeyRelease>", self.update_reset_password_note)
        tk.Label(frame, text="Confirm New Password:", bg=COLOR_BG, fg=COLOR_TEXT_DARK, font=FONT_LABEL).pack(anchor="w", padx=40, pady=(0, 5))
        self.reset_confirm_password = tk.Entry(frame, show="*", width=38, relief="solid", bd=1); self.reset_confirm_password.pack(padx=40, pady=(0, 10))
        self.reset_show_password = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="Show Password", variable=self.reset_show_password, command=self.toggle_reset_password,
                       bg=COLOR_BG, fg=COLOR_TEXT_MUTED, selectcolor=COLOR_BG).pack(anchor="w", padx=40, pady=(0, 10))
        make_button(frame, "Submit Reset Request", self.handle_reset_submit, kind="primary", width=20, height=2).pack(pady=10)

    def update_register_password_note(self, event=None):
        self._update_password_note(self.register_password_note, self.register_password.get())

    def update_reset_password_note(self, event=None):
        self._update_password_note(self.reset_password_note, self.reset_new_password.get())

    @staticmethod
    def _update_password_note(label_widget, password):
        missing = get_password_requirements(password)
        if not password:
            label_widget.config(text=PASSWORD_REQUIREMENTS_TEXT, fg="#B3413E")
        elif missing:
            label_widget.config(text="Password is missing:\n• " + "\n• ".join(missing), fg="#B3413E")
        else:
            label_widget.config(text="✓ Password meets all requirements.", fg="#2F7D5B")

    def toggle_login_password(self):
        self.login_password.config(show="" if self.login_show_password.get() else "*")

    def toggle_register_password(self):
        self.register_password.config(show="" if self.register_show_password.get() else "*")

    def toggle_reset_password(self):
        show_char = "" if self.reset_show_password.get() else "*"
        self.reset_new_password.config(show=show_char)
        self.reset_confirm_password.config(show=show_char)

    def handle_login(self):
        user = self.login_username.get().strip(); pwd = self.login_password.get()
        status, msg, role = self.controller.login_user(user, pwd)
        if status == "success":
            messagebox.showinfo("Success", msg); self.on_success(user, role)
        elif status == "locked":
            messagebox.showerror("Account Locked", msg)
            self.reset_username.delete(0, tk.END); self.reset_username.insert(0, user)
            self.notebook.select(self.reset_frame)
        else:
            messagebox.showerror("Login Failed", msg)

    def handle_register(self):
        user = self.register_username.get().strip(); email = self.register_email.get().strip(); pwd = self.register_password.get(); role = self.register_role.get().strip()
        success, msg = self.controller.submit_registration_request(user, email, pwd, role)
        if success:
            messagebox.showinfo("Account Request Submitted", msg)
            for entry in (self.register_username, self.register_email, self.register_password): entry.delete(0, tk.END)
            self.register_role.current(0); self.update_register_password_note(); self.notebook.select(self.login_frame)
        else:
            messagebox.showwarning("Account Request", msg)

    def handle_reset_submit(self):
        username = self.reset_username.get().strip(); email = self.reset_email.get().strip(); new_password = self.reset_new_password.get(); confirm_password = self.reset_confirm_password.get()
        success, msg = self.controller.submit_reset_request(username, email, new_password, confirm_password)
        if success:
            messagebox.showinfo("Request Submitted", msg)
            for entry in (self.reset_username, self.reset_email, self.reset_new_password, self.reset_confirm_password): entry.delete(0, tk.END)
            self.update_reset_password_note(); self.notebook.select(self.login_frame)
        else:
            messagebox.showwarning("Reset Request Error", msg)

# ==========================================
# 8. INVENTORY WINDOW
# ==========================================

class InventoryWindow:

    def __init__(self, root, username, role, on_logout):
        self.root = root; self.username = username; self.role = role; self.on_logout = on_logout
        self.controller = InventoryController()
        self.is_admin = role in (ROLE_ADMIN, ROLE_SUPER_ADMIN)
        self.is_super_admin = role == ROLE_SUPER_ADMIN
        self.cart = []  # list of dicts: {"item_id", "item_name", "quantity", "available"}
        self.root.title(f"Campus Hardware Inventory - User: {self.username} ({self.role})")
        self.root.geometry("1060x860")
        self.root.configure(bg=COLOR_BG)

        header = tk.Frame(self.root, bg=COLOR_HEADER_BG); header.pack(fill="x")
        tk.Label(header, text=f"Logged in as: {self.username}  |  Role: {self.role}", font=("Segoe UI", 11, "bold"), bg=COLOR_HEADER_BG, fg=COLOR_HEADER_FG, pady=10, padx=12).pack(side="left")
        self.lbl_valuation = tk.Label(header, text="Total Asset Value: $0.00", font=("Segoe UI", 11, "bold"), bg=COLOR_HEADER_BG, fg=COLOR_HEADER_FG, pady=10, padx=12); self.lbl_valuation.pack(side="right")

        self.notebook = ttk.Notebook(self.root); self.notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self.catalog_frame = tk.Frame(self.notebook, bg=COLOR_BG); self.notebook.add(self.catalog_frame, text="  Hardware Catalog  "); self.build_catalog_tab(self.catalog_frame)

        if self.is_admin:
            self.approvals_frame = tk.Frame(self.notebook, bg=COLOR_BG); self.notebook.add(self.approvals_frame, text="  Requests & Approvals  "); self.build_approvals_tab(self.approvals_frame)
            if self.is_super_admin:
                self.accounts_frame = tk.Frame(self.notebook, bg=COLOR_BG); self.notebook.add(self.accounts_frame, text="  Manage Accounts  "); self.build_accounts_tab(self.accounts_frame)
        else:
            self.profile_frame = tk.Frame(self.notebook, bg=COLOR_BG); self.notebook.add(self.profile_frame, text="  My Profile and Security  "); self.build_profile_tab(self.profile_frame)

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        frame_bottom = tk.Frame(self.root, bg=COLOR_BG); frame_bottom.pack(fill="x", padx=10, pady=(0, 10))
        make_button(frame_bottom, "Logout", self.logout, kind="danger").pack(side="right", padx=5)
        self.refresh_data()

    def on_tab_changed(self, event=None):
        selected = self.notebook.select()
        if self.is_admin and selected == str(self.approvals_frame):
            self.refresh_approvals()
        elif self.is_super_admin and selected == str(self.accounts_frame):
            self.refresh_accounts()

    # ==========================================
    # HARDWARE CATALOG TAB (shared by all roles;
    # non-admin users borrow directly from here via a cart)
    # ==========================================

    def build_catalog_tab(self, parent):
        if self.is_admin:
            frame_form = tk.LabelFrame(parent, text="Add New Equipment", padx=10, pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold")); frame_form.pack(fill="x", padx=10, pady=5)
            inner_form = tk.Frame(frame_form, bg=COLOR_PANEL_BG); inner_form.pack(side="left", padx=5)
            tk.Label(inner_form, text="Name:", bg=COLOR_PANEL_BG).grid(row=0,column=0,padx=5,pady=5,sticky="e"); self.ent_name=tk.Entry(inner_form,width=20,relief="solid",bd=1); self.ent_name.grid(row=0,column=1,padx=5,pady=5)
            tk.Label(inner_form,text="Category:", bg=COLOR_PANEL_BG).grid(row=0,column=2,padx=5,pady=5,sticky="e"); self.ent_cat=tk.Entry(inner_form,width=20,relief="solid",bd=1); self.ent_cat.grid(row=0,column=3,padx=5,pady=5)
            tk.Label(inner_form,text="Quantity:", bg=COLOR_PANEL_BG).grid(row=1,column=0,padx=5,pady=5,sticky="e"); self.ent_qty=tk.Entry(inner_form,width=20,relief="solid",bd=1); self.ent_qty.grid(row=1,column=1,padx=5,pady=5)
            tk.Label(inner_form,text="Unit Price ($):", bg=COLOR_PANEL_BG).grid(row=1,column=2,padx=5,pady=5,sticky="e"); self.ent_price=tk.Entry(inner_form,width=20,relief="solid",bd=1); self.ent_price.grid(row=1,column=3,padx=5,pady=5)
            make_button(inner_form,"Save Item",self.add_item,kind="primary",padx=10).grid(row=0,column=4,rowspan=2,padx=15,pady=5,sticky="nsew")
            frame_legend=tk.LabelFrame(frame_form,text="Status Legend",padx=10,pady=5, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold")); frame_legend.pack(side="right",padx=15,pady=5)
            tk.Label(frame_legend,text="In Stock (> 5)",bg=COLOR_IN_STOCK_BG,fg=COLOR_IN_STOCK_FG,font=("Segoe UI",8,"bold"),relief="solid",bd=1).grid(row=0,column=0,padx=5,pady=2,sticky="ew")
            tk.Label(frame_legend,text="Low Stock (1-5)",bg=COLOR_LOW_STOCK_BG,fg=COLOR_LOW_STOCK_FG,font=("Segoe UI",8,"bold"),relief="solid",bd=1).grid(row=1,column=0,padx=5,pady=2,sticky="ew")
            tk.Label(frame_legend,text="Out of Stock (0)",bg=COLOR_OUT_STOCK_BG,fg=COLOR_OUT_STOCK_FG,font=("Segoe UI",8,"bold"),relief="solid",bd=1).grid(row=2,column=0,padx=5,pady=2,sticky="ew")
        else:
            tk.Label(parent, text="Browse equipment below. Select an item, choose a quantity, and add it to your borrow cart.", font=("Segoe UI", 10), bg=COLOR_BG, fg=COLOR_TEXT_DARK).pack(anchor="w", padx=15, pady=(10, 0))

        frame_filter=tk.LabelFrame(parent,text="Filter & Search",padx=10,pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold")); frame_filter.pack(fill="x",padx=10,pady=5)
        tk.Label(frame_filter,text="Category:", bg=COLOR_PANEL_BG).pack(side="left",padx=(5,5)); self.category_filter=ttk.Combobox(frame_filter,state="readonly",width=22); self.category_filter.pack(side="left",padx=(0,20)); self.category_filter.bind("<<ComboboxSelected>>",lambda e:self.refresh_data())
        tk.Label(frame_filter,text="Search Name:", bg=COLOR_PANEL_BG).pack(side="left",padx=(5,5)); self.search_entry=tk.Entry(frame_filter,width=30,relief="solid",bd=1); self.search_entry.pack(side="left",padx=(0,5)); self.search_entry.bind("<KeyRelease>",lambda e:self.refresh_data())
        make_button(frame_filter,"Clear Filters",self.clear_filters,kind="secondary").pack(side="left",padx=10)

        frame_table=tk.Frame(parent, bg=COLOR_BG); frame_table.pack(fill="both",expand=True,padx=10,pady=5); scroll_y=tk.Scrollbar(frame_table,orient=tk.VERTICAL)
        self.tree=ttk.Treeview(frame_table,columns=("ID","Name","Category","Qty","Price","Status"),show="headings",yscrollcommand=scroll_y.set); scroll_y.config(command=self.tree.yview); scroll_y.pack(side=tk.RIGHT,fill=tk.Y)
        for col in self.tree["columns"]: self.tree.heading(col,text=col); self.tree.column(col,width=120,anchor="center")
        self.tree.tag_configure("In Stock",background=COLOR_IN_STOCK_BG,foreground=COLOR_IN_STOCK_FG); self.tree.tag_configure("Low Stock",background=COLOR_LOW_STOCK_BG,foreground=COLOR_LOW_STOCK_FG); self.tree.tag_configure("Out of Stock",background=COLOR_OUT_STOCK_BG,foreground=COLOR_OUT_STOCK_FG); self.tree.pack(fill="both",expand=True)

        if self.is_admin:
            frame_update=tk.LabelFrame(parent,text="Update / Delete Selected Record",padx=10,pady=5, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold")); frame_update.pack(fill="x",padx=10,pady=5); inner=tk.Frame(frame_update, bg=COLOR_PANEL_BG); inner.pack()
            tk.Label(inner,text="New Quantity:", bg=COLOR_PANEL_BG).grid(row=0,column=0,padx=5,pady=5,sticky="e"); self.ent_up_qty=tk.Entry(inner,width=18,relief="solid",bd=1); self.ent_up_qty.grid(row=0,column=1,padx=5,pady=5)
            tk.Label(inner,text="New Unit Price ($):", bg=COLOR_PANEL_BG).grid(row=0,column=2,padx=5,pady=5,sticky="e"); self.ent_up_price=tk.Entry(inner,width=18,relief="solid",bd=1); self.ent_up_price.grid(row=0,column=3,padx=5,pady=5)
            make_button(inner,"Update Record",self.update_item,kind="secondary",padx=10).grid(row=0,column=4,padx=15,pady=5); make_button(inner,"Delete Record",self.delete_item,kind="danger",padx=10).grid(row=0,column=5,padx=5,pady=5)
            controls=tk.Frame(parent, bg=COLOR_BG); controls.pack(fill="x",padx=10,pady=10); make_button(controls,"Export Inventory to CSV",self.export_csv,kind="secondary").pack(side="left",padx=5)
        else:
            self.build_cart_section(parent)

    # ------------------------------------------
    # Borrow Cart (non-admin users)
    # ------------------------------------------

    def build_cart_section(self, parent):
        frame_cart_controls = tk.LabelFrame(parent, text="Add to Borrow Cart", padx=10, pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold"))
        frame_cart_controls.pack(fill="x", padx=10, pady=5)
        tk.Label(frame_cart_controls, text="Quantity:", bg=COLOR_PANEL_BG).pack(side="left", padx=5)
        self.cart_qty_entry = tk.Entry(frame_cart_controls, width=10, relief="solid", bd=1)
        self.cart_qty_entry.pack(side="left", padx=5)
        self.cart_qty_entry.insert(0, "1")
        make_button(frame_cart_controls, "Add Selected Item to Cart", self.add_to_cart, kind="secondary", padx=10).pack(side="left", padx=15)

        frame_cart = tk.LabelFrame(parent, text="Borrow Cart", padx=10, pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold"))
        frame_cart.pack(fill="both", padx=10, pady=5)

        cart_table_frame = tk.Frame(frame_cart, bg=COLOR_PANEL_BG); cart_table_frame.pack(fill="both", expand=True)
        cart_scroll = tk.Scrollbar(cart_table_frame, orient=tk.VERTICAL)
        self.cart_tree = ttk.Treeview(cart_table_frame, columns=("Item", "Quantity"), show="headings", height=6, yscrollcommand=cart_scroll.set)
        cart_scroll.config(command=self.cart_tree.yview); cart_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for col in self.cart_tree["columns"]:
            self.cart_tree.heading(col, text=col)
            self.cart_tree.column(col, width=200 if col == "Item" else 100, anchor="center")
        self.cart_tree.pack(fill="both", expand=True)

        cart_buttons = tk.Frame(frame_cart, bg=COLOR_PANEL_BG); cart_buttons.pack(fill="x", pady=8)
        make_button(cart_buttons, "Remove Selected from Cart", self.remove_from_cart, kind="danger").pack(side="left", padx=5)
        make_button(cart_buttons, "Clear Cart", self.clear_cart, kind="secondary").pack(side="left", padx=5)
        make_button(cart_buttons, "Submit Borrow Request", self.submit_cart, kind="primary", padx=10).pack(side="right", padx=5)

        # Regular users can also pull a CSV snapshot of the current
        # inventory catalog for their own records / printing.
        frame_reports = tk.LabelFrame(parent, text="Reports", padx=10, pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold"))
        frame_reports.pack(fill="x", padx=10, pady=5)
        tk.Label(frame_reports, text="Export the current hardware catalog to a CSV file you can open in Excel or print.",
                 bg=COLOR_PANEL_BG, fg=COLOR_TEXT_MUTED, font=("Segoe UI", 9)).pack(side="left", padx=5)
        make_button(frame_reports, "Export Inventory to CSV", self.export_csv, kind="secondary", padx=10).pack(side="right", padx=5)

    def add_to_cart(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Selection Error", "Please select an item from the catalog to add to your cart.")
            return

        values = self.tree.item(selected[0], "values")
        item_id, item_name, category, available, price, status = values
        available = int(available)

        try:
            qty = int(self.cart_qty_entry.get().strip())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid Quantity", "Please enter a valid whole number greater than 0.")
            return

        already_in_cart = sum(c["quantity"] for c in self.cart if c["item_id"] == item_id)

        if qty + already_in_cart > available:
            messagebox.showwarning(
                "Not Enough Stock",
                f"Only {available} unit(s) of '{item_name}' are available "
                f"({already_in_cart} already in your cart)."
            )
            return

        for c in self.cart:
            if c["item_id"] == item_id:
                c["quantity"] += qty
                break
        else:
            self.cart.append({
                "item_id": item_id,
                "item_name": item_name,
                "quantity": qty,
                "available": available
            })

        self.refresh_cart_tree()

    def remove_from_cart(self):
        selected = self.cart_tree.selection()
        if not selected:
            messagebox.showwarning("Selection Error", "Please select a cart entry to remove.")
            return
        index = self.cart_tree.index(selected[0])
        del self.cart[index]
        self.refresh_cart_tree()

    def clear_cart(self):
        self.cart = []
        self.refresh_cart_tree()

    def refresh_cart_tree(self):
        if not hasattr(self, "cart_tree"):
            return
        for row in self.cart_tree.get_children():
            self.cart_tree.delete(row)
        for c in self.cart:
            self.cart_tree.insert("", tk.END, values=(c["item_name"], c["quantity"]))

    def submit_cart(self):
        if not self.cart:
            messagebox.showwarning("Empty Cart", "Add at least one item to your cart before submitting.")
            return
        cart_items = [(c["item_id"], c["quantity"]) for c in self.cart]
        success, msg = self.controller.submit_borrow_cart(self.username, cart_items)
        if success:
            messagebox.showinfo("Borrow Request Submitted", msg)
            self.clear_cart()
            self.refresh_data()
        else:
            messagebox.showwarning("Borrow Request", msg)

    # ==========================================
    # PROFILE TAB (non-admin users)
    # ==========================================

    def build_profile_tab(self,parent):
        profile_row=self.controller.get_user_profile(self.username); acc_username,acc_email,acc_role=profile_row if profile_row else (self.username,"",self.role)
        overview=tk.LabelFrame(parent,text="Account Overview",padx=15,pady=15, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold")); overview.pack(fill="x",padx=20,pady=20)
        tk.Label(overview,text=f"Username: {acc_username}",font=("Segoe UI",10), bg=COLOR_PANEL_BG, fg=COLOR_TEXT_DARK).grid(row=0,column=0,sticky="w",pady=3); tk.Label(overview,text=f"Registered Email: {acc_email}",font=("Segoe UI",10), bg=COLOR_PANEL_BG, fg=COLOR_TEXT_DARK).grid(row=1,column=0,sticky="w",pady=3); tk.Label(overview,text=f"Account Role: {acc_role}",font=("Segoe UI",10), bg=COLOR_PANEL_BG, fg=COLOR_TEXT_DARK).grid(row=2,column=0,sticky="w",pady=3)
        security=tk.LabelFrame(parent,text="Update Password Directly",padx=15,pady=15, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 9, "bold")); security.pack(fill="x",padx=20,pady=(0,20))
        tk.Label(security,text="New Password:", bg=COLOR_PANEL_BG).grid(row=0,column=0,sticky="e",padx=5,pady=5); self.profile_new_password=tk.Entry(security,show="*",width=30,relief="solid",bd=1); self.profile_new_password.grid(row=0,column=1,padx=5,pady=5)
        tk.Label(security,text="Confirm Password:", bg=COLOR_PANEL_BG).grid(row=1,column=0,sticky="e",padx=5,pady=5); self.profile_confirm_password=tk.Entry(security,show="*",width=30,relief="solid",bd=1); self.profile_confirm_password.grid(row=1,column=1,padx=5,pady=5)
        self.profile_password_note=tk.Label(security,text=PASSWORD_REQUIREMENTS_TEXT,fg="#B3413E",bg=COLOR_PANEL_BG,font=("Segoe UI",9),wraplength=360,justify="left"); self.profile_password_note.grid(row=2,column=0,columnspan=2,sticky="w",padx=5,pady=5); self.profile_new_password.bind("<KeyRelease>",self.update_profile_password_note)
        self.profile_show_password=tk.BooleanVar(value=False); tk.Checkbutton(security,text="Show Password",variable=self.profile_show_password,command=self.toggle_profile_password, bg=COLOR_PANEL_BG, selectcolor=COLOR_PANEL_BG).grid(row=3,column=0,columnspan=2,sticky="w",padx=5,pady=(0,10)); make_button(security,"Update Password",self.handle_profile_password_update,kind="secondary",padx=10).grid(row=4,column=0,columnspan=2,pady=5)

    def update_profile_password_note(self,event=None): LoginWindow._update_password_note(self.profile_password_note,self.profile_new_password.get())
    def toggle_profile_password(self):
        show_char="" if self.profile_show_password.get() else "*"; self.profile_new_password.config(show=show_char); self.profile_confirm_password.config(show=show_char)
    def handle_profile_password_update(self):
        success,msg=self.controller.update_password_direct(self.username,self.profile_new_password.get(),self.profile_confirm_password.get())
        if success: messagebox.showinfo("Success",msg); self.profile_new_password.delete(0,tk.END); self.profile_confirm_password.delete(0,tk.END); self.update_profile_password_note()
        else: messagebox.showerror("Password Update Failed",msg)

    # ==========================================
    # REQUESTS & APPROVALS TAB (Admin + SuperAdmin)
    # ==========================================

    def build_approvals_tab(self,parent):
        approvals_canvas = tk.Canvas(parent, highlightthickness=0, bg=COLOR_BG)
        approvals_scroll = tk.Scrollbar(parent, orient=tk.VERTICAL, command=approvals_canvas.yview)
        approvals_body = tk.Frame(approvals_canvas, bg=COLOR_BG)
        approvals_body.bind("<Configure>", lambda e: approvals_canvas.configure(scrollregion=approvals_canvas.bbox("all")))
        approvals_canvas.create_window((0, 0), window=approvals_body, anchor="nw")
        approvals_canvas.configure(yscrollcommand=approvals_scroll.set)
        approvals_canvas.pack(side="left", fill="both", expand=True)
        approvals_scroll.pack(side="right", fill="y")

        # SuperAdmin-only account creation approvals
        if self.is_super_admin:
            account_box=tk.LabelFrame(approvals_body,text="Pending Account Creation Requests",padx=10,pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 10, "bold")); account_box.pack(fill="both",expand=True,padx=15,pady=10)
            af=tk.Frame(account_box, bg=COLOR_PANEL_BG); af.pack(fill="both",expand=True); asc=tk.Scrollbar(af,orient=tk.VERTICAL)
            self.account_requests_tree=ttk.Treeview(af,columns=("Request ID","Username","Email","Role","Timestamp"),show="headings",height=5,yscrollcommand=asc.set); asc.config(command=self.account_requests_tree.yview); asc.pack(side=tk.RIGHT,fill=tk.Y)
            for col in self.account_requests_tree["columns"]: self.account_requests_tree.heading(col,text=col); self.account_requests_tree.column(col,width=140,anchor="center")
            self.account_requests_tree.pack(fill="both",expand=True)
            ab=tk.Frame(account_box, bg=COLOR_PANEL_BG); ab.pack(fill="x",pady=8); make_button(ab,"Approve Account",self.handle_approve_account,kind="primary",width=18).pack(side="left",padx=10); make_button(ab,"Reject Account",self.handle_reject_account,kind="danger",width=18).pack(side="left",padx=10)

        borrow_box=tk.LabelFrame(approvals_body,text="Pending Borrow Requests",padx=10,pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 10, "bold")); borrow_box.pack(fill="both",expand=True,padx=15,pady=10)
        bf=tk.Frame(borrow_box, bg=COLOR_PANEL_BG); bf.pack(fill="both",expand=True); bsc=tk.Scrollbar(bf,orient=tk.VERTICAL)
        self.borrow_requests_tree=ttk.Treeview(bf,columns=("Request ID","Username","Item","Quantity","Timestamp"),show="headings",height=5,yscrollcommand=bsc.set); bsc.config(command=self.borrow_requests_tree.yview); bsc.pack(side=tk.RIGHT,fill=tk.Y)
        for col in self.borrow_requests_tree["columns"]: self.borrow_requests_tree.heading(col,text=col); self.borrow_requests_tree.column(col,width=145,anchor="center")
        self.borrow_requests_tree.pack(fill="both",expand=True)
        bb=tk.Frame(borrow_box, bg=COLOR_PANEL_BG); bb.pack(fill="x",pady=8); make_button(bb,"Approve Borrow",self.handle_approve_borrow,kind="primary",width=18).pack(side="left",padx=10); make_button(bb,"Reject Borrow",self.handle_reject_borrow,kind="danger",width=18).pack(side="left",padx=10); make_button(bb,"Refresh Requests",self.refresh_approvals,kind="secondary").pack(side="left",padx=10)

        # Password Reset / Unlock approvals (Admin + SuperAdmin)
        reset_box=tk.LabelFrame(approvals_body,text="Pending Password Reset / Unlock Requests",padx=10,pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 10, "bold")); reset_box.pack(fill="both",expand=True,padx=15,pady=10)
        rrf=tk.Frame(reset_box, bg=COLOR_PANEL_BG); rrf.pack(fill="both",expand=True); rrsc=tk.Scrollbar(rrf,orient=tk.VERTICAL)
        self.reset_requests_tree=ttk.Treeview(rrf,columns=("Request ID","Username","Email","Timestamp"),show="headings",height=5,yscrollcommand=rrsc.set); rrsc.config(command=self.reset_requests_tree.yview); rrsc.pack(side=tk.RIGHT,fill=tk.Y)
        for col in self.reset_requests_tree["columns"]: self.reset_requests_tree.heading(col,text=col); self.reset_requests_tree.column(col,width=160,anchor="center")
        self.reset_requests_tree.pack(fill="both",expand=True)
        rrb=tk.Frame(reset_box, bg=COLOR_PANEL_BG); rrb.pack(fill="x",pady=8)
        make_button(rrb,"Approve Reset",self.handle_approve_reset,kind="primary",width=18).pack(side="left",padx=10)
        make_button(rrb,"Reject Reset",self.handle_reject_reset,kind="danger",width=18).pack(side="left",padx=10)
        make_button(rrb,"Refresh Requests",self.refresh_approvals,kind="secondary").pack(side="left",padx=10)
        tk.Label(reset_box, text="Approving unlocks the account and applies the password the user submitted.",
                 bg=COLOR_PANEL_BG, fg=COLOR_TEXT_MUTED, font=("Segoe UI", 8, "italic")).pack(anchor="w", padx=5, pady=(0, 5))

        # Active borrows / returns section (visible to Admin and SuperAdmin)
        returns_box=tk.LabelFrame(approvals_body,text="Borrowed Items (Mark as Returned)",padx=10,pady=10, bg=COLOR_PANEL_BG, fg=COLOR_HEADER_BG, font=("Segoe UI", 10, "bold")); returns_box.pack(fill="both",expand=True,padx=15,pady=10)
        rf=tk.Frame(returns_box, bg=COLOR_PANEL_BG); rf.pack(fill="both",expand=True); rsc=tk.Scrollbar(rf,orient=tk.VERTICAL)
        self.active_borrows_tree=ttk.Treeview(rf,columns=("Request ID","Username","Item","Quantity","Borrowed On"),show="headings",height=5,yscrollcommand=rsc.set); rsc.config(command=self.active_borrows_tree.yview); rsc.pack(side=tk.RIGHT,fill=tk.Y)
        for col in self.active_borrows_tree["columns"]: self.active_borrows_tree.heading(col,text=col); self.active_borrows_tree.column(col,width=145,anchor="center")
        self.active_borrows_tree.pack(fill="both",expand=True)
        rb=tk.Frame(returns_box, bg=COLOR_PANEL_BG); rb.pack(fill="x",pady=8); make_button(rb,"Mark as Returned",self.handle_mark_returned,kind="secondary",width=18).pack(side="left",padx=10); make_button(rb,"Refresh",self.refresh_approvals,kind="secondary").pack(side="left",padx=10)

        self.refresh_approvals()

    def refresh_approvals(self):
        if self.is_super_admin and hasattr(self,"account_requests_tree"):
            for row in self.account_requests_tree.get_children(): self.account_requests_tree.delete(row)
            for r in self.controller.get_pending_account_requests(): self.account_requests_tree.insert("",tk.END,values=r)
        if hasattr(self, "borrow_requests_tree"):
            for row in self.borrow_requests_tree.get_children(): self.borrow_requests_tree.delete(row)
            for r in self.controller.get_pending_borrow_requests(): self.borrow_requests_tree.insert("",tk.END,values=r)
        if hasattr(self, "reset_requests_tree"):
            for row in self.reset_requests_tree.get_children(): self.reset_requests_tree.delete(row)
            for r in self.controller.get_pending_reset_requests(): self.reset_requests_tree.insert("",tk.END,values=r)
        if hasattr(self, "active_borrows_tree"):
            for row in self.active_borrows_tree.get_children(): self.active_borrows_tree.delete(row)
            for r in self.controller.get_active_borrows(): self.active_borrows_tree.insert("",tk.END,values=r)

    def handle_approve_account(self):
        selected=self.account_requests_tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select an account request."); return
        request_id=self.account_requests_tree.item(selected[0],"values")[0]; success,msg=self.controller.approve_account_request(request_id); (messagebox.showinfo if success else messagebox.showerror)("Account Approval",msg); self.refresh_approvals()
    def handle_reject_account(self):
        selected=self.account_requests_tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select an account request."); return
        request_id=self.account_requests_tree.item(selected[0],"values")[0]; success,msg=self.controller.reject_account_request(request_id); (messagebox.showinfo if success else messagebox.showerror)("Account Request",msg); self.refresh_approvals()
    def handle_approve_borrow(self):
        selected=self.borrow_requests_tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select a borrow request."); return
        request_id=self.borrow_requests_tree.item(selected[0],"values")[0]; success,msg=self.controller.approve_borrow_request(request_id); (messagebox.showinfo if success else messagebox.showerror)("Borrow Approval",msg); self.refresh_approvals(); self.refresh_data()
    def handle_reject_borrow(self):
        selected=self.borrow_requests_tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select a borrow request."); return
        request_id=self.borrow_requests_tree.item(selected[0],"values")[0]; success,msg=self.controller.reject_borrow_request(request_id); (messagebox.showinfo if success else messagebox.showerror)("Borrow Request",msg); self.refresh_approvals()
    def handle_approve_reset(self):
        selected=self.reset_requests_tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select a password reset request."); return
        request_id=self.reset_requests_tree.item(selected[0],"values")[0]; success,msg=self.controller.approve_reset_request(request_id); (messagebox.showinfo if success else messagebox.showerror)("Reset Approval",msg); self.refresh_approvals()
    def handle_reject_reset(self):
        selected=self.reset_requests_tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select a password reset request."); return
        request_id=self.reset_requests_tree.item(selected[0],"values")[0]; success,msg=self.controller.reject_reset_request(request_id); (messagebox.showinfo if success else messagebox.showerror)("Reset Request",msg); self.refresh_approvals()
    def handle_mark_returned(self):
        selected=self.active_borrows_tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select a borrowed item to mark as returned."); return
        request_id=self.active_borrows_tree.item(selected[0],"values")[0]; success,msg=self.controller.mark_borrow_returned(request_id); (messagebox.showinfo if success else messagebox.showerror)("Mark as Returned",msg); self.refresh_approvals(); self.refresh_data()

    # ==========================================
    # MANAGE ACCOUNTS TAB (SuperAdmin only)
    # ==========================================

    def build_accounts_tab(self, parent):
        tk.Label(parent, text="All registered accounts (Admins and Users). The permanent SuperAdmin account cannot be removed.", font=("Segoe UI", 10), bg=COLOR_BG, fg=COLOR_TEXT_DARK, wraplength=700, justify="left").pack(anchor="w", padx=15, pady=(15, 10))

        frame = tk.Frame(parent, bg=COLOR_BG); frame.pack(fill="both", expand=True, padx=15, pady=5)
        scroll = tk.Scrollbar(frame, orient=tk.VERTICAL)
        self.accounts_tree = ttk.Treeview(frame, columns=("Username", "Email", "Role", "Locked"), show="headings", yscrollcommand=scroll.set)
        scroll.config(command=self.accounts_tree.yview); scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for col in self.accounts_tree["columns"]:
            self.accounts_tree.heading(col, text=col)
            self.accounts_tree.column(col, width=150, anchor="center")
        self.accounts_tree.pack(fill="both", expand=True)

        controls = tk.Frame(parent, bg=COLOR_BG); controls.pack(fill="x", padx=15, pady=10)
        make_button(controls, "Remove Selected Account", self.handle_remove_account, kind="danger", width=22).pack(side="left", padx=10)
        make_button(controls, "Refresh", self.refresh_accounts, kind="secondary").pack(side="left", padx=10)

        self.refresh_accounts()

    def refresh_accounts(self):
        if not hasattr(self, "accounts_tree"):
            return
        for row in self.accounts_tree.get_children():
            self.accounts_tree.delete(row)
        for username, email, role, locked in self.controller.get_all_accounts():
            self.accounts_tree.insert("", tk.END, values=(username, email, role, "Yes" if locked else "No"))

    def handle_remove_account(self):
        selected = self.accounts_tree.selection()
        if not selected:
            messagebox.showwarning("Selection Error", "Please select an account to remove.")
            return
        values = self.accounts_tree.item(selected[0], "values")
        username, email, role, locked = values
        if not messagebox.askyesno("Confirm Removal", f"Are you sure you want to permanently remove the account '{username}' ({role})? This cannot be undone."):
            return
        success, msg = self.controller.remove_account(username)
        (messagebox.showinfo if success else messagebox.showerror)("Remove Account", msg)
        self.refresh_accounts()

    # ==========================================
    # SHARED HELPERS
    # ==========================================

    def refresh_categories(self):
        categories=["All Categories"]+self.controller.get_distinct_categories(); current=self.category_filter.get(); self.category_filter["values"]=categories; self.category_filter.set(current if current in categories else "All Categories")
    def clear_filters(self): self.search_entry.delete(0,tk.END); self.category_filter.set("All Categories"); self.refresh_data()
    def refresh_data(self):
        self.refresh_categories()
        for row in self.tree.get_children(): self.tree.delete(row)
        rows=self.controller.fetch_filtered_hardware(self.category_filter.get() or "All Categories",self.search_entry.get() if hasattr(self,"search_entry") else "")
        for r in rows: self.tree.insert("",tk.END,values=r,tags=(r[5],))
        self.lbl_valuation.config(text=f"Total Asset Value: ${self.controller.get_total_asset_value():,.2f}")

    def add_item(self):
        success,msg=self.controller.add_hardware(self.ent_name.get().strip(),self.ent_cat.get().strip(),self.ent_qty.get().strip(),self.ent_price.get().strip())
        if success:
            messagebox.showinfo("Success",msg)
            for e in (self.ent_name,self.ent_cat,self.ent_qty,self.ent_price): e.delete(0,tk.END)
            self.refresh_data()
        else: messagebox.showwarning("Duplicate or Invalid Entry",msg)
    def update_item(self):
        selected=self.tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select a row from the table to update!"); return
        item_id=self.tree.item(selected[0],"values")[0]; success,msg=self.controller.update_hardware(item_id,self.ent_up_qty.get().strip(),self.ent_up_price.get().strip())
        (messagebox.showinfo if success else messagebox.showerror)("Update",msg)
        if success: self.ent_up_qty.delete(0,tk.END); self.ent_up_price.delete(0,tk.END); self.refresh_data()
    def delete_item(self):
        selected=self.tree.selection()
        if not selected: messagebox.showwarning("Selection Error","Please select a row from the table to delete!"); return
        vals=self.tree.item(selected[0],"values"); item_id,item_name=vals[0],vals[1]
        if not messagebox.askyesno("Confirm Delete",f"Are you sure you want to delete '{item_name}'? This cannot be undone."): return
        success,msg=self.controller.delete_hardware(item_id); (messagebox.showinfo if success else messagebox.showerror)("Delete",msg); self.refresh_data()
    def export_csv(self):
        success,msg=self.controller.export_to_csv(); (messagebox.showinfo if success else messagebox.showerror)("Export",msg)
    def logout(self): logger.info(f"User '{self.username}' logged out."); self.on_logout()

# ==========================================
# 9. APP LAUNCHER / WINDOW MANAGER
# ==========================================

def launch_main_app(username, role):

    for widget in root.winfo_children():
        widget.destroy()

    InventoryWindow(
        root,
        username,
        role,
        on_logout=launch_login
    )


def launch_login():

    for widget in root.winfo_children():
        widget.destroy()

    LoginWindow(
        root,
        on_success=launch_main_app
    )


# ==========================================
# 10. PROGRAM ENTRY POINT
# ==========================================

if __name__ == "__main__":

    init_db()

    root = tk.Tk()
    configure_app_styles()

    launch_login()

    root.mainloop()