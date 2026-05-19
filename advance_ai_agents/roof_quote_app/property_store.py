import sqlite3
import json
import base64
import os
from typing import Optional
from models import Property, RoofMeasurement

DB_PATH = os.getenv("PROPERTY_DB_PATH", "roof_crm.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                property_id TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                data        TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS property_images (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id TEXT NOT NULL,
                label       TEXT,
                image_b64   TEXT NOT NULL,
                FOREIGN KEY (property_id) REFERENCES properties(property_id)
            )
        """)
        conn.commit()


def save_property(prop: Property) -> str:
    data = prop.model_dump_json()
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO properties (property_id, created_at, updated_at, data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(property_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                data       = excluded.data
        """, (prop.property_id, prop.created_at, prop.updated_at, data))
        conn.commit()
    return prop.property_id


def get_property(property_id: str) -> Optional[Property]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM properties WHERE property_id = ?", (property_id,)
        ).fetchone()
    if row:
        return Property.model_validate_json(row["data"])
    return None


def list_properties() -> list[Property]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT data FROM properties ORDER BY created_at DESC"
        ).fetchall()
    return [Property.model_validate_json(r["data"]) for r in rows]


def delete_property(property_id: str):
    with _get_conn() as conn:
        conn.execute("DELETE FROM property_images WHERE property_id = ?", (property_id,))
        conn.execute("DELETE FROM properties WHERE property_id = ?", (property_id,))
        conn.commit()


def search_properties(query: str) -> list[Property]:
    q = f"%{query.lower()}%"
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT data FROM properties WHERE LOWER(data) LIKE ? ORDER BY created_at DESC", (q,)
        ).fetchall()
    return [Property.model_validate_json(r["data"]) for r in rows]


# ------------------------------------------------------------------
# Image storage
# ------------------------------------------------------------------

def save_images(property_id: str, images: list[tuple[str, bytes]]):
    """Save list of (label, raw_bytes) pairs for a property."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM property_images WHERE property_id = ?", (property_id,))
        for label, raw in images:
            b64 = base64.b64encode(raw).decode()
            conn.execute(
                "INSERT INTO property_images (property_id, label, image_b64) VALUES (?, ?, ?)",
                (property_id, label, b64)
            )
        conn.commit()


def get_images(property_id: str) -> list[tuple[str, bytes]]:
    """Return list of (label, raw_bytes) for a property."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT label, image_b64 FROM property_images WHERE property_id = ?",
            (property_id,)
        ).fetchall()
    return [(r["label"], base64.b64decode(r["image_b64"])) for r in rows]


def add_image(property_id: str, label: str, raw_bytes: bytes):
    b64 = base64.b64encode(raw_bytes).decode()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO property_images (property_id, label, image_b64) VALUES (?, ?, ?)",
            (property_id, label, b64)
        )
        conn.commit()


def delete_image(property_id: str, label: str):
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM property_images WHERE property_id = ? AND label = ?",
            (property_id, label)
        )
        conn.commit()


def image_count(property_id: str) -> int:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM property_images WHERE property_id = ?",
            (property_id,)
        ).fetchone()
    return row["cnt"] if row else 0
