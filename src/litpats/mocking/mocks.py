from contextlib import contextmanager
from ..mocking import core_mock, _resolve_qual_name


@core_mock('litp.service.dispatcher.wrap_handler')
def _mock_wrap_handler(func):
    '''
    Bypasses setup of a new thread-local scopes with new database session for
    each cherrypy controller.
    '''
    return func


@core_mock('litp.core.worker.celery_app.init_metrics')
def _mock_init_metrics():
    '''
    Bypasses reinit of metrics collection during eager celery task
    execution during execution of plans in ATs.
    '''
    pass


@core_mock('litp.core.mixins.SnapshotExecutionMixin.'
        '_update_ss_timestamp_successful')
def _mock_snap_timestamp_success(execution_manager):
    '''
    Ensures that the successful execution of a mocked snapshot plan causes
    the ``timestamp`` property of the relevant snapshot item to be updated to a
    deterministic value.
    '''
    execution_manager._update_ss_timestamp('123')


def _mock_mco_output_selector(action, nodes):
    result = {}
    if action == "create":
        for node in nodes:
            result[node] = {
                'data': {
                    'out': "",
                    'status': 0,
                    'err': ''
                },
                'errors': ''
            }
            return result
    elif action == 'lvs':
        for node in nodes:
            result[node] = {
                'data': {
                    'out': "'/dev/vg_root/lv_root' 24.10g owi-aos-- /",
                    'status': 0,
                    'err': ''
                },
                'errors': ''
            }
            return result
    elif action == 'lsblk':
        for node in nodes:
            result[node] = {
                'data': {
                    'out': "FSTYPE=ext4",
                    'status': 0,
                    'err': ''
                },
                'errors': ''
            }
            return result
    else:
        return []


@core_mock('litp.core.rpc_commands.run_rpc_command')
def mock_rpc_command(*args, **kwargs):
    '''
    Mocks the MCollective RPC operations performed by core so that they
    immediately return a deterministic dictionary of results.
    '''
    nodes, _, action = args[:3]
    return _mock_mco_output_selector(action, nodes)


@core_mock('litp.core.plugin_context_api.PluginApiContext.rpc_command')
def mock_plugin_api_rpc_command(*args, **kwargs):
    '''
    Mocks the MCollective RPC operations performed by plugins so that they
    immediately return a deterministic dictionary of results.
    '''
    _, nodes, _, action = args[:4]
    return _mock_mco_output_selector(action, nodes)


@core_mock('litp.service.utils.get_litp_packages')
def _mock_get_litp_packages(*args, **kwargs):
    '''
    Ensures we do not actually collect RPM data on the system running the AT
    when a HAL context is generated for the deployment model root item.
    '''
    return []


@core_mock('litp.core.rpc_commands.PuppetMcoProcessor.run_puppet')
def _mock_run_puppet(*args, **kwargs):
    '''
    Mocks all Puppet-related MCollective actions performed through the
    PuppetMcoProcessor so that they return immediately.
    '''
    return None


@core_mock(
    'litp.core.nextgen.puppet_manager.PuppetManager._check_puppet_status'
)
def _mock_check_puppet_status(*args, **kwargs):
    '''
    Mocks the logic used to determine when the Puppet agent is fully inactive
    on the managed nodes and management server so that it returns immediately.
    '''
    return None


@core_mock(
    'litp.core.nextgen.puppet_manager.PuppetManager._stop_puppet_applying'
)
def _mock_stop_puppet_applying(*args, **kwargs):
    '''
    Mocks the logic used in _stop_puppet_applying so that
    it returns immediately.
    '''
    return None


@core_mock(
    'litp.core.nextgen.puppet_manager.PuppetManager._clear_puppet_cache'
)
def _mock_clear_puppet_cache(*args, **kwargs):
    '''
    Mocks the logic used in _clear_puppet_cache so that
    it returns immediately.
    '''
    return None


@core_mock(
    'litp.core.nextgen.execution_manager.ExecutionManager._is_node_reachable'
)
def _mock_check_node_reachable(*args, **kwargs):
    '''
    Mocks the logic used in _check_node_reachable so that
    it always returns True.
    '''
    return True


@core_mock('litp.core.validators.DirectoryExistValidator.validate')
def _mock_dir_exists(*args, **kwargs):
    '''
    Mocks DirectoryExistValidator so that it never fails to find a directory.
    '''
    return None


@core_mock('socket.gethostname')
def _hardcoded_ms_hostname():
    '''
    Ensures that attempts to resolve the management server's hostname
    return a static value and not the name of the system executing ATs.
    Note: You can override the value returned by this mock using the
    ``setHostname`` command.
    '''
    return "ms1"


@core_mock('litp.core.base_plugin_api._SecurityApi._create_keyset')
def _mock_create_keyset(*args, **kwargs):
    '''
    Ensures a new keyset is not created by SecurityApi in ATs.
    '''
    pass


@core_mock('litp.core.worker.celery_app.engine_context')
@contextmanager
def engine_context():
    '''
    Ensures existing engine is reused during AT runs, to ensure use of
    same throwaway in-memory database instance.
    '''
    _, _, cherrypy_config = _resolve_qual_name('cherrypy.config')
    yield cherrypy_config["db_storage"]._engine


@core_mock('litp.core.plan.BasePlan._dump_phase_graph')
def _dump_phase_graph(*args, **kwargs):
    '''
    Ensures a Graphviz dot file isn't created when LITP is in debug mode.
    '''
    pass
