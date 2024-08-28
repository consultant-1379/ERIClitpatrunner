import copy
import functools
import cherrypy
from ..mocking import core_patch, _resolve_qual_name
from litpats.mocking.mock_puppetdb_api import MockPuppetDbApi


@core_patch('litp.core.puppetdb_api.urlopen')
def _url_open(original_funcion):
    """Patch urllib.urlopen() used in PuppetDbApi class."""

    mock_api = MockPuppetDbApi()

    def new_func(url):
        # Celery Job has execution_manager instance with a plan,
        # which is aware of its current phase
        execution = cherrypy.config.get("execution_manager")
        mock_api.set_attrs(execution, url)

        endpoint = url.partition('?')[0].partition('/localhost:8080/v3/')[2]
        switch = {
                'reports': mock_api.generate_reports,
                'events': mock_api.generate_events,
                'resources': mock_api.generate_resources,
        }
        return switch.get(endpoint)()

    return new_func


@core_patch('litp.core.plugin_manager._Registry._add')
def _decorate_registry_add(core_add):
    '''
    Mocks the logic used to add a plugin or extension to the relevant
    Registry instance.
    This ensures that the plugin and extension versions serialised by the
    ModelItemContainer are deterministic, which allows the contents of
    ``LAST_KNOWN_CONFIG`` and ``SNAPSHOT_PLAN_*`` files to be compared against
    static files.
    '''
    @functools.wraps(core_add)
    def version_clamp_wrapper(_registry_instance, name, klass, _, cls):
        return core_add(_registry_instance, name, klass, '1.2.3', cls)

    return version_clamp_wrapper


@core_patch('litp.core.puppet_manager_templates.PuppetManagerTemplates.'
        '_format_classdec')
def _decorate_format_classdec(core_format_classdec):
    '''
    Ensures Puppet class descriptions are deterministic by stripping
    ConfigTasks' ``uuid`` attributes.
    '''
    @functools.wraps(core_format_classdec)
    def uuid_strip_wrapper(puppet_mgr_templates_instance, task):
        # Make a copy of the task and strip it of its uuid
        copied_task = copy.copy(task)
        copied_task._id = None

        return core_format_classdec(
            puppet_mgr_templates_instance,
            copied_task
        )

    return uuid_strip_wrapper


@core_patch('litp.core.nextgen.execution_manager.ExecutionManager.'
        '_process_callback_task')
def _decorate_process_callback_task(core_process_callback_task):
    '''
    Ensures CallbackTasks can be selectively failed or unmocked.
    '''
    @functools.wraps(core_process_callback_task)
    def cbtask_handling_selector(exec_mgr_instance, task):
        _, _, task_success = _resolve_qual_name(
            'litp.core.constants.TASK_SUCCESS'
        )
        _, _, task_failed = _resolve_qual_name(
            'litp.core.constants.TASK_FAILED'
        )
        value = exec_mgr_instance._meta.referred_tasks.get(task._id)
        if value == "_disabled_mocked_callback":
            return core_process_callback_task(exec_mgr_instance, task)
        elif value == "_failed":
            task.state = task_failed
            return None, {'error': "failed"}

        task.state = task_success
        exec_mgr_instance._set_task_lock(task)
        return "success", None

    return cbtask_handling_selector


@core_patch('litp.core.nextgen.execution_manager.ExecutionManager.run_plan')
def _decorate_run_plan(core_run_plan):
    '''
    Ensures snapshot-type plans can be selectively failed from an AT by causing
    all CallbackTasks to fail.
    '''

    @functools.wraps(core_run_plan)
    def run_plan_wrapper(exec_mgr_instance, celery_request_id=None):
        if exec_mgr_instance.is_snapshot_plan:
            if exec_mgr_instance._meta.fail_next_snapshot_plan:
                _snapshot_plan_hook(exec_mgr_instance)
                exec_mgr_instance._meta.fail_next_snapshot_plan = False
            elif (exec_mgr_instance
                    ._meta
                    .disable_callbacks_for_next_snapshot_plan):
                _snapshot_plan_callback(exec_mgr_instance)
                del (exec_mgr_instance
                        ._meta
                        .disable_callbacks_for_next_snapshot_plan[:])
        ret = core_run_plan(
            exec_mgr_instance, celery_request_id=celery_request_id)
        return {"success": str(ret)}

    return run_plan_wrapper


