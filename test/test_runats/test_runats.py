import os
import imp
import unittest
import logging
import StringIO
from mock import patch
from mock import Mock
from mock import MagicMock
from mock import call

from litpats.atcli import ATCli
import litpats.mocking.mocks
import litpats.mocking.patches
from litpats.mocking import enable_core_bypass
from litp.core.model_manager import ModelManager
from litp.core.nextgen.execution_manager import ExecutionManager
from litp.core.nextgen.puppet_manager import PuppetManager
from litp.core.nextgen.plugin_manager import PluginManager
from litp.core.task import ConfigTask
from litp.core.task import CleanupTask
from litp.extensions.core_extension import CoreExtension
from litp.core.model_type import Property
from litp.core.model_type import ItemType
from litp.core.scope_utils import threadlocal_scope
from litp.core.plugin_context_api import PluginApiContext


class TestRunats(unittest.TestCase):
    def setUp(self):
        enable_core_bypass()

        self.atcli = ATCli()
        self.atcli.line = 0

        self.patcher1 = patch.object(
            PluginManager, "add_extensions",
            side_effect=lambda conf_dir: self._register_core_extensions())
        self.patcher2 = patch.object(PluginManager, "add_plugins")

        self.patcher1.start()
        self.patcher2.start()

        self.atcli.run("clearLandscape", [])
        self.api = PluginApiContext(self.atcli.model_manager)

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()

    def _register_core_extensions(self):
        core_extension = CoreExtension()
        property_types = core_extension.define_property_types()
        self.atcli.model_manager.register_property_types(property_types)
        item_types = core_extension.define_item_types()
        self.atcli.model_manager.register_item_types(item_types)
