from simplenetlink import SimpleNetlink

# switch to namespace test (will be created if not exists)
ip.set_current_namespace('test')


#create ipvlan interface in new or existing namespace test with ipv4 address and implicitly switch to namespace test
ip.ensure_interface_exists("ipvlan_test", namespace='test', link_state='up', parent_interface='eth0', type='ipvlan',  ipv4=['100.64.0.11/24'])

#add default route to current namespace which is test at the moment
ip.add_route('0.0.0.0/0','100.64.0.1')

#add route to current namespace which is test at the moment
ip.add_route('10.100.0.0/24','100.64.0.2')

# delete namespace test
ip.delete_namespace('test')
