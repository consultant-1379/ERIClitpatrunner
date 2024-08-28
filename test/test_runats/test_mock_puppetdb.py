import unittest
from mock import patch

from litpats.atcli import ATCli
from litpats.mocking.mock_puppetdb_api import MockPuppetDbApi
from litpats.mocking import enable_core_bypass
from litp.core.nextgen.plugin_manager import PluginManager
from litp.core.task import ConfigTask
from litp.extensions.core_extension import CoreExtension
from litp.core.plan import Plan
from litp.core.scope_utils import threadlocal_scope
from litp.core.plugin_context_api import PluginApiContext
import logging

class TestMockPuppetDb(unittest.TestCase):
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
        self.puppetdb = MockPuppetDbApi()
        self.puppetdb.set_attrs(self.atcli.execution, 'foo')

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()

    def _register_core_extensions(self):
        core_extension = CoreExtension()
        property_types = core_extension.define_property_types()
        self.atcli.model_manager.register_property_types(property_types)
        item_types = core_extension.define_item_types()
        self.atcli.model_manager.register_item_types(item_types)

    @threadlocal_scope
    def test_mock_wait_for_puppet_feedback_fails_dependent_tasks(self):
        node = self.api.query_by_vpath("/ms")
        cfg_task_1 = ConfigTask(
            node,
            node,
            "I am a ConfigTask. Yay!",
            "foo",
            "alpha"
        )
        cfg_task_1._id = "4a9cd60771b7433ca1a7a4e69654a786"

        cfg_task_2 = ConfigTask(
            node,
            node,
            "I depend on the other task!",
            "bar",
            "beta"
        )
        cfg_task_2._id = "832fa47508414e53aaa832c418a6bfb1"
        cfg_task_2._requires = set([cfg_task_1.unique_id])

        puppet_phase = [cfg_task_1, cfg_task_2]
        self.atcli.add_failed_task(cfg_task_1)
        self.atcli.model_manager.configuration_logging_level = logging.INFO
        self.atcli.model_manager.set_debug(False, normal_start=False)
        self.atcli.execution.plan = Plan([puppet_phase])
        self.atcli.execution.plan.set_ready()
        self.atcli.execution.plan.current_phase = 0

        expected_failures = set([cfg_task_1._id, cfg_task_2._id])
        self.assertEquals(expected_failures, self.puppetdb.get_tasks_to_fail())
