import json
import shlex
import os
import stat
import re
import difflib
import sys
import pprint
import tempfile
import shutil
import logging
import StringIO
import argparse
import cherrypy
from contextlib import contextmanager
from collections import OrderedDict
import ConfigParser
from Crypto.Cipher import AES
from base64 import standard_b64encode, standard_b64decode
import socket
from mock import MagicMock

from litpcli.litp import LitpCli, SortedChoicesArgumentParser
from litpats.mock_http_connection import MockHTTPConnection
from litp.core.litpcrypt import pad
from litpats.mockfilesystem import MockFilesystem

from litp.data.db_storage import DbStorage
from litp.data.test_db_engine import get_engine
from litp.core.scope_utils import threadlocal_scope
from litp.core import scope
from litp.service.cherrypy_server import CherrypyServer
from litp.core.nextgen.execution_manager import ExecutionManager
from litp.core.execution_manager import CallbackExecutionException
from litp.core.nextgen.puppet_manager import PuppetManager
from litp.core.nextgen.plugin_manager import PluginManager
from litp.core.nextgen.model_manager import ModelManager
from litp.xml.xml_loader import XmlLoader
from litp.xml.xml_exporter import XmlExporter
from litp.core.task import RemoteExecutionTask
from litp.core.task import ConfigTask
from litp.core.task import CleanupTask
from litp.core.task import CallbackTask
from litp.core.future_property_value import FuturePropertyValue
from litp.core import constants
from litp.core.schemawriter import SchemaWriter
from litp.core.service import update_plugins
from litp.core.worker.celery_app import celery_app
from xml.etree import ElementTree


SECURITY_CONF = """
[keyset]
path: /opt/ericsson/nms/litp/keyset/keyset1
[password]
path: /opt/ericsson/nms/litp/etc/litp_shadow
"""
SECURITY_KEYSET = "j0zP+vqUgnCJQ6W+ErOmv39KF4jmfuHVvOfu0dG5i3w="
ansi_escape = re.compile(r'\x1b[^m]*m')
celery_app.conf.CELERY_ALWAYS_EAGER = True


def print_deprecation_warning(deprecated_callable):
    """Note: AT commands are not deprecated for ERIClitpcore use."""
    def check_core_wrapper(*args, **kwargs):
        pom_path = os.path.join(
                os.path.abspath(__file__).split("target")[0], "pom.xml")
        if os.path.exists(pom_path):
            root = ElementTree.parse(pom_path)
            art_id = root.find('{http://maven.apache.org/POM/4.0.0}artifactId')
            if art_id is not None and art_id.text != "ERIClitpcore":
                print 'Warning: Deprecated command has been used in this AT'
        return deprecated_callable(*args, **kwargs)
    return check_core_wrapper


@contextmanager
def ignored(*exceptions):
    try:
        yield
    except exceptions:
        pass


@contextmanager
def handled_errors(args):
    try:
        yield
    except SystemExit:
        # AT raised error correctly
        pass
    except AssertionError:
        raise
    except Exception:
        raise AssertionError("Unexpected exception for command %s" % (args,))


def _use_colour_output():
    try:
        stdout_is_tty_like = any((
            # STDOUT is an actual TTY as far as Python can tell
            sys.stdout.isatty(),
            # STDOUT has been dup2'd to a pipe
            stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode),
            # We're runnning from the Maven runner
            # XXX Is this redundant with the previous condition?
            os.getenv('RUN_FROM_MAVEN'),
        ))
        return stdout_is_tty_like
    except AttributeError:
        # sys.stdout is a 'Tee' object and it has no isatty attribute.
        return False

_colors = dict(
    green="1;32m",
    red="1;31m",
    yellow="1;33m"
)


def _colored(msg, color):
    if _use_colour_output():
        CSI = "\x1B["
        return CSI + _colors.get(color, "1;32m") + msg + CSI + "0m"
    else:
        return msg


def _green(msg):
    return _colored(msg, "green")


def _red(msg):
    return _colored(msg, "red")


def _print_verbose(cli, msg, print_to_console=False):
    if cli.verbose or print_to_console:
        print msg
    if cli.verbose_to_file:
        cli.verbose_log_file.write("{0}\n".format(ansi_escape.sub('', msg)))


class Mock(object):
    pass


class MockFilesystemContext(object):
    """Context manager to hookup and release AT MockFilesystem."""

    def __init__(self, atcli_instance):
        self.atcli_instance = atcli_instance

    def __enter__(self):
        self.atcli_instance.filesystem.hookup()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.atcli_instance.filesystem.release()


class MetaData(object):
    def __init__(self):
        self.fail_next_snapshot_plan = False
        self.disable_callbacks_for_next_snapshot_plan = []
        self.referred_tasks = {}


