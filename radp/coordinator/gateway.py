"""User-facing request handling (plan.md §2.1 RequestGateway, §2.2 normal flow).

The gateway:
  1. Accepts a Generate request (prompt, max_tokens) from a client.
  2. Drives the pipeline: stage 1 -> stage 2 -> ... -> stage N.
  3. Mirrors each stage's input activation into ActivationCache.
  4. Streams tokens back to the client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from radp.common.types import Placement
from radp.coordinator.activation_cache import ActivationCache


class RequestGateway:
    def __init__(
        self,
        placement: Placement,
        activation_cache: ActivationCache,
    ) -> None:
        self.placement = placement
        self.activation_cache = activation_cache

    async def generate(self, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        """Run the pipeline and yield decoded tokens as they arrive."""
        if False:
            yield ""  # mark as async generator for the type checker
        raise NotImplementedError
