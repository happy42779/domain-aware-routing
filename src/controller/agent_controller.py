import aiohttp
import logging
import asyncio

from typing import List, Dict, Optional


class AsyncAgentController:
    def __init__(self, agent_url: str, logger: logging.Logger) -> None:
        if not agent_url or not logger:
            raise ValueError("agent_url or logger is None")

        self.agent_url = agent_url
        self.session = None
        self.logger = logger

    async def __aenter__(self):
        try:
            self.session = aiohttp.ClientSession()
        except Exception as e:
            self.logger.error(f"Failed to create aiohttp session: {e}")
            raise

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tab):
        if self.session:
            await self.session.close()

    async def add_route(self, destination: str, nexthop: str, interface=None):
        url = f"{self.agent_url}/routes"
        data = {"destination": destination, "nexthop": nexthop}

        if not self.session:
            self.logger.error("session not connected")
            return

        if interface:
            data["interface"] = interface

        try:
            async with self.session.post(url, json=data) as response:
                return await response.json()
        except asyncio.TimeoutError:
            self.logger.error("Request timed out in add_route")
            raise
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP error in add_route: {e}")
            raise

    async def delete_route(self, destination: str):
        # encoded_destination = urllib.parse.quote(destination, safe="")
        # url = f"{self.agent_url}/routes/{encoded_destination}"
        if not self.session:
            self.logger.error("session not connected")
            return
        url = f"{self.agent_url}/routes/{destination}"

        try:
            async with self.session.delete(url) as response:
                return await response.json()
        except asyncio.TimeoutError:
            self.logger.error("Request timed out in delete_route")
            raise
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP error in delete_route: {e}")
            raise

    async def batch_add_routes(self, routes: List[Dict]):
        if not self.session:
            self.logger.error("session not connected")
            return

        url = f"{self.agent_url}/routes/batch"
        data = {"routes": routes}

        try:
            async with self.session.post(url, json=data) as response:
                return await response.json()
        except asyncio.TimeoutError:
            self.logger.error("Request timed out in batch_add_routes")
            raise
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP error in batch_add_routes: {e}")
            raise

    async def batch_delete_routes(self, destinations: List[str]):
        if not self.session:
            self.logger.error("session not connected")
            return

        url = f"{self.agent_url}/routes/batch"
        data = {"destinations": destinations}

        try:
            async with self.session.delete(url, json=data) as response:
                return await response.json()
        except asyncio.TimeoutError:
            self.logger.error("Request timed out in batch_delete_routes")
            raise
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP error in batch_delete_routes: {e}")
            raise
