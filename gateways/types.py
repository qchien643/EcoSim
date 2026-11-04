"""Transport result shared by providers and simulation decisions."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GatewayResponse:
    output: dict[str, Any]
    provider: str
    model: str
    request: dict[str, Any]
