"""
Utility functions.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

def format_greeting(name: str, greeting: str = "Hello") -> str:
    """Format a greeting with the given name."""
    return f"{greeting}, {name}!"

def safe_get(dictionary: Dict[str, Any], key: str, default: Optional[Any] = None) -> Any:
    """Safely get a value from a dictionary, logging if key missing."""
    if key in dictionary:
        return dictionary[key]
    logger.warning("Key '%s' not found in dictionary", key)
    return default