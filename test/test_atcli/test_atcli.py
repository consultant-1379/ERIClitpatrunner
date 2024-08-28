import os
import unittest
import logging
import StringIO

from mock import patch
from mock import Mock
from mock import MagicMock
from mock import call

from litpats.atcli import ATCli, MockFilesystemContext
from litpats import mockfilesystem
from litp.core.model_manager import ModelManager
from litp.core.nextgen.execution_manager import ExecutionManager
from litp.core.nextgen.puppet_manager import PuppetManager
from litp.core.nextgen.plugin_manager import PluginManager
from litp.core.plugin_context_api import PluginApiContext
from litp.core.task import ConfigTask
from litp.core.task import CleanupTask
from litp.core.task import RemoteExecutionTask
from litp.extensions.core_extension import CoreExtension
from litp.core.model_type import Property
from litp.core.model_type import ItemType
from litp.core.scope_utils import threadlocal_scope
from xml.etree import ElementTree


class TestATCli(unittest.TestCase):
    def setUp(self):
        self.atcli = ATCli()
        self.atcli.line = 0

        self.count_register_core_extensions = 0

        original_add_extensions = PluginManager.add_extensions
        def add_extensions(conf_dir):
            if not self.count_register_core_extensions:
                self._register_core_extensions()
            else:
                original_add_extensions(self.atcli.plugin_manager, conf_dir)
            self.count_register_core_extensions += 1

        self.patcher1 = patch.object(
            PluginManager, "add_extensions",
            side_effect=add_extensions)
        self.patcher2 = patch.object(PluginManager, "add_plugins")

        self.patcher1.start()
        self.patcher2.start()

        self.atcli.run("clearLandscape", [])

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()

        if mockfilesystem.MockFilesystem._instance:
            mockfilesystem.destroy()

    def _register_core_extensions(self):
        core_extension = CoreExtension()
        property_types = core_extension.define_property_types()
        self.atcli.model_manager.register_property_types(property_types)
        item_types = core_extension.define_item_types()
        self.atcli.model_manager.register_item_types(item_types)

    def _register_auxiliary_extensions(self):
        package = ItemType("package",
                            extend_item="software-item",
                            name=Property("basic_string",
                                required=True,
                                updatable_rest=False))
        self.atcli.model_manager.register_item_type(package)

    def _create_model(self):
        self._register_auxiliary_extensions()

        model_manager = self.atcli.model_manager
        model_manager.create_root_item("root")
        # Source item
        model_manager.create_item(
                'package', '/software/items/telnet', name='telnet')
        # Single inherit
        model_manager.create_inherited(
                '/software/items/telnet', '/ms/items/telnet')
        model_manager.create_item('deployment', '/deployments/local')
        model_manager.create_item(
                'cluster', '/deployments/local/clusters/cluster1')
        model_manager.create_item(
                'node', '/deployments/local/clusters/cluster1/nodes/node1',
                hostname="node1")
        model_manager.create_item(
                'node', '/deployments/local/clusters/cluster1/nodes/node2',
                hostname="node2")
        # Double inherit
        model_manager.create_inherited(
                '/ms/items/telnet',
                '/deployments/local/clusters/cluster1/nodes/node1/items/telnet',)
        # Triple inherit
        model_manager.create_inherited(
                '/deployments/local/clusters/cluster1/nodes/node1/items/telnet',
                '/deployments/local/clusters/cluster1/nodes/node2/items/telnet')

        self.api = PluginApiContext(model_manager)
        self.ms = self.api.query_by_vpath('/ms')
        self.node1 = self.api.query_by_vpath(
            '/deployments/local/clusters/cluster1/nodes/node1')
        self.item1 = self.api.query_by_vpath(
            '/deployments/local/clusters/cluster1/nodes/node1/items/telnet')

    def test_mockfilesystem_context(self):
        atcli = ATCli()
        atcli.filesystem = mockfilesystem.create('/tmp')
        self.assertFalse(atcli.filesystem.active)
        self.assertEqual(open.__name__, 'open')
        self.assertFalse(os.path.exists('some_mock_file.foo'))
        with MockFilesystemContext(atcli):
            self.assertTrue(atcli.filesystem.active)
            self.assertEqual(open.__name__, 'mock_open')
            mock_file = open('some_mock_file.foo', 'w')
            mock_file.write('abc')
            mock_file.close
            self.assertTrue('some_mock_file.foo' in atcli.filesystem._files)
        self.assertFalse(atcli.filesystem.active)
        self.assertEqual(open.__name__, 'open')
        self.assertFalse(os.path.exists('some_mock_file.foo'))

    @threadlocal_scope
    @patch('litpats.atcli.sys.stdout.write')
    @patch('litpats.atcli.ElementTree.parse')
    @patch('litpats.atcli.os.path.exists')
    def test_print_deprecated_waring(self, mock_exists, mock_parse, mock_stdout):
        mock_exists.return_value = True
        # Assert happy path - no warning printed from core
        core_pom = '<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd"><artifactId>ERIClitpcore</artifactId></project>'
        mock_root = ElementTree.fromstring(core_pom)
        mock_parse.return_value = mock_root

        self.atcli.command_assert_plan_length(0)
        self.assertFalse(mock_stdout.called)

        # Assert negative path - warning printed from outside core
        non_core_pom = '<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd"><artifactId>ERIClitppackage</artifactId></project>'
        mock_root = ElementTree.fromstring(non_core_pom)
        mock_parse.return_value = mock_root

        self.atcli.command_assert_plan_length(0)
        expected = [call('Warning: Deprecated command has been used in this AT'), call('\n')]
        self.assertTrue(mock_stdout.called)
        self.assertEqual(expected, mock_stdout.call_args_list)

    @threadlocal_scope
    def test_command_restart_litp(self):
        model_manager = ModelManager()
        plugin_manager = PluginManager(model_manager)
        puppet_manager = PuppetManager(model_manager)
        execution = ExecutionManager(model_manager, puppet_manager, plugin_manager)
        execution.fix_plan_at_service_startup = Mock()

        atcli = ATCli()
        atcli.model_manager, atcli.plugin_manager = model_manager, plugin_manager
        atcli.execution, atcli.puppet_manager = execution, puppet_manager

        atcli.command_restart_litp()

        self.assertTrue(execution.fix_plan_at_service_startup.called)

    def test__unify_kwargs_escaping(self):
        ''' Test escaping and unescaping special characters. '''
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name=user-data',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        ret_kwargs, ret_task_kwargs = self.atcli._unify_kwargs(args, task)
        self.assertEquals(ret_kwargs, ret_task_kwargs)

    def test__task_has_kwargs_positive_equal_sign_in_value(self):
        task = Mock()
        args = ('path=12.12.12.12:/nas_shared/ro_unmanaged',
                'mount_point=/cluster_ro',
                'mount_status=remount',
                'mount_options=soft,intr,timeo=30,noexec,nosuid')
        task.kwargs = {'path': '12.12.12.12:/nas_shared/ro_unmanaged',
                'mount_point': '/cluster_ro',
                'mount_status': 'remount',
                'mount_options': 'soft,intr,timeo=30,noexec,nosuid'}
        ret_kwargs, ret_task_kwargs = self.atcli._unify_kwargs(args, task)
        self.assertEquals(ret_kwargs, ret_task_kwargs)

    def test__unify_kwargs_dict(self):
        ''' Test parsing of jsonified dict passed as an argument. '''
        task = Mock()
        args = ('rule3={"name": "001 basetcp ipv6", "chain": "INPUT", '
                    '"proto": "tcp", "title": "001_basetcp_ipv6", '
                    '"dport": ["22", "80", "111", "443", "3000", "25151"], '
                    '"state": ["NEW"], '
                    '"ensure": "present", '
                    '"provider": "ip6tables", "action": "accept"}',
                'rule2={"name": "1001 basetcp ipv4", "chain": "OUTPUT", '
                    '"proto": "tcp", "title": "1001_basetcp_ipv4", '
                    '"dport": ["22", "80", "111", "443", "3000", "25151"], '
                    '"state": ["NEW"], '
                    '"ensure": "present", '
                    '"provider": "iptables", "action": "accept"}')
        task.kwargs = {
                'rule3': {'name': '001 basetcp ipv6', 'chain': 'INPUT',
                    'proto': 'tcp', 'title': '001_basetcp_ipv6',
                    'dport': [u'22', u'80', u'111', u'443', u'3000', u'25151'],
                    'state': ['NEW'],
                    'ensure': 'present',
                    'provider': 'ip6tables', 'action': 'accept'},
                'rule2': {'name': '1001 basetcp ipv4', 'chain': 'OUTPUT',
                    'proto': 'tcp', 'title': '1001_basetcp_ipv4',
                    'dport': [u'22', u'80', u'111', u'443', u'3000', u'25151'],
                    'state': ['NEW'],
                    'ensure': 'present',
                    'provider': 'iptables', 'action': 'accept'}}
        ret_kwargs, ret_task_kwargs = self.atcli._unify_kwargs(args, task)
        self.assertEquals(ret_kwargs, ret_task_kwargs)

    def test__format_properties(self):
        task = Mock()
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        expected = (r"target_path='/var/lib/libvirt/instances/fmmed1' "
                        r"file_name='user-data' "
                        r"content='\#cloud-config\nyum_repos:\n  enm_a:\n    "
                        r"baseurl: http://example.com/yum_repo\n    "
                        r"enabled: true\n    gpgcheck: false\n    "
                        r"name: enm_a\n'")
        actual = self.atcli._format_properties(task.kwargs.items())
        self.assertEquals(actual, expected)

    def test__task_has_kwargs_strict_positive(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name=user-data',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs_strict(task, args)
        self.assertTrue(result)

    def test__task_has_kwargs_strict_negative_missing_arg(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs_strict(task, args)
        self.assertFalse(result)

    def test__task_has_kwargs_strict_negative_invalid_value(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name=user-data_INVALID',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs_strict(task, args)
        self.assertFalse(result)

    def test__task_has_kwargs_strict_negative_invalid_key(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name_INVALID=user-data',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs_strict(task, args)
        self.assertFalse(result)

    def test__task_has_kwargs_positive(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name=user-data',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n',
                'rule2.proto=tcp',
                'rule2.dport=["22", "80", "111", "443", "3000", "25151"]')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n',
                'rule2': {'name': '1001 basetcp ipv4', 'chain': 'OUTPUT',
                    'proto': 'tcp', 'title': '1001_basetcp_ipv4',
                    'dport': [u'22', u'80', u'111', u'443', u'3000', u'25151'],
                    'state': ['NEW'],
                    'ensure': 'present',
                    'provider': 'iptables', 'action': 'accept'}
                    }
        result = self.atcli._task_has_kwargs(task, args)
        self.assertTrue(result)

    def test__task_has_kwargs_dict_negative(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name=user-data',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n',
                'rule2.proto=tcp',
                'rule2.dport=["22", "80", "111", "443", "3000", "25151"]')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n',
                'rule2': {'name': '1001 basetcp ipv4', 'chain': 'OUTPUT',
                    'proto': 'tcp', 'title': '1001_basetcp_ipv4',
                    'dport': [u'80', u'111', u'443', u'3000', u'25151'],
                    'state': ['NEW'],
                    'ensure': 'present',
                    'provider': 'iptables', 'action': 'accept'}
                    }
        result = self.atcli._task_has_kwargs(task, args)
        self.assertFalse(result)

    def test__task_has_kwargs_positive_missing_arg(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs(task, args)
        self.assertTrue(result)

    def test__task_has_kwargs_negative_missing_task_kwarg(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name=user-data',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs(task, args)
        self.assertFalse(result)

    def test__task_has_kwargs_negative_invalid_value(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name=user-data_invalid',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs(task, args)
        self.assertFalse(result)

    def test__task_has_kwargs_negative_invalid_key(self):
        task = Mock()
        args = ('target_path=/var/lib/libvirt/instances/fmmed1',
                'file_name_INVALID=user-data',
                'content=\\#cloud-config\\nyum_repos:\\n  enm_a:\\n    '
                    'baseurl: http://example.com/yum_repo\\n    '
                    'enabled: true\\n    gpgcheck: false\\n    name: enm_a\\n')
        task.kwargs = {'target_path': u'/var/lib/libvirt/instances/fmmed1',
                'file_name': 'user-data',
                'content': '#cloud-config\nyum_repos:\n  enm_a:\n    '
                    'baseurl: http://example.com/yum_repo\n    '
                    'enabled: true\n    gpgcheck: false\n    name: enm_a\n'}
        result = self.atcli._task_has_kwargs(task, args)
        self.assertFalse(result)

    @threadlocal_scope
    def test_assert_no_cleanup_task(self):
        self._create_model()

        ms = self.ms
        node = self.node1
        task1 = ConfigTask(ms, ms, 'desc', 'foo', 'bar')
        task2 = ConfigTask(node, node, 'desc2', 'foo2', 'bar2')
        cleanup_task_for_ms = CleanupTask(ms)

        self.atcli.execution = MagicMock()
        self.atcli.execution.plan_phases.return_value = [
            [task1, task2], [cleanup_task_for_ms]]
        self.assertRaises(AssertionError, \
                self.atcli.command_assert_no_cleanup_task, '/ms')

        cleanup_task_for_ms.model_item = Mock(get_vpath=lambda: "/not_ms")
        self.assertEquals("Pass", self.atcli.command_assert_no_cleanup_task('/ms'))

    @patch('litpcli.litp.LitpCli.run_command', return_value=None)
    def test_command_litp(self, mock_run_cmd):
        atcli = ATCli()
        atcli.line = 1
        atcli.filesystem = MagicMock()
        cmd_list = ['create', '-p', '/software/items/telnet', '-t',
                'mock-package', '-o', 'name=telnet']
        self.assertEqual(None, atcli.run('show', cmd_list))
        self.assertEquals([call(cmd_list)], mock_run_cmd.mock_calls)

    @patch('litpcli.litp.LitpCli.run_command', return_value="something")
    def test_command_assertError(self, mock_run_cmd):
        atcli = ATCli()
        atcli.line = 1
        atcli.filesystem = MagicMock()
        cmd_list = ['create_plan']
        self.assertRaises(AssertionError, lambda: atcli.run('assertError',
            cmd_list))
        self.assertEquals(call(cmd_list), mock_run_cmd.call_args)

    @patch('litpats.mock_http_connection.MockHTTPResponse')
    @patch('litpats.atcli.LitpCli._execute_request')
    def test_command_litp_mock_execute_request(self, mock_execute_request,
            MockHTTPResponse):
        atcli = ATCli()
        atcli.line=1
        atcli.filesystem = MagicMock()
        cmd = 'litp'
        cmd_list = ['create', '-p', '/software/items/litpcds_5281',
                '-t', 'mock-package']
        ret_message = r'{"properties": {"ensure": "installed", "name":'\
                '"litpcds_5281"}, "item-type-name": "mock-package", '\
                '"applied_properties_determinable": true, "state": '\
                '"Initial", "_links": {"self": {"href": '\
                '"/software/items/litpcds_5281"}, "item-type": {"href": '\
                '"/item-types/mock-package"}}, "id": "litpcds_5281"}'
        reps = MockHTTPResponse
        reps.status = 201
        reps.read.return_value = ret_message
        reps.text = ret_message
        mock_execute_request.return_value = (reps,None)
        self.assertEqual(0, atcli.run(cmd, cmd_list))
        self.assertEqual(mock_execute_request.call_count, 1)

        # Missing -p parameter
        cmd_list = ['create', '/software/items/litpcds_5281', '-t',
                'mock-package']
        mock_execute_request.return_value = (reps,None)
        self.assertRaises(AssertionError, lambda: atcli.run(cmd, cmd_list))

    def set_assertError_environment(self, MockHTTPResponse):
        atcli = ATCli()
        atcli.show_errors = False
        atcli.line=1
        atcli.filesystem = MagicMock()
        cmd = 'assertError'
        cmd_list = ['--err_type', 'InvalidLocationError', '--err_message',
                'Path not found', 'create', '-p',
                '/software/itms/litpcds_5281', '-t', 'mock-package']
        ret_message =r'{"messages": [{"_links": {"self": {"href": '\
                '"/software/XXXX/litpcds_5281"}}, "message": '\
                '"Path not found", "type": "InvalidLocationError"}], '\
                '"_links": {"self": {"href": "/software/XXXX/litpcds_5281"}}}'
        reps = MockHTTPResponse
        reps.status = 404
        reps.read.return_value = ret_message
        reps.text = ret_message
        return atcli, cmd, cmd_list, reps


    @patch('litpats.mock_http_connection.MockHTTPResponse')
    @patch('litpats.atcli.LitpCli._execute_request')
    def test_command_assertError_mock_execute_request(self,
            mock_execute_request, MockHTTPResponse):
        atcli, cmd, cmd_list, reps = \
                self.set_assertError_environment(MockHTTPResponse)
        cmd_list = ['create', '-p', '/software/itms/litpcds_5281',
                '-t', 'mock-package']
        mock_execute_request.return_value = (reps, None)
        self.assertEqual(1, atcli.run(cmd, cmd_list))
        self.assertEqual(mock_execute_request.call_count, 1)

    @patch('litpats.mock_http_connection.MockHTTPResponse')
    @patch('litpats.atcli.LitpCli._execute_request')
    def test_command_assertError_mock_execute_request_with_err_message(self,
            mock_execute_request, MockHTTPResponse):
        atcli, cmd, cmd_list, reps = \
                self.set_assertError_environment(MockHTTPResponse)
        mock_execute_request.return_value = (reps, None)
        self.assertEqual(1, atcli.run(cmd, cmd_list))
        self.assertEqual(mock_execute_request.call_count, 1)

    @patch('litpats.mock_http_connection.MockHTTPResponse')
    @patch('litpats.atcli.LitpCli._execute_request')
    def test_command_assertError_mock_execute_request_with_wrong_err_type(
            self, mock_execute_request, MockHTTPResponse):
        atcli, cmd, cmd_list, reps = self.set_assertError_environment(\
                MockHTTPResponse)
        mock_execute_request.return_value = (reps, None)
        cmd_list = ['--err_type', 'MissingRequiredItemError', '--err_message',
                'Path not found', 'create', '-p',
                '/software/itms/litpcds_5281', '-t', 'mock-package']
        self.assertRaises(AssertionError, lambda: atcli.run(cmd, cmd_list))
        self.assertEqual(mock_execute_request.call_count, 1)

    @patch('litpats.mock_http_connection.MockHTTPResponse')
    @patch('litpats.atcli.LitpCli._execute_request')
    def test_command_assertError_mock_execute_request_with_wrong_err_message(
            self, mock_execute_request, MockHTTPResponse):
        atcli, cmd, cmd_list, reps = self.set_assertError_environment(\
                MockHTTPResponse)
        mock_execute_request.return_value = (reps, None)
        cmd_list = ['--err_type', 'InvalidLocationError', '--err_message',
                'Dummy message', 'create', '-p', '/software/itms/litpcds_5281',
                '-t', 'mock-package']
        self.assertRaises(AssertionError, lambda: atcli.run(cmd, cmd_list))
        self.assertEqual(mock_execute_request.call_count, 1)

    def test_command_assertLogMessage(self):
        atcli = ATCli()

        # No logger handler defined
        self.assertRaises(AttributeError, lambda:
                atcli.command_assert_log_message("Dummy message"))

        test_logging_stream = StringIO.StringIO()
        del logging.getLogger().handlers[0]
        test_log_handler = logging.StreamHandler(test_logging_stream)
        logging.getLogger().addHandler(test_log_handler)
        # Message found
        logging.getLogger().handlers[0].stream.write('valid message X')
        self.assertTrue(atcli.command_assert_log_message("valid"))
        self.assertTrue(atcli.command_assert_log_message("message"))
        self.assertTrue(atcli.command_assert_log_message("X"))
        self.assertTrue(atcli.command_assert_log_message("valid message X"))

        # Message not found
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_log_message("valid X"))
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_log_message("valid message 4"))

        atcli.command_clear_logs()
        self.assertRaises(AssertionError, lambda:
            atcli.command_assert_log_message("valid message X"))

        # Run time error
        logging.getLogger().handlers=[]
        self.assertRaises(RuntimeError, lambda:
                atcli.command_assert_log_message("valid message X"))

    @patch('litpcli.litp.LitpCli.run_command', return_value=None)
    def test_command_show(self, mock_run_cmd):
        atcli = ATCli()
        atcli.line = 1
        atcli.filesystem = MagicMock()
        cmd_list = ['show', '-p', '/']
        self.assertEqual(None, atcli.run('show', cmd_list))
        self.assertTrue(mock_run_cmd.called)
        self.assertEqual(mock_run_cmd.call_count, 1)
        self.assertEqual(call(cmd_list), mock_run_cmd.call_args)

        mock_run_cmd.reset_mock()
        cmd_list = ['show', '-p', '/', '-r']
        self.assertEqual(None, atcli.run('show', cmd_list))
        self.assertTrue(mock_run_cmd.called)
        self.assertEqual(mock_run_cmd.call_count, 1)
        self.assertEqual(call(cmd_list), mock_run_cmd.call_args)

    @patch('litpats.atcli.ATCli.item_by_path')
    def test_command_assertNone(self, mock_item_by_path):
        atcli = ATCli()
        mock_item_by_path.return_value = "Something"
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_none('-p', '/software/profiles'))
        mock_item_by_path.return_value = None
        self.assertEqual("Pass", atcli.command_assert_none('-p',
            '/software/profiles/ubuntu'))

    @patch('litpats.atcli.ATCli.item_by_path')
    def test_command_assertState(self, mock_item_by_path):
        atcli = ATCli()

        # Two arguments defined
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_state('-p', '/deployements'))
        self.assertEqual(mock_item_by_path.call_count, 0)

        # No such item
        mock_item_by_path.return_value = None
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_state('-p', '/deployements', 'Applied'))
        self.assertEqual(mock_item_by_path.call_count, 1)

        # Expected state is wrong
        mock_item_by_path.reset_mock()
        mockItem = MagicMock(return_value = 'Initial')
        mockItem.Applied = 'Applied'
        mockItem.get_state = MagicMock(return_value = 'Initial')
        mockItem._mock_children = MagicMock(return_value = 'Initial')
        mock_item_by_path.return_value = mockItem
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_state('-p', '/deployements', 'Applied'))
        self.assertEqual(mock_item_by_path.call_count, 1)

        # Happy path
        mock_item_by_path.reset_mock()
        mockItem.get_state.return_value = 'Applied'
        mockItem._mock_children.get.return_value = 'Applied'
        self.assertEqual("Pass", atcli.command_assert_state('-p',
            '/deployements', 'Applied'))
        self.assertEqual(mock_item_by_path.call_count, 1)

    @patch('litpats.atcli.ATCli.item_by_path', return_value=None)
    def test_command_assertAppliedPropertiesDeterminable(self,
                    mock_item_by_path):
        atcli = ATCli()
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_apd('-p', '/deployments/dep1/nodes/node1',
                    'Trues'))
        self.assertEqual(mock_item_by_path.call_count, 0)

        mockItem = MagicMock()
        mock_item_by_path.return_value = mockItem
        mockItem.applied_properties_determinable = False
        self.assertRaises(AssertionError, lambda:
                atcli.command_assert_apd('-p', '/deployments/dep1/nodes/node1',
                    'True'))
        self.assertEqual(mock_item_by_path.call_count, 1)

        mock_item_by_path.reset_mock()
        mock_item_by_path.return_value = mockItem
        mockItem.applied_properties_determinable = True
        self.assertEqual("Pass", atcli.command_assert_apd('-p',\
                '/deployments/dep1/nodes/node1', 'True'))
        self.assertEqual(mock_item_by_path.call_count, 1)

    def test_command_assertProperty_missing_argument(self):
        atcli = self.atcli
        self.assertRaises(ValueError,
            atcli.command_assert_property, '-o', 'ipaddress="10.46.86.98')
        self.assertRaises(ValueError,
            atcli.command_assert_property, '/a/b', 'ipaddress="10.46.86.98"')
        self.assertRaises(AssertionError,
            atcli.command_assert_property, '/a/b', '-o')

    @patch('litpats.atcli.ATCli.item_by_path', return_value=None)
    def test_command_assertProperty_wrong_argument(self, mock_item_by_path):
        atcli = self.atcli
        self.assertRaises(ValueError,
            atcli.command_assert_property,
                '/a/b', '-oo', 'ipaddress="10.46.86.98"')
        self.assertEqual(mock_item_by_path.call_count, 0)

    @patch('litpats.atcli.ATCli.item_by_path', return_value=None)
    def test_command_assertProperty_wrong_path(self, mock_item_by_path):
        atcli = self.atcli
        try:
            atcli.command_assert_property(
                '/a/b/c', '-o', 'ipaddress="10.46.86.98"')
        except AssertionError as e:
            self.assertEquals(str(e), "No such item: /a/b/c")
        else:
            self.fail("Should have raised AssertionError")
        self.assertEqual(mock_item_by_path.call_count, 1)

    @threadlocal_scope
    def test_command_assertProperty_get_properties(self):
        self._create_model()
        atcli = self.atcli

        # Happy path - property is as expected
        vpath = '/software/items/telnet'
        self.assertEqual("Pass",
            atcli.command_assert_property(vpath, '-o', 'name=telnet'))

        # The property is not as expected
        vpath = '/software/items/telnet'
        try:
            atcli.command_assert_property(vpath, '-o', 'name=EXPECTED')
        except AssertionError as e:
            self.assertEquals(str(e),
                    "{0}: expected {1} but was {2}".format(
                        vpath, "EXPECTED", "telnet"))
        else:
            self.fail("AssertionError should have been raised")

        # Single inheritance - property found
        vpath = '/ms/items/telnet'
        self.assertEqual("Pass",
            atcli.command_assert_property(vpath, '-o', 'name=telnet'))

        # Single inheritance - property is not as expected
        vpath = '/ms/items/telnet'
        try:
            atcli.command_assert_property(vpath, '-o', 'name=EXPECTED')
        except AssertionError as e:
            self.assertEquals(str(e),
                    "{0}: expected {1} but was {2}".format(
                        vpath, "EXPECTED", "telnet"))
        else:
            self.fail("AssertionError should have been raised")

        # Multiple inheritance - property found
        vpath = '/deployments/local/clusters/cluster1/nodes/node2/items/telnet'
        self.assertEqual("Pass",
            atcli.command_assert_property(vpath, '-o', 'name=telnet'))

        # Multiple inheritance - is not as expected
        vpath = '/deployments/local/clusters/cluster1/nodes/node2/items/telnet'
        try:
            atcli.command_assert_property(vpath, '-o', 'name=EXPECTED')
        except AssertionError as e:
            self.assertEquals(str(e),
                    "{0}: expected {1} but was {2}".format(
                        vpath, "EXPECTED", "telnet"))
        else:
            self.fail("AssertionError should have been raised")

    @patch('litpats.atcli.ATCli.run', return_value=None)
    def test_command_run_litp_script(self, mock_run):
        atcli = ATCli()
        atcli.model_manager = ModelManager()
        atcli.test_dir = MagicMock()
        atcli.filesystem = MagicMock()
        atcli.filesystem.mock_exists.return_value = None
        atcli.show_errors = MagicMock()
        atcli.server = MagicMock()

        # Testing _read_file() on non-valid file name
        self.assertRaises(Exception, lambda: atcli._read_file(\
            '/dummy_path/dummy_file.txt'))

        # Test command_run_litp_script() on non-valid file name
        mock_run.reset_mock()
        self.assertRaises(Exception, lambda: atcli.command_run_litp_script(\
            '/dummy_path/dummy_file.txt'))

        # Happy path
        mock_run.reset_mock()
        path = os.path.dirname(os.path.abspath(__file__))
        atcli.command_run_litp_script(path + '/dummy_script.inc')
        self.assertEqual(mock_run.call_count, 26)

    def test_command_assert_plan_state(self):
        atcli = ATCli()
        atcli.execution = MagicMock()
        atcli.execution.plan_state.return_value = 'expected_value'

        self.assertRaises(AssertionError, lambda: atcli.\
                command_assert_plan_state())
        self.assertRaises(AssertionError, lambda: atcli.\
                command_assert_plan_state('not_expected_value'))
        self.assertEquals("Pass", atcli.command_assert_plan_state(\
                'expected_value'))

    @threadlocal_scope
    def test_command_add_plugins(self):
        # happy path test case
        test_dir, file = os.path.split(os.path.realpath(__file__))
        self.atcli.test_dir = test_dir
        try:
            self.atcli.command_add_plugins(test_dir)
        except:
            self.fail("Encountered an unexpected exception.")

    @threadlocal_scope
    def test_command_add_extensions(self):
        # happy path test case
        test_dir, file = os.path.split(os.path.realpath(__file__))
        self.atcli.test_dir = test_dir
        try:
            self.atcli.command_add_extensions(test_dir)
        except:
            self.fail("Encountered an unexpected exception.")

    def test_command_let_var(self):
        self.assertRaises(AssertionError, lambda: self.atcli.command_let_var(\
                'test_string'))
        try:
            self.atcli.command_let_var('__test_string')
        except:
            self.fail("Encountered an unexpected exception.")

    @threadlocal_scope
    def test_command_assert_task(self):
        atcli = ATCli()
        self._create_model()
        node1 = self.node1
        item1 = self.item1
        plan_task1 = ConfigTask(node1, item1, 'Desc1', 'call_type1',
                'call_id1', foo='foo1')
        atcli._get_phase = Mock(return_value=[plan_task1])
        ok_kwarg = 'foo=foo1'

        # Assert passes with correct details
        result = atcli.command_assert_task(0, plan_task1.call_type,
                node1.hostname, item1.get_vpath(), plan_task1.state,
                plan_task1.description, ok_kwarg)
        self.assertEqual("Pass", result)

        # Assert correct call_type
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                'call_type_WRONG', node1.hostname, item1.get_vpath(),
                plan_task1.state, plan_task1.description, ok_kwarg)

        # Assert correct hostname
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                plan_task1.call_type, 'WRONG_HOST', item1.get_vpath(),
                plan_task1.state, plan_task1.description, ok_kwarg)

        # Assert correct vpath
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                plan_task1.call_type, node1.hostname, 'WRONG_VPATH',
                plan_task1.state, plan_task1.description, ok_kwarg)

        # Assert correct state
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                plan_task1.call_type, node1.hostname, item1.get_vpath(),
                'WRONG_STATE', plan_task1.description, ok_kwarg)

        # Assert correct state
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                plan_task1.call_type, node1.hostname, item1.get_vpath(),
                plan_task1.state, 'WRONG_DESC', ok_kwarg)

        # Assert correct kwarg (right key, wrong value)
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                plan_task1.call_type, node1.hostname, item1.get_vpath(),
                plan_task1.state, plan_task1.description, 'foo=WRONG')

        # Assert correct kwarg (wrong key, right value)
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                plan_task1.call_type, node1.hostname, item1.get_vpath(),
                plan_task1.state, plan_task1.description, 'WRONG=foo1')

        # Assert wrong phase
        atcli._get_phase = Mock(return_value=[])
        self.assertRaises(AssertionError, atcli.command_assert_task, 0,
                plan_task1.call_type, node1.hostname, item1.get_vpath(),
                plan_task1.state, plan_task1.description, ok_kwarg)

    def setup_assert_task(self):
        self._create_model()
        self.atcli.execution = MagicMock()
        self.atcli.execution.plan_phases.return_value = []

        node1 = self.node1
        item1 = self.item1

        task1 = ConfigTask(node1, item1, 'Desc1', 'foo', 'foo1')
        task2 = ConfigTask(node1, item1, 'Desc1', 'foo', 'foo2')
        task3 = ConfigTask(node1, item1, 'Desc1', 'foo', 'foo3')
        task4 = ConfigTask(node1, item1, 'Desc1', 'foo', 'foo4', name='dummy')

        self.atcli.let_container['task1'] = (
            'ConfigTask', node1.hostname, 'foo', 'foo1', item1.vpath)
        self.atcli.let_container['task2'] = (
            'ConfigTask', node1.hostname, 'foo', 'foo2', item1.vpath)
        self.atcli.let_container['task3'] = (
            'ConfigTask', node1.hostname, 'foo', 'foo3', item1.vpath)
        self.atcli.let_container['task4'] = (
            'ConfigTask', node1.hostname, 'foo', 'foo4', item1.vpath,
            'name=dummy')

        self.atcli.execution.plan_phases = MagicMock(return_value = [[task1, \
                task2, task3, task4]])

    @threadlocal_scope
    def test_command_assert_remote_execution_task(self):
        self.setup_assert_task()
        self.atcli.execution = MagicMock()
        self.atcli.execution.plan_phases.return_value = []

        node = self.node1
        item = self.item1
        task_agent = 'lock_unlock'
        task_action = 'lock_b'

        get_task_args = lambda: [
            item.vpath, node.hostname, task_agent, task_action]

        # no task in phase
        self.assertRaises(
            AssertionError, self.atcli.command_assert_remote_execution_task,
            0, *get_task_args())

        # state is indifferent/incorrect/correct
        task = RemoteExecutionTask([node], item,
                                   '', task_agent, task_action)

        self.atcli.execution.plan_phases = MagicMock(return_value = [[task]])
        self.assertEqual("Pass",
                         self.atcli.command_assert_remote_execution_task(
                             0, *get_task_args()))

        task.state = 'Applied'
        self.assertRaises(AssertionError,
                          lambda: self.atcli.command_assert_remote_execution_task(
                              0, *get_task_args() + ['Initial']))

        task.state = 'Initial'
        self.assertEqual("Pass",
                         self.atcli.command_assert_remote_execution_task(
                             0, *get_task_args()))

        # description is incorrect/correct
        task.description = 'Wrong description'
        self.atcli.command_assert_remote_execution_task(0, *get_task_args())

        self.assertRaises(AssertionError,
                          lambda: self.atcli.command_assert_remote_execution_task(
                              0, *get_task_args() + [task.state, 'Correct description']))

        task.description = 'Correct description'
        self.assertEqual("Pass",
                         self.atcli.command_assert_remote_execution_task(
                             0, *get_task_args()))

    @threadlocal_scope
    def test_command_assert_task_before_task(self):
        self.setup_assert_task()
        # Wrong order
        self.assertRaises(AssertionError, lambda: self.atcli.command_assert_task_before_task('task2', 'task1', 'task3'))
        # Happy path
        self.atcli.command_assert_task_before_task('task1', 'task2', 'task3')
        self.atcli.command_assert_task_before_task('task1', 'task1', 'task2', \
                'task2', 'task3', 'task3')

    @threadlocal_scope
    def test_command_assert_config_task(self):
        self.setup_assert_task()
        node1 = self.node1
        item1 = self.item1
        # Wrong attributes
        self.assertRaises(AssertionError, lambda: \
                self.atcli.command_assert_config_task('dummy-hostname', \
                'foo', 'foo1', item1.vpath))
        self.assertRaises(AssertionError, lambda: \
                self.atcli.command_assert_config_task(node1.hostname, \
                'dummy_call_type', 'foo1', item1.vpath))
        self.assertRaises(AssertionError, lambda: \
                self.atcli.command_assert_config_task(node1.hostname, 'foo', \
                'dummy_call_id', item1.vpath))
        self.assertRaises(AssertionError, lambda: \
                self.atcli.command_assert_config_task(node1.hostname, 'foo', \
                'foo1', '/dummy_path/items/x'))
        self.assertRaises(AssertionError, lambda: \
                self.atcli.command_assert_config_task(node1.hostname, 'foo', \
                'foo1', '/dummy_path/items/x', 'name=dummy'))
        # Unexpected kwargs
        self.assertRaises(AssertionError, lambda: \
                self.atcli.command_assert_config_task(node1.hostname, 'foo', \
                'foo4', item1.vpath, 'name=xx'))
        self.assertRaises(AssertionError, lambda: \
                self.atcli.command_assert_config_task(node1.hostname, 'foo', \
                'foo1', item1.vpath, 'name=dummy'))

        # Happy path
        self.atcli.command_assert_config_task(node1.hostname, 'foo', 'foo3', \
                item1.vpath)
        self.atcli.command_assert_config_task(node1.hostname, 'foo', 'foo1', \
                item1.vpath)
        # Happy path with kwargs
        self.atcli.command_assert_config_task(node1.hostname, 'foo', 'foo4', \
                item1.vpath, 'name=dummy')

    @threadlocal_scope
    def test_command_assert_number_config_tasks(self):
        self.setup_assert_task()

        node1 = self.node1
        self.atcli.command_assert_number_config_tasks(node1.hostname, '4')
        self.assertRaises(AssertionError, lambda: self.atcli.command_assert_number_config_tasks(node1.hostname, '100'))
        self.assertRaises(AssertionError, lambda: self.atcli.command_assert_number_config_tasks(node1.hostname, '0'))

    @patch('litpats.atcli.ATCli.get_item_source')
    @patch('litpats.atcli.ATCli.item_by_path')
    def test_assert_source(self,mock_item_by_path, mock_get_item_source):
        #no item
        mock_item_by_path.return_value = None
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node1/services/parent1',
            '-s',
            '/software/serices/parent1')

        #no source
        mock_get_item_source.return_value = None
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node1/services/parent1',
            '-s',
            '/software/services/parent1')

        #no source
        mock_get_item_source.return_value = None
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node1/services/parent1',
            '-s',
            '/software/services/parent1',
            '--inheritance_layers','0')

        item = Mock()
        mock_item_by_path.return_value = item

        item_source = Mock()
        mock_get_item_source.return_value = item_source
        item_source.vpath = '/software/services/parent1'

        self.assertEqual("Pass", self.atcli.command_assert_source('-p',
            '/deployements/d1/clusters/cluster1/nodes/node1/services/parent1',
            '-s','/software/services/parent1'))

    @patch('litpats.atcli.ATCli.get_item_source')
    @patch('litpats.atcli.ATCli.item_by_path')
    def test_assert_source_has_source(self,mock_item_by_path,
                                      mock_get_item_source):
        # no item
        mock_item_by_path.return_value = None
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node2/services/parent1',
            '-s',
            '/software/services/parent1',
            '--inheritance_layers','2')

        # no source
        mock_get_item_source.return_value = None
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node2/services/parent1',
            '-s',
            '/software/services/parent1',
            '--inheritance_layers', '2')

        item = Mock()
        item_source = Mock()
        item1_source = Mock()

        # fail: second source item does not exist
        mock_item_by_path.side_effect = [item, None]
        item_source.vpath = '/deployments/d1/clusters/cluster1/nodes/node1/' \
            'services/parent1'
        mock_get_item_source.side_effect = [item_source, None]
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node2/services/parent1',
            '-s',
            '/software/services/parent1',
            '--inheritance_layers',
            '2')

        # fail: second source item exists, but does not have source
        mock_item_by_path.side_effect = None
        mock_item_by_path.return_value = item
        item_source.vpath = '/deployments/d1/clusters/cluster1/nodes/node1/' \
            'services/parent1'
        mock_get_item_source.side_effect = [item_source, None]
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node2/services/parent1',
            '-s',
            '/software/services/parent1',
            '--inheritance_layers',
            '2')

        # fail: second source item not equal to specified source
        mock_item_by_path.side_effect = None
        mock_item_by_path.return_value = item
        item_source.vpath = '/deployments/d1/clusters/cluster1/nodes/node1/' \
            'services/parent1'
        item1_source.vpath = '/software/services/parentA'
        mock_get_item_source.side_effect = [item_source, item1_source]
        self.assertRaises(AssertionError, self.atcli.command_assert_source,
            '-p',
            '/deployements/d1/clusters/cluster1/nodes/node2/services/parent1',
            '-s',
            '/software/services/parent1',
            '--inheritance_layers',
            '2')

        # pass: second item exists and has source
        mock_item_by_path.side_effect = None
        mock_item_by_path.return_value = item
        item_source.vpath = '/deployments/d1/clusters/cluster1/nodes/node1/' \
            'services/parent1'
        item1_source.vpath = '/software/services/parent1'
        mock_get_item_source.side_effect = [item_source, item1_source]
        self.assertEqual("Pass", self.atcli.command_assert_source('-p',
            '/deployements/d1/clusters/cluster1/nodes/node2/services/parent1',
            '-s', '/software/services/parent1', '--inheritance_layers', '2'))

    @patch('litpats.atcli.ATCli.get_item_source')
    @patch('litpats.atcli.ATCli.item_by_path')
    def test_get_property(self, mock_item_by_path, mock_get_item_source):

        atcli = ATCli()
        #variable name
        self.assertRaises(AssertionError, self.atcli.command_get_property,
                'test_string', '/item_path', 'property' )

        #parameter number wrong
        self.assertRaises(TypeError, self.atcli.command_get_property, 1, 2)
        self.assertRaises(TypeError, self.atcli.command_get_property, 1, 2, 3,
                4)

        #item not existing
        mock_item_by_path.return_value = None
        mock_get_item_source.return_value = None
        self.assertRaises(AssertionError, atcli.command_get_property, '__test',
            '/I_m_not_here', 'property')

        #happy path
        item = Mock(properties={'some_prop':'value'})
        mock_item_by_path.return_value = item

        self.atcli.command_get_property('__test', '/', 'some_prop')
        self.assertEqual(self.atcli.let_container['__test'], 'value')

        #property not existing
        mock_get_item_source.return_value=None
        self.assertRaises(AssertionError, atcli.command_get_property, '__test',
            '/', 'prop')

        #get property from source item
        source_item = Mock(properties={'source_prop':'value_source'})
        mock_get_item_source.return_value=source_item
        self.atcli.command_get_property('__test', '/', 'source_prop')
        self.assertEqual(self.atcli.let_container['__test'], 'value_source')

    def test_assert_values_equal(self):
        self.atcli = ATCli()
        self.atcli.let_container['__a'] = "1"
        self.atcli.let_container['__b'] = "11"
        self.atcli.let_container['__c'] = "one"

        result = self.atcli.command_assert_values_equal('__a', "1")
        self.assertEqual(result, "Pass")
        result = self.atcli.command_assert_values_equal('__a', "1",'1')
        self.assertEqual(result, "Pass")

        self.assertRaises(AssertionError, self.atcli.command_assert_values_equal,
        '__a')
        self.assertRaises(AssertionError, self.atcli.command_assert_values_equal,
        '__a', '__b', '__c')
        self.assertRaises(AssertionError, self.atcli.command_assert_values_equal,
        '__a', '__b', '100')
        self.assertRaises(AssertionError, self.atcli.command_assert_values_equal,
        '__a', '__b', '__d')
        self.assertRaises(AssertionError, self.atcli.command_assert_values_equal,
        '__a', '__b')

    def test_assert_values_not_equal(self):
        self.atcli = ATCli()
        self.atcli.let_container['__a'] = "1"
        self.atcli.let_container['__b'] = "11"
        self.atcli.let_container['__c'] = "one"

        self.assertRaises(AssertionError,
                self.atcli.command_assert_values_not_equal, '__a', "1")
        self.assertRaises(AssertionError,
                self.atcli.command_assert_values_not_equal, '__a')
        self.assertRaises(AssertionError,
                self.atcli.command_assert_values_not_equal)
        self.assertRaises(AssertionError,
                self.atcli.command_assert_values_not_equal, '__a', "1",'1')

        result = self.atcli.command_assert_values_not_equal('__a', '__b', '__c')
        self.assertEqual(result, "Pass")
        result = self.atcli.command_assert_values_not_equal('__a', '__b', '100')
        self.assertEqual(result, "Pass")
        result = self.atcli.command_assert_values_not_equal('__a', '__b', '__d')
        self.assertEqual(result, "Pass")
        result = self.atcli.command_assert_values_not_equal('__a', '__b')
        self.assertEqual(result, "Pass")

    @patch('litpats.atcli.ATCli.item_by_path')
    def test_assert_property_empty_string(self, mock_item_by_path):
        item = Mock(get_merged_properties=lambda: {'empty_string_allowed':''})
        mock_item_by_path.return_value = item
        atcli = ATCli()
        atcli.model_manager = Mock()

        # Test for source items
        result = atcli.command_assert_property('/source', '-o', 'empty_string_allowed=')
        self.assertEqual(result, "Pass")
        # Not equal empty string
        self.assertRaises(AssertionError, atcli.command_assert_property,
                '/source', '-o', 'empty_string_allowed=foo')
        # Empty string property doesn't exist
        self.assertRaises(AssertionError, atcli.command_assert_property,
                '/source', '-o', 'empty_string_NON_EXIST=')

        # Test for non source items
        atcli.model_manager.get_source = Mock(return_value=None)
        result = atcli.command_assert_property('/ref', '-o', 'empty_string_allowed=')
        self.assertEqual(result, "Pass")
        self.assertRaises(AssertionError, atcli.command_assert_property,
                '/ref', '-o', 'empty_string_allowed=foo')
        # Empty string property doesn't exist
        self.assertRaises(AssertionError, atcli.command_assert_property,
                '/ref', '-o', 'empty_string_NON_EXIST=')

    @patch('litpats.atcli.ATCli.item_by_path')
    def test_assert_property_unset_empty_string(self, mock_item_by_path):
        item = Mock(properties={'empty_string_allowed':''})
        mock_item_by_path.return_value = item
        atcli = ATCli()

        # Property exists with empty string -> Not unset so raise
        self.assertRaises(AssertionError, atcli.command_assert_property_unset,
                '-p', '/item', '-o', 'empty_string_allowed')
        # Property doesn't exist at all -> Its unset so passes
        result = atcli.command_assert_property_unset(
                '-p', '/item', '-o', 'PROPERTY_NOT_THERE')
        self.assertEqual(result, "Pass")
