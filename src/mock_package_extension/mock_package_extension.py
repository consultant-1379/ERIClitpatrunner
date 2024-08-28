##############################################################################
# COPYRIGHT Ericsson AB 2013
#
# The copyright to the computer program(s) herein is the property of
# Ericsson AB. The programs may be used and/or copied only with written
# permission from Ericsson AB. or in accordance with the terms and
# conditions stipulated in the agreement/contract under which the
# program(s) have been supplied.
##############################################################################


from litp.core.extension import ModelExtension
from litp.core.model_type import ItemType
from litp.core.model_type import Property
from litp.core.model_type import Collection


class MockPackageExtension(ModelExtension):
    """
    LITP Mock package extension for testing.
    """

    def define_item_types(self):
        return [
            ItemType(
                "mock-package-list",
                item_description=("This item type represents a collection "
                                "of software packages to install."),
                extend_item="software-item",
                packages=Collection("mock-package"),
                name=Property(
                    "basic_string",
                    prop_description="Name of package collection",
                ),
                version=Property(
                    "basic_string",
                    prop_description="Version of package collection",
                )
            ),
            ItemType(
                "mock-package",
                         extend_item="software-item",
                         item_description=("This item type represents "
                                        "a software package to install."),
                         name=Property("basic_string",
                                        prop_description="Package name to "
                                                         "install/remove.",
                                       required=True,
                                       ),
                         version=Property("any_string",
                                           prop_description="Package version "
                                                       "to install/remove.",
                                           ),
                         release=Property("any_string",
                                          prop_description="Package release "
                                                         "to install/remove.",
                                            ),
                         arch=Property("any_string",
                                       prop_description="Package arch to "
                                                        "install/remove.",
                                        ),
                         ensure=Property("any_string",
                                    prop_description="Constraint for package "
                                                     "enforcement.",
                                    default="installed",
                                   ),
                         config=Property("any_string",
                                    prop_description="Constraint for "
                                                 "configuration retention.",
                                    ),
                         repository=Property("any_string",
                                    prop_description="Name of repository "
                                                         "to get Package.",
                                    ),
                         not_updatable=Property("any_string",
                                    prop_description="Updatable rest = False",
                                    updatable_rest=False
                                    ),
                    )
                ]
