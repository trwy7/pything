"""Setting declarations for apps."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import state

if TYPE_CHECKING:
    from .app import App


class Setting:
    """
    A setting is a configuration option for an app. Do not call this directly.
    """

    def __init__(
        self, id: str, display_name: str, default: Any, type: str, hidden: bool = False
    ):
        self.id = id
        self.display_name = display_name
        self.default = default
        self.hidden = hidden
        self.type = type
        self.app: App | None = None

    def get_value(self):
        if self.app is None:
            raise ValueError("Setting must be added to an app")
        return state.config[self.app.id][self.id]

    def set_value(self, value: Any, persist: bool = True):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        state.config[self.app.id][self.id] = value
        if persist:
            state.save_config()


class StringSetting(Setting):
    def __init__(self, id: str, display_name: str, default: str, hidden: bool = False):
        super().__init__(id, display_name, default, "string", hidden)


class BooleanSetting(Setting):
    def __init__(self, id: str, display_name: str, default: bool, hidden: bool = False):
        super().__init__(id, display_name, default, "bool", hidden)


class FloatSetting(Setting):
    def __init__(
        self,
        id: str,
        display_name: str,
        default: float,
        hidden: bool = False,
        min_value: float | None = None,
        max_value: float | None = None,
        unit: str | None = None,
    ):
        super().__init__(id, display_name, default, "float", hidden)
        self.min_value = min_value
        self.max_value = max_value
        self.unit = unit


class IntegerSetting(Setting):
    def __init__(
        self,
        id: str,
        display_name: str,
        default: int,
        hidden: bool = False,
        min_value: int | None = None,
        max_value: int | None = None,
        unit: str | None = None,
    ):
        super().__init__(id, display_name, default, "int", hidden)
        self.min_value = min_value
        self.max_value = max_value
        self.unit = unit


class SelectSetting(Setting):
    def __init__(
        self,
        id: str,
        display_name: str,
        default: str,
        options: dict[str, str],
        hidden: bool = False,
    ):
        super().__init__(id, display_name, default, "select", hidden)
        self.options = options


class DataSetting(Setting):
    def __init__(self, id: str, default: Any):
        super().__init__(id, "", default, "data", True)


class ElementSetting:
    def __init__(self, id: str, type: str, hidden: bool = False):
        self.type = type
        self.id = id
        self.hidden = hidden

    def get_value(self):
        raise NotImplementedError(
            "ElementSettings cannot store data, but get_value was called."
        )

    def set_value(self, value: Any):
        raise NotImplementedError(
            "ElementSettings cannot store data, but set_value was called."
        )


class LinkSetting(ElementSetting):
    def __init__(self, id: str, label: str, link: str, hidden: bool = False):
        super().__init__(id, "link", hidden)
        self.label = label
        self.link = link


class LabelSetting(ElementSetting):
    def __init__(self, id: str, label: str, hidden: bool = False):
        super().__init__(id, "label", hidden)
        self.label = label
