.. SPDX-FileCopyrightText: 2026 The meson-python developers
..
.. SPDX-License-Identifier: MIT

.. _how-to-guides-dynamic-metadata:

****************
Dynamic metadata
****************

``meson-python`` fills the ``version``, ``license``, and ``license-files``
fields declared as dynamic in the ``project`` section of ``pyproject.toml``
with the values specified in the ``meson.build`` file.  Other dynamic fields
can be computed at build time by dynamic-metadata_ plugins.  Plugins are
regular Python packages implementing the `dynamic-metadata protocol`_ and can
compute any metadata field except ``name``: for example the package version
from a file or from the state of the version control system, the readme from
several file fragments, or the dependencies from a requirements file.

To use dynamic-metadata plugins, add the ``dynamic-metadata`` package and the
chosen plugins to the build dependencies, declare the fields as dynamic, and
configure the plugins in ``tool.dynamic-metadata`` entries:

.. code-block:: toml

   [build-system]
   build-backend = 'mesonpy'
   requires = ['meson-python', 'dynamic-metadata', 'example-plugin']

   [project]
   name = 'example'
   version = '1.0.0'
   dynamic = ['dependencies']

   [[tool.dynamic-metadata]]
   provider = 'example_plugin'
   option = 'value'

Each entry names a plugin in the ``provider`` key: either a registered plugin
name, or a table like ``provider = {path = 'scripts', module = 'my_plugin'}``
importing a local module, similar to the ``backend-path`` key in the
``build-system`` section.  All other keys in the entry are passed to the
plugin as settings.  Entries are processed in order, and later entries can
read the fields computed by earlier ones.  Refer to the `dynamic-metadata
documentation`_ for the configuration of the individual plugins.

Listing ``dynamic-metadata`` in ``build-system.requires`` is recommended:
extra build dependencies requested by the plugins themselves can only be
collected when the package is importable while the build front-end queries the
build requirements.

Fields that plugins declare as computed at wheel build time via the
``dynamic_wheel()`` plugin hook are marked with ``Dynamic`` in the source
distribution metadata, as specified by the `core metadata`_ version 2.2.

.. _dynamic-metadata: https://pypi.org/project/dynamic-metadata/
.. _dynamic-metadata protocol: https://scikit-build.github.io/dynamic-metadata/
.. _dynamic-metadata documentation: https://scikit-build.github.io/dynamic-metadata/
.. _core metadata: https://packaging.python.org/en/latest/specifications/core-metadata/
