import aiohttp
import logging

from typing import Dict, List


class AsyncNBApiClient:
    def __init__(self, controller_url: str) -> None:
        if not controller_url:
            raise Exception("controller_url or logger is None")

        self.controller_url = controller_url
        self.session = None
        self.logger = logging.getLogger(__name__)

    async def __aenter__(self):
        try:
            self.session = aiohttp.ClientSession()
        except Exception:
            raise

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tab):
        if self.session:
            await self.session.close()

    async def route(self, nexthop: str, ips: List[str]):
        if not self.session:
            raise Exception("NB Api Client session is None")

        url = f"{self.controller_url}/api/route"
        data = {"nexthop": nexthop, "ips": ips}

        async with self.session.post(url, json=data) as response:
            return await response.json()

    async def block(self, ips: List[str]):
        if not self.session:
            raise Exception("NB Api Client session is None")

        url = f"{self.controller_url}/api/block"
        data = {"ips": ips}

        async with self.session.post(url, json=data) as response:
            return await response.json()

    async def remove_flow(self, ips: List[str]):
        if not self.session:
            raise Exception("NB Api Client session is None")

        self.logger.debug("Gotten request /api/remove/flow ")

        url = f"{self.controller_url}/api/remove/flow"
        data = {"ips": ips}

        async with self.session.delete(url, json=data) as response:
            return await response.json()

    async def remove_route(self, ips: List[str]):
        if not self.session:
            raise Exception("NB Api Client session is None")

        url = f"{self.controller_url}/api/remove/route"
        data = {"ips": ips}

        async with self.session.delete(url, json=data) as response:
            return await response.json()

    async def batch(self, commands: List[Dict[str, str]]):
        """
        batch the operation to save some io time.
        """
        if not self.session:
            raise Exception("NB Api Client session is None")

        url = f"{self.controller_url}/api/batch"
        data = {"commands": commands}

        async with self.session.post(url, json=data) as response:
            return await response.json()
