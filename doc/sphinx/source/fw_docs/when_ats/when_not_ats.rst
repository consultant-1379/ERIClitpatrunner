What Are the Limitations of ATs?
================================

Take note of the following limitations when using ATs:

#. They are not suitable for integration testing with 3PPs.

#. They are more suitable for testing core functionality than testing plugins.

#. Tasks do not usually execute.

#. A HTTP connection is not used to connect to the REST interface.

#. You cannot test migrations.

#. You cannot fully test integration with Puppet.

#. You cannot execute a snapshot plan.

When Should I Not Use ATs?
==========================

As a general rule, do not use ATs if you are testing integration with third-party software (such as Puppet, RHEL, Mco or VCS).

Do not use ATs as a replacement for other types of tests (such as unit tests). Use ATs in conjunction with other types of tests to ensure proper coverage.

What Is Mocked in ATs?
======================

The following list outlines the main elements of LITP which are mocked in ATs:

#. Puppet feedback

   - ATs never interact with an actual Puppet master or Puppet agent. Feedback is mocked so that all resources in the report are successfully applied, although you can set ConfigTasks to fail in an AT.

#. HTTP connection

   - However, the actual REST client logic is used.

#. LITP service

   - The litp service never actually stops or starts in the context of ATs, but a restart of the service can be simulated.

#. The filesystem

   - ATrunner uses a custom MockFilesystem class which acts as an overlay between LITP and the filesystem on which the ATs are executing.
   - Real files are never written, instead a 'virtual' file is created in memory for LITP to read and write to during the execution of an AT.

#. Task execution

   - ConfigTasks are written to manifests on the mocked filesystem, but never configure anything.
   - CallbackTasks are mocked by default, but can be 'enabled' by using the disableCallbackMock command. Only use this for predictable and safe operations, such as updating the model.
   - Task execution always defaults to Success, but can be Failed or Stopped.

#. MCollective commands

#. ConfigTask UUID

#. Snapshot item timestamp property during serialisation

#. Plugin and extension versions during serialisation
