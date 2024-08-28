from litp.core.plugin import Plugin
from litp.core.task import ConfigTask
from litp.core.task import CallbackTask
from litp.core.task import RemoteExecutionTask
from litp.core.task import OrderedTaskList


class MultipleTasksPlugin(Plugin):
    def __init__(self, *args, **kwargs):
        super(MultipleTasksPlugin, self).__init__(*args, **kwargs)

    def _do_nothing(self, callback_api, *args, **kwargs):
        pass

    def create_configuration(self, api):
        return self.create_configuration_1(api)

    def create_configuration_1(self, api):
        tasks = []
        for node in sorted(api.query("node")):
            for task_qi in node.query("multiple"):
                if task_qi.is_initial() or task_qi.is_updated():
                    node_tasks = []
                    node_tasks.append(
                        ConfigTask(node, task_qi, "ConfigTask", "resource_type", "task_id")
                    )
                    node_tasks.append(
                        CallbackTask(task_qi, "CallbackTask", self._do_nothing)
                    )

                    tasks.append(OrderedTaskList(task_qi, node_tasks))
        return tasks
