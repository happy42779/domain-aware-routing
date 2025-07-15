import asyncio
import json
import logging
import traceback

from ryu.app.wsgi import ControllerBase, route
from webob import Response

"""
Rest apis exposed for SDN applications
"""

REST_API_INSTANCE_NAME = "rest_api_app"

PRIORITY = 77


class RestNBController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(RestNBController, self).__init__(req, link, data, **config)
        self.app = data[REST_API_INSTANCE_NAME]
        self.logger = logging.getLogger(__name__)

    @route("switches", "/api/switches", methods=["GET"])
    def get_switches(self, req, **kwargs):
        switches_list = list(self.app.switches.keys())
        body = json.dumps({"swithces": switches_list}).encode()
        return Response(content_type="application/json", body=body)

    @route("flows", "/api/flows/{dpid}", methods=["GET"])
    def get_flows(self, req, **kwargs):
        dpid = int(kwargs["dpid"])

        future = asyncio.run_coroutine_threadsafe(
            self.app.request_flow_stats_async(dpid), self.app.loop
        )

        try:
            result = future.result(timeout=2)
            body = json.dumps(result).encode()
            return Response(content_type="application/json", body=body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            return Response(content_type="application/json", body=body, status=500)

    @route("block", "/api/block", methods=["POST"])
    def add_flow_block(self, req, **kwargs):
        try:
            data = json.loads(req.body)
            ips = data.get("ips")
            priority = data.get("priority", PRIORITY)

            if ips is None:
                body = json.dumps(
                    {"error": "Missing required parameters: ips"}
                ).encode()
                return Response(content_type="application/json", body=body, status=400)
            result = self.app.add_flow_block(ips, priority)
            body = json.dumps(result).encode()

            if "error" in result:
                return Response(content_type="application/json", body=body, status=404)
            else:
                return Response(content_type="application/json", body=body)

        except json.JSONDecodeError:
            body = json.dumps({"error": "Invalid JSON in request body"}).encode()
            return Response(content_type="application/json", body=body, status=400)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            return Response(content_type="application/json", body=body, status=500)

    @route("route", "/api/route", methods=["POST"])
    def add_flow_route(self, req, **kwargs):
        try:
            data = json.loads(req.body)
            ips = data.get("ips")
            nexthop = data.get("nexthop")
            priority = data.get("priority", PRIORITY)

            if ips is None or nexthop is None:
                body = json.dumps(
                    {"error": "Missing required parameters: ips, nexthop"}
                ).encode()
                return Response(content_type="application/json", body=body, status=400)
            result = self.app.add_flow_route(ips, nexthop, priority)
            body = json.dumps(result).encode()

            if "error" in result:
                return Response(content_type="application/json", body=body, status=404)
            else:
                return Response(content_type="application/json", body=body)

        except json.JSONDecodeError:
            body = json.dumps({"error": "Invalid JSON in request body"}).encode()
            return Response(content_type="application/json", body=body, status=400)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            return Response(content_type="application/json", body=body, status=500)

    @route("remove", "/api/remove/flow", methods=["DELETE"])
    def remove_flow(self, req, **kwargs):
        self.logger.debug("correctly getting /remove/flow requests")
        try:
            data = json.loads(req.body)
            ips = data.get("ips")

            if ips is None:
                body = json.dumps(
                    {"error": "Missing required parameters: ips"}
                ).encode()
                return Response(content_type="application/json", body=body, status=400)
            result = self.app.remove_flow(ips)
            body = json.dumps(result).encode()

            if "error" in result:
                return Response(content_type="application/json", body=body, status=404)
            else:
                return Response(content_type="application/json", body=body)

        except json.JSONDecodeError:
            body = json.dumps({"error": "Invalid JSON in request body"}).encode()
            return Response(content_type="application/json", body=body, status=400)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            traceback.print_exc()
            return Response(content_type="application/json", body=body, status=500)

    @route("remove", "/api/remove/route", methods=["DELETE"])
    def remove_route(self, req, **kwargs):
        try:
            data = json.loads(req.body)
            ips = data.get("ips")

            if ips is None:
                body = json.dumps(
                    {"error": "Missing required parameters: ips"}
                ).encode()
                return Response(content_type="application/json", body=body, status=400)
            result = self.app._remove_route_via_agent(ips)
            body = json.dumps(result).encode()

            if "error" in result:
                return Response(content_type="application/json", body=body, status=404)
            else:
                return Response(content_type="application/json", body=body)

        except json.JSONDecodeError:
            body = json.dumps({"error": "Invalid JSON in request body"}).encode()
            return Response(content_type="application/json", body=body, status=400)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            return Response(content_type="application/json", body=body, status=500)

    @route("batch", "/api/batch", methods=["POST"])
    def batch_flow_route(self, req, **kwargs):
        try:
            data = json.loads(req.body)
            commands = data.get("commands")
            results = {}
            for cmd in commands:
                if "route" == cmd["type"] and "remove" == cmd["action"]:
                    result = self.app._remove_route_via_agent(cmd["ips"])
                elif "flow" == cmd["type"] and "block" == cmd["action"]:
                    result = self.app.add_flow_block(cmd["ips"], PRIORITY)
                else:
                    continue

                if "error" in result:
                    results["error"] = []
                    results["error"].append(result)
                else:
                    results["resp"] = []
                    results["resp"].append(result)

            body = json.dumps(results).encode()

            # checking error
            if "error" in results:
                return Response(content_type="application/json", body=body, status=404)
            else:
                return Response(content_type="application/json", body=body)

        except json.JSONDecodeError:
            body = json.dumps({"error": "Invalid JSON in request body"}).encode()
            return Response(content_type="application/json", body=body, status=400)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            traceback.print_exc()
            return Response(content_type="application/json", body=body, status=500)
