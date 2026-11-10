"""
tests for the per-operation plugin selection context

All plugins used here are registered temporarily inside the test process
and removed again afterwards.  No extra Excel plugin is required.
"""

import sys
import threading
import types
from unittest import TestCase

import pyexcel_io.manager as manager
from pyexcel_io import get_data, save_data
from pyexcel_io._compact import BytesIO
from pyexcel_io.exceptions import (
    AmbiguousPluginFound,
    NoSupportingPluginFound,
    PluginLoadError,
)
from pyexcel_io.plugins import NEW_READERS, NEW_WRITERS
from pyexcel_io.reader import Reader
from pyexcel_io.selection import (
    READ_ACTION,
    WRITE_ACTION,
    PluginSelectionContext,
    plugin_name,
)
from pyexcel_io.writer import Writer

from .nose_tools import eq_, raises

FAKE_FILE_TYPE = "fakesel"
READER_A_MODULE = "fake_reader_a_pkg.fake_reader"
READER_B_MODULE = "fake_reader_b_pkg.fake_reader"
BROKEN_WRITER_MODULE = "fake_broken_writer_pkg.fake_writer"


def make_fake_module(module_name, class_name, class_obj, broken=False):
    module = types.ModuleType(module_name)
    if broken:

        def __getattr__(name):
            raise ImportError("internal dependency 'missing_dep' is absent")

        module.__getattr__ = __getattr__
    else:
        setattr(module, class_name, class_obj)
    return module


class FakeReaderA:
    def __init__(self, source, file_type, **keywords):
        self.source = source

    def __len__(self):
        return 1

    def sheet_names(self):
        return ["sheet1"]

    def read_sheet(self, index):
        return self

    def row_iterator(self):
        return iter([["a"]])

    def column_iterator(self, row):
        return iter(row)

    def close(self):
        pass


class FakeReaderB(FakeReaderA):
    pass


def register_fake(manager_obj, key, module_name, class_name, class_obj):
    from pyexcel_io.plugins import IOPluginInfo

    plugin_info = IOPluginInfo(
        manager_obj.plugin_name,
        abs_class_path="%s.%s" % (module_name, class_name),
        file_types=[key],
        stream_type="text",
    )
    manager_obj.load_me_later(plugin_info)
    return plugin_info


class SelectionTestBase(TestCase):
    registry_keys = ()

    def setUp(self):
        self._registry_snapshots = {
            key: list(NEW_READERS.registry.get(key, []))
            for key in self.registry_keys
        }
        self._writer_snapshots = {
            key: list(NEW_WRITERS.registry.get(key, []))
            for key in self.registry_keys
        }
        self._modules = {}
        self._stream_snapshot = (
            list(manager.TEXT_STREAM_TYPES),
            list(manager.BINARY_STREAM_TYPES),
            manager.FILE_TYPES,
        )

    def tearDown(self):
        for key, snapshot in self._registry_snapshots.items():
            if snapshot:
                NEW_READERS.registry[key] = snapshot
            else:
                NEW_READERS.registry.pop(key, None)
        for key, snapshot in self._writer_snapshots.items():
            if snapshot:
                NEW_WRITERS.registry[key] = snapshot
            else:
                NEW_WRITERS.registry.pop(key, None)
        for module_name in self._modules:
            sys.modules.pop(module_name, None)
        manager.TEXT_STREAM_TYPES[:] = self._stream_snapshot[0]
        manager.BINARY_STREAM_TYPES[:] = self._stream_snapshot[1]
        manager.FILE_TYPES = self._stream_snapshot[2]

    def add_reader(self, location, module_name, class_name, class_obj):
        key = "%s-%s" % (location, FAKE_FILE_TYPE)
        self._registry_snapshots.setdefault(key, list(
            NEW_READERS.registry.get(key, [])
        ))
        info = register_fake(
            NEW_READERS, key, module_name, class_name, class_obj
        )
        if module_name not in sys.modules:
            self._modules[module_name] = make_fake_module(
                module_name, class_name, class_obj
            )
            sys.modules[module_name] = self._modules[module_name]
        return info

    def add_broken_writer(self, location):
        key = "%s-%s" % (location, FAKE_FILE_TYPE)
        self._writer_snapshots.setdefault(
            key, list(NEW_WRITERS.registry.get(key, []))
        )
        info = register_fake(
            NEW_WRITERS,
            key,
            BROKEN_WRITER_MODULE,
            "BrokenWriter",
            None,
        )
        self._modules[BROKEN_WRITER_MODULE] = make_fake_module(
            BROKEN_WRITER_MODULE, "BrokenWriter", None, broken=True
        )
        sys.modules[BROKEN_WRITER_MODULE] = self._modules[
            BROKEN_WRITER_MODULE
        ]
        return info


