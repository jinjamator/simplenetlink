from simplenetlink import SimpleNetlink
import yaml
from pprint import pprint

ip = SimpleNetlink()

yml="""
vl1_1:
    namespace: test
    link_state: up
    parent_interface: eth0
    type: ipvlan
    ipv4:
        - 100.64.0.11/24
vl1_2:
    namespace: test2
    link_state: up
    parent_interface: eth0
    type: ipvlan
    ipv4:
        - 100.64.0.12/24
vl2:
    namespace: test3
    link_state: up
    parent_interface: eth0
    type: tagged
    vlan_id: 2
    ipv4:
        - 100.64.1.11/24
vl2_2:
    namespace: test4
    link_state: up
    parent_interface: vl2
    type: ipvlan
    ipv4:
        - 100.64.1.12/24

"""

config=yaml.safe_load(yml)

# for k,v in config.items():
#     if v.get('namespace'):
#         ip.delete_namespace(v.get('namespace'))
        
for k,v in config.items():
    ip.ensure_interface_exists(k,**v)

ip.set_current_namespace('test')
ip.add_route('0.0.0.0/0','100.64.0.1')
ip.set_current_namespace('test2')
ip.add_route('0.0.0.0/0','100.64.0.1')
ip.set_current_namespace('test3')
ip.add_route('0.0.0.0/0','100.64.1.1')
ip.set_current_namespace('test4')
ip.add_route('0.0.0.0/0','100.64.1.1')



from pprint import pprint
for namespace in ip.get_namespaces():
    ip.set_current_namespace(namespace)
    pprint(ip.get_network_interfaces_info())