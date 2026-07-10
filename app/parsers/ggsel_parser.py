from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.core.http_client import HttpClient
from app.parsers.base import BaseParser
from app.parsers.models import ParsedOffer


class GGSelParser(BaseParser[ParsedOffer]):
    BASE_URL = "https://ggsel.net"
    CATALOG_URL = f"{BASE_URL}/catalog"
    API_URL = f"{BASE_URL}/api"

    def __init__(self, http_client: HttpClient) -> None:
        self._http_client = http_client

    async def fetch(self) -> str:
        try:
            response = await self._http_client.get(self.CATALOG_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            msg = "Failed to fetch GGSEL source response"
            raise RuntimeError(msg) from exc

        return response.text

    async def parse(self, raw_response: str) -> list[ParsedOffer]:
        if not raw_response.strip():
            return []

        # TODO: GGSEL catalog currently exposes data through the rendered HTML
        # page and hydrated frontend state. Do not add HTML parsing here until
        # the source contract is documented. If a stable public JSON endpoint is
        # confirmed later, only this extraction step should convert raw source
        # data into ParsedOffer objects.
        return []

    async def run(self) -> Sequence[ParsedOffer]:
        payload = await self.fetch()
        return await self.parse(payload)
