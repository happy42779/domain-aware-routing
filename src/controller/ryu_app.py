import logging
import sys
import asyncio
import threading
import pathlib
# from concurrent.futures import ThreadPoolExecutor, thread

from typing import List

from ryu.app.wsgi import WSGIApplication
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    DEAD_DISPATCHER,
    set_ev_cls,
)
from ryu.ofproto import ofproto_v1_3

from ryu.lib.packet import ethernet, packet, ether_types

# local imports
from agent_controller import AsyncAgentController
from nb_controller import RestNBController

"""
This contoller consists of two components: unix socket server and ryu controller.
The unix socket server communicates with dns policy engine.

"""

REST_API_INSTANCE_NAME = "rest_api_app"
log_path = pathlib.Path(__file__).parent.parent.parent / "log"

log_file = log_path / "ryu_app.log"


AGENT_URL = "http://10.0.0.254:8080"


class AsyncController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(AsyncController, self).__init__(*args, **kwargs)

        # setup logger
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d: %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )

        for handler in self.logger.handlers:
            handler.setFormatter(formatter)
            # handler.setLevel(logging.DEBUG)

        # ryu related
        self.switches = {}
        self.flow_stats = {}
        self.mac_ports = {}
        self.lock = threading.Lock()
        # self.executor = ThreadPoolExecutor(max_workers=10)
        # cache for policy decisions
        self.policy_cache = {}

        # register rest api applicaiton
        wsgi = kwargs["wsgi"]
        wsgi.register(RestNBController, {REST_API_INSTANCE_NAME: self})

        # set defualt priority
        self.default_priority = 10
        self.idle_timeout = 30

        self.agent_controller = None
        self.agent_url = AGENT_URL

        try:
            # Initialize asyncio event loop for async operations
            self.loop = asyncio.new_event_loop()
            threading.Thread(target=self._run_async_loop, daemon=True).start()

            # initialize the sdn controller with in the event loop
            asyncio.run_coroutine_threadsafe(self._init_agent_controller(), self.loop)

        except Exception as e:
            self.logger.error(f"Failed to start Ryu controller: {str(e)}")
            # sys.exit(1)

        self.logger.info("Ryu controller started with REST Api")

    ######################### Internal API ############################
    def _run_async_loop(self):
        try:
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
        except Exception as e:
            self.logger.error(
                f"Failed to setup event loop for SDN agent communication daemon: {str(e)}"
            )

    async def _init_agent_controller(self):
        try:
            self.agent_controller = await AsyncAgentController(
                self.agent_url, self.logger
            ).__aenter__()
        except Exception as e:
            self.logger.debug(
                f"Error starting communication daemon to the SDN agent: {str(e)}"
            )

    # def _process_message(self, msg):
    #     """process incoming messsage from client"""
    #     if not isinstance(msg, dict) or "command" not in msg:
    #         raise ValueError("Invalid message format")
    #
    #     # received items from policy engine would look like:
    #     #
    #     # {'command': "block", 'ips': ['157.240.22.35']}
    #     # {'command': "route", "nexthop": "192.168.1.1", 'ips': ['157.240.22.35']}
    #
    #     cmd = msg["command"]
    #
    #     if cmd not in ["block", "route"]:
    #         raise ValueError(f"Unknown message type: {cmd}")
    #
    #     # add to agent, if it's route
    #     if cmd == "route":
    #         self._add_route_to_agent(msg["ips"], msg["nexthop"])
    #
    #     for dp in self.datapaths.values():
    #         for ip in msg["ips"]:
    #             actions = []
    #             idle_timeout = self.idle_timeout
    #             match = dp.ofproto_parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip)
    #             if cmd == "route":
    #                 actions = [dp.ofproto_parser.OFPActionOutput(port=1)]
    #             if cmd == "block":
    #                 idle_timeout = 0
    #
    #             self._add_flow_with_notification(
    #                 dp,
    #                 self.default_priority,
    #                 match,
    #                 actions,
    #                 idle_timeout=idle_timeout,
    #             )

    def _add_route_via_agent(self, ips: List[str], nexthop: str):
        if self.agent_controller is None:
            self.logger.debug("controller is None!")
            return {"error": "Interal Error!"}

        routes = [{"destination": i, "nexthop": nexthop} for i in ips]

        """
        ## what batch_add_routes expect:

        routes = [
            {"destination": "192.168.100.0/24", "nexthop": "198.19.249.192"},
            {"destination": "172.16.0.0/12", "nexthop": "198.19.249.192"},
        ]
        """

        # Run async function from sync context
        coro = self.agent_controller.batch_add_routes(routes)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        try:
            result = future.result(timeout=1)
            self.logger.debug(f"Route add result: {result}")
            return {"success": "Requested operation is done."}
        except asyncio.TimeoutError as e:
            self.logger.debug(f"Batch_add_routes timed out: {str(e)}")
            return {"error": "Operation timed out."}
        except Exception as e:
            self.logger.debug(f"Error adding route: {str(e)}")
            return {"error": "Adding route failed."}

    def _remove_route_via_agent(self, ips: List[str]):
        """
        To delete a route when openflow is removed (because of timeout)
        """

        if self.agent_controller is None:
            self.logger.debug("controller is None!")
            return {"error": "Interal Error!"}

        # run async in another thread that maintains the async loop
        coro = self.agent_controller.batch_delete_routes(ips)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        try:
            result = future.result(timeout=1)
            self.logger.debug(f"Route delete result: {result}")
            return {"success": "Requested operation is done."}
        except asyncio.TimeoutError as e:
            self.logger.debug(f"Batch_delete_routes timed out: {str(e)}")
            return {"error": "Operation timed out."}
        except Exception as e:
            self.logger.debug(f"Error deleting route: {str(e)}")
            return {"error": "Deleting route failed"}

    def _add_flow(
        self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0
    ):
        """
        Add flow to switch, could be dropping or routing
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        if buffer_id is not None:
            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=priority,
                buffer_id=buffer_id,
                match=match,
                instructions=inst,
                idle_timeout=idle_timeout,
            )
        else:
            mod = parser.OFPFlowMod(
                datapath=datapath, priority=priority, match=match, instructions=inst
            )
        datapath.send_msg(mod)

    def _add_flow_with_notification(
        self,
        datapath,
        priority,
        match,
        actions,
        buffer_id=None,
        idle_timeout=0,
        hard_timeout=0,
    ):
        """
        Only idle timeout will be used to have flow removed
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        # enable flow removal notifications
        flags = ofproto.OFPFF_SEND_FLOW_REM

        if buffer_id is not None:
            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=priority,
                buffer_id=buffer_id,
                match=match,
                instructions=inst,
                flags=flags,
                idle_timeout=idle_timeout,
                hard_timeout=hard_timeout,
            )
        else:
            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=priority,
                match=match,
                instructions=inst,
                flags=flags,
                idle_timeout=idle_timeout,
                hard_timeout=hard_timeout,
            )
        datapath.send_msg(mod)
        self.logger.debug(
            f"Flow added to switch {datapath.id} with removal nofification"
        )
        # self.logger.debug(f"Flow added to switch {datapath.id}")

    ######################## ryu event handlers #################################
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """handle switch features event"""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id

        # store switch
        self.switches[dpid] = {"datapath": datapath, "ports": {}}
        self.logger.info(f"Switch connected: {dpid}")

        # install talbe miss flow entry
        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)
        ]
        self._add_flow(datapath, 0, match, actions)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """handle packet in event"""
        """ 
        This method is not used at the moment.
        A default miss entry talbe is used, therefore, when there's 
        no specific dns rule is matched, it's sent out via the default port.

        """
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug(
                "packet truncated: only %s of %s bytes",
                ev.msg.msg_len,
                ev.msg.total_len,
            )

        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            # ignore lldp packet
            return

        dst = eth.dst
        src = eth.src

        dpid = format(datapath.id, "d").zfill(16)
        self.mac_ports.setdefault(dpid, {})

        self.logger.debug(f"packet in {dpid} {src} {dst} {in_port}")

        # learn a mac address to avoid FLOOD next time.
        self.mac_ports[dpid][src] = in_port

        if dst in self.mac_ports[dpid]:
            out_port = self.mac_ports[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in nex time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            # verify if we have a valid buffer_id, if yes avoid to send both
            # # flow_mod & packet_out
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self._add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self._add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        flows = []
        datapath = ev.msg.datapath
        dpid = datapath.id

        for stat in ev.msg.body:
            flows.append(
                {
                    "table_id": stat.table_id,
                    "duration_sec": stat.duration_sec,
                    "duration_nsec": stat.duration_nsec,
                    "priority": stat.priority,
                    "idle_timeout": stat.idle_timeout,
                    "hard_timeout": stat.hard_timeout,
                    "packet_count": stat.packet_count,
                    "byte_count": stat.byte_count,
                    "match": stat.match,
                    "actions": [action for action in stat.instructions],
                }
            )

        with self.lock:
            self.flow_stats[dpid] = flows

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        if msg.reason == ofproto.OFPRR_IDLE_TIMEOUT:
            reason = "IDLE_TIMEOUT"
        elif msg.reason == ofproto.OFPRR_HARD_TIMEOUT:
            reason = "HARD_TIMEOUT"
        elif msg.reason == ofproto.OFPRR_DELETE:
            reason = "DELETE"
        elif msg.reason == ofproto.OFPRR_GROUP_DELETE:
            reason = "GROUP_DELETE"
        else:
            reason = "UNKOWN"

        if reason in ["IDLE_TIMEOUT", "HARD_TIMEOUT"]:
            match = msg.match
            ipv4_dst = [match.get("ipv4_dst", None)]

            if ipv4_dst:
                # call the route deleting
                try:
                    self._remove_route_via_agent(ipv4_dst)
                except Exception as e:
                    self.logger.error(f"Error deleting routes via agent: {e}")

        self.logger.debug(
            "Flow removed: "
            "cookie=%d priority=%d reason=%s match=%s "
            "duration_sec=%d duration_nsec=%d "
            "idle_timeout=%d hard_timeout=%d "
            "packet_count=%d byte_count=%d",
            msg.cookie,
            msg.priority,
            reason,
            msg.match,
            msg.duration_sec,
            msg.duration_nsec,
            msg.idle_timeout,
            msg.hard_timeout,
            msg.packet_count,
            msg.byte_count,
        )

    @set_ev_cls(
        ofp_event.EventOFPErrorMsg,
        [ofproto_v1_3.OFP_VERSION, CONFIG_DISPATCHER, MAIN_DISPATCHER],
    )
    def error_msg_handler(self, ev):
        msg = ev.msg
        self.logger.error(
            "OFPErrorMsg received: type=0x%02x code=0x%02x message=%s",
            msg.type,
            msg.code,
            msg.data,
        )

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == DEAD_DISPATCHER:
            # switch disconnected
            self.logger.info(f"Switch {datapath.id} disconnected")
            # remove it from the switches
            self.switches.pop(datapath.id, None)

    ######################## REST API handlers #################################
    async def request_flow_stats_async(self, dpid):
        if dpid not in self.switches:
            return {"error": f"Switch {dpid} not found"}

        datapath = self.switches[dpid]["datapath"]
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.EventOFPFlowStatsReply(datapath)
        datapath.send_msg(req)

        # wait for the stats to be updated ( with timtouts)
        for _ in range(5):  # 5 retries
            await asyncio.sleep(0.5)
            with self.lock:
                if dpid in self.flow_stats:
                    return {"flows": self.flow_stats[dpid]}

        return {"error": "Timeout waiting for flow stats"}

    def add_flow_route(
        self, ips: List[str], nexthop: str, priority: int, add_route: bool = True
    ):
        """
        Actual function to be called by rest api handler to specify next top.

        Note: the validity of data shoudl be done by the handler

        """
        error = False
        # add route to via the agent
        if add_route:
            try:
                self._add_route_via_agent(ips=ips, nexthop=nexthop)
            except Exception as e:
                self.logger.error(f"Error adding routes via agent: {e}")
                error = True

        # prepare for adding the flow
        for dpid in self.switches.keys():
            dp = self.switches[dpid].get("datapath", None)
            if dp is None:
                error = True
                self.logger.error("Invalid dpid")

                continue

            for ip in ips:
                match = dp.ofproto_parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip)
                actions = [dp.ofproto_parser.OFPActionOutput(port=1)]
                self._add_flow_with_notification(
                    dp,
                    priority=priority,
                    match=match,
                    actions=actions,
                    idle_timeout=self.idle_timeout,
                )

        if error:
            return {"error": "Interal error"}
        else:
            return {"success": "flow route added"}

    def add_flow_block(self, ips: List[str], priority: int):
        """
        Actual function to be called by rest api handler to block a dest ip

        Flows to block a certain ip has a lower priority of 70
        """

        error = False
        # prepare for addding the flow
        for dpid in self.switches.keys():
            dp = self.switches[dpid].get("datapath", None)
            if dp is None:
                self.logger.error("Invalid dpid")
                error = True
                continue

            actions = []
            for ip in ips:
                match = dp.ofproto_parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip)
                self._add_flow_with_notification(
                    dp,
                    priority=priority,
                    match=match,
                    actions=actions,
                )

        if error:
            return {"error": "Interal error"}
        else:
            return {"success": "block flow added"}

    def remove_flow(self, ips: List[str]):
        """
        Actual function to be called by rest api handler to block a dest ip
        """
        error = False
        # prepare for removing a flow
        for dpid in self.switches.keys():
            dp = self.switches[dpid].get("datapath", None)
            if dp is None:
                self.logger.error("Invalid dpid")
                error = True
                continue

            self.logger.debug(f"gotten :{ips}")

            for ip in ips:
                match = dp.ofproto_parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip)
                mod = dp.ofproto_parser.OFPFlowMod(
                    datapath=dp,
                    command=dp.ofproto.OFPFC_DELETE,
                    out_port=dp.ofproto.OFPP_ANY,
                    out_group=dp.ofproto.OFPG_ANY,
                    match=match,
                )
                dp.send_msg(mod)

        if error:
            return {"error": "Internal error"}
        else:
            return {"success": "flow removed successfuly"}