class TestPluginSelection(SelectionTestBase):
    registry_keys = (
        "file-" + FAKE_FILE_TYPE,
        "memory-" + FAKE_FILE_TYPE,
        "content-" + FAKE_FILE_TYPE,
    )

    def setUp(self):
        SelectionTestBase.setUp(self)
        self.info_a = self.add_reader(
            "file", READER_A_MODULE, "FakeReaderA", FakeReaderA
        )
        self.info_b = self.add_reader(
            "file", READER_B_MODULE, "FakeReaderB", FakeReaderB
        )

    def test_plugin_name_normalisation(self):
        eq_(plugin_name(self.info_a), "fake-reader-a-pkg")

    def test_single_candidate_keeps_registry_order(self):
        context = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            candidates=["fake-reader-a-pkg"],
        )
        eq_(context.load_plugin(), FakeReaderA)

    def test_explicit_priority_overrides_registry_order(self):
        context = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            priorities={
                "fake-reader-a-pkg": 1,
                "fake-reader-b-pkg": 5,
            },
        )
        eq_(context.load_plugin(), FakeReaderB)

    def test_candidate_whitelist_filters_first(self):
        context = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            candidates=["fake-reader-b-pkg"],
            priorities={"fake-reader-a-pkg": 100},
        )
        eq_(context.load_plugin(), FakeReaderB)

    def test_library_restricts_candidates(self):
        context = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            library="fake-reader-b-pkg",
        )
        eq_(context.load_plugin(), FakeReaderB)

    def test_location_filter_uses_path_vs_stream_support(self):
        memory_context = PluginSelectionContext(
            READ_ACTION, FAKE_FILE_TYPE, location="memory"
        )
        try:
            memory_context.load_plugin()
        except NoSupportingPluginFound:
            pass
        else:
            raise AssertionError("memory location has no registered reader")

        self.add_reader(
            "memory", READER_B_MODULE, "FakeReaderB", FakeReaderB
        )
        eq_(
            memory_context.load_plugin(),
            FakeReaderB,
        )

    def test_equal_priority_reports_ambiguity(self):
        context = PluginSelectionContext(
            READ_ACTION, FAKE_FILE_TYPE, location="file"
        )
        try:
            context.select_plugin_info()
        except AmbiguousPluginFound as error:
            message = str(error)
            assert "fake-reader-a-pkg" in message
            assert "fake-reader-b-pkg" in message
            assert FAKE_FILE_TYPE in message
        else:
            raise AssertionError("AmbiguousPluginFound was not raised")

    def test_only_chosen_candidate_is_imported(self):
        assert self.info_a.cls is None
        assert self.info_b.cls is None
        context = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            priorities={"fake-reader-b-pkg": 9},
        )
        eq_(context.load_plugin(), FakeReaderB)
        assert self.info_b.cls is FakeReaderB
        assert self.info_a.cls is None

    def test_context_does_not_change_process_registry(self):
        before = list(NEW_READERS.registry["file-" + FAKE_FILE_TYPE])
        context = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            priorities={"fake-reader-b-pkg": 9},
        )
        context.load_plugin()
        after = NEW_READERS.registry["file-" + FAKE_FILE_TYPE]
        eq_(before, after)
        eq_(before[0], self.info_a)

    def test_opposite_priorities_are_isolated_across_threads(self):
        context_a = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            priorities={"fake-reader-a-pkg": 9},
        )
        context_b = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            priorities={"fake-reader-b-pkg": 9},
        )
        results = {}
        barrier = threading.Barrier(2)

        def worker(name, context, expected):
            barrier.wait()
            for _ in range(20):
                resolved = context.load_plugin()
                assert resolved is expected, name
            results[name] = expected

        thread_a = threading.Thread(
            target=worker,
            args=("a", context_a, FakeReaderA),
        )
        thread_b = threading.Thread(
            target=worker,
            args=("b", context_b, FakeReaderB),
        )
        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()
        eq_(results, {"a": FakeReaderA, "b": FakeReaderB})

    def test_reader_uses_context_for_each_location(self):
        reader = Reader(
            FAKE_FILE_TYPE,
            context=PluginSelectionContext(
                READ_ACTION,
                FAKE_FILE_TYPE,
                priorities={"fake-reader-b-pkg": 9},
            ),
        )
        reader.open("whatever." + FAKE_FILE_TYPE)
        assert isinstance(reader.reader, FakeReaderB)


