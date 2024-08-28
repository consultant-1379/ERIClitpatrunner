from litp.core.extension import ModelExtension
from litp.core.model_type import ItemType
from litp.core.model_type import Property


class MultipleTasksExtension(ModelExtension):
    def define_item_types(self):
        return [
            ItemType(
                "multiple",
#                extend_item="software-item",
#                count=Property("positive_integer")
            ),
        ]
