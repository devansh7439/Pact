"""Kettle & Crumb's catalog. The merchant's prices are authoritative: an agent
checkout whose amount disagrees with price × quantity is refused."""

from __future__ import annotations

CATALOG: dict[str, dict] = {
    "beans-ethiopia-1kg": {"name": "Ethiopia Yirgacheffe beans, 1 kg", "category": "coffee",
                           "price_minor": 3200},
    "beans-colombia-1kg": {"name": "Colombia Huila beans, 1 kg", "category": "coffee",
                           "price_minor": 2800},
    "beans-house-500g": {"name": "House blend, 500 g", "category": "coffee", "price_minor": 1600},
    "tea-sencha-200g": {"name": "Sencha green tea, 200 g", "category": "tea", "price_minor": 1400},
    "filters-v60-100": {"name": "V60 paper filters, 100", "category": "brewing-supplies",
                        "price_minor": 400},
    "kettle-gooseneck": {"name": "Gooseneck kettle", "category": "brewing-supplies",
                         "price_minor": 12000},
    "grinder-burr": {"name": "Burr grinder", "category": "brewing-supplies", "price_minor": 30000},
    "reorder-fortnightly": {"name": "Fortnightly beans reorder", "category": "coffee",
                            "price_minor": 4800},
}


def price(sku: str, quantity: int) -> int | None:
    item = CATALOG.get(sku)
    return item["price_minor"] * quantity if item and quantity >= 1 else None
