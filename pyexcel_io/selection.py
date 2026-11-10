"""
pyexcel_io.selection
~~~~~~~~~~~~~~~~~~~~

Per-operation plugin selection context.

A selection context is an immutable, operation local description of which
reader or writer plugins are eligible.  It never mutates the process level
plugin registry maintained by lml, so two concurrent operations may use
contradicting priorities without interfering with each other.

:copyright: (c) 2014-2026 by C Wang
:license: New BSD License, see LICENSE for more details
"""

import importlib

from pyexcel_io import exceptions
from pyexcel_io.plugins import NEW_READERS, NEW_WRITERS

READ_ACTION = "read"
WRITE_ACTION = "write"

DEFAULT_PRIORITY = 0


def plugin_name(plugin_info):
    """Return the distribution style name of a plugin info object."""
    if plugin_info.absolute_import_path:
        name = plugin_info.absolute_import_path.split(".")[0]
    else:
        name = plugin_info.cls.__module__.split(".")[0]
    return name.replace("_", "-")


class PluginSelectionContext:
    """Selection rules for a single read or write operation.

    :param action: ``"read"`` or ``"write"``.
    :param file_type: file format, e.g. ``"csv"``.
    :param location: ``"file"``, ``"content"`` or ``"memory"``.
    :param candidates: optional whitelist of plugin names.  When given,
                       plugins not in the list are excluded.
    :param priorities: optional mapping of plugin name to an integer
                       priority.  Higher numbers win.
    :param library: optional single plugin name, equivalent to a one
                    element candidate whitelist.
    """

    def __init__(
        self,
        action,
        file_type,
        location=None,
        candidates=None,
        priorities=None,
        library=None,
    ):
        self.action = action
        self.file_type = file_type.lower()
        self.location = location
        if candidates is None:
            self.candidates = None
        else:
            self.candidates = [name.replace("_", "-") for name in candidates]
        self.priorities = {
            name.replace("_", "-"): value
            for name, value in (priorities or {}).items()
        }
        if library is not None:
            library = library.replace("_", "-")
            if self.candidates is None:
                self.candidates = [library]
            elif library not in self.candidates:
                self.candidates = self.candidates + [library]
        self.library = library

    def bind_location(self, location):
        """Return a copy bound to a concrete source location."""
        return PluginSelectionContext(
            self.action,
            self.file_type,
            location=location,
            candidates=self.candidates,
            priorities=self.priorities,
            library=self.library,
        )

    @property
    def manager(self):
        if self.action == READ_ACTION:
            return NEW_READERS
        return NEW_WRITERS

    def _registry_key(self):
        return "%s-%s" % (self.location, self.file_type)

    def _matches(self, plugin_info):
        name = plugin_name(plugin_info)
        if self.candidates is not None and name not in self.candidates:
            return False
        if self.library is not None and name != self.library:
            return False
        return True

    def _eligible_plugins(self):
        registry = self.manager.registry
        key = self._registry_key()
        if key not in registry:
            return []
        return [
            plugin_info
            for plugin_info in registry[key]
            if self._matches(plugin_info)
        ]

    def _priority_of(self, plugin_info):
        return self.priorities.get(
            plugin_name(plugin_info), DEFAULT_PRIORITY
        )

    def _raise_no_plugin(self, tried):
        if tried:
            message = (
                "No eligible %s plugin for file type '%s' after trying: %s"
                % (self.action, self.file_type, ",".join(tried))
            )
        else:
            message = (
                "No eligible %s plugin found for file type '%s'"
                % (self.action, self.file_type)
            )
        raise exceptions.NoSupportingPluginFound(message)

    def select_plugin_info(self):
        """Filter candidates and pick one by declared priority.

        Filtering happens first (action, format, location, whitelist),
        priority ordering afterwards.  Plugins sharing the highest
        priority raise :class:`AmbiguousPluginFound`.  No plugin module
        is imported by this method.
        """
        eligible = self._eligible_plugins()
        if not eligible:
            self._raise_no_plugin([])

        ranked = sorted(
            eligible,
            key=self._priority_of,
            reverse=True,
        )
        highest_priority = self._priority_of(ranked[0])
        winners = [
            plugin_info
            for plugin_info in ranked
            if self._priority_of(plugin_info) == highest_priority
        ]
        if len(winners) > 1:
            names = sorted(plugin_name(info) for info in winners)
            raise exceptions.AmbiguousPluginFound(
                "Ambiguous %s plugins for file type '%s' at location "
                "'%s' with priority %s: %s. Declare an explicit priority "
                "or pass a candidate whitelist."
                % (
                    self.action,
                    self.file_type,
                    self.location,
                    highest_priority,
                    ",".join(names),
                )
            )
        return winners[0]

    def load_plugin(self):
        """Select a plugin and import only the chosen candidate."""
        plugin_info = self.select_plugin_info()
        name = plugin_name(plugin_info)
        if plugin_info.cls is not None:
            return plugin_info.cls
        try:
            module_name, class_name = (
                plugin_info.absolute_import_path.rsplit(".", 1)
            )
            module = importlib.import_module(module_name)
            plugin_info.cls = getattr(module, class_name)
        except Exception as original_error:
            raise exceptions.PluginLoadError(
                "Failed to import %s plugin '%s' for file type '%s': %s: %s"
                % (
                    self.action,
                    name,
                    self.file_type,
                    type(original_error).__name__,
                    original_error,
                )
            ) from original_error
        return plugin_info.cls

    def get_a_plugin(self, location=None):
        """Resolve a plugin class, optionally rebinding the location."""
        context = self
        if location is not None and location != self.location:
            context = self.bind_location(location)
        return context.load_plugin()
