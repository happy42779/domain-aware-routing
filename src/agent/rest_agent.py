"""
SDN Agent that listens for http requests
to manage routes
"""

import json
import logging
import aiofiles
import asyncio
import ipaddress
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from aiohttp import web
from aiohttp.web import Request, Response, json_response
import signal
import sys
import pathlib

import time

TEST_DATA_FILE = pathlib.Path(__file__).parent.parent.parent / "result/agent.csv"
FILE_LOCK = asyncio.Lock()


try:
    from pyroute2 import AsyncIPRoute
    from pyroute2.netlink.exceptions import NetlinkError

    PYROUTE2_AVAILABLE = True
except ImportError:
    print("Warning: pyroute2 not available, install with: pip install pyroute2")
    PYROUTE2_AVAILABLE = False
    sys.exit(1)
log_path = pathlib.Path(__file__).parent.parent.parent / "log"

log_file = log_path / "agent.log"

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file)],
)
logger = logging.getLogger(__name__)


######################## Metric logging function
async def log_metric_async(line: str):
    # write metrics to file
    async with FILE_LOCK:
        async with aiofiles.open(TEST_DATA_FILE, mode="a") as f:
            await f.write(line)


@dataclass
class RouteEntry:
    """Represents a route entry"""

    destination: str  # CIDR notation (e.g., "192.168.1.0/24")
    nexthop: str  # Gateway IP
    interface: Optional[str] = None
    metric: Optional[int] = None
    table: int = 254  # Default table (main)
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class AsyncRouteManager:
    """Async wrapper for Linux routing table management using pyroute2"""

    def __init__(self, max_workers: int = 4):
        self.routes: Dict[str, RouteEntry] = {}  # destination -> RouteEntry

    async def add_route(
        self,
        destination: str,
        nexthop: str,
        interface: str = None,
        metric: int = None,
        table: int = 254,
        aipr: AsyncIPRoute = None,
    ) -> Tuple[bool, str]:
        """Add a route to the routing table"""
        try:
            # Validate destination network
            network = ipaddress.ip_network(destination, strict=False)
            nexthop_ip = ipaddress.ip_address(nexthop)

            # debug
            # print(self.routes)

            # Check if route already exists
            if destination in self.routes:
                existing = self.routes[destination]
                if existing.nexthop == nexthop:
                    return True, f"Route {destination} via {nexthop} already exists"
                else:
                    # Update existing route
                    return await self._update_route(
                        destination, nexthop, interface, metric, table
                    )

            # Prepare route parameters
            route_params = {
                "dst": str(network),
                "gateway": str(nexthop_ip),
                "table": table,
            }

            # Add interface if specified
            if interface:
                interface_index = await self._get_interface_index(interface)
                if interface_index is None:
                    return False, f"Interface {interface} not found"
                route_params["oif"] = interface_index

            # Add metric if specified
            if metric is not None:
                route_params["priority"] = metric

            # Add the route in thread pool
            if aipr is None:
                async with AsyncIPRoute() as aipr:
                    await aipr.route("add", **route_params)
            else:
                await aipr.route("add", **route_params)

            # Store route entry
            route_entry = RouteEntry(
                destination=destination,
                nexthop=nexthop,
                interface=interface,
                metric=metric,
                table=table,
            )
            self.routes[destination] = route_entry

            logger.info(f"Added route: {destination} via {nexthop}")
            return True, f"Successfully added route {destination} via {nexthop}"

        except NetlinkError as e:
            error_msg = f"Netlink error adding route {destination} via {nexthop}: {e}"
            logger.error(error_msg)
            return False, error_msg
        except ValueError as e:
            error_msg = f"Invalid IP address/network: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error adding route: {e}"
            logger.error(error_msg)
            return False, error_msg

    async def delete_route(
        self,
        destination: str,
        nexthop: str = None,
        table: int = 254,
        aipr: AsyncIPRoute = None,
    ) -> Tuple[bool, str]:
        """Delete a route from the routing table"""

        try:
            # Check if route exists in our tracking
            if destination not in self.routes:
                return False, f"Route {destination} not found in tracking"

            route_entry = self.routes[destination]

            # Use stored nexthop if not provided
            if nexthop is None:
                nexthop = route_entry.nexthop

            # Validate addresses
            network = ipaddress.ip_network(destination, strict=False)
            nexthop_ip = ipaddress.ip_address(nexthop)

            # Prepare route parameters
            route_params = {
                "dst": str(network),
                "gateway": str(nexthop_ip),
                "table": table,
            }

            if aipr is None:
                async with AsyncIPRoute() as aipr:
                    await aipr.route("del", **route_params)
            else:
                await aipr.route("del", **route_params)

            # Remove from tracking
            del self.routes[destination]

            logger.info(f"Deleted route: {destination} via {nexthop}")
            return True, f"Successfully deleted route {destination} via {nexthop}"

        except NetlinkError as e:
            error_msg = f"Netlink error deleting route {destination}: {e}"
            logger.error(error_msg)
            return False, error_msg
        except ValueError as e:
            error_msg = f"Invalid IP address/network: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error deleting route: {e}"
            logger.error(error_msg)
            return False, error_msg

    async def _update_route(
        self,
        destination: str,
        nexthop: str,
        interface: str = None,
        metric: int = None,
        table: int = 254,
    ) -> Tuple[bool, str]:
        """Update an existing route"""

        # Delete old route
        success, msg = await self.delete_route(destination, table=table)
        if not success:
            return False, f"Failed to delete old route: {msg}"

        # Add new route
        return await self.add_route(destination, nexthop, interface, metric, table)

    async def _get_interface_index(self, interface_name: str) -> Optional[int]:
        """Get interface index by name"""
        try:
            async with AsyncIPRoute() as aipr:
                links = await aipr.get_links()

            for link in links:
                for attr in link["attrs"]:
                    if attr[0] == "IFLA_IFNAME" and attr[1] == interface_name:
                        return link["index"]
            return None
        except Exception:
            return None

    async def batch_add_routes(self, routes: List[Dict]) -> List[Tuple[bool, str]]:
        """Add multiple routes concurrently"""
        tasks = []

        async with AsyncIPRoute() as aipr:
            for route_data in routes:
                task = self.add_route(
                    route_data["destination"],
                    route_data["nexthop"],
                    route_data.get("interface"),
                    route_data.get("metric", 77),
                    route_data.get("table", 254),
                    aipr=aipr,
                )
                tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error tuples
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append((False, str(result)))
            else:
                processed_results.append(result)

        return processed_results

    async def batch_delete_routes(
        self, destinations: List[str], table: int = 254
    ) -> List[Tuple[bool, str]]:
        """Delete multiple routes concurrently"""
        tasks = []

        async with AsyncIPRoute() as aipr:
            for destination in destinations:
                task = self.delete_route(destination, table=table, aipr=aipr)
                tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error tuples
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append((False, str(result)))
            else:
                processed_results.append(result)

        return processed_results

    async def cleanup_all_managed_routes(self):
        """Clean up all routes managed by this agent (for shutdown)"""
        logger.info("Cleaning up all managed routes...")

        routes_to_delete = list(self.routes.keys())

        await self.batch_delete_routes(routes_to_delete)

        # for destination in routes_to_delete:
        #     try:
        #         success, message = await self.delete_route(destination)
        #         if success:
        #             logger.info(f"Cleaned up route {destination}")
        #         else:
        #             logger.error(f"Failed to clean up route {destination}: {message}")
        #     except Exception as e:
        #         logger.error(f"Exception cleaning up route {destination}: {e}")


