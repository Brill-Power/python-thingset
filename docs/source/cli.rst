Command Line Interface
======================

The **python-thingset** library implements Python client for the `ThingSet <https://thingset.io/>`_
protocol.

.. code-block:: python
   :linenos:

   from python_thingset import ThingSet

   with ThingSet() as ts:
       response = ts.get(0xF03)
       print(response)                  # 0x85 (CONTENT): native_posix
