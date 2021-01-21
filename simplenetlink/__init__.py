from pyroute2 import IPRoute, netns, NetNS, netlink
import socket
import logging
import time


class SimpleNetlink(object):
    def __init__(self, namespace=None):
        self.ipr = IPRoute()
        self._log = logging.getLogger("SimpleNetlink")
        self._current_namespace = namespace
        self._previous_namespace_instance = None
        self._previous_namespace = None
        # self._log.level = logging.DEBUG
        self._supported_virtual_interface_types = ["ipvlan", "tagged"]

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
        ns = netns.create(namespace)

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
            ns = NetNS(namespace)
            ns.close()
            ns.remove()

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
        idx = None
        namespace = self.get_current_namespace_name()
        try:
            self.set_current_namespace(None)
            idx = self.get_interface_index(interface_name)
            namespace = self.get_current_namespace_name()
            self.restore_previous_namespace()
        except ValueError:
            for namespace in self.get_namespaces():
                self._log.debug(f"switching namespace to {namespace}")
                self.set_current_namespace(namespace)
                try:
                    idx = self.get_interface_index(interface_name)
                    break
                except:
                    pass
                self.restore_previous_namespace()
        if idx:
            self._log.debug(
                f"found interface {interface_name} in namespace {namespace} with index {idx}"
            )
        else:
            self._log.debug(f"cannot find interface {interface_name} in any namespace")
        return (namespace, idx)

    def __create_tagged(self, interface_name, **kwargs):
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

            self.ipr.link(
                "add",
                ifname=interface_name,
                kind="vlan",
                link=base_idx,
                vlan_id=int(kwargs.get("vlan_id")),
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

    def __create_ipvlan(self, interface_name, **kwargs):
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
                ipvlan_mode=ipvlan_modes[
                    "l2"
                ],  # l2 mode so arp can be handled from namespace
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

    def create_interface(self, interface_name, **kwargs):

        f = getattr(self, f"_SimpleNetlink__create_{kwargs.get('type')}")
        if f:
            (namespace, idx) = f(interface_name, **kwargs)
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

    def ensure_interface_exists(self, interface, **kwargs):

        namespace, idx = self.find_interface_in_all_namespaces(interface)
        if idx:
            if kwargs.get("namespace") != namespace:
                self._log.debug(
                    f'interface is in namespace {namespace} -> moving to {kwargs.get("namespace")}'
                )

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

        for ipv4_config_item in kwargs.get("ipv4", []):
            self.interface_add_ipv4(interface, ipv4_config_item)

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

    def interface_up(interface_name):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        self.ipr.link("set", index=idx, state="up")

    def interface_down(interface_name):
        idx = self.get_interface_index(interface_name)
        if not idx:
            raise ValueError(
                f"interface {interface_name} not found in namespace {self._current_namespace}"
            )
        self.ipr.link("set", index=idx, state="down")

    def get_routes(self):
        retval = {
            'static':{},
            'dynamic':{},
            'local':{}
        }
        for route in self.ipr.route("show", type=1):
            if route.get_attr('RTA_GATEWAY'):
                dest = route.get_attr('RTA_DST')
                if dest:
                    dest=f"{dest}/{route.get('dst_len')}"
                else:
                    dest='default'
                if dest not in retval['static']:
                    retval['static'][dest]=[]
                retval['static'][dest].append(route.get_attr('RTA_GATEWAY'))
            elif route.get_attr('RTA_PREFSRC'):
                dest = f"{route.get_attr('RTA_DST')}/{route.get('dst_len')}"
                if dest not in retval['local']:
                    retval['local'][dest]=[]
                retval['local'][dest].append(f"{route.get_attr('RTA_PREFSRC')}")
            else:
                raise ValueError(f'Never come here, if so something is really wrong. {route}')
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
            ipv4 = []
            ipv6 = []
            for addr in self.ipr.get_addr(
                family=socket.AF_INET, label=link.get_attr("IFLA_IFNAME")
            ):
                ipv4.append(
                    {
                        "prefix_length": addr["prefixlen"],
                        "address": addr.get_attr("IFA_ADDRESS"),
                    }
                )
            for addr in self.ipr.get_addr(
                family=socket.AF_INET6, label=link.get_attr("IFLA_IFNAME")
            ):
                ipv6.append(
                    {
                        "prefix_length": addr["prefixlen"],
                        "address": addr.get_attr("IFA_ADDRESS"),
                    }
                )
            results[link.get_attr("IFLA_IFNAME")] = {
                "link_state": link["state"].lower(),
                "oper_state": link.get_attr("IFLA_OPERSTATE").lower(),
                "mac_address": link.get_attr("IFLA_ADDRESS", "None").lower(),
                "mtu": link.get_attr("IFLA_MTU"),
                "ipv4": ipv4,
                "ipv6": ipv6,
            }
        return results