"""
AIO HTTP Server
"""


class AsyncSDNAgent:
    """Async SDN Agent with aiohttp web server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.route_manager = AsyncRouteManager()
        self.app = None
        self.runner = None
        self.site = None

        # Setup routes for api
        self._setup_routes()

    def _setup_routes(self):
        """Setup HTTP routes"""
        self.app = web.Application()

        # Add routes
        self.app.router.add_post("/routes", self.add_route)
        self.app.router.add_delete("/routes/{destination:.+}", self.delete_route)
        self.app.router.add_post("/routes/batch", self.batch_add_routes)
        self.app.router.add_delete("/routes/batch", self.batch_delete_routes)

        # Add CORS middleware
        self.app.middlewares.append(self._cors_middleware)

        # Add logging middleware
        self.app.middlewares.append(self._logging_middleware)

    @web.middleware
    async def _cors_middleware(self, request: Request, handler):
        """CORS middleware"""
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)

        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, DELETE, OPTIONS"
        )
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"

        return response

    @web.middleware
    async def _logging_middleware(self, request: Request, handler):
        """Logging middleware"""
        start_time = asyncio.get_event_loop().time()

        try:
            response = await handler(request)
            process_time = asyncio.get_event_loop().time() - start_time
            logger.info(
                f"{request.method} {request.path} - {response.status} - {process_time:.3f}s"
            )
            return response
        except Exception as e:
            process_time = asyncio.get_event_loop().time() - start_time
            logger.error(
                f"{request.method} {request.path} - ERROR: {e} - {process_time:.3f}s"
            )
            raise

    async def add_route(self, request: Request) -> Response:
        """Add route endpoint"""

        # Timeframe receiving the request
        T1 = time.perf_counter()

        try:
            data = await request.json()

            # Validate required fields
            required_fields = ["destination", "nexthop"]
            for field in required_fields:
                if field not in data:
                    return json_response(
                        {"success": False, "error": f"Missing required field: {field}"},
                        status=400,
                    )

            # Extract parameters
            destination = data["destination"]
            nexthop = data["nexthop"]
            interface = data.get("interface")
            metric = data.get("metric", 77)
            table = data.get("table", 254)

            # Timeframe before calling applying rules
            T1a = time.perf_counter()

            # Add route
            success, message = await self.route_manager.add_route(
                destination, nexthop, interface, metric, table
            )

            # Timeframe after applying rules
            T2 = time.perf_counter()

            # log time
            await log_metric_async(
                f"{destination}, {nexthop}, {T1a - T1:.6f}, {T2 - T1a:.6f}"
            )

            if success:
                response_data = {
                    "success": True,
                    "message": message,
                    "route": {
                        "destination": destination,
                        "nexthop": nexthop,
                        "interface": interface,
                        "metric": metric,
                        "table": table,
                    },
                    "timestamp": datetime.now().isoformat(),
                }
                return json_response(response_data, status=201)
            else:
                return json_response({"success": False, "error": message}, status=400)

        except json.JSONDecodeError:
            return json_response(
                {"success": False, "error": "Invalid JSON in request body"}, status=400
            )
        except Exception as e:
            logger.error(f"Error adding route: {e}")
            return json_response({"success": False, "error": str(e)}, status=500)

    async def delete_route(self, request: Request) -> Response:
        """Delete route endpoint"""
        try:
            # raw_destination = request.match_info["destination"]
            # destination = urllib.parse.unquote(raw_destination)
            destination = request.match_info["destination"]

            # Parse JSON body for additional parameters
            try:
                data = await request.json()
            except:
                data = {}

            nexthop = data.get("nexthop")
            table = data.get("table", 254)

            # Delete route
            success, message = await self.route_manager.delete_route(
                destination, nexthop, table
            )

            if success:
                response_data = {
                    "success": True,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                }
                return json_response(response_data)
            else:
                return json_response({"success": False, "error": message}, status=400)

        except Exception as e:
            logger.error(f"Error deleting route: {e}")
            return json_response({"success": False, "error": str(e)}, status=500)

    async def batch_add_routes(self, request: Request) -> Response:
        """Batch add routes endpoint"""
        try:
            data = await request.json()

            if not isinstance(data.get("routes"), list):
                return json_response(
                    {
                        "success": False,
                        "error": 'Expected "routes" array in request body',
                    },
                    status=400,
                )

            routes_data = data["routes"]

            # Validate each route
            for i, route_data in enumerate(routes_data):
                required_fields = ["destination", "nexthop"]
                for field in required_fields:
                    if field not in route_data:
                        return json_response(
                            {
                                "success": False,
                                "error": f"Route {i}: Missing required field: {field}",
                            },
                            status=400,
                        )

            # Add routes concurrently
            results = await self.route_manager.batch_add_routes(routes_data)

            # Prepare response
            response_routes = []
            for i, (success, message) in enumerate(results):
                response_routes.append(
                    {
                        "index": i,
                        "route": routes_data[i],
                        "success": success,
                        "message": message,
                    }
                )

            overall_success = all(result[0] for result in results)

            response_data = {
                "success": overall_success,
                "results": response_routes,
                "total": len(routes_data),
                "successful": sum(1 for result in results if result[0]),
                "failed": sum(1 for result in results if not result[0]),
                "timestamp": datetime.now().isoformat(),
            }

            status_code = 201 if overall_success else 207  # 207 Multi-Status
            return json_response(response_data, status=status_code)

        except json.JSONDecodeError:
            return json_response(
                {"success": False, "error": "Invalid JSON in request body"}, status=400
            )
        except Exception as e:
            logger.error(f"Error in batch add routes: {e}")
            return json_response({"success": False, "error": str(e)}, status=500)

    async def batch_delete_routes(self, request: Request) -> Response:
        """Batch delete routes endpoint"""
        try:
            data = await request.json()

            if not isinstance(data.get("destinations"), list):
                return json_response(
                    {
                        "success": False,
                        "error": 'Expected "destinations" array in request body',
                    },
                    status=400,
                )

            destinations = data["destinations"]
            table = data.get("table", 254)

            # Delete routes concurrently
            results = await self.route_manager.batch_delete_routes(destinations, table)

            # Prepare response
            response_routes = []
            for i, (success, message) in enumerate(results):
                response_routes.append(
                    {
                        "index": i,
                        "destination": destinations[i],
                        "success": success,
                        "message": message,
                    }
                )

            overall_success = all(result[0] for result in results)

            response_data = {
                "success": overall_success,
                "results": response_routes,
                "total": len(destinations),
                "successful": sum(1 for result in results if result[0]),
                "failed": sum(1 for result in results if not result[0]),
                "timestamp": datetime.now().isoformat(),
            }

            return json_response(response_data)

        except json.JSONDecodeError:
            return json_response(
                {"success": False, "error": "Invalid JSON in request body"}, status=400
            )
        except Exception as e:
            logger.error(f"Error in batch delete routes: {e}")
            return json_response({"success": False, "error": str(e)}, status=500)

    async def start(self):
        """Start the async SDN agent"""
        logger.info(f"Starting Async SDN Agent on {self.host}:{self.port}")

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        logger.info(f"Async SDN Agent listening on http://{self.host}:{self.port}")
        logger.info("API endpoints:")
        logger.info("  POST   /routes              - Add route")
        logger.info("  DELETE /routes/{destination} - Delete route")
        logger.info("  POST   /routes/batch         - Batch add routes")
        logger.info("  DELETE /routes/batch          - Batch delete route")

    async def stop(self):
        """Stop the async SDN agent"""
        logger.info("Stopping Async SDN Agent...")

        if self.site:
            await self.site.stop()

        # cleanup managed routes
        await self.route_manager.cleanup_all_managed_routes()

        if self.runner:
            await self.runner.cleanup()

        logger.info("Async SDN Agent stopped")


async def main():
    """Main async function"""
    import argparse

    parser = argparse.ArgumentParser(description="Async SDN Agent for Linux Router")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )

    args = parser.parse_args()

    # Set log level
    logger.setLevel(getattr(logging, args.log_level))

    # Create SDN agent
    agent = AsyncSDNAgent(host=args.host, port=args.port)

    # Setup signal handlers
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Received shutdown signal")
        shutdown_event.set()

    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, signal_handler)

    try:
        # Start the agent
        await agent.start()

        # Keep running until signal
        await shutdown_event.wait()

    except Exception as e:
        logger.error(f"Failed to start async SDN agent: {e}")
        await agent.stop()
        raise
    finally:
        await agent.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, exiting...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