class TestBrokenWriterDiagnostics(SelectionTestBase):
    registry_keys = ("file-" + FAKE_FILE_TYPE,)

    def setUp(self):
        SelectionTestBase.setUp(self)
        self.broken_info = self.add_broken_writer("file")

    def test_import_failure_keeps_plugin_name_and_original_error(self):
        context = PluginSelectionContext(
            WRITE_ACTION, FAKE_FILE_TYPE, location="file"
        )
        try:
            context.load_plugin()
        except PluginLoadError as error:
            message = str(error)
            assert "fake-broken-writer-pkg" in message
            assert "ImportError" in message
            assert "missing_dep" in message
            assert isinstance(error.__cause__, ImportError)
        else:
            raise AssertionError("PluginLoadError was not raised")
        assert self.broken_info.cls is None

    def test_writer_surfaces_load_error_not_install_message(self):
        writer = Writer(
            FAKE_FILE_TYPE,
            context=PluginSelectionContext(
                WRITE_ACTION, FAKE_FILE_TYPE
            ),
        )
        try:
            writer.open("whatever." + FAKE_FILE_TYPE)
        except PluginLoadError as error:
            assert "fake-broken-writer-pkg" in str(error)
        else:
            raise AssertionError("PluginLoadError was not raised")


class TestNoEligiblePlugin(SelectionTestBase):
    registry_keys = ("file-" + FAKE_FILE_TYPE,)

    @raises(NoSupportingPluginFound)
    def test_unknown_format(self):
        PluginSelectionContext(
            READ_ACTION, FAKE_FILE_TYPE, location="file"
        ).load_plugin()

    def test_whitelist_excluding_everything(self):
        self.add_reader(
            "file", READER_A_MODULE, "FakeReaderA", FakeReaderA
        )
        context = PluginSelectionContext(
            READ_ACTION,
            FAKE_FILE_TYPE,
            location="file",
            candidates=["some-other-plugin"],
        )
        try:
            context.load_plugin()
        except NoSupportingPluginFound as error:
            assert FAKE_FILE_TYPE in str(error)
        else:
            raise AssertionError("NoSupportingPluginFound was not raised")


class TestBuiltinCsvEntries(SelectionTestBase):
    def test_csv_round_trip_with_context(self):
        context = PluginSelectionContext(
            WRITE_ACTION, "csv", candidates=["pyexcel-io"]
        )
        stream = manager.get_io("csv")
        save_data(
            stream,
            {"sheet1": [[1, 2], [3, 4]]},
            file_type="csv",
            context=context,
        )
        stream.seek(0)
        data = get_data(
            stream,
            file_type="csv",
            context=PluginSelectionContext(
                READ_ACTION, "csv", candidates=["pyexcel-io"]
            ),
        )
        eq_(data["csv"], [[1, 2], [3, 4]])

    def test_csvz_round_trip_with_context(self):
        stream = BytesIO()
        save_data(
            stream,
            {"sheet1": [[1, 2], [3, 4]]},
            file_type="csvz",
            context={
                "candidates": ["pyexcel-io"],
                "priorities": {"pyexcel-io": 10},
            },
        )
        stream.seek(0)
        data = get_data(
            stream,
            file_type="csvz",
            context=PluginSelectionContext(
                READ_ACTION, "csvz", candidates=["pyexcel-io"]
            ),
        )
        eq_(list(data.values())[0], [[1, 2], [3, 4]])

    def test_legacy_path_without_context_still_works(self):
        stream = manager.get_io("csv")
        save_data(stream, {"sheet1": [[1]]}, file_type="csv")
        stream.seek(0)
        data = get_data(stream, file_type="csv")
        eq_(data["csv"], [[1]])
