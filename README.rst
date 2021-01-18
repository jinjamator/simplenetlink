Introduction
==================


Simplenetlink is an abstraction layer to simplify programatic non-persistant network configuration for linux on top of pyroute2. It was written to have a simple interface for network test setups. 

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

.. literalinclude:: examples/create_tagged_interface.py
  :language: python


.. literalinclude:: examples/create_ipvlan_interface.py
  :language: python


.. literalinclude:: examples/add_route_to_namespace.py
  :language: python


.. literalinclude:: examples/create_config_from_yaml.py
  :language: python



Contribute
----------

- Issue Tracker: https://github.com/jinjamator/simplenetlink/issues
- Source Code: https://github.com/jinjamator/simplenetlink

Roadmap
-----------------

Selected Roadmap items:
    * add support for more virtual interface types e.g.: macvlan, vxlan, bridges
    * add support for ipv6

For documentation please refer to https://simplenetlink.readthedocs.io/en/latest/

License
-----------------

This project is licensed under the Apache License Version 2.0