from simplenetlink import SimpleNetlink
from pprint import pprint
ip = SimpleNetlink()
import logging
ip._log.debug=print

import atexit
atexit.register(ip.delete_namespace,'test')

# switch to namespace test (will be created if not exists)
ip.set_current_namespace('test')


#create ipvlan interface in new or existing namespace test with ipv4 address and implicitly switch to namespace test
ip.ensure_interface_exists("ipvlan_test", namespace='test', link_state='up', parent_interface='eth0', type='ipvlan',  ipv4=['100.64.0.11/24','1.1.1.1/23'])

#add default route to current namespace which is test at the moment
ip.add_route('0.0.0.0/0','100.64.0.1')

#add route to current namespace which is test at the moment
ip.add_route('9.1.1.0/24','100.64.0.2')

# show routing table
pprint(ip.get_routes())


#delete route from current namespace which is test at the moment
ip.delete_route('9.1.1.0/24','100.64.0.2')

# show routing table
pprint(ip.get_routes())

# delete namespace test
ip.delete_namespace('test')

