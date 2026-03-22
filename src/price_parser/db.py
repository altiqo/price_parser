from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from .models import Marketplace, PriceSnapshot, TrackTarget


def _utcnow() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


class Database:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS track_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    marketplaces_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_notified_price REAL,
                    is_active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    price REAL NOT NULL,
                    currency TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    seller TEXT,
                    captured_at TEXT NOT NULL,
                    FOREIGN KEY(target_id) REFERENCES track_targets(id)
                );

                CREATE INDEX IF NOT EXISTS idx_track_targets_chat_id
                    ON track_targets(chat_id);
                CREATE INDEX IF NOT EXISTS idx_price_snapshots_target_id_captured_at
                    ON price_snapshots(target_id, captured_at);
                """
            )
            await db.commit()

    async def add_target(
        self,
        chat_id: int,
        query: str,
        marketplaces: list[Marketplace],
    ) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO track_targets(chat_id, query, marketplaces_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, query, json.dumps([item.value for item in marketplaces]), _utcnow()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def list_targets(self, chat_id: int) -> list[TrackTarget]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, chat_id, query, marketplaces_json, created_at, last_notified_price, is_active
                FROM track_targets
                WHERE chat_id = ?
                ORDER BY created_at DESC
                """,
                (chat_id,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_target(row) for row in rows]

    async def get_target(self, target_id: int, chat_id: int | None = None) -> TrackTarget | None:
        query = (
            """
            SELECT id, chat_id, query, marketplaces_json, created_at, last_notified_price, is_active
            FROM track_targets
            WHERE id = ? AND chat_id = ?
            """
            if chat_id is not None
            else """
            SELECT id, chat_id, query, marketplaces_json, created_at, last_notified_price, is_active
            FROM track_targets
            WHERE id = ?
            """
        )
        params = (target_id, chat_id) if chat_id is not None else (target_id,)
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
        return self._row_to_target(row) if row else None

    async def delete_target(self, target_id: int, chat_id: int) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM track_targets WHERE id = ? AND chat_id = ?",
                (target_id, chat_id),
            )
            await db.execute("DELETE FROM price_snapshots WHERE target_id = ?", (target_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def clear_targets(self, chat_id: int) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM track_targets WHERE chat_id = ?",
                (chat_id,),
            )
            ids = [row[0] for row in await cursor.fetchall()]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            await db.execute(
                f"DELETE FROM price_snapshots WHERE target_id IN ({placeholders})",
                ids,
            )
            await db.execute(
                "DELETE FROM track_targets WHERE chat_id = ?",
                (chat_id,),
            )
            await db.commit()
            return len(ids)

    async def save_snapshot(
        self,
        target_id: int,
        price: float,
        currency: str,
        title: str,
        url: str,
        marketplace: Marketplace,
        seller: str | None,
    ) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO price_snapshots(
                    target_id, price, currency, title, url, marketplace, seller, captured_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    price,
                    currency,
                    title,
                    url,
                    marketplace.value,
                    seller,
                    _utcnow(),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def update_last_notified_price(self, target_id: int, price: float) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE track_targets SET last_notified_price = ? WHERE id = ?",
                (price, target_id),
            )
            await db.commit()

    async def list_snapshots(self, target_id: int, limit: int = 100) -> list[PriceSnapshot]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, target_id, price, currency, title, url, marketplace, seller, captured_at
                FROM price_snapshots
                WHERE target_id = ?
                ORDER BY captured_at ASC
                LIMIT ?
                """,
                (target_id, limit),
            )
            rows = await cursor.fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    async def list_active_targets(self) -> list[TrackTarget]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, chat_id, query, marketplaces_json, created_at, last_notified_price, is_active
                FROM track_targets
                WHERE is_active = 1
                ORDER BY id ASC
                """
            )
            rows = await cursor.fetchall()
        return [self._row_to_target(row) for row in rows]

    @staticmethod
    def _row_to_target(row: tuple) -> TrackTarget:
        marketplaces = [Marketplace(item) for item in json.loads(row[3])]
        return TrackTarget(
            id=row[0],
            chat_id=row[1],
            query=row[2],
            marketplaces=marketplaces,
            created_at=datetime.fromisoformat(row[4]),
            last_notified_price=row[5],
            is_active=bool(row[6]),
        )

    @staticmethod
    def _row_to_snapshot(row: tuple) -> PriceSnapshot:
        return PriceSnapshot(
            id=row[0],
            target_id=row[1],
            price=row[2],
            currency=row[3],
            title=row[4],
            url=row[5],
            marketplace=Marketplace(row[6]),
            seller=row[7],
            captured_at=datetime.fromisoformat(row[8]),
        )
