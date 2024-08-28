.. _Plugin SDK: https://arm1s11-eiffel004.eiffel.gic.ericsson.se:8443/nexus/content/sites/litp2/ERIClitpdocs/latest/plugin_sdk/acceptance_tests.html
.. _ipdb breakpoint: https://pypi.python.org/pypi/ipdb

What Version of ATRunner Am I Using?
====================================

All the tests for a given repo are run when the repo is built. However, the version of ATRunner used in running those tests is not a strightforward dependency.

ATRunner is not listed as a dependency of any plugin repo except for core. This is because ATRunner and core have a level of integration which means ATRunner is not always backwards compatible with older versions of core. Therefore, plugin repos do not directly inherit a specific version of ATRunner within their POM files. Instead, plugin repos have a dependency on a version of core and therefore inherit the version of ATRunner that has been stated as compatible with that version of core.

How Do I Use a Later Version of ATRunner for My ATs?
----------------------------------------------------

Each plugin repo can be built against the latest version of dependencies or a stated minimum version of dependencies. Both of these builds will be run during code reviews.

If you intend to write an AT for your repo which requires a new feature or bug fix in a version X of ATRunner, then perform the actions detailed below:

To get the latest-deps build to work:

#. Ensure that the core repo has version X or later stated as its minimum version of ATRunner.
#. Ensure that this version of core has passed KGB.

To get the current-deps build to work:

Update your stated minimum version of the core dependency to a version of core which has version x of ATRunner stated as its minimum version.

How Do I Enable Logging?
========================

Use the ``-l`` option to enable logging in ATs:

.. code-block:: bash

    ldu runats ats/testset_story9657/test_09_n_prepare_for_restore_remove_dependencies.at -l

This outputs any logs from LITP to the command line.

How Do I Enable Debugging?
==========================

Use the ``-d`` option to enable debugging in ATs, followed by the test line number where you want to set a breakpoint:

.. code-block:: bash

    ldu runats ats/testset_story9657/test_09_n_prepare_for_restore_remove_dependencies.at -d 39

The debugging option inserts an ipdb breakpoint in the code to allow for debugging.

.. warning:: The debugging option requires the line number to contain test logic (that is, not comments or empty lines).

You can insert an ipdb breakpoint manually into the source code of your plugin or extension using the following statements: ``import ipdb; ipdb.set_trace()``.
When this pair of statements is encountered as part of an AT execution, the terminal on which the ``runats`` command was launched cedes control to the ``ipdb`` interactive debugger.

.. warning:: This is a temporary debugging tool and causes automated AT executions (that is, AT executions performed by Jenkins jobs) to hang.

How Do I Enable Metrics?
========================

Use the ``-m`` or ``--metrics`` option to enable metrics in ATs:

.. code-block:: bash

    ldu runats ats/testset_story9657/test_09_n_prepare_for_restore_remove_dependencies.at -m

This outputs metrics from LITP to the command line.

What Parts of Core Are Not Mocked in ATRunner?
==============================================

ATRunner does not run the LITP service itself. Instead, it instantiates the following core modules:

* ModelManager
* PuppetManager
* PluginManager
* ExecutionManager
* ModelContainer
* CherrypyServer
* XmlLoader
* XmlExported
* SchemaWriter

Areas outside this are mocked, so exercise caution when writing ATs which fall outside these areas. For more information, see  :ref:`AT-when-label`

Useful Links
============

The plugin SDK gives a helpful introduction to ATs. For more information, see   `Plugin SDK`_.
