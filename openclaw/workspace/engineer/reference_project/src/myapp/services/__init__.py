"""Business logic services."""

from typing import Protocol


class Database(Protocol):
    """Database protocol."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def query(self, sql: str) -> list[dict]: ...


class ItemService:
    """Service for managing items."""

    def __init__(self, db: Database) -> None:
        """Initialize the service."""
        self._db = db

    async def get_item(self, item_id: str) -> dict | None:
        """Get an item by ID."""
        results = await self._db.query(f"SELECT * FROM items WHERE id = '{item_id}'")
        return results[0] if results else None

    async def list_items(self, limit: int = 100) -> list[dict]:
        """List all items."""
        return await self._db.query(f"SELECT * FROM items LIMIT {limit}")