class ATCli(LitpCli):
    DEFAULT_ROOT = '/opt/ericsson/nms/litp'

    def __init__(self):
        super(ATCli, self).__init__()
        # Note: AT Docs are reliant on 'commands' variable name. Don't rename!
        self.commands = {
            'clearLandscape': self.create_landscape,
            'clearLogs': self.command_clear_logs,
            'litp': self.command_litp,
            'assertError': self.command_assert_error,
            'assertErrorMessage': self.command_assert_error_message,
            'assertLogMessage': self.command_assert_log_message,
            'assertNoLogMessage': self.command_assert_no_log_message,
            'show': self.command_show,
            'create': self.command_create,
            'assertNone': self.command_assert_none,
            'assertState': self.command_assert_state,
            'assertAppliedPropertiesDeterminable': self.command_assert_apd,
            'assertProperty': self.command_assert_property,
            'getProperty': self.command_get_property,
            'assertPropertyUnset': self.command_assert_property_unset,
            'assertNotOverridden': self.command_assert_property_not_overridden,
            'assertDirectoryContents': self.command_assert_directory_contents,
            'runLitpScript': self.command_run_litp_script,
            'addMockDirectory': self.command_add_mock_directory,
            'assertFileContents': self.command_assert_file_contents,
            'assertPlanState': self.command_assert_plan_state,
            'assertPhaseLength': self.command_assert_phase_length,
            'assertPlanLength': self.command_assert_plan_length,
            'assertNoPlan': self.command_assert_no_plan,
            'assertTask': self.command_assert_task,
            'assertConfigTask': self.command_assert_config_task,
            'assertNoConfigTask': self.command_assert_no_config_task,
            'assertNumberConfigTasks':
                    self.command_assert_number_config_tasks,
            'assertNumberLockTasks':
                    self.command_assert_number_lock_tasks,
            'assertNumberUnlockTasks':
                    self.command_assert_number_unlock_tasks,
            'assertNumberCallbackTasks':
                    self.command_assert_number_callback_tasks,
            'assertCallbackTask': self.command_assert_callback_task,
            'assertNoCallbackTask': self.command_assert_no_callback_task,
            'assertRemoteTask': self.command_assert_remote_task,
            'assertRemoteExecutionTask':
                    self.command_assert_remote_execution_task,
            'assertCleanupTask': self.command_assert_cleanup_task,
            'assertNoCleanupTask': self.command_assert_no_cleanup_task,
            'assertTaskInPlan': self.command_assert_task_in_plan,
            'assertTaskBeforeTask': self.command_assert_task_before_task,
            'assertValuesEqual': self.command_assert_values_equal,
            'assertValuesNotEqual': self.command_assert_values_not_equal,
            'assertSource': self.command_assert_source,
            'failConfigTask': self.command_fail_config_task,
            'unfailConfigTask': self.command_unfail_config_task,
            'failCallbackTask': self.command_fail_callback_task,
            'unfailCallbackTask': self.command_unfail_callback_task,
            'failSnapshotPlan': self.command_fail_snapshot_plan,
            'disableCallbackMock': self.command_disable_callback_mock,
            'disableCallbackMockInNextSnapshotPlan':
                    self.command_disable_callback_mock_in_next_snapshot_plan,
            'methodCall': self.command_method_call,
            'runPlanStart': self.command_run_plan_start,
            'runPlanEnd': self.command_run_plan_end,
            'runPlanUntil': self.command_run_plan_until,
            'stopPlan': self.command_stop_plan,
            'add-plugins': self.command_add_plugins,
            'add-extensions': self.command_add_extensions,
            'debug': self.command_debug,
            'let': self.command_let_var,
            'litpcrypt': self.litp_crypt,
            'loadModel': self.command_load_model,
            'setHostname': self.command_set_hostname,
            'restartLitp': self.command_restart_litp
        }

        self.debug_line = None
        self.update_expected = False
        self.verbose = False
        self.verbose_to_file = False
        self.performance = False
        self.root_path = ATCli.DEFAULT_ROOT
        self.environment = dict()
        self.puppet_manager = None
        self.execution = None
        self.plugin_manager = None
        self.errors = []
        self.result = {}
        self.printout = False
        self.temp_dir = None
        self.extra_extensions = []
        self.let_container = dict()
        self.xsds_generated = False
        self.original_error_handler = SortedChoicesArgumentParser.error
        SortedChoicesArgumentParser.error = self.argparser_error_handler()
        self.meta = MetaData()

    def argparser_error_handler(self):
        def error(argparser_instance, message):
            self.errors.append(
                    ('%s: error: %s\n') % (argparser_instance.prog, message))
            self.original_error_handler(argparser_instance, message)
        return error

    def command_restart_litp(self):
        """
        Provides a mocked version of ``service litpd restart``.

        Example:

        .. code-block:: bash

            # Restart during running plan
            runPlanUntil 1
            restartLitp
        """
        self.execution.fix_plan_at_service_startup()

    def command_set_hostname(self, hostname):
        """
        Sets the local hostname to a specific value.

        Example:

        .. code-block:: bash

            setHostname myms1
        """
        socket.gethostname = MagicMock(return_value=hostname)

    def command_load_model(self, model_filename):
        """
        Loads the specified ``LAST_KNOWN_CONFIG`` model file.

        Example:

        .. code-block:: bash

            loadModel MY_LAST_KNOWN_CONFIG
        """
        serializer = cherrypy.config.get('serializer')
        serializer.restore_from_backup_data(
                       serializer._load_raw_json(
                           self._local(model_filename))
                   )

    def litp_crypt(self, action, key, user, password):
        """
        Mocks the ``litpcrypt`` command using the mocked filesystem
        (at present only the 'set' action is supported).

        Example:

        .. code-block:: bash

            litpcrypt set service user password
        """
        if action.strip() != "set":
            raise NotImplementedError

        def encrypt(data):
            k = standard_b64decode(SECURITY_KEYSET)
            bsize = '0' * AES.block_size
            encryptor = AES.new(k, AES.MODE_CFB, bsize, segment_size=128)
            return standard_b64encode(encryptor.encrypt(pad(data)))

        b64_user = standard_b64encode(user).replace('=', '')
        enc_password = encrypt(password)

        fs = MockFilesystem.get_instance()
        fs.add_file('/etc/litp_security.conf', SECURITY_CONF)
        fs.add_file('/opt/ericsson/nms/litp/keyset/keyset1', SECURITY_KEYSET)
        shadow_file_path = '/opt/ericsson/nms/litp/etc/litp_shadow'
        if not shadow_file_path in fs._files:
            fs.add_file(shadow_file_path, "")

        cp = ConfigParser.SafeConfigParser(dict_type=OrderedDict)
        cp.optionxform = str
        with fs.mock_open(shadow_file_path, 'r') as shadow_file:
            cp.readfp(shadow_file)
        if not cp.has_section(key):
            cp.add_section(key)
        cp.set(key, b64_user, enc_password)
        with fs.mock_open(shadow_file_path, 'wb') as shadow_file:
            cp.write(shadow_file)

    def create_landscape(self):
        '''
        Used internally for creating the landscape where ATs live.
        You can also use it to reset the landscape inside an AT script.

        Example:

        .. code-block:: bash

            clearLandscape
        '''

        self._create_new_model()
        self.create_litp_services()

        self.xsds_generated = False
        self.reconfigure_server()

    def create_litp_services(self):
        model_manager = self.model_manager
        logging_item = model_manager.create_item('logging', '/litp/logging')
        # These 2 lines are meant to emulate the operations performed by the
        # LitpServiceController when /litp/logging is updated
        # pylint: disable=E1103
        logging_item.properties['force_debug'] = 'true'
        model_manager.configuration_logging_level = logging.INFO
        model_manager.set_debug(True)
        model_manager.create_item('restore', '/litp/restore_model')
        model_manager.create_item('prepare-restore', '/litp/prepare-restore')
        if not model_manager.has_item('/litp/maintenance'):
            model_manager.create_item('maintenance', '/litp/maintenance')
        # TODO: remove try block when the code in core_extension is merged
        try:
            if model_manager.get_item('/litp/maintenance').enabled == 'true':
                enabled = True
            else:
                enabled = False
        except Exception:  # pylint: disable=W0703
            enabled = False
        cherrypy.config.update({'maintenance': enabled})

    def reconfigure_server(self):
        cherrypy.config.update({
            'execution_manager': self.execution,
            'puppet_manager': self.puppet_manager,
            'plugin_manager': self.plugin_manager,
            'litp_root': '/opt/ericsson/nms/litp'
        })

        self.server = CherrypyServer()
        self.server.login = True

    def generate_missing_xsds(self):
        if self.xsds_generated:
            return
        self.regenerate_xsds()
        self.xsds_generated = True

    def regenerate_xsds(self):
        self._remove_old_xsds()
        self._generate_xsd_schema()
        xml_loader = self._create_xml_loader()
        xml_exporter = self._create_xml_exporter()
        cherrypy.config.update({
            'xml_loader': xml_loader,
            'xml_exporter': xml_exporter,
        })
        self.reconfigure_server()

    def _remove_old_xsds(self):
        if self.temp_dir:
            try:
                shutil.rmtree(self.temp_dir)
            except:  # pylint: disable=W0702
                pass

    def _create_xml_loader(self):
        schema_path = os.path.join(self.temp_dir, "share", "xsd")
        xsd_file = os.path.join(schema_path, "litp.xsd")
        xml_loader = XmlLoader(self.model_manager, xsd_file)
        return xml_loader

    def _create_xml_exporter(self):
        schema_path = os.path.join(self.temp_dir, "share", "xsd")
        xml_exporter = XmlExporter(self.model_manager)
        return xml_exporter

    def _generate_xsd_schema(self):
        self.temp_dir = tempfile.mkdtemp(prefix="litp_xsds_")
        schema_path = os.path.join(self.temp_dir, "share", "xsd")
        os.makedirs(schema_path)
        basepaths = [os.path.join(self.root_path, "etc/plugins"),
            os.path.join(self.root_path, "etc/extensions")]
        SchemaWriter(schema_path, basepaths + self.extra_extensions).write()

    def _print_out(self, msg):
        if self.printout:
            sys.stdout.write(msg + "\n")

    def _print_err(self, msg):
        if self.verbose:
            super(ATCli, self)._print_err(msg)

    def _create_new_model(self):
        self.plugin_manager = PluginManager(self.model_manager)
        self.plugin_manager.add_extensions(os.path.join(self.root_path,
            "etc/extensions"))
        self.plugin_manager.add_plugins(os.path.join(self.root_path,
            "etc/plugins"))
        update_plugins(scope.data_manager, self.plugin_manager)
        self.plugin_manager.add_default_model()

        self.puppet_manager = PuppetManager(self.model_manager)
        self.execution = ExecutionManager(
            self.model_manager, self.puppet_manager, self.plugin_manager)
        self.execution._meta = self.meta
        self.extra_extensions = []

    def get_user_passwd(self, username, password):
        return "litp-admin", "passw0rd"

    def run_command(self, args):
        if args[0] in set(["load", "export"]):
            self.generate_missing_xsds()

        with MockFilesystemContext(self):
            try:
                return super(ATCli, self).run_command(args)
            except SystemExit:
                converterrors = {u'messages': [{
                    u'message': u'%s' % self.errors,
                        }]}
                self.result = converterrors
                del self.errors[:]
                return -1

    def command_litp(self, *args):
        '''
        Runs a LITP command.

        Example:

        .. code-block:: bash

            litp create -p /deployments/dep1 deployment
            litp create -p /infrastructure/systems/sys1 system
        '''
        all_args = list(args)
        result = self.run_command(all_args)
        if self.errors:
            if self.show_errors:
                raise AssertionError(
                    "Errors in call to (%s): %s" % (
                        args, "\n".join([
                            json.dumps(l1, indent=4)
                            for l1 in self.errors
                        ])))
            else:
                raise AssertionError("Errors in call to (%s): %s" % (
                    args, self.errors))
        if result:
            raise AssertionError("Error in call: %s" % self.result)
        return result

    def _execute_request(self, url, method, data, content_type):
        result, errors = super(ATCli, self)._execute_request(
                                            url, method, data, content_type)
        self.result = {}
        try:
            self.result = json.loads(result.text)
        except:  # pylint: disable=W0702
            self.result = errors
        return result, errors

    def _cb_function(self, *args, **kwargs):
        pass

    def _cb_function_fail(self, *args, **kwargs):
        raise CallbackExecutionException("fail")

    def command_assert_error(self, *args):
        """
        Called in place of a normal LITP command, but validates on the error
        list returned.

        The following parameters can be checked:
            - message
            - error type
            - vpath
            - property
            - total number of error messages returned

        Using optional arguments:
            - ``--err_message``
            - ``--err_type``
            - ``--err_vpath``
            - ``--err_property``
            - ``--errors_length``

        You can check multiple errors using the ``let`` facility.

        Examples:

        .. code-block:: bash

            assertError create_plan

            assertError --err_type ValidationError --err_property hostname \
--errors_length 1 create -p /deployments/dep1/clusters/cluster1/nodes/node2 \
-t node -o hostname=node2

            let __err_test --err_type CardinalityError \
--err_message "Some message"
            assertError __err_test create_plan

            let __err_a --err_type MissingRequiredItemError --err_message \
'ItemType "node" is required to have a "reference" with name "storage_profile"'
            let __err_b --err_type MissingRequiredItemError --err_message \
'ItemType "node" is required to have a "reference" with name "system"'
            let __err_c --err_type CardinalityError
            assertError __err_a __err_b __err_c --err_message \
'collection requires a minimum of 1 items not marked for removal' create_plan

        """
        err_parser = argparse.ArgumentParser()
        err_parser.add_argument("--err_type", dest="type")
        err_parser.add_argument("--err_message", dest="message")
        err_parser.add_argument("--err_vpath", dest="vpath")
        err_parser.add_argument("--err_property", dest="property")

        err_len_parser = argparse.ArgumentParser()
        err_len_parser.add_argument("--errors_length", dest="length")

        pargs = err_parser.parse_known_args(args)
        err_len_pargs = err_len_parser.parse_known_args(pargs[1])

        assert_args = [pargs[0]]
        err_len_args = err_len_pargs[0]

        parse = lambda arg: err_parser.parse_known_args(
                                    self.let_container[arg])[0]
        let_args = [parse(arg) for arg in pargs[1]
                        if arg in self.let_container]
        litp_args = [arg for arg in err_len_pargs[1]
                        if arg not in self.let_container]

        with handled_errors(args):
            result = self.run_command(litp_args)

            assert_errors = []
            for err_args in assert_args + let_args:
                to_validate = self._get_args_to_validate(err_args)
                error = self._find_assert_error(to_validate)
                assert_errors.extend(error)
            assert_errors = '\n'.join(assert_errors)

            if err_len_args.length:
                actual_length = str(len(self._get_errors(self.result)))
                if actual_length != err_len_args.length:
                    len_msg = "Expected number of errors (%s) differs from " \
                        "actual (%s)." % (err_len_args.length, actual_length)
                    raise AssertionError(len_msg)

            if assert_errors or not result:
                msg = "Expected error not found in call"
                if assert_errors:
                    msg += ": %s" % assert_errors
                raise AssertionError(msg)

            return result

    def _get_args_to_validate(self, assert_args):
        to_validate = dict()
        for arg in dir(assert_args):
            if not arg.startswith('_'):
                value = getattr(assert_args, arg)
                if value is not None:
                    to_validate[arg] = value
        return to_validate

    def _is_error_in_result(self, expected_error):
        for err in self._get_errors(self.result):
            checked = []
            for key, expected_value in expected_error.iteritems():
                actual_value = self._get_value_from_error(key, err)
                if key == 'message':
                    checked.append(expected_value in actual_value)
                else:
                    checked.append(expected_value == actual_value)
            if all(checked):
                return True
        return False

    def _find_assert_error(self, expected_error):
        assert_errors = []
        if not self._is_error_in_result(expected_error):
            msg = ['%s: %s' % (k, v) for k, v in expected_error.iteritems()]
            msg = ', '.join(msg)
            msg = 'No error with ' + msg
            assert_errors.append(msg)
        return assert_errors

    def _get_value_from_error(self, key, json_error):
        if key == 'type':
            return json_error.get("type")
        if key == 'vpath' and json_error.get("_links"):
            return json_error.get("_links").get("self").get("href")
        if key == 'property':
            return json_error.get("property_name")
        if key == 'message':
            return json_error.get('message')

    @classmethod
    def _get_errors(self, result):
        errors = {}
        with ignored(KeyError):
            errors = result['messages']
        return errors

    @print_deprecation_warning
    def command_assert_error_message(self, message, *args):
        """
        This command is now deprecated. Use ``assertError`` instead.

        Called in place of a normal LITP command, but asserts that the
        command returns an error with the expected message.

        Example:

        .. code-block:: bash

            assertErrorMessage "Failed somehow" create \
-p /infrastructure/nonexistant/sys1 system
        """
        try:
            result = self.run_command(args)
            for error in self.errors:
                if message in error:
                    return True
            raise AssertionError("Error message not found in response: %s" % (
                self.errors,))
        except AssertionError, ae:
            raise
        except Exception, e:
            raise AssertionError("Unexpected exception for command %s" % (
                args,))

    def command_assert_log_message(self, message):
        """
        Asserts that a log message occurs at least once in the litpd logging
        stream.

        Example:

        .. code-block:: bash

            assertLogMessage "OrderedTaskList \
can only contain tasks for the same node"
        """
        _buffer = self._buffer_logs()
        pos = _buffer.pos
        try:
            _buffer.seek(0)
            for log_message in _buffer.readlines():
                if message in log_message:
                    return True
            raise AssertionError("Error message not found in logs: %s" %
                    message)
        finally:
            _buffer.seek(pos)

    def command_assert_no_log_message(self, message):
        """
        Called to assert that a log message has not occured in the litpd
        logging stream.

        Example:

        .. code-block:: bash

            assertNoLogMessage "OrderedTaskList \
can only contain tasks for the same node"
        """
        _buffer = self._buffer_logs()
        pos = _buffer.pos
        try:
            _buffer.seek(0)
            for log_message in _buffer.readlines():
                if message in log_message:
                    raise AssertionError("Error message found in logs: %s" %
                        message)
            return True
        finally:
            _buffer.seek(pos)

    def command_clear_logs(self):
        """
        Clears the litp logging stream
        """
        _buffer = self._buffer_logs()
        _buffer.seek(0)
        _buffer.truncate()

    def _buffer_logs(self):
        _buffer = None
        for handler in logging.getLogger().handlers:
            if isinstance(handler.stream, StringIO.StringIO):
                _buffer = handler.stream
                return _buffer
        if not _buffer:
            raise RuntimeError("Could not find log _buffer")

    def _format_errors(self, error_list):
        all_errors = []
        for errors in error_list:
            all_errors.extend([s.strip() for s in errors.split('\n')])
        return all_errors

    def command_show(self, *args):
        '''
        Similar to the ``litp`` command, except it prints the
        output from the command.

        Examples:

        .. code-block:: bash

            show show_plan
            show show -p /software/items/finger

        '''
        cherrypy.request.method = 'GET'
        args = list(args)
        try:
            self.printout = True
            result = self.command_litp(*args)
            return result
        finally:
            self.printout = False

    def command_create(self, vpath, *args):
        '''
        Similar to the ``litp`` command, except it prints the
        output from the command.

        Example:

        .. code-block:: bash

            create create -p /ms/configs/alias_config/aliases/master1 \
-t alias -o address="11.11.11.1" alias_names="master1,master2"
        '''
        cherrypy.request.method = 'POST'
        result = self.command_litp(vpath, *args)
        # print simplejson.dumps(result, indent=4)
        print result
        return result

    def _create_https_connection(self, host):
        return self._create_http_connection(host)

    def _create_http_connection(self, host):
        return MockHTTPConnection(host)

    def _configure_storage(self):
        storage = DbStorage(get_engine())
        storage.reset()
        cherrypy.config["db_storage"] = storage

        self.model_manager = ModelManager()
        cherrypy.config["model_manager"] = self.model_manager

    def run(self, command, args):
        args = [self._env(arg) for arg in args]

        self._check_debug()

        if command == "runLitpScript":
            return self.commands[command](*args)

        if command == "clearLandscape":
            self._configure_storage()

        return self._run(command, args)

    @threadlocal_scope
    def _run(self, command, args):
        return self.commands[command](*args)

    def _env(self, line):
        for key, value in self.environment.items():
            line = line.replace("'${%s}'" % key.lower(), value)
            line = line.replace("${%s}" % key.lower(), value)
        return line

    def _check_debug(self):
        if self.debug_line == self.line:
            self.command_debug()

    def command_debug(self):
        '''
        Debugs a running script at this line in the script.
        It is recommended that you use the -d option of the ATRunner instead
        of this command.
        '''
        try:
            import ipdb
            ipdb.set_trace()
        except:  # pylint: disable=W0702
            import pdb
            pdb.set_trace()

    def _find_errors(self, response):
        errors = 0
        if isinstance(response, dict):
            errors = len(response.get('messages', []))
        return errors

    def _first_error(self, response):
        if isinstance(response, dict):
            if response.get('messages'):
                return response['messages'][0]

    def find_item(self, vpath):
        vpath = vpath.rstrip('/')
        parent_path = '/'.join(vpath.split('/')[:-1])
        parent = self.model_manager.get_item(parent_path)
        return parent, vpath.split('/')[-1]

    def item_by_path(self, path):
        return self.model_manager.get_item(path)

    def get_item_source(self, item):
        return self.model_manager.get_source(item)

    def command_assert_apd(self, *args):
        '''
        Asserts whether an item's applied properties are determinable.

        Example:

        .. code-block:: bash

            assertAppliedPropertiesDeterminable \
-p /deployments/dep1/nodes/node1 True \n
            assertAppliedPropertiesDeterminable \
-p /deployments/dep1/nodes/node2 False
        '''
        apd_parser = argparse.ArgumentParser()
        apd_parser.add_argument('-p', dest='path', nargs=1)
        apd_parser.add_argument('expected_apd', nargs=1)
        apd_args = apd_parser.parse_args(args)

        if not apd_args.path:
            raise AssertionError("Item path specification mandatory")

        vpath = apd_args.path[0]
        expected = apd_args.expected_apd[0]
        if not expected.lower() in ('true', 'false'):
            raise AssertionError("Invalid expected Applied Properties "
                    "Determinable state: %s" % expected)
        item = self.item_by_path(vpath)
        if not item:
            raise AssertionError("No such item: %s" % (vpath,))

        apd = str(item.applied_properties_determinable)
        if apd.lower() != expected.lower():
            raise AssertionError("%s: expected %s but was %s" %
                                 (vpath, expected, apd))
        return "Pass"

    def command_assert_state(self, *args):
        '''
        Asserts the state of the item.

        Example:

        .. code-block:: bash

            assertState -p /deployments/dep1/nodes/node1 Applied
        '''
        if len(args) != 3:
            raise AssertionError('Only 3 arguments are expected')
        vpath, expected = args[1:]
        item = self.item_by_path(vpath)
        if not item:
            raise AssertionError("No such item: %s" % (vpath,))
        state = item.get_state()
        if hasattr(item, expected) and callable(getattr(item, expected)):
            if not getattr(item, expected)():
                raise AssertionError("%s: expected %s but wasn't" %
                                     (vpath, expected))
        elif expected != state:
            raise AssertionError("%s: expected %s but was %s" %
                                 (vpath, expected, state))
        return "Pass"

    def command_assert_plan_state(self, *args):
        '''
        Asserts the state of the current plan.

        Example:

        .. code-block:: bash

            assertPlanState initial
        '''
        if len(args) != 1:
            raise AssertionError('Only 1 argument is expected')

        expected = args[0]
        state = self.execution.plan_state()

        if expected != state:
            raise AssertionError(
                'expected %s got %s' % (expected, state)
               )

        return 'Pass'

    def command_assert_values_not_equal(self, *args):
        '''
        Asserts whether at least two out of the given variable values
        are not equal.

        Example:

        .. code-block:: bash

            assertValuesNotEqual __hash __hash2 __hash3
            assertValuesNotEqual __hash 123
        '''

        if len(args) < 2:
            raise AssertionError("At least two parameters are expected")
        values = set()
        for val in args:
            if val in self.let_container:
                values.add(self.let_container[val])
            else:
                values.add(val)

        if len(values) == 1:
            raise  AssertionError("Values %s are equal" %
                                 (values))
        return "Pass"

    def command_assert_values_equal(self, *args):
        '''
        Asserts whether all given variables values are equal.

        Example:

        .. code-block:: bash

            assertValuesEqual __hash __hash2 __hash3
            assertValuesEqual __hash 123
        '''

        if len(args) < 2:
            raise AssertionError("At least two parameters are expected")

        values = set()
        for val in args:
            if val in self.let_container:
                values.add(self.let_container[val])
            else:
                values.add(val)

        if len(values) != 1:
            raise  AssertionError("Values %s are not equal" %
                                 (values))
        return "Pass"

    def command_assert_source(self, *args):
        '''
        Asserts whether a model item has a source item.
        You can use option ``--inheritance_layers`` to check that the target
        item inherits from the source item through the expected number of
        inheritance layers.

        Example:

        .. code-block:: bash

            assertSource -p /deployments/d1/clusters/cluster1/nodes/\
    node1/services/parent1 -s /software/services/parent1

            assertSource -p /deployments/d1/clusters/cluster1/nodes/\
    node2/services/parent1 -s /software/services/parent1 --inheritance_layers 2
        '''

        arg_parser = argparse.ArgumentParser()
        arg_parser.add_argument("-p", dest="vpath", type=str, required=True)
        arg_parser.add_argument("-s", dest="source", type=str, required=True)
        arg_parser.add_argument("--inheritance_layers",
                                dest="inheritance_layers",
                                type=int)

        pargs = arg_parser.parse_known_args(args)
        assert_args = pargs[0]

        src_vpath = assert_args.vpath

        if assert_args.inheritance_layers:

            inheritance_layers = assert_args.inheritance_layers

            while inheritance_layers > 0:

                item = self.item_by_path(src_vpath)

                if item:
                    src_item = self.get_item_source(item)

                    if src_item and inheritance_layers > 0:
                        src_vpath = src_item.vpath
                        inheritance_layers -= 1
                    else:
                        raise AssertionError("%s has as no source item %s "
                                             "(inheritance_layers=%s)"
                                             % (assert_args.vpath,
                                                assert_args.source,
                                                assert_args.inheritance_layers)
                                             )
                else:
                    raise AssertionError("No item at %s" % src_vpath)

            if src_vpath != assert_args.source:
                raise AssertionError("%s has no source item %s "
                                     "(inheritance_layers=%s)" %
                                     (assert_args.vpath,
                                      assert_args.source,
                                      assert_args.inheritance_layers))
        else:
            while src_vpath != assert_args.source:

                item = self.item_by_path(src_vpath)

                if item:
                    src_item = self.get_item_source(item)

                    if src_item:
                        src_vpath = src_item.vpath
                    else:
                        raise AssertionError("%s has no source item %s"
                                             % (assert_args.vpath,
                                                assert_args.source))
                else:
                    raise AssertionError("No item at %s" % src_vpath)

        return "Pass"

    def command_get_property(self, var_name, vpath, propertyname):
        '''
        Writes the value of a property into a variable.

        Example:

        .. code-block:: bash

            getProperty __var1 \
    /deployments/local_vm/clusters/cluster1/nodes/node1/network_interfaces/\
    ip1 paddress
        '''
        if not var_name.startswith('__'):
            raise AssertionError(
                    "Variable names must start with double underscore '__'")

        item = self.item_by_path(vpath)
        if not item:
            raise AssertionError("No such item: %s" % (vpath,))
        propertyvalue = item.properties.get(propertyname)
        item_source = self.get_item_source(item)
        if propertyvalue is None and item_source:
            propertyvalue = item_source.properties.get(propertyname)

        if propertyvalue is None:
            raise AssertionError("No such property for item %s: %s" % (vpath,
                propertyname))

        self.let_container[var_name] = propertyvalue

    def command_assert_property(self, vpath, *args):
        '''
        Asserts that a property exists in a model item and has a specific
        value.

        Example:

        .. code-block:: bash

            assertProperty \
/deployments/local_vm/clusters/cluster1/nodes/node1/network_interfaces/ip1 \
-o ipaddress="10.46.86.98"
        '''
        option_index = args.index('-o')
        if option_index == -1 or not args[option_index + 1:]:
            raise AssertionError("No properties specified with -o option")

        properties = {}
        for raw_props in args[option_index + 1:]:
            if '=' in raw_props and not raw_props.startswith('-'):
                prop_name, prop_value = raw_props.split('=', 1)
                properties[prop_name] = prop_value
            else:
                break

        item = self.item_by_path(vpath)
        if not item:
            raise AssertionError("No such item: %s" % (vpath,))
        for prop, expected in properties.iteritems():
            propertyvalue = item.get_merged_properties().get(prop)
            if expected != propertyvalue:
                raise AssertionError("%s: expected %s but was %s" % (vpath,
                    expected, propertyvalue))

        return "Pass"

    def command_assert_property_unset(self, *args):
        '''
        Asserts that a property value for an item is unset (None).

        Example:

        .. code-block:: bash

            assertPropertyUnset -p /software/profiles/redhat1 -o arch
        '''
        option_index = args.index('-o')
        if option_index == -1 or not args[option_index + 1:]:
            raise AssertionError("No properties specified with -o option")

        properties = args[option_index + 1:]
        vpath = args[1]
        item = self.item_by_path(vpath)
        if not item:
            raise AssertionError("No such item: %s" % (vpath,))
        for property_name in properties:
            propertyvalue = item.properties.get(property_name)
            if propertyvalue is not None:
                raise AssertionError("%s: expected unset but was %s" % (vpath,
                propertyvalue))
        return "Pass"

    def command_assert_property_not_overridden(self, *args):
        '''
        Asserts that a property value for a reference is not overridden.

        Example:

        .. code-block:: bash

            assertNotOverridden -p \
/deployments/local/clusters/cluster1/nodes/node1/os -o arch
        '''
        option_index = args.index('-o')
        if option_index == -1 or not args[option_index + 1:]:
            raise AssertionError("No properties specified with -o option")

        properties = args[option_index + 1:]
        vpath = args[1]
        item = self.item_by_path(vpath)
        if not item:
            raise AssertionError("No such item: %s" % (vpath,))
        item_source = self.model_manager.get_source(item)
        if not item_source:
            raise AssertionError("Item %s is not a reference" % (vpath,))

        for property_name in properties:
            propertyvalue = item.properties.get(property_name)

            if propertyvalue:
                raise AssertionError("%s: property %s is overridden from "\
                        "source item %s" % (
                            vpath,
                            property_name,
                            item_source.get_vpath()
                        )
                    )
        return "Pass"

    def command_assert_directory_contents(self, expected, actual):
        '''
        Asserts the content of a directory tree. A local directory
        is used for comparison.

        Example:

        .. code-block:: bash

            assertDirectoryContents expected/ /tmp/puppet_manifests/
        '''
        if self.update_expected:
            self._copy_actual_to_expected(actual, expected)
        else:
            for filename in self.filesystem._files.keys():
                if filename.startswith(actual):
                    expected_filename = os.path.join(self._local(expected),
                                                     filename[len(actual):])
                    self.command_assert_file_contents(expected_filename,
                                                      filename)

            expected = self._local(expected)
            for root, dirs, files in os.walk(expected):
                actual_dir = os.path.join(
                    actual, root[len(expected):].lstrip('/'))
                for filename in files:
                    self.command_assert_file_contents(
                        os.path.join(
                            root, filename), os.path.join(actual_dir, filename)
                    )
        return "Pass"

    def command_assert_none(self, *args):
        '''
        Asserts the given item does not exist.

        Example:

        .. code-block:: bash

            assertNone -p /software/profiles/ubuntu
        '''
        vpath = args[-1]
        item = self.item_by_path(vpath)
        if item:
            raise AssertionError("Expected None but was %s: %s" % (item,
                vpath,))
        return "Pass"

    def command_run_litp_script(self, script_file):
        '''
        Runs another LITP script. You can use this command to include the
        setup from another script.

        Example:

        .. code-block:: bash

            runLitpScript setup_deployment.at
        '''
        cli = ATCli()
        cli.root = self.root_path
        cli.model_manager = self.model_manager
        cli.execution = self.execution
        cli.test_dir = os.path.dirname(self._local(script_file))
        cli.filesystem = self.filesystem
        cli.verbose_to_file = self.verbose_to_file
        if cli.verbose_to_file:
            cli.verbose_log_file = self.verbose_log_file
        cli.verbose = self.verbose
        cli.show_errors = self.show_errors
        cli.server = self.server
        cli.environment = self.environment.copy()
        script = self._read_file(script_file).split("\n")
        cli.line = 0
        cli.meta = self.meta
        previous_line = ''
        for line in script:
            if line.endswith("\\"):
                previous_line += line.split("\\")[0]
                cli.line += 1
                continue
            if previous_line:
                line = previous_line + line
                previous_line = ''
            cli.line += 1
            line = line.split("#")[0]
            if line.startswith('../'):
                line = 'runLitpScript ' + line
            args = shlex.split(line)
            if args:
                command = args.pop(0)
                if command in self.commands:
                    if cli.run(command, args) == "Pass":
                        _print_verbose(cli, "{0:4}: {1} {2} {3}".format(cli.
                            line, _green("Pass"), command, " ".join(args)),
                            False)
                    else:
                        _print_verbose(cli, "{0:4}: {1} {2}".format(cli.line,
                            command, " ".join(args)), False)

    def _read_file(self, filename):
        if self.filesystem.mock_exists(filename):
            return self.filesystem.mock_open(filename).read().strip()
        elif os.path.exists(self._local(filename)):
            return open(self._local(filename)).read().strip()
        elif os.path.exists(self._include_file(filename)):
            return open(self._include_file(filename)).read().strip()
        else:
            raise Exception("No such file %s" % (filename,))

    def _local(self, filename):
        return os.path.join(self.test_dir, filename)

    def _include_file(self, filename):
        """Map filename to filepath using include path.

        For now, include path is just "/var/litp/atrunner" or equivalent.
        (When building repos that depend on this one, the equivalent will
        be "./target/deps/var/litp/atrunner".)"""

        prog = sys.argv[0]

        BIN = '/usr/bin/runats'

        root = '/'
        if prog != BIN and prog.endswith(BIN):
            root = prog[:-(len(BIN))]
        elif prog.endswith("/ERIClitpatrunner/bin/runats"):
            root = prog[:-len("/bin/runats")]
        return os.path.join(root, 'var/litp/atrunner', filename)

    def command_add_mock_directory(self, link_dir, relative_dir,
                                   overlay="True"):
        '''
        Adds the given local directory to the mock file system.
        If your plugin requires certain files to be installed
        or included to run, use this to add them.

        By default, real files are listed along with the mocked ones. Set the
        optional ``overlay`` flag to False if you want to filter out real files
        from the mocked directory.

        Example:

        .. code-block:: bash

            addMockDirectory /opt/ericsson/nms/litp/random random/
            addMockDirectory /opt/ericsson/nms/litp/random random/ False
        '''
        self.filesystem.add_directory(link_dir, self._local(relative_dir),
                overlay=self._bool_value(overlay))

    def _bool_value(self, string_value):
        if string_value in ('True', 'true'):
            return True
        if string_value in ('False', 'false'):
            return False
        raise ValueError('Boolean value must be one of "True", "true", '
                         '"False" or "false".')

    def command_assert_file_contents(self, expected, actual):
        '''
        Asserts the contents of the given file. A local file is used
        for comparison.

        Example:

        .. code-block:: bash

            assertFileContents expected.xml /tmp/output_from_litp.xml
        '''
        expected_contents = self._read_file(expected)
        actual_contents = self.filesystem.mock_open(actual).read().strip()
        if expected_contents != actual_contents:
            if self.update_expected:
                self._save_file(expected, actual_contents)
                print "Updated expected file %s" % (expected,)
            else:
                diff = difflib.unified_diff(expected_contents.split('\n'),
                    actual_contents.split('\n'), expected, actual)
                diff_str = "\n".join([line for line in diff])
                raise AssertionError("Files differ...:\n%s"
                    % (diff_str,))
        return "Pass"

    @print_deprecation_warning
    def command_assert_phase_length(self, phase_index, task_count):
        '''
        This command is now deprecated for use outside of ERIClitpcore. Use
        assertConfigTask, assertCallbackTask or assertRemoteTask instead.
        '''
        phase_index = int(phase_index)
        task_count = int(task_count)
        phase = self._get_phase(phase_index)
        phase_length = len(phase)
        if task_count != phase_length:
            msg = "Phase {0} length ({1}) is different than expected ({2})"
            raise AssertionError(
                    msg.format(phase_index, phase_length, task_count))
        return "Pass"

    @print_deprecation_warning
    def command_assert_plan_length(self, phase_count):
        '''
        This command is now deprecated for use outside of ERIClitpcore. Use
        assertConfigTask, assertCallbackTask or assertRemoteTask instead.
        '''
        phase_count = int(phase_count)
        plan = self.execution.plan_phases()
        plan_length = len(plan)
        if plan_length != phase_count:
            template = "Plan length ({0}) is different than expected ({1})"
            raise AssertionError(template.format(plan_length, phase_count))
        return "Pass"

    def command_assert_no_plan(self):
        '''
        Asserts that no plan exists.
        '''
        if self.execution.plan_has_tasks():
            raise AssertionError("Expected no plan, found a plan")
        return 'Pass'

    def _get_phase(self, phase_index):
        plan = self.execution.plan_phases()
        if phase_index >= len(plan):
            raise AssertionError("No such phase %s in plan" % (phase_index,))
        return plan[phase_index]

    def _find_config_task_loose(self, hostname, call_type, call_id, vpath,
            *arglist):
        return self._find_config_task(hostname, call_type, call_id, vpath,
                False, *arglist)

    def _find_config_task_strict(self, hostname, call_type, call_id, vpath,
            *arglist):
        return self._find_config_task(hostname, call_type, call_id, vpath,
                True, *arglist)

    def _find_config_task(self, hostname, call_type, call_id, vpath,
            strict, *arglist):
        if strict:
            _kwargs_search_method = self._task_has_kwargs_strict
        else:
            _kwargs_search_method = self._task_has_kwargs
        for p, phase in enumerate(self.execution.plan_phases()):
            for t, task in enumerate(phase):
                if type(task) is ConfigTask and \
                        task.call_type == call_type and \
                        task.call_id == call_id and \
                        vpath == task._model_item_vpath and \
                        self._check_hostname(task, hostname) and \
                        _kwargs_search_method(task, arglist):
                    return (task, p, t)

    def _get_number_config_tasks(self, hostname):
        number_of_config_tasks = 0
        for phase in self.execution.plan_phases():
            for task in phase:
                if type(task) is ConfigTask and self._check_hostname(
                        task, hostname):
                    number_of_config_tasks += 1
        return number_of_config_tasks

    def _get_number_callback_tasks(self):
        number_of_callback_tasks = 0
        for phase in self.execution.plan_phases():
            for task in phase:
                if type(task) is CallbackTask:
                    number_of_callback_tasks += 1
        return number_of_callback_tasks

    def _get_lock_unlock_tasks(self, hostname):
        lock_tasks = 0
        unlock_tasks = 0
        for phase in self.execution.plan_phases():
            for task in phase:
                if (not isinstance(task.model_item, basestring) and
                    getattr(task.model_item, 'hostname', '') == hostname):
                    if task.lock_type == task.TYPE_LOCK:
                        lock_tasks += 1
                    if task.lock_type == task.TYPE_UNLOCK:
                        unlock_tasks += 1
        return lock_tasks, unlock_tasks

    def _find_callback_task(self, call_method, vpath,
            *arglist):
        for p, phase in enumerate(self.execution.plan_phases()):
            for t, task in enumerate(phase):
                if type(task) is CallbackTask and \
                        task.call_type == call_method and \
                        vpath == task._model_item_vpath and \
                        self._task_has_pargs(task, arglist) and \
                        self._task_has_kwargs(task, arglist):
                    return (task, p, t)

    def _find_remote_execution_task(self,
            item_vpath, node_hostname, agent, action):
        for p, phase in enumerate(self.execution.plan_phases()):
            for t, task in enumerate(phase):
                if type(task) is RemoteExecutionTask and \
                        item_vpath == task._model_item_vpath and \
                        any(node.hostname == node_hostname
                                for node in task.nodes) and \
                        agent == task.agent and \
                        action == task.action:
                    return (task, p, t)

    def _find_remote_execution_task_in_phase(
            self, phase, item_vpath, node_hostname, agent, action):
        for task in phase:
            if (
                type(task) is RemoteExecutionTask and
                item_vpath == task._model_item_vpath and
                any(node.hostname == node_hostname for node in task.nodes) and
                agent == task.agent and
                action == task.action
            ):
                return task

    def _assert_task_index(self, task, phase, index):
        found_index = phase.index(task)
        if found_index != index:
            raise AssertionError("Task %s at wrong index (%s != %s)" % (
                task, found_index, index))

    def _assert_task_state(self, task, state):
        if state and state != task.state:
            raise AssertionError("Task %s state incorrect: %s != %s" %
                                 (task, task.state, state))

    def command_assert_task(self, phase_index, call_type, node_hostname,
            item_vpath, state=None, description="", *kwargs):
        '''
        Asserts that a task with the given call_type and vpath exists
        in the given phase of the current plan.

        Example:

        .. code-block:: bash

            assertTask 1 nfs::configure /infrastructure/shares/nfs
        '''

        phase_index = int(phase_index)
        phase = self._get_phase(phase_index)

        for task in phase:
            if (
                task.call_type == call_type and
                item_vpath == task._model_item_vpath and
                self._check_hostname(task, node_hostname) and
                self._check_task_kwargs(task, kwargs) and
                (task.description == description if description else True)
            ):
                self._assert_task_state(task, state)
                return "Pass"
        raise AssertionError("No such task in phase %s: %s %s" % (phase,
            call_type, item_vpath))

    def command_assert_config_task(self, hostname, call_type, call_id, vpath,
            *arglist):
        '''
        Asserts that a config task exists, given the node hostname with the
        call_id, call_type, the vpath of the item and any optional
        arguments.

        Example:

        .. code-block:: bash

            assertConfigTask node1 hosts::hostentry master1 \
/deployments/local_vm/clusters/cluster1/configs/alias_config/aliases/master1 \
ip=11.11.11.1
            assertConfigTask node1 hosts::hostentry master1 /ms dict.a.b.c=5  \
 # would verify c in a dictionary like \
 dict = {a : {b : {c : 5, d : 7} } }

        '''
        if self._find_config_task_strict(
                hostname, call_type, call_id, vpath, *arglist):
            return "Pass"

        msg = "No such ConfigTask in plan %s %s %s %s %s; " % (
            hostname, call_type, call_id, vpath, arglist)
        close_match = None
        result = self._find_config_task_loose(
                hostname, call_type, call_id, vpath, *arglist)
        if result:
            task = result[0]
            properties = self._format_properties(task.kwargs.items())
            close_match = "%s %s %s %s %s" % (
                    hostname, call_type, call_id, vpath, properties)
        msg += "\nClosest match: %s" % close_match
        raise AssertionError(msg)

    def command_assert_number_config_tasks(self, hostname, expected_number):
        '''
        Asserts that the number of config tasks for a node hostname in a plan
        is equal to the supplied integer.

        Example:

        .. code-block:: bash

            assertNumberConfigTasks node1 3
        '''
        number_config_tasks = self._get_number_config_tasks(hostname)
        if number_config_tasks == int(expected_number):
            return "Pass"

        msg = ("In the plan, there are %s ConfigTasks on node %s, not %s." % (
            number_config_tasks, hostname, expected_number))
        raise AssertionError(msg)

    def command_assert_number_lock_tasks(self, hostname, expected_number):
        '''
        Asserts that the number of lock tasks for a node hostname in a plan
        is equal to the supplied integer.

        Example:

        .. code-block:: bash

            assertNumberLockTasks node1 3
        '''
        lock_tasks, unlock_tasks = self._get_lock_unlock_tasks(hostname)
        if lock_tasks == int(expected_number):
            return "Pass"

        msg = ("In the plan, there are %s Lock tasks on node %s, not %s." % (
            lock_tasks, hostname, expected_number))
        raise AssertionError(msg)

    def command_assert_number_unlock_tasks(self, hostname, expected_number):
        '''
        Asserts that the number of unlock tasks for a node hostname in a plan
        is equal to the supplied integer.

        Example:

        .. code-block:: bash

            assertNumberUnlockTasks node1 3
        '''
        lock_tasks, unlock_tasks = self._get_lock_unlock_tasks(hostname)
        if unlock_tasks == int(expected_number):
            return "Pass"

        msg = ("In the plan, there are %s Unlock tasks on node %s, not %s." % (
            unlock_tasks, hostname, expected_number))
        raise AssertionError(msg)

    def command_assert_number_callback_tasks(self, expected_number):
        '''
        Asserts that the number of callback tasks for a node hostname in a plan
        is equal to the supplied integer.

        Example:

        .. code-block:: bash

            assertNumberCallbackTasks 3
        '''
        number_callback_tasks = self._get_number_callback_tasks()
        if number_callback_tasks == int(expected_number):
            return "Pass"

        msg = ("In the plan, there are %s CallbackTasks, not %s."
            % (number_callback_tasks, expected_number))
        raise AssertionError(msg)

    def _format_properties(self, properties):
        ''' It's just a helper function that is meant to format the task.kwargs
        the way a user can copy it and paste directly into AT test. Since
        assertConfigTask requires all properties to be passed it's become
        difficult and tedious if properties happen to be complex data
        structures containing hashes, jsonified dictionaries and new line
        characters. All of these have to be escaped.

        '''
        jsonified = lambda value: json.dumps(value).strip('"\'')
        escaped = lambda value: value.replace(r'#', r'\#')
        formatted = lambda key, value: "{0}='{1}'".format(
                key, escaped(jsonified(value)))
        return _colored(
            ' '.join([formatted(key, value) for (key, value) in properties]),
            'yellow')

    def command_assert_no_config_task(self,
            hostname, call_type, call_id, vpath, *arglist):
        '''
        Asserts that no config task exists. You can use it, for example, if a
        plugin does not add a task under certain circumstances.

        Example:

        .. code-block:: bash

            assertNoConfigTask node1 hosts::hostentry master1 \
/deployments/local_vm/clusters/cluster1/configs/alias_config/aliases/master1 \
ip=11.11.11.1
        '''
        if self._find_config_task_strict(hostname, call_type, call_id, vpath,
                *arglist):
            raise AssertionError("ConfigTask found in plan %s %s %s %s"
                                    % (hostname, call_type, call_id, vpath))
        return "Pass"

    def command_assert_callback_task(self, call_method, vpath,
            *arglist):
        '''
        Asserts that a callback task exists, given the plugin method,
        with the vpath of the item and any optional arguments.

        Example:

        .. code-block:: bash

            assertCallbackTask create_dir \
/deployments/local_vm/clusters/cluster1/nodes/node1 dirpath=/mnt/somedir
            assertCallbackTask _cb /ms dict.a.b.c=5  # would verify c in a \
dictionary like dict = {a : {b : {c : 5, d : 7} } }

        '''
        if self._find_callback_task(call_method, vpath, *arglist):
            return "Pass"
        raise AssertionError("No such CallbackTask in plan %s %s" % (
            call_method, vpath))

    def command_assert_no_callback_task(self, call_method, vpath,
            *arglist):
        '''
        Asserts that a callback task does not exist given the plugin method,
        with the vpath of the item and any optional arguments.

        Example:

        .. code-block:: bash

            assertCallbackTask create_dir \
/deployments/local_vm/clusters/cluster1/nodes/node1 dirpath=/mnt/somedir
        '''
        if self._find_callback_task(call_method, vpath, *arglist):
            raise AssertionError("CallbackTask exists in plan %s %s" % (
                call_method, vpath))
        return "Pass"

    def command_assert_remote_task(self, action, vpath,
            *arglist):
        '''
        Asserts that a remote task exists,  given the action, with the
        vpath of the item and any optional arguments.

        Example:

        .. code-block:: bash

            assertRemoteTask ping \
/deployments/local_vm/clusters/cluster1/nodes/node1
        '''
        for phase in self.execution.plan_phases():
            for task in phase:
                if type(task) is RemoteExecutionTask and \
                        task.action == action and \
                        vpath == task._model_item_vpath and \
                        self._task_has_kwargs(task, arglist):
                    return "Pass"
        raise AssertionError("No such RemoteExecutionTask in plan %s %s" % (
            action, vpath))

    def _check_hostname(self, task, hostname):
        if type(task) is ConfigTask:
            return hostname == task.node.hostname
        else:
            return True

    def command_assert_remote_execution_task(self,
            phase_index, item_vpath, node_hostname, agent, action, state=None,
            description=None):
        """
        Asserts that a RemoteExecutionTask with the given arguments exists
        in the given phase of the current plan.

        Example:

        .. code-block:: bash

            assertRemoteExecutionTask 0 \
/software/items/vim node1 service restart Initial 'Description goes here'
        """
        phase_index = int(phase_index)
        phase = self._get_phase(phase_index)

        task = self._find_remote_execution_task_in_phase(
                phase, item_vpath, node_hostname, agent, action)
        if task is None:
            raise AssertionError("No such task in phase %s: (%s %s %s %s)" %
                            (phase, item_vpath, node_hostname, agent, action))

        self._assert_task_state(task, state)
        if description is not None:
            if description != task.description:
                raise AssertionError(
                    "No such task with description %s" % description)
        return "Pass"

    def command_assert_cleanup_task(self, phase_index, item_vpath, state):
        '''
        Asserts that a cleanup task exists in the current plan for the item at
        the specified vpath and that its state is as expected.

        Example:

        .. code-block:: bash

            litp create_plan
            assertCleanupTask 0 /infrastructure/systems/system3 Initial
            litp run_plan
            assertCleanupTask 0 /infrastructure/systems/system3 Success
        '''
        phase_index = int(phase_index)
        phase = self._get_phase(phase_index)
        for task in phase:
            if (isinstance(task, CleanupTask) and
                    item_vpath == task._model_item_vpath):
                self._assert_task_state(task, state)
                return "Pass"
        raise AssertionError("No such cleanup task in phase %s: %s " % (
            phase, item_vpath))

    def command_assert_no_cleanup_task(self, item_vpath):
        '''
        Asserts that a cleanup task with the given item path does not
        exist in the cleanup phase of the current plan.

        Example:

        .. code-block:: bash

            assertNoCleanupTask /deployments/local_vm/clusters/cluster1/
            nodes/node1
        '''
        plan = self.execution.plan_phases()
        phase = self._get_phase(len(plan) - 1)
        for task in phase:
            if (isinstance(task, CleanupTask) and
                    item_vpath == task._model_item_vpath):
                raise AssertionError("Cleanup task for %s present in plan" %\
                        (item_vpath))
        return "Pass"

    def command_assert_task_in_plan(self, call_type, item_vpath):
        '''
        Asserts that a task with the given call_type and vpath exists
        in the current plan.

        Example:

        .. code-block:: bash

            assertTaskInPlan nfs::configure /infrastructure/shares/nfs
        '''
        for phase in self.execution.plan_phases():
            for task in phase:
                if task.call_type == call_type and \
                    item_vpath == task._model_item_vpath:
                    return "Pass"
        raise AssertionError("No such task in plan: %s %s" % (call_type,
            item_vpath))

    def command_let_var(self, var_name, *args):
        '''
        Enables creation of script-variables that can be used as arguments to
        other AT commands. Variables must start with a double underscore
        ``__``.

        Example:

        .. code-block:: bash

            let __task1 ConfigTask node1 hosts::hostentry master1 \
/deployments/d1/clusters/c1/configs/alias_config/aliases/master1 ip=11.11.11.1
            let __task2 CallbackTask create_dir \
/deployments/d1/clusters/c1/nodes/node1 dirpath=/mnt/somedir
            assertTaskBeforeTask __task1 __task2
        '''
        if not var_name.startswith('__'):
            raise AssertionError(
                    "Variable names must start with double underscore '__'")
        self.let_container[var_name] = args

    def command_assert_task_before_task(self, *arg_tasks):
        '''
        Asserts that a task1 with the given call_type and vpath exists in the
        current plan before another task2.
        It requires that you load tasks using the ``let`` command.

        Example:

        .. code-block:: bash

            let __task1 ConfigTask node1 hosts::hostentry master1 \
/deployments/d1/clusters/c1/configs/alias_config/aliases/master1 ip=11.11.11.1
            let __task2 CallbackTask create_dir \
/deployments/d1/clusters/c1/nodes/node1 dirpath=/mnt/somedir
            assertTaskBeforeTask __task1 __task2
        '''
        # Check that at least two tasks are in place and all tasks are
        # found in the plan.
        let_tasks = [self.let_container.get(t) for t in arg_tasks]
        if len(let_tasks) < 2:
            raise ValueError(
                "At least two tasks need to be passed as arguments")
        if None in let_tasks:
            raise ValueError(
                "One or more tasks passed as arguments could not be found")

        tasks = [self._get_let_task(task) for task in let_tasks]

        # Check that the tasks are in order, Ignore the last task in list.
        for i, task in enumerate(tasks[:-1]):

            f_task_obj, f_phase, f_sub_phase = task
            l_task_obj, l_phase, l_sub_phase = tasks[i + 1]

            if ((f_phase > l_phase) or
                    (f_phase == l_phase and f_sub_phase > l_sub_phase)):
                raise AssertionError(
                    'The task: "%s" with phase "%s" and sub_phase "%s" is '
                    'located in the plan after the task: "%s" with phase: '
                    '"%s" and sub_phase: "%s"' % (
                        f_task_obj, f_phase, f_sub_phase,
                        l_task_obj, l_phase, l_sub_phase))

    def _get_let_task(self, let_task):
        """
        Get the task from the plan that match the corresponding arguments
        given in the `let_task`.
        """
        TASK_TYPES = {
            'ConfigTask': self._find_config_task_loose,
            'CallbackTask': self._find_callback_task,
            'RemoteExecutionTask': self._find_remote_execution_task,
        }

        task_type, task_args = let_task[0], let_task[1:]
        try:
            _method = TASK_TYPES[task_type]
        except IndexError:
            raise IndexError(
                "Tasks type not recognized, please use one of: "
                "|".join(TASK_TYPES.keys()))

        # Remaining task arguments are used to locate the specific task
        # in the plan.
        task = _method(*task_args)
        if task is None:
            raise ValueError(
                "Task with args '%s' could not be found in the plan" %
                ", ".join(task_args))
        return task

    def add_non_mocked_callback_task(self, task):
        if not isinstance(task, CallbackTask):
            raise TypeError(
                    "Disabling mocking only available for CallbackTask")
        self._save_task_for_reference(task, "_disabled_mocked_callback")

    def add_failed_task(self, task):
        self._save_task_for_reference(task, "_failed")

    def remove_failed_task(self, task):
        self._save_task_for_reference(task, "_not_failed")

    def _save_task_for_reference(self, task, coll_attr):
        referred_tasks = self.meta.referred_tasks

        value = referred_tasks.get(task._id)
        if value is not None and coll_attr == "_not_failed":
            del referred_tasks[task._id]

        elif (
            value is not None and coll_attr in set([
                "_disabled_mocked_callback", "_failed"
            ])
        ):
            if len(set([value, coll_attr])) > 1:
                raise ValueError(
                    "disableCallbackMock and failCallbackTask cannot "
                    "be used simultaneously on same task")
        referred_tasks[task._id] = coll_attr

    def find_config_task_in_plan(self, call_type, node_hostname, item_vpath):
        for phase in self.execution.plan.phases:
            for task in phase:
                if not isinstance(task, ConfigTask):
                    continue
                if (
                    task.call_type == call_type and
                    task.get_node().hostname == node_hostname and
                    task.item_vpath == item_vpath
                ):
                    return task

    def command_fail_config_task(self, call_type, node_hostname, item_vpath):
        '''
        Fails a ConfigTask during the next plan run.

        Example:

        .. code-block:: bash

            failConfigTask package node1 \
/deployments/d1/clusters/c1/nodes/node1/package
        '''
        task = self.find_config_task_in_plan(
            call_type, node_hostname, item_vpath)
        if task is None:
            raise ValueError(
                "Can't find the specified ConfigTask in the plan")
        self.add_failed_task(task)

    def command_unfail_config_task(self, call_type, node_hostname, item_vpath):
        '''
        Lets a ConfigTask previously set to fail using the ``failConfigTask``
        command be successful when the plan is resumed.

        Example:

        .. code-block:: bash

            unfailConfigTask package node1 \
/deployments/d1/clusters/c1/nodes/node1/package
        '''
        task = self.find_config_task_in_plan(
            call_type, node_hostname, item_vpath)
        if task is None:
            raise ValueError(
                "Can't find the specified ConfigTask in the plan")
        self.remove_failed_task(task)

    def command_unfail_callback_task(self, method_name, item_vpath):
        '''
        Lets a CallbackTask previously set to fail using the
        ``failCallbackTask`` command be successful when the plan is resumed.

        Example:

        .. code-block:: bash

            unfailCallbackTask cb__write_snippet \
/ms/services/cobbler/ms/services/cobbler
        '''
        task = self.find_callback_task_in_plan(method_name, item_vpath)
        if task is None:
            raise ValueError(
                "Can't find the specified CallbackTask in the plan")
        self.remove_failed_task(task)

    def find_callback_task_in_plan(self, method_name, item_vpath):
        for phase in self.execution.plan.phases:
            for task in phase:
                if not isinstance(task, CallbackTask):
                    continue
                if (
                    task.call_type == method_name and
                    task.item_vpath == item_vpath
                ):
                    return task

    def command_disable_callback_mock(self, method_name, item_vpath):
        '''
        Enables execution of a callback defined for a CallbackTask.

        Example:

        .. code-block:: bash

            disableCallbackMock cb__write_snippet \
/ms/services/cobbler/ms/services/cobbler
        '''
        task = self.find_callback_task_in_plan(method_name, item_vpath)
        if task is None:
            raise ValueError(
                "can't find the specified CallbackTask in the plan")
        self.add_non_mocked_callback_task(task)

    def command_disable_callback_mock_in_next_snapshot_plan(self, method_name,
            item_vpath):
        """
        Enables execution of a callback defined for a CallbackTask for snapshot
        plans only (i.e. when the plan does not yet exist), for deployment
        plans use disableCallbackMock

        Example:

        .. code-block:: bash

            disableCallbackMockInNextPlan cb__write_snippet \
/ms/services/cobbler/ms/services/cobbler
             litp create_snapshot

        """
        self.execution._meta.disable_callbacks_for_next_snapshot_plan.append(
            (method_name, item_vpath))

    def command_fail_callback_task(self, method_name, item_vpath):
        '''
        Fails a CallbackTask during the next plan run.

        Example:

        .. code-block:: bash

            failCallbackTask cb__write_snippet \
/ms/services/cobbler/ms/services/cobbler
        '''
        task = self.find_callback_task_in_plan(method_name, item_vpath)

        if task is None:
            raise ValueError(
                "can't find the specified CallbackTask in the plan")
        self.add_failed_task(task)

    def command_fail_snapshot_plan(self):
        '''
        Causes the next snapshot plan to fail.

        Example:

        .. code-block:: bash

            failSnapshotPlan
        '''
        # The snapshot plan does *NOT* exist yet, so we'll have to add an
        # attribute to the execution manager itself
        self.execution._meta.fail_next_snapshot_plan = True

    def command_method_call(self, item_path, method):
        '''
        Executes a method in an specified model item.

        Example:

        .. code-block:: bash

            methodCall /deployments/d1/clusters/cluster1/nodes is_for_removal
            methodCall /deployments/d1/clusters/cluster1/nodes set_for_removal
            methodCall /deployments/d1/clusters/cluster1/nodes is_for_removal
        '''
        print "Executing method %s.%s" % (item_path, method)
        pp = pprint.PrettyPrinter(indent=4)
        if item_path == "/execution":
            pp.pprint(getattr(self.execution, method)())
        else:
            item = self.model_manager.get_item(item_path)
            pp.pprint(getattr(item, method)())

    def _check_task_kwargs(self, task, args):
        # TODO: Do we need this method? There's _task_has_kwargs.
        kwargs = [arg.split('=') for arg in args]
        for key, value in kwargs:
            if key not in task.kwargs:
                raise AssertionError("Task %s has no field %s" % (task, key))
            if value != task.kwargs[key]:
                raise AssertionError("Task %s field incorrect %s != %s" % (
                    key, value, task.kwargs[key]))
        return True

    def _unify_kwargs(self, assert_args, task):
        def eval_value(val):
            if isinstance(val, FuturePropertyValue):
                return val.value
            elif isinstance(val, list):
                return [eval_value(i) for i in val]
            elif isinstance(val, dict):
                return dict((k, eval_value(v)) for (k, v) in val.iteritems())
            return val

        unescape = lambda val: val.replace(r'\n', '\n').replace(r'\#', r'#')
        kwargs = [arg.split('=', 1) for arg in assert_args if '=' in arg]
        kwargs = [(key, self._safe_read_json(unescape(val)))
                for (key, val) in kwargs]
        kwargs = dict(kwargs)
        task_kwargs = [(key, eval_value(self._safe_read_json(val)))
                for (key, val) in task.kwargs.items()]
        task_kwargs = dict(task_kwargs)
        return kwargs, task_kwargs

    def _unify_pargs(self, assert_args, task):
        def eval_value(val):
            if isinstance(val, FuturePropertyValue):
                return val.value
            elif isinstance(val, list):
                return [eval_value(i) for i in val]
            elif isinstance(val, dict):
                return dict((k, eval_value(v)) for (k, v) in val.iteritems())
            return val

        unescape = lambda val: val.replace(r'\n', '\n').replace(r'\#', r'#')
        pargs = [arg for arg in assert_args if '=' not in arg]
        pargs = tuple([
            self._safe_read_json(unescape(parg)) for parg in pargs
        ])

        task_pargs = tuple([
            eval_value(self._safe_read_json(arg)) for arg in task.args
        ])
        return pargs, task_pargs

    def _task_has_pargs(self, task, args):
        # This applies only to callback tasks
        args, task_args = self._unify_pargs(args, task)
        # Not all assertions provide the expected positional arguments. In that
        # case, we don't want to fail the assertion
        if not args:
            return True
        return args == task_args

    def _task_has_kwargs(self, task, args):
        kwargs, task_kwargs = self._unify_kwargs(args, task)
        for key in kwargs:
            if key not in task_kwargs:
                if "." in key:
                    try:
                        key_path = key.split(".")
                        value = reduce(dict.__getitem__, key_path[1:],
                                task_kwargs[key_path[0]])
                        task_kwargs[key] = value
                    except ValueError:
                        return False
                else:
                    return False
            if kwargs[key] != task_kwargs[key]:
                return False
        return True

    def _task_has_kwargs_strict(self, task, args):
        ''' Verify if task has exactly the same kwargs as passed in - both
        value-wise and length-wise.

        '''
        kwargs, task_kwargs = self._unify_kwargs(args, task)
        if kwargs == task_kwargs:
            return True
        return False

    def _safe_read_json(self, msg):
        try:
            return json.loads(msg)
        except:  # pylint: disable=W0702
            return msg

    def _copy_actual_to_expected(self, actual, expected):
        for filename in self.filesystem._files.keys():
            if filename.startswith(actual):
                expected_filename = os.path.join(
                    expected, filename[len(actual):]
                )
                self._save_file(
                    expected_filename,
                    self.filesystem.mock_open(filename).read()
                )
                print "Updated expected file %s" % (expected_filename,)

    def _run_plan_until(self, phase_index):
        if self.execution.plan.is_initial():
            self.execution.plan.run()
            self.execution.data_manager.commit()
        for i in range(phase_index):
            if self.execution._is_phase_complete(i):
                if any(task.state == constants.TASK_FAILED
                       for task in self.execution.plan.get_phase(i)):
                    return {
                        "error": "can't continue plan, phase %s failed" %
                        (i + 1)
                    }
            if not self.execution._is_phase_complete(i):
                result = self.execution._run_plan_phase(i)
                if result:
                    return result

    def command_run_plan_start(self):
        '''
        Starts running the plan and enables control of its execution using ATs.

        Example:

        .. code-block:: bash

            litp create_plan
            assertPlanState initial
            runPlanStart
            assertPlanState running
            runPlanUntil 1
            litp stop_plan
            assertPlanState stopping
            runPlanEnd
            assertPlanState successful
        '''
        self.execution.plan.run()

    def command_run_plan_end(self):
        '''
        Runs the current plan until the end.

        Example:

        .. code-block:: bash

            runPlanStart
            runPlanEnd
            assertPlanState successful
        '''
        with MockFilesystemContext(self):
            num_phases = len(self.execution.plan_phases())
            result = self._run_plan_until(num_phases)
            if result:
                self.execution._run_plan_complete(False)
                return result

            self.execution._run_plan_complete(True)
            self.execution._backup_model_for_restore()
            return self.execution._run_plan_success()

    def command_stop_plan(self):
        '''
        Triggers a manual stop of the current plan.

        Example:

        .. code-block:: bash

            runPlanStart
            stopPlan
            assertPlanState failed
        '''
        return self.execution.stop_plan()

    def command_run_plan_until(self, phase_index):
        '''
        Runs the current plan up to the given phase index.

        Example:

        .. code-block:: bash

            runPlanUntil 2
        '''
        with MockFilesystemContext(self):
            return self._run_plan_until(int(phase_index))

    def command_add_plugins(self, plugin_conf_dir):
        '''
        Installs plugins listed in dir.
        For full example, check: \
                ERIClitpcore \
/ats/model/safe_remove/do_not_validate_for_removal_item.at
        '''
        conf_dir = self._local(plugin_conf_dir)
        sys.path.append(conf_dir)
        self.plugin_manager.add_plugins(conf_dir)
        update_plugins(scope.data_manager, self.plugin_manager)
        if not hasattr(self.plugin_manager, "_added_plugin_paths"):
            self.plugin_manager._added_plugin_paths = []
        self.plugin_manager._added_plugin_paths.append(conf_dir)

    def command_add_extensions(self, ext_conf_dir):
        '''
        Installs extensions listed in dir.
        For a full example, check: \
                ERIClitpcore \
/ats/model/safe_remove/do_not_validate_for_removal_item.at
        '''
        conf_dir = self._local(ext_conf_dir)
        sys.path.append(conf_dir)
        self.plugin_manager.add_extensions(conf_dir)
        update_plugins(scope.data_manager, self.plugin_manager)
        self.extra_extensions.append(conf_dir)
        self.regenerate_xsds()
        if not hasattr(self.plugin_manager, "_added_extension_paths"):
            self.plugin_manager._added_extension_paths = []
        self.plugin_manager._added_extension_paths.append(conf_dir)

    def _load_file(self, filepath):
        if self.filesystem.mock_exists(self.args.file):
            return self.filesystem.mock_open(self.args.file).read()
        else:
            return open(self._local(self.args.file)).read()

    def _save_file(self, filename, contents):
        dirname = os.path.dirname(self._local(filename))
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname)
        savefile = open(self._local(filename), "w")
        savefile.write(contents)
        savefile.close()
