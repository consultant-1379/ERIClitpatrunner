The Advantages of Using ATs
===========================

**When appropriate**, write test cases as ATs instead of ITs. Using ATs over ITs has a number of significant advantages:

1. Bugs can be found before new code is merged.

  When performing a local build of a repo, all ATs are automatically run. This means bugs found can be fixed before the developer has even submitted the code for
  review. This helps to keep the team's bug count low by having bugs fixed before they are even merged to master.

2. Helps developers to debug.

  ATs provide a number of useful tools to help developers to debug new code.

3. Fast execution time.

  An AT test typically takes less than a second to run and provides a near instant feedback loop.

4. ATs test compatibility with minimum versions of dependencies with every change.

  When a code change is submitted for review, two Jenkins builds are triggered. One tests a build with the stated minimum version of all dependencies and
  the other job tests the build with the latest versions of all dependencies that have passed KGB. If any AT fails, the build fails and the code is
  blocked from merging. Note that ITs are only run against the last good known baseline. Unlike ATs, they provide no testing against minimum stated versions
  of dependencies.

.. _AT-when-label:

When Are ATs Useful?
====================

As explained in section :ref:`ats-execute-label`, ATs are executed against an instantiated core version with 3PP-related functionality mocked out. As a result, there are several cases, particularly end-to-end tests, where ATs should not be used.

In general, use ATs if you are testing either core itself or logic that executes entirely within the LITP daemon.

The following sections detail areas where ATs are useful.

Testing Validation Errors
-------------------------

Validation errors are generated either by a plugin itself or by core directly. Assuming no callback task is involved in generating a validation error (this should be a rare case), you can write ATs for these tests.

Below is an example AT which checks for validation errors on ``litp create_plan``:

.. code-block:: bash

    ## Create a default 2 node cluster deployment
    runLitpScript ../queryitems/setup_twonodes.inc

    ## Run the plan so that cluster is in applied state
    litp create_plan
    litp run_plan

    ## Update hostname to its current value. Assert create plan says nothing to do
    litp update -p /deployments/site1/clusters/cluster1/nodes/node1 -o hostname="node1"
    assertError --err_message 'no tasks were generated' create_plan

    ## Try to update hostname to a new value, results in an error as this is an Applied readonly value
    assertError --err_type 'InvalidRequestError' --err_message 'Unable to modify readonly property: hostname' update -p /deployments/site1/clusters/cluster1/nodes/node1 -o hostname="newhostname"

A big advantage to using ATs for validation checking is that you can set up a model in an Applied state almost instantly to allow easy checking of different validation error cases.


Testing Expected States
-----------------------

The state of items in the model is controlled by core and so is a candidate for AT testing. ATs also enable testing of validation errors which should be generated when items are in specific states.

The example test below tests that manifest files are generated when a package is installed and are then removed when ``litp prepare_restore`` is run.

.. code-block:: bash

    ## Basic deployment script
    runLitpScript ../setup_two_nodes.inc
    
    ## Create items and assert they are in state Initial
    litp create -p /software/items/x -t mock-package -o name=x
    litp inherit -p /deployments/site1/clusters/cluster1/nodes/node1/items/x -s /software/items/x 
    litp inherit -p /deployments/site1/clusters/cluster1/nodes/node2/items/x -s /software/items/x
    assertState -p /deployments/site1/clusters/cluster1/nodes/node1/items/x Initial
    assertState -p /deployments/site1/clusters/cluster1/nodes/node2/items/x Initial

    ## Create plan and assert items are still in state initial
    litp create_plan
    assertState -p /software/items/x Initial
    assertState -p /deployments/site1/clusters/cluster1/nodes/node1/items/x Initial
    assertState -p /deployments/site1/clusters/cluster1/nodes/node2/items/x Initial

    ## Run plan and assert state goes to Applied
    litp run_plan
    assertState -p /software/items/x Applied
    assertState -p /deployments/site1/clusters/cluster1/nodes/node1/items/x Applied
    assertState -p /deployments/site1/clusters/cluster1/nodes/node2/items/x Applied

    ## Remove an item and check it goes to state ForRemoval
    litp remove -p /deployments/site1/clusters/cluster1/nodes/node1/items/x
    assertState -p /deployments/site1/clusters/cluster1/nodes/node1/items/x ForRemoval

    ## Assert a validation error is given when an attempt is made to delete an item which is a parent for an item in Applied State
    ## NB: Note above that the item on node2 is in state Applied
    assertError --err_message 'Cannot delete an item that is a source for inherited items with state "Applied" or "Updated"' remove -p /software/items/x

Testing Property Values
-----------------------

You can use ATs to test default property values and how property values can be updated (as this is functionality provided either by the plugin or by core).

The simple test below verifies that the property value of a model item has been updated:

.. code-block:: bash

    ## Create example items in the model
    litp create -p /infrastructure/networking/networks/ms_network -t network -o name='nodes' subnet='10.10.10.0/24'
    litp create -p /ms/network_interfaces/ip1 -t network-interface -o network_name='nodes' ipaddress='10.10.10.100'
    litp create -p /deployments/local_vm -t deployment
    litp create -p /deployments/local_vm/clusters/cluster1 -t cluster
    litp create -p /deployments/local_vm/clusters/cluster1/nodes/node1 -t node -o hostname='node1'
    litp create -p /deployments/local_vm/clusters/cluster1/nodes/node1/network_interfaces/eth1 -t eth -o device_name=eth1 network_name='nodes' -o ipaddress="10.46.86.97"

    ## Check expected property value is set
    assertProperty /deployments/local_vm/clusters/cluster1/nodes/node1/network_interfaces/eth1 -o ipaddress="10.46.86.97"
    
    ## following update check expected property is updated
    litp update -p /deployments/local_vm/clusters/cluster1/nodes/node1/network_interfaces/ip1 -o network_name=nodes1 ipaddress='10.46.86.98'
    assertProperty /deployments/local_vm/clusters/cluster1/nodes/node1/network_interfaces/ip1 -o ipaddress="10.46.86.98"


