"""Data models."""

from pydantic import BaseModel, Field


class Item(BaseModel):
    """Example item model."""

    id: str = Field(..., description="Unique item identifier")
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    price: float = Field(..., gt=0)
    quantity: int = Field(default=0, ge=0)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "item-001",
                    "name": "Example Item",
                    "description": "An example item",
                    "price": 9.99,
                    "quantity": 10,
                }
            ]
        }
    }
