Introduction
==================


Simplenetlink is an abstraction layer to simplify programatic non-persistent network configuration for linux on top of pyroute2. It was written to have a simple interface for network test setups. 

Features
-----------------

Simplenetlink has following features:
    * create and manage linux namespaces
    * move interfaces between namespaces
    * create tagged vlan interfaces
    * create ipvlan interfaces
    * configure ipv4 addresses
    * idempotent

Installation
------------

Install simplenetlink by running:

.. code-block:: bash

    pip3 install simplenetlink


Examples
---------

Create Tagged VLAN interface in namespace and set IPv4 configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from simplenetlink import SimpleNetlink
    from pprint import pprint

    ip = SimpleNetlink()

    #create vlan interface in new or existing namespace test with ipv4 address and implicitly switch to namespace test
    ip.ensure_interface_exists("vlan2", namespace='test', link_state='up', parent_interface='eth0', type='tagged', vlan_id='2', ipv4=['100.64.0.10/24'])

    #show interfaces of namespace test
    pprint(ip.get_network_interfaces_info())

    #move tagged interface from namespace test to namespace test2 and implicitly switch to namespace test2
    ip.ensure_interface_exists("vlan2", namespace='test2', link_state='up', parent_interface='eth0', type='tagged', vlan_id='2', ipv4=['100.64.0.10/24'])

    #show interfaces of namespace test2
    pprint(ip.get_network_interfaces_info())

    # remove namespace test
    ip.delete_namespace('test')

    # remove namespace test2
    ip.delete_namespace('test2')


Create IPVLAN interface in namespace and set IPv4 configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

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


Add route to namespace
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

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


Configure multiple interfaces in multiple namespaces from a YAML description
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

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


Contribute
----------

- Issue Tracker: https://github.com/jinjamator/simplenetlink/issues
- Source Code: https://github.com/jinjamator/simplenetlink

Roadmap
-----------------

Selected Roadmap items:
    * add support for more virtual interface types e.g.: macvlan, vxlan, bridges
    * add support for ipv6
    * add class documentation

For documentation please refer to https://simplenetlink.readthedocs.io/en/latest/

License
-----------------

This project is licensed under the Apache License Version 2.0