import mock
import json
import urlparse

from ..mocking import _resolve_qual_name
from collections import defaultdict


class MockPuppetDbApi(object):
    """Generate mock response to PuppetDb API calls"""

    def __init__(self):
        self.resource_task_dict = defaultdict(list)  # Set when urlopen patched
        self.response = mock.Mock()
        self.execution = None
        self.url = None

    def set_attrs(self, execution, url):
        """Set execution_ manager and url attributes of mock PuppetDbApi.

        Set execution manager at this point, when the mock urlopen() is
        called, as celery job will have its own instance of execution manager.
        """
        self.execution = execution
        self.url = url

    @property
    def puppet_phase(self):
        return self.execution.plan.phases[self.execution.plan.current_phase]

    @property
    def puppet_manager(self):
        return self.execution.puppet_manager

    def get_tasks_to_fail(self):
        _, _, config_task_class = _resolve_qual_name(
            'litp.core.task.ConfigTask')

        tasks_to_fail = set()
        unique_ids = {}
        for task in self.puppet_phase:
            unique_ids[(task.node.hostname, task.unique_id)] = task
            if self.execution._meta.referred_tasks.get(task._id) == "_failed":
                tasks_to_fail.add(task._id)

        indirect_failures = set()
        for task in self.puppet_phase:
            if task._id in tasks_to_fail:
                continue

            # Does this task depend on any of the tasks set up to fail?
            for dep_unique_id in task._requires:
                try:
                    dep_task = unique_ids[(task.node.hostname, dep_unique_id)]
                    if dep_task._id in tasks_to_fail:
                        indirect_failures.add(task._id)
                except KeyError:
                    continue

        tasks_to_fail |= indirect_failures
        return tasks_to_fail

    @staticmethod
    def get_resource_dict(task):
        return {
            u'certname': task.get_node().hostname.lower(),
            u'exported': False,
            u'file': u'/opt/puppet/manifests/plugins/ms1.pp',
            u'line': 531,
            u'parameters': {u'ensure': u'installed',
                         u'require': [],
                         u'tag': u'tuuid_99bf6bea-6477-471a-1f67dab1622c'},
            u'resource': u'855b71e01851f010bca72f85e397730dee3c322a',
            u'tags': [u'node',
                   u'telnet',
                   u'package',
                   u'ms1',
                   u'tuuid_{0}'.format(task.uuid),
                   u'task_{0}'.format(task.unique_id),
                   u'class'],
            u'title': task.call_id,
            u'type': task.call_type.capitalize()
        }

    def generate_reports(self):
        # Reset known resources for each new phase
        self.resource_task_dict.clear()
        reports = []
        for certname in self.puppet_manager._processing_nodes:
            reports.append({
                "end-time": "2016-09-12T07:52:43.243Z",
                "certname": certname.lower(),
                "hash": "df29434b04bf39810c7ec5396ff7b3101978368c",
                "report-format": 4,
                "start-time": "2016-09-12T07:52:16.991Z",
                "puppet-version": "3.3.2",
                "configuration-version":
                    unicode(self.puppet_manager.phase_config_version),
                "transaction-uuid": "56448938-76d2-449b-f59068dbfe7e",
                "receive-time": "2016-09-12T07:52:58.031Z"
            })
        self.response.read.return_value = json.dumps(reports)
        return self.response

    def generate_events(self):
        # Build set of tasks to fail from AT
        tasks_to_fail = self.get_tasks_to_fail()

        # 2. Build report events
        events = []
        for task in self.puppet_phase:
            state = u"fail" if task._id in tasks_to_fail else u"success"
            events.append({
                  u'certname': task.get_node().hostname.lower(),
                  u'configuration-version':
                      unicode(self.puppet_manager.phase_config_version),
                  u'containing-class': u'Task_ms1__package__telnet',
                  u'containment-path': [u'Stage[main]',
                                        u'Task_ms1__package__telnet',
                                        u'Package[telnet]'],
                  u'file': u'/opt/puppet/manifests/plugins/ms1.pp',
                  u'line': 531,
                  u'message': u'removed',
                  u'new-value': u'absent',
                  u'old-value': u'0.17-48.el6',
                  u'property': u'ensure',
                  # 'report' value matches 'hash' of reports endpoint
                  u'report': u'df29434b04bf39810c7ec5396ff7b3101978368c',
                  u'report-receive-time': u'2016-08-22T10:14:48.143Z',
                  u'resource-title': task.call_id,
                  u'resource-type': task.call_type.capitalize(),
                  u'run-end-time': u'2016-08-22T10:14:12.500Z',
                  u'run-start-time': u'2016-08-22T10:13:23.669Z',
                  u'status': state,
                  u'timestamp': u'2016-08-22T10:14:00.383Z'
            })
            unique_key = (
                task.call_id,
                task.call_type.capitalize(),
                task.get_node().hostname.lower()
            )
            self.resource_task_dict[unique_key].append(task)
        self.response.read.return_value = json.dumps(events)
        return self.response

    def generate_resources(self):
        # 3. Build event resources
        # Decode query url and extract resource title, type and certname
        parsed = urlparse.parse_qs(self.url)
        params = json.loads(
            parsed['http://localhost:8080/v3/resources?query'][0])
        # Query report resources
        if len(params) == 4:
            unique_key = (
                params[1][2],  # task.call_id / resource title
                params[2][2],  # task.call_type / resource type
                params[3][2]   # certname
            )
            # take the first task to represent its resource
            task = self.resource_task_dict[unique_key][0]
            resource = [self.get_resource_dict(task)]
            self.response.read.return_value = json.dumps(resource)
        else:
            # 4. Build all node resources, return known resources here
            node_resources = []
            for task_list in self.resource_task_dict.itervalues():
                # choose 1st task to represent resource
                task = task_list[0]
                node_resources.append(self.get_resource_dict(task))
            self.response.read.return_value = json.dumps(node_resources)
        return self.response