Testing Puppet Manifest File Generation
---------------------------------------

When a plan is executed, LITP updates the Puppet manifest files which direct how Puppet behaves. For example, if you execute a plan to install a package on node1, the manifest mandates that the package should be present on the node when the plan has finished execution. Although you cannot use ATs to test Puppet behaviour, you can use the AT mock file system to test the contents of the generated manifest files.

The mock file system is a concept where files generated by LITP during the execution of an AT are stored in memory rather than actually being written to disk. You can interact with these files while the AT is running, but they are removed from memory when the AT finishes.

The below is an example test which tests that manifest files are generated when a package is installed and then are removed when ``litp prepare_restore`` is run.

.. code-block:: bash

    ## Basic deployment script
    runLitpScript ../include/two_nodes.at

    ## Install a package on nodes. This shuld cause puppet manifests to be generated
    litp create -p /software/items/telnet -t mock-package -o name=telnet
    litp inherit -p /ms/items/telnet -s /software/items/telnet
    litp inherit -p /deployments/local/clusters/cluster1/nodes/node1/items/telnet -s /software/items/telnet
    litp inherit -p /deployments/local/clusters/cluster1/nodes/node2/items/telnet -s /software/items/telnet

    ## Run plan and assert it completes successfully
    litp create_plan
    litp run_plan
    assertPlanState successful

    ## Assert that manifests have been generated. This method compares an actual local
    ## folder called manifests with the contents generated in the mocked file system
    assertDirectoryContents manifests/ /opt/ericsson/nms/litp/etc/puppet/manifests/plugins/

    litp prepare_restore

    ## Assert manifests have been removed by prepare restore
    assertDirectoryContents manifests/empty/ /opt/ericsson/nms/litp/etc/puppet/manifests/plugins/

Testing XML File Generation
---------------------------

As XML file generation is a function of core and involves no 3PP interaction, ATs are ideal for XML test cases.

The mock file system explained above enables you to compare files generated by the AT with real local files you have checked into the ATs folder. This means you can generate XML files with LITP or a third-party tool, check them into Git and then use those local files when testing with ATs.

Below is a simple test case which checks that the XML generated by an AT matches an XML file prepared beforehand:

.. code-block:: bash

    ## We first create a model for us to use to test export.
    litp create -p /software/profiles/rhel_6_2 -t os-profile -o name='sample-profile' path='/profiles/node-iso/'
    litp create -p /infrastructure/storage/storage_profiles/profile_1 -t storage-profile-base
    litp create -p /infrastructure/systems/system1 -t system -o system_name='MN1VM'

    litp create -p /deployments/local_vm -t deployment
    litp create -p /deployments/local_vm/clusters/cluster1 -t cluster

    litp create -p /deployments/local_vm/clusters/cluster1/nodes/node1 -t node -o hostname=node1 
    litp create -p /deployments/local_vm/clusters/cluster1/nodes/node1/network_interfaces/ip1 -t network-interface -o network_name=nodes
    litp inherit -p /deployments/local_vm/clusters/cluster1/nodes/node1/os -s /software/profiles/rhel_6_2 
    litp inherit -p /deployments/local_vm/clusters/cluster1/nodes/node1/storage_profile -s /infrastructure/storage/storage_profiles/profile_1
    litp inherit -p /deployments/local_vm/clusters/cluster1/nodes/node1/system -s /infrastructure/systems/system1

    ## We now export to an xml file
    litp export -p / -f /tmp/root.xml

    ## We now test that the exported file matches the prepared exported_root.xml file
    ## we have already generated and checked into git
    assertFileContents exported_root.xml /tmp/root.xml

You can easily generate a model with items in a combination of states for more advanced XML testing.

Asserting Plan Contents and Task Ordering
-----------------------------------------

The tasks present in a plan and the ordering/phasing in which they appear is handled between core and the plugin. Therefore, as no external 3PPs are involved, you can use ATs for this kind of testing.

The example below asserts that the listed tasks all appear in the first phase of a plan:

.. code-block:: bash

    ## Run a custom LITP script
    runLitpScript setup_twonodes.inc
    ##Install a custom plugin for testing
    add-plugins ../plugins/mock_volmgr_plugin

    ## Create plan
    litp create_plan

    ## Assert package related tasks are in the 1st phase of a plan (phase 0) as is defined in 
    ## the custom plugin
    assertTask 0 package node1 /deployments/site1/clusters/cluster1/nodes/node1/items/package_file
    assertTask 0 package node1 /deployments/site1/clusters/cluster1/nodes/node1/items/package_vim
    assertTask 0 package node2 /deployments/site1/clusters/cluster1/nodes/node2/items/package_file
    assertTask 0 package node2 /deployments/site1/clusters/cluster1/nodes/node2/items/package_vim


Other Uses of ATs
-----------------

The examples above are not exhaustive but are intended to illustrate the areas in which you can use ATs. You can review other areas on a case-by-case basis to identify which are suitable for AT testing and which you should test using ITs.
