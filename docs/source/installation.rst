Installation
============

Installing **python-thingset** is very simple as the package is available on
`PyPI <https://pypi.org/project/python-thingset/>`_. 

To install the package:

.. code-block:: shell
   :linenos:

   pip install python-thingset

To install the optional development dependencies required for linting and running
unit tests (quotation marks (`'...'`) may be required if using a shell like Zsh to
avoid issues whereby the square brackets are misinterpreted):

.. code-block:: shell
   :linenos:

   pip install 'python-thingset[dev]'

To install the package in editable mode (only possible locally, so it is necessary
to clone the repository):

.. code-block:: shell
   :linenos:

   cd python-thingset
   pip install -e .
