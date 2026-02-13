Usage
=====

The **python-thingset** library implements Python client for the `ThingSet <https://thingset.io/>`_
protocol. Binary mode is supported when using either the CAN or TCP/IP transports and text mode is
supported when using the Serial transport.

As well as providing an importable Python package, a fully-featured command line tool is included to
enable simple interaction with ThingSet-enabled devices.

Below is a brief example showing how to use **python-thingset**. By default, if no arguments are
provided when instantiating a `ThingSet()` object, the Socket transport will be used and will attempt
to connect to a client running on *127.0.0.1*. In this example, a client defines a property containing
the string `native_posix` with the property identifier `0xF03` which is retrieved by the code below.

.. code-block:: python
   :linenos:

   from python_thingset import ThingSet

   with ThingSet() as ts:
       response = ts.get(0xF03)
       print(response)                  # 0x85 (CONTENT): native_posix
