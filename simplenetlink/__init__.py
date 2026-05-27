from pyroute2 import IPRoute, netns, NetNS, netlink
import socket
import logging
import subprocess
import time


class SimpleNetlink(object):
    def __init__(self, namespace=None):
        self.ipr = IPRoute()
        self._log = logging.getLogger("SimpleNetlink")
        self._current_namespace = namespace
        self._previous_namespace_instance = None
        self._previous_namespace = None
        self._log.level = logging.DEBUG
        self._supported_virtual_interface_types = ["ipvlan", "macvlan", "tagged", "tun"]
        self._dhcp_interfaces = set()   # set of (interface_name, namespace) tuples

    def reset(self):
        self._current_namespace = None
        self._previous_namespace_instance = None
        self._previous_namespace = None
        if self.ipr:
            self.ipr.close()
        self.ipr = IPRoute()

    def get_interface_index(self, ifname):
        res = self.ipr.link_lookup(ifname=ifname)
        if len(res) == 1:
            return res[0]
        else:
            if len(res) == 0:
                raise ValueError(
                    f"no result found for {ifname} in namespace {self.get_current_namespace_name()}"
                )
            else:
                self._log.error(
                    f"multiple results found for {ifname}: {res} -> returning first"
                )
                return res[0]

    def create_namespace(self, namespace):
        if namespace not in self.get_namespaces():
            netns.create(namespace)

        self.set_current_namespace(namespace)
        idx = self.get_interface_index("lo")
        self.ipr.link("set", index=idx, state="up")

        self.restore_previous_namespace()

    def set_current_namespace(self, namespace):
        if not namespace:
            if self._current_namespace:
                self._log.info(f"close {self._current_namespace}")
                self.ipr.close()
            self._previous_namespace = self._current_namespace
            self.ipr = IPRoute()
            self._current_namespace = namespace
        elif namespace not in self.get_namespaces():
            self._log.debug(
                f"{namespace} does not exist, implicitly creating namespace {namespace}"
            )
            self.create_namespace(namespace)
        if namespace:
            self._previous_namespace = self._current_namespace
            if self.ipr:
                self.ipr.close()
            self.ipr = NetNS(namespace)
            self._current_namespace = namespace
        self._log.debug(
            f"switched namespace from {self._previous_namespace} to {self._current_namespace}"
        )
        return True

    def restore_previous_namespace(self):
        tmp_i = self.ipr
        tmp = self._current_namespace
        self.ipr = self._previous_namespace_instance
        self._current_namespace = self._previous_namespace
        self._previous_namespace_instance = tmp_i
        self._previous_namespace = tmp
        self._log.debug(f"restored previous namespace {self._current_namespace}")
        return True

    def delete_namespace(self, namespace):
        if namespace in self.get_namespaces():
            self.set_current_namespace(namespace)
            for interface_name, interface_cfg in self.get_network_interfaces_info().items():
                if interface_name == "lo":
                    continue
                for ipv4 in interface_cfg.get("ipv4", []):
                    self.interface_delete_ipv4(interface_name, ipv4["prefix"])
                for ipv6 in interface_cfg.get("ipv6", []):
                    self.interface_delete_ipv6(interface_name, ipv6["prefix"])
                iface_type = interface_cfg.get("type")
                if iface_type in ("tagged", "ipvlan", "tun", "tap"):
                    try:
                        idx = self.get_interface_index(interface_name)
                        self.ipr.link("del", index=idx)
                        self._log.debug(f"deleted {iface_type} interface {interface_name} from {namespace}")
                    except Exception as e:
                        self._log.debug(f"could not delete interface {interface_name}: {e}")
            self.ipr.close()
            self.ipr.remove()
            self.restore_previous_namespace()

            # ns = NetNS(namespace)

            # ns.close()
            # ns.remove()

            self._log.debug(f"removed namespace {namespace}")
            if namespace == self._current_namespace:
                self.set_current_namespace(None)
            time.sleep(
                0.1
            )  # give kernel some time, this workarounds various 'already existing' problams
        else:
            self._log.debug(
                f"cannot remove non existing namespace {namespace} -> ignoring request"
            )

    def get_current_namespace_name(self):
        return self._current_namespace

    def get_namespaces(self):
        return list(netns.listnetns())

    def find_interface_in_all_namespaces(self, interface_name):
        # Use independent IPRoute/NetNS instances so the search never corrupts self.ipr state.
        # Callers always call set_current_namespace(namespace) on the returned value before use.
        with IPRoute() as root:
            res = root.link_lookup(ifname=interface_name)
            if res:
                self._log.debug(
                    f"found interface {interface_name} in namespace None with index {res[0]}"
                )
                return (None, res[0])

        for ns in self.get_namespaces():
            self._log.debug(f"switching namespace to {ns}")
            try:
                with NetNS(ns) as ns_ipr:
                    res = ns_ipr.link_lookup(ifname=interface_name)
                    if res:
                        self._log.debug(
                            f"found interface {interface_name} in namespace {ns} with index {res[0]}"
                        )
                        return (ns, res[0])
            except Exception:
                pass

        self._log.debug(f"cannot find interface {interface_name} in any namespace")
        return (self.get_current_namespace_name(), None)

    def __create_tagged(self, interface_name, options={}, **kwargs):
        if kwargs.get("parent_interface"):
            (base_namespace, base_idx) = self.find_interface_in_all_namespaces(
                kwargs.get("parent_interface")
            )
            self._log.debug(
                f"found parent_interface {kwargs.get('parent_interface')} in namespace {base_namespace}"
            )
            if not kwargs.get("vlan_id"):
                raise ValueError(
                    "vlan_id not specified -> cannot create tagged vlan interface without"
                )
            else:
                self._log.debug(
                    f"creating tagged interface {interface_name} with tag on base_interface"
                )

            self.set_current_namespace(base_namespace)

            # EEXIST (17) here with no visible interface in any namespace indicates stale
            # 8021q kernel state after a prior netns move; fix: modprobe -r 8021q && modprobe 8021q
            self.ipr.link(
                "add",
                ifname=interface_name,
                kind="vlan",
                link=base_idx,
                vlan_id=int(kwargs.get("vlan_id")),
                **options,
            )
            idx = self.get_interface_index(interface_name)
            namespace = kwargs.get("namespace")
            if namespace:
                if kwargs.get("namespace") not in self.get_namespaces():
                    self.create_namespace(namespace)
                self.ipr.link("set", index=idx, net_ns_fd=namespace)
                self.set_current_namespace(namespace)
                idx = self.get_interface_index(interface_name)
            else:
                self.ipr.link("set", index=idx, net_ns_pid=1)
            return (namespace, idx)
        else:
            raise ValueError(
                f"parent_interface not specified for vlan interface {interface_name}"
            )

    def __create_ipvlan(self, interface_name, options={}, **kwargs):
        ipvlan_modes = {
            "l2": 0,
            "l3": 1,
            "l3s": 2,
        }
        if kwargs.get("parent_interface"):
            (base_namespace, base_idx) = self.find_interface_in_all_namespaces(
                kwargs.get("parent_interface")
            )
            self._log.debug(f"found parent_interface in namespace {base_namespace}")
            self.set_current_namespace(base_namespace)

            self.ipr.link(
                "add",
                ifname=interface_name,
                kind="ipvlan",
                link=base_idx,
                ipvlan_mode=ipvlan_modes.get(kwargs.get("ipvlan_mode", "l2"), ipvlan_modes["l2"]),
                **options,
            )
            idx = self.get_interface_index(interface_name)
            namespace = kwargs.get("namespace")
            if namespace:
                self.set_current_namespace(namespace)
                self.set_current_namespace(base_namespace)
                self.ipr.link("set", index=idx, net_ns_fd=kwargs.get("namespace"))
                self.set_current_namespace(namespace)
            else:
                self.ipr.link("set", index=idx, net_ns_pid=1)
                self.set_current_namespace(None)
            idx = self.get_interface_index(interface_name)
            return (namespace, idx)
        else:
            raise ValueError(
                f"parent_interface not specified for ipvlan interface {interface_name}"
            )

    def __create_macvlan(self, interface_name, options={}, **kwargs):
        macvlan_modes = {
            "bridge": 4,
            "passthru": 8,
            "private": 1,
            "vepa": 2,
        }
        if not kwargs.get("parent_interface"):
            raise ValueError(
                f"parent_interface not specified for macvlan interface {interface_name}"
            )
        (base_namespace, base_idx) = self.find_interface_in_all_namespaces(
            kwargs.get("parent_interface")
        )
        self._log.debug(f"found parent_interface in namespace {base_namespace}")
        self.set_current_namespace(base_namespace)

        mode = kwargs.get("macvlan_mode", "bridge")
        self.ipr.link(
            "add",
            ifname=interface_name,
            kind="macvlan",
            link=base_idx,
            macvlan_mode=macvlan_modes.get(mode, macvlan_modes["bridge"]),
            **options,
        )
        idx = self.get_interface_index(interface_name)
        namespace = kwargs.get("namespace")
        if namespace:
            self.set_current_namespace(namespace)
            self.set_current_namespace(base_namespace)
            self.ipr.link("set", index=idx, net_ns_fd=kwargs.get("namespace"))
            self.set_current_namespace(namespace)
        else:
            self.ipr.link("set", index=idx, net_ns_pid=1)
            self.set_current_namespace(None)
        idx = self.get_interface_index(interface_name)
        return (namespace, idx)

    def __create_tun(self, interface_name, options={}, **kwargs):
        return self.__create_tuntap(interface_name, options, **kwargs, mode="tun")

    def __create_tap(self, interface_name, options={}, **kwargs):
        return __create_tuntap(interface_name, options, **kwargs, mode="tap")

    def __create_tuntap(self, interface_name, options={}, **kwargs):
        self.ipr.link(
            "add",
            ifname=interface_name,
            kind="tuntap",
            mode=options.get("mode","tun"),
            **options,
        )
        idx = self.get_interface_index(interface_name)
        namespace = kwargs.get("namespace")
        if namespace:
            self.set_current_namespace(namespace)
            self.set_current_namespace(base_namespace)
            self.ipr.link("set", index=idx, net_ns_fd=kwargs.get("namespace"))
            self.set_current_namespace(namespace)
        else:
            self.ipr.link("set", index=idx, net_ns_pid=1)
            self.set_current_namespace(None)
        idx = self.get_interface_index(interface_name)
        return (namespace, idx)
    
       

    def create_interface(self, interface_name, **kwargs):
        options = {}
        if kwargs.get("mtu"):
            options["mtu"] = kwargs.get("mtu")

        f = getattr(self, f"_SimpleNetlink__create_{kwargs.get('type')}")
        if f:
            (namespace, idx) = f(interface_name, options, **kwargs)
            if kwargs.get("link_state", "").lower() == "down":
                self.ipr.link("set", index=idx, state="down")
            else:
                self._log.debug(
                    f"enabling interface {interface_name} in namespace {namespace}"
                )
                self.ipr.link("set", index=idx, state="up")
            return (namespace, idx)
        else:
            raise ValueError(f"type {kwargs.get('type')} not implemented")

    def _resolve_interface_type_by_index(self, idx):
        info = {}
        for attr in self.ipr.link("get", index=idx)[0]["attrs"]:
            if attr[0] == "IFLA_LINKINFO":
                for inner_attr in attr[1]["attrs"]:
                    if inner_attr[0] == "IFLA_INFO_KIND":
                        info["type"] = inner_attr[1]
                        if info["type"] == "vlan":
                            info["type"] = "tagged"
                    if info["type"] == "tagged" and inner_attr[0] == "IFLA_INFO_DATA":
                        for ii in inner_attr[1]["attrs"]:
                            if ii[0] == "IFLA_VLAN_ID":
                                info["vlan_id"] = ii[1]
                break
        return info

    def get_interface_mtu(self):
        for attr in self.ipr.link("get", index=idx)[0]["attrs"]:
            if attr[0] == "IFLA_MTU":
                return attr[1]

    def get_interface_ip(self, interface, **kwargs):
        namespace, idx = self.find_interface_in_all_namespaces(interface)
        self.set_current_namespace(namespace)
        retval = {"ipv4": [], "ipv6": []}

        for entry in self.ipr.get_addr(index=idx):
            for attr in entry["attrs"]:
                if attr[0] == "IFA_ADDRESS":
                    if entry["family"] == 2:
                        retval["ipv4"].append(f"{attr[1]}/{entry['prefixlen']}")
                    if entry["family"] == 10:
                        retval["ipv6"].append(f"{attr[1]}/{entry['prefixlen']}")
                break

        return retval

    def get_interface_ipv4(self, interface):
        return self.get_interface_ip(interface)["ipv4"]

    def get_interface_ipv6(self, interface):
        return self.get_interface_ip(interface)["ipv6"]

    def _dhclient_pidfile(self, interface_name, namespace=None):
        ns_tag = f"{namespace}-" if namespace else ""
        return f"/run/dhclient-nettestbed-{ns_tag}{interface_name}.pid"

    def _is_dhclient_running(self, interface_name, namespace=None):
        """Check our explicit pidfile — reliable across process/worker restarts."""
        try:
            with open(self._dhclient_pidfile(interface_name, namespace)) as f:
                pid = int(f.read().strip())
            subprocess.run(["kill", "-0", str(pid)], check=True, capture_output=True)
            return True
        except Exception:
            return False

    def _shell_detached(self, cmd):
        """Run via bash with & so bash is our only direct child (reaped by
        subprocess.run) and dhclient is immediately reparented to init."""
        import shlex
        shell_cmd = " ".join(shlex.quote(a) for a in cmd)
        subprocess.run(f"nohup {shell_cmd} >/dev/null 2>&1 &",
                       shell=True, executable="/bin/bash")

    def enable_dhcp(self, interface_name, namespace=None):
        key = (interface_name, namespace)
        if self._is_dhclient_running(interface_name, namespace):
            self._log.debug(f"dhclient already running for {interface_name}, skipping")
            self._dhcp_interfaces.add(key)
            return
        pidfile = self._dhclient_pidfile(interface_name, namespace)
        cmd = ["dhclient", "-v", "-pf", pidfile, interface_name]
        if namespace:
            cmd = ["ip", "netns", "exec", namespace] + cmd
        self._shell_detached(cmd)
        self._dhcp_interfaces.add(key)
        self._log.debug(f"started dhclient for {interface_name} in namespace {namespace or 'root'}")

    def disable_dhcp(self, interface_name, namespace=None):
        key = (interface_name, namespace)
        pidfile = self._dhclient_pidfile(interface_name, namespace)
        cmd = ["dhclient", "-x", "-pf", pidfile, interface_name]
        if namespace:
            cmd = ["ip", "netns", "exec", namespace] + cmd
        self._shell_detached(cmd)
        self._dhcp_interfaces.discard(key)
        self._log.debug(f"stopped dhclient for {interface_name} in namespace {namespace or 'root'}")

    def ensure_interface_exists(self, interface, **kwargs):
        self.reset()
        namespace, idx = self.find_interface_in_all_namespaces(interface)
        self.set_current_namespace(namespace)

        if idx:
            if kwargs.get("namespace") != namespace:
                self._log.debug(
                    f'interface is in namespace {namespace} -> moving to {kwargs.get("namespace")}'
                )
                self.disable_dhcp(interface, namespace)

                if kwargs.get("namespace"):
                    self.set_current_namespace(kwargs.get("namespace"))
                    self.set_current_namespace(namespace)
                    self.ipr.link("set", index=idx, net_ns_fd=kwargs.get("namespace"))
                    self.set_current_namespace(kwargs.get("namespace"))
                    self.interface_up(interface)
                else:
                    self.set_current_namespace(namespace)
                    self.ipr.link("set", index=idx, net_ns_pid=1)
                    self.set_current_namespace(None)
                    self.interface_up(interface)

            interface_info = self._resolve_interface_type_by_index(idx)
            if kwargs.get("type"):
                if interface_info.get("type") != kwargs.get("type"):
                    self.delete_interface()
                    raise ValueError(
                        "Cannot change interface type. please delete the interface and recreate with new configuration"
                    )

            if kwargs.get("mtu"):
                self.ipr.link("set", index=idx, mtu=kwargs.get("mtu"))

            if kwargs.get("link_state") in ["up", "down"]:
                if kwargs.get("link_state") == "up":
                    self.interface_up(interface)
                else:
                    self.interface_down(interface)
            elif kwargs.get("link_state") == None:
                pass
            else:
                raise ValueError(
                    f"{kwargs['link_state']} is not a valid link state. Valid link_state values up,down"
                )

        else:
            if kwargs.get("type") in self._supported_virtual_interface_types:
                self._log.debug(
                    f'interface type of {interface} is virtual interface of type {kwargs.get("type")} which does not exist -> creating'
                )
                namespace, idx = self.create_interface(interface, **kwargs)
            else:
                raise ValueError(
                    f"either physical interface just doesn't exist (typo?) or virtual type {kwargs.get('type')} is not supported"
                )

        ipv4_list = kwargs.get("ipv4", [])
        namespace = kwargs.get("namespace")

        if "auto" in ipv4_list:
            self.enable_dhcp(interface, namespace)
        else:
            self.disable_dhcp(interface, namespace)
            v4_diff_list = self.get_interface_ipv4(interface)
            for ipv4_config_item in ipv4_list:
                self.interface_add_ipv4(interface, ipv4_config_item)
                if ipv4_config_item in v4_diff_list:
                    v4_diff_list.remove(ipv4_config_item)
            if v4_diff_list:
                self._log.debug(
                    f"interface {interface} has dangling ipv4 addresses {v4_diff_list}"
                )
                for ip in v4_diff_list:
                    self.interface_delete_ipv4(interface, ip)

        v6_diff_list = self.get_interface_ipv6(interface)

        for ipv6_config_item in kwargs.get("ipv6", []):
            self.interface_add_ipv6(interface, ipv6_config_item)
            if ipv6_config_item in v6_diff_list:
                v6_diff_list.remove(ipv6_config_item)
        if v6_diff_list:
            self._log.debug(
                f"interface {interface} has dangling ipv6 addresses {v6_diff_list}"
            )
            for ip in v6_diff_list:
                self.interface_delete_ipv6(interface, ip)

        return (namespace, idx)

    def interface_add_ipv4(self, interface_name, prefix):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        address, prefix_len = prefix.strip().split("/")
        prefix_len = int(prefix_len)
        try:
            self.ipr.addr("add", index=idx, address=address, prefixlen=prefix_len)
        except netlink.exceptions.NetlinkError as e:
            if e.code == 98 or e.code == 17:
                self._log.debug(
                    f"prefix {prefix} already in use in namespace {self._current_namespace} -> ignoring request"
                )
                self._log.debug(e)
                return True
            else:
                raise (e)
        self._log.debug(
            f"setting ipv4_address {prefix} on {interface_name} in namespace {self._current_namespace}"
        )
        return True

    def interface_delete_ipv4(self, interface_name, prefix):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        address, prefix_len = prefix.strip().split("/")
        prefix_len = int(prefix_len)
        try:
            self.ipr.addr("del", index=idx, address=address, prefixlen=prefix_len)
        except netlink.exceptions.NetlinkError as e:
            if e.code == 98 or e.code == 17:
                self._log.debug(
                    f"prefix {prefix} already in use in namespace {self._current_namespace} -> ignoring request"
                )
                self._log.debug(e)
                return True
            else:
                raise (e)
        self._log.debug(
            f"setting ipv4_address {prefix} on {interface_name} in namespace {self._current_namespace}"
        )
        return True

    def interface_add_ipv6(self, interface_name, prefix):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        address, prefix_len = prefix.strip().split("/")
        prefix_len = int(prefix_len)
        try:
            self.ipr.addr(
                "add",
                index=idx,
                address=address,
                prefixlen=prefix_len,
                family=socket.AF_INET6,
            )
        except netlink.exceptions.NetlinkError as e:
            if e.code == 98 or e.code == 17:
                self._log.debug(
                    f"prefix {prefix} already in use in namespace {self._current_namespace} -> ignoring request"
                )
                self._log.debug(e)
                return True
            else:
                raise (e)
        self._log.debug(
            f"setting ipv6_address {prefix} on {interface_name} in namespace {self._current_namespace}"
        )
        return True

    def interface_delete_ipv6(self, interface_name, prefix):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        address, prefix_len = prefix.strip().split("/")
        prefix_len = int(prefix_len)
        try:
            self.ipr.addr(
                "del",
                index=idx,
                address=address,
                prefixlen=prefix_len,
                family=socket.AF_INET6,
            )
        except netlink.exceptions.NetlinkError as e:
            if e.code == 98 or e.code == 17:
                self._log.debug(
                    f"prefix {prefix} already not present in namespace {self._current_namespace} -> ignoring request"
                )
                self._log.debug(e)
                return True
            else:
                raise (e)
        self._log.debug(
            f"deleting ipv6_address {prefix} on {interface_name} in namespace {self._current_namespace}"
        )
        return True

    def interface_up(self, interface_name):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        self.ipr.link("set", index=idx, state="up")

    def interface_down(self, interface_name):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        self.ipr.link("set", index=idx, state="down")

    def delete_interface(self, interface_name):
        self.disable_dhcp(interface_name, self._current_namespace)
        idx = self.get_interface_index(interface_name)
        self.ipr.link("del", index=idx)
        self._log.debug(f"deleted interface {interface_name} from namespace {self._current_namespace}")

    def move_interface_to_root(self, interface_name):
        idx = self.get_interface_index(interface_name)
        self.ipr.link("set", index=idx, net_ns_pid=1)
        self._log.debug(f"moved interface {interface_name} from {self._current_namespace} to root namespace")

    def get_routes(self):
        import socket
        retval = {"static": {}, "dynamic": {}, "local": {}}
        for route in self.ipr.route("show", type=1, family=socket.AF_INET):
            if route.get_attr("RTA_GATEWAY"):
                dest = route.get_attr("RTA_DST")
                if dest:
                    dest = f"{dest}/{route.get('dst_len')}"
                else:
                    dest = "default"
                if dest not in retval["static"]:
                    retval["static"][dest] = []
                retval["static"][dest].append(route.get_attr("RTA_GATEWAY"))
            elif route.get_attr("RTA_PREFSRC"):
                dest = f"{route.get_attr('RTA_DST')}/{route.get('dst_len')}"
                if dest not in retval["local"]:
                    retval["local"][dest] = []
                retval["local"][dest].append(f"{route.get_attr('RTA_PREFSRC')}")
            else:
                self._log.debug(f"skipping route with no gateway or prefsrc: {route}")
        return retval

    def add_route(self, prefix, nexthop):
        try:
            self.ipr.route("add", gateway=nexthop, dst=prefix)
            self._log.debug(
                f"added route {prefix} via {nexthop} in namespace {self._current_namespace}"
            )
        except netlink.exceptions.NetlinkError as e:
            if e.code == 17:
                self._log.debug(
                    f"route {prefix} via {nexthop} in namespace {self._current_namespace} exists -> ignoring"
                )
                pass
            else:
                raise (e)

    def delete_route(self, prefix, nexthop):
        try:
            self.ipr.route("del", gateway=nexthop, dst=prefix)
        except netlink.exceptions.NetlinkError as e:
            if e.code == 3:
                self._log.debug(
                    f"route {prefix} via {nexthop} in namespace {self._current_namespace} does not exist -> ignoring request to delete"
                )
            else:
                raise (e)

    def get_network_interfaces_info(self):
        results = {}
        for link in self.ipr.get_links():
            interface_name=link.get_attr("IFLA_IFNAME")
            interface_type=None
            additional_parameters={}
            if link.get_attr("IFLA_LINKINFO"):
                _kind = link.get_attr("IFLA_LINKINFO").get_attr("IFLA_INFO_KIND")
                if _kind == "vlan":
                    additional_parameters["type"] = "tagged"
                    additional_parameters["vlan_id"] = link.get_attr("IFLA_LINKINFO").get_attr("IFLA_INFO_DATA").get_attr("IFLA_VLAN_ID")
                    parent_idx = link.get_attr("IFLA_LINK")
                    if parent_idx:
                        try:
                            with IPRoute() as _root:
                                additional_parameters["parent_interface"] = _root.link('get', index=parent_idx)[0].get_attr("IFLA_IFNAME")
                        except Exception:
                            pass
                elif _kind == "ipvlan":
                    additional_parameters["type"] = "ipvlan"
                    parent_idx = link.get_attr("IFLA_LINK")
                    if parent_idx:
                        try:
                            with IPRoute() as _root:
                                additional_parameters["parent_interface"] = _root.link('get', index=parent_idx)[0].get_attr("IFLA_IFNAME")
                        except Exception:
                            pass
                elif _kind == "macvlan":
                    additional_parameters["type"] = "macvlan"
                    parent_idx = link.get_attr("IFLA_LINK")
                    if parent_idx:
                        try:
                            with IPRoute() as _root:
                                additional_parameters["parent_interface"] = _root.link('get', index=parent_idx)[0].get_attr("IFLA_IFNAME")
                        except Exception:
                            pass
                elif _kind == "tun":
                    try:
                        info_data = link.get_attr("IFLA_LINKINFO").get_attr("IFLA_INFO_DATA")
                        tun_type = info_data.get_attr("IFLA_TUN_TYPE") if info_data else None
                        additional_parameters["type"] = "tap" if tun_type == 2 else "tun"
                    except Exception:
                        additional_parameters["type"] = "tun"

            ipv4 = []
            ipv6 = []
            for addr in self.ipr.get_addr(
                family=socket.AF_INET, label=interface_name
            ):
                ipv4.append(
                    {
                        "prefix_length": addr["prefixlen"],
                        "address": addr.get_attr("IFA_ADDRESS"),
                        "prefix": f'{addr.get_attr("IFA_ADDRESS")}/{addr["prefixlen"]}',
                    }
                )
            for addr in self.ipr.get_addr(
                family=socket.AF_INET6, label=interface_name
            ):
                ipv6.append(
                    {
                        "prefix_length": addr["prefixlen"],
                        "address": addr.get_attr("IFA_ADDRESS"),
                        "prefix": f'{addr.get_attr("IFA_ADDRESS")}/{addr["prefixlen"]}',
                    }
                )
            results[interface_name] = {
                "link_state": link["state"].lower(),
                "oper_state": link.get_attr("IFLA_OPERSTATE").lower(),
                "mac_address": link.get_attr("IFLA_ADDRESS", "None").lower(),
                "mtu": link.get_attr("IFLA_MTU"),
                "ipv4": ipv4,
                "ipv6": ipv6,
                "dhcp": (interface_name, self._current_namespace) in self._dhcp_interfaces,
                **additional_parameters
            }
        return results
