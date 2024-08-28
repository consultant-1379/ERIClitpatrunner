##############################################################################
# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################

from litp.core.plugin import Plugin
from litp.core.execution_manager import ConfigTask


class MockPackagePlugin(Plugin):
    """
    LITP Mock package plugin for testing.
    """

    def create_configuration(self, plugin_api_context):
        """
        Provides support testing using a mock-package-item.

        *An example of package usage:*

        .. code-block:: bash

            litp create -p /software/items/package_vim -t mock-package -o \
            name="vim-enhanced"

            litp link -p /software/profiles/rhel_6_4/items/package_vim -t \
            mock-package -o name="vim-enhanced"

        """
        tasks = []
        nodes = plugin_api_context.query("node") + \
                plugin_api_context.query("ms")
        for node in nodes:
            for package in node.query("mock-package", is_initial=True):
                tasks.append(
                    ConfigTask(node, package, "Description", "package",
                               package.name,
                               **self._get_values(package))
                )
            for package in node.query("mock-package", is_updated=True):
                tasks.append(
                    ConfigTask(node, package, "Update", "package",
                               package.name,
                               **self._get_values(package))
                )
            for package in node.query("mock-package", is_for_removal=True):
                tasks.append(
                    ConfigTask(node, package, "deconfigure", "package",
                               package.name,
                               **self._get_removal_values(package))
                )
        return tasks

    def _get_values(self, item, applied=False):
        # get configuration values from items properties for a task
        values = {}
        ensure = item.ensure
        if ensure:
            values['ensure'] = ensure
        if item.version:
            if item.release:
                if applied:
                    values['ensure'] = '-'.join([item.version,
                                             item.release])
                else:
                    values['ensure'] = '-'.join([
                        item.applied_properties.get("version", None),
                        item.applied_properties.get("release", None)])
            else:
                if applied:
                    values['ensure'] = item.version
                else:
                    values['ensure'] = item.applied_properties.get(
                                                            "version", None)
        repo = item.repository

        permanent_repos = ['OS', 'CUSTOM', 'UPDATES', 'LITP']
        if repo and repo not in permanent_repos:
            values['require'].extend([{'type':
                                    'Yum::Repo', 'value': repo}])
        config = item.config
        if config:
            values['configfiles'] = config
        return values

    def _get_removal_values(self, item, applied=True):
        # get values from items properties for removal task
        values = self._get_values(item, applied)
        values['ensure'] = "absent"
        return values
