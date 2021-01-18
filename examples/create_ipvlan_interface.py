from simplenetlink import SimpleNetlink
from pprint import pprint

ip = SimpleNetlink()

#create ipvlan interface in new or existing namespace test with ipv4 address and implicitly switch to namespace test
ip.ensure_interface_exists("ipvlan_test", namespace='test', link_state='up', parent_interface='eth0', type='ipvlan',  ipv4=['100.64.0.11/24'])

#show interfaces of namespace test
pprint(ip.get_network_interfaces_info())

#move ipvlan interface from namespace test to namespace test2 and implicitly switch to namespace test2
ip.ensure_interface_exists("ipvlan_test", namespace='test2', link_state='up', parent_interface='eth0', type='ipvlan', ipv4=['100.64.0.11/24'])


#show interfaces of namespace test2
pprint(ip.get_network_interfaces_info())


# remove namespace test
ip.delete_namespace('test')

# remove namespace test2
ip.delete_namespace('test2')