def _snapshot_plan_callback(exec_mgr_instance):
    _, _, cbtask_class = _resolve_qual_name('litp.core.task.CallbackTask')
    for method, vpath in \
        exec_mgr_instance._meta.disable_callbacks_for_next_snapshot_plan:
        for task in exec_mgr_instance.plan.get_tasks():
            if isinstance(task, cbtask_class):
                if task.call_type == method and task.item_vpath == vpath:
                    exec_mgr_instance._meta.referred_tasks[task._id] = \
                        "_disabled_mocked_callback"
                    break
        else:
            raise ValueError("Can't find the specified callback task {0} {1}"
                "in plan".format(method, vpath))


def _snapshot_plan_hook(exec_mgr_instance):
    # Set up all callback tasks to fail
    _, _, cbtask_class = _resolve_qual_name('litp.core.task.CallbackTask')
    for task in exec_mgr_instance.plan.get_tasks():
        if isinstance(task, cbtask_class):
            exec_mgr_instance._meta.referred_tasks[task._id] = "_failed"


@core_patch('litp.core.worker.celery_app.configure_worker')
def _decorate_configure_worker(core_configure_worker):
    '''
    Ensures that Celery worker ("task") processes aren't used during the
    execution of plans in ATs.
    '''

    @functools.wraps(core_configure_worker)
    def configure_worker_wrapper(*args, **kwargs):
        _, _, cherrypy_config = _resolve_qual_name('cherrypy.config')
        _, _, scope = _resolve_qual_name('litp.core.scope')
        backup = cherrypy_config.copy()
        cherrypy_config.clear()
        cherrypy_config["_atrunner_backup"] = {
            "cherrypy_config": backup,
            "scope_data_manager": scope.data_manager,
        }
        del scope.data_manager

        core_configure_worker(*args, **kwargs)

        cherrypy_config["execution_manager"]._meta = \
            backup["execution_manager"]._meta

        if hasattr(backup["plugin_manager"], "_added_plugin_paths"):
            for path in backup["plugin_manager"]._added_plugin_paths:
                cherrypy_config["plugin_manager"].add_plugins(path)
            cherrypy_config["plugin_manager"]._added_plugin_paths = \
                backup["plugin_manager"]._added_plugin_paths

        if hasattr(backup["plugin_manager"], "_added_extension_paths"):
            for path in backup["plugin_manager"]._added_extension_paths:
                cherrypy_config["plugin_manager"].add_extensions(path)
            cherrypy_config["plugin_manager"]._added_extension_paths = \
                backup["plugin_manager"]._added_extension_paths

    return configure_worker_wrapper


@core_patch('litp.core.worker.celery_app.deconfigure_worker')
def _decorate_deconfigure_worker(core_deconfigure_worker):
    '''
    Ensures that Celery worker ("task") processes aren't used during the
    execution of plans in ATs.
    '''

    @functools.wraps(core_deconfigure_worker)
    def deconfigure_worker_wrapper(*args, **kwargs):
        _, _, cherrypy_config = _resolve_qual_name('cherrypy.config')

        def mock_dispose():
            pass
        cherrypy_config["db_storage"]._engine.dispose = mock_dispose

        core_deconfigure_worker(*args, **kwargs)

        _, _, scope = _resolve_qual_name('litp.core.scope')
        backup = cherrypy_config["_atrunner_backup"]
        cherrypy_config.clear()
        cherrypy_config.update(backup["cherrypy_config"])
        scope.data_manager = backup["scope_data_manager"]

    return deconfigure_worker_wrapper
