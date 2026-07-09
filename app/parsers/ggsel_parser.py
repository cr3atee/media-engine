from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core.http_client import HttpClient
from app.parsers.base import BaseParser, RawItem


class GGSelParser(BaseParser):
    BASE_URL = "https://ggsel.net"
    CATALOG_URL = f"{BASE_URL}/catalog"
    API_URL = f"{BASE_URL}/api"

    def __init__(self, http_client: HttpClient) -> None:
        self._http_client = http_client

    async def fetch(self) -> str:
        return ""

    async def parse(self, raw_html: str) -> list[RawItem]:
        return []

    async def run(self) -> Sequence[RawItem]:
        payload = await self.fetch()
        return await self.parse(payload)
