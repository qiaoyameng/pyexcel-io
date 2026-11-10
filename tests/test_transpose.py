import os
import tempfile
from unittest import TestCase

from pyexcel_io import get_data, save_data
from pyexcel_io.transpose import (
    REJECT,
    transpose_data,
    iget_transposed_data,
)
from pyexcel_io.exceptions import RaggedSheetError
from pyexcel_io._compact import OrderedDict


def naive_transpose(matrix, fill=""):
    width = max(len(row) for row in matrix)
    return [
        [row[index] if index < len(row) else fill for row in matrix]
        for index in range(width)
    ]


class ExplodingStream(object):
    """a text stream that blows up after a number of lines"""

    def __init__(self, lines, explode_after):
        self._lines = lines
        self._explode_after = explode_after
        self._index = 0

    def read(self, size=-1):
        return ""

    def close(self):
        pass

    def __iter__(self):
        return self

    def __next__(self):
        if self._index == self._explode_after:
            raise IOError("the source blew up")
        if self._index >= len(self._lines):
            raise StopIteration
        line = self._lines[self._index]
        self._index += 1
        return line


class TestTransposeCSV(TestCase):
    def setUp(self):
        self.test_file = "transpose_fixture.csv"
        self.out_file = "transpose_out.csv"

    def tearDown(self):
        for afile in [self.test_file, self.out_file]:
            if os.path.exists(afile):
                os.unlink(afile)

    def write_file(self, content):
        with open(self.test_file, "w") as afile:
            afile.write(content)

    def test_transpose_a_rectangle(self):
        self.write_file("1,2,3\n4,5,6\n")
        transpose_data(self.test_file, self.out_file)
        data = get_data(self.out_file)
        self.assertEqual(list(data[self.out_file]), [[1, 4], [2, 5], [3, 6]])

    def test_double_transpose_restores_a_rectangle(self):
        matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        save_data(self.test_file, {"sheet1": matrix})
        intermediate = "transpose_intermediate.csv"
        try:
            transpose_data(self.test_file, intermediate)
            transpose_data(intermediate, self.out_file)
            data = get_data(self.out_file)
            self.assertEqual(list(data[self.out_file]), matrix)
        finally:
            if os.path.exists(intermediate):
                os.unlink(intermediate)

    def test_quoted_newline_is_not_split(self):
        self.write_file('a,"x\ny",c\n1,2,3\n')
        transpose_data(self.test_file, self.out_file)
        data = get_data(self.out_file)
        self.assertEqual(
            list(data[self.out_file]),
            [["a", 1], ["x\ny", 2], ["c", 3]],
        )

    def test_ragged_rows_are_rejected_by_default(self):
        self.write_file("1,2,3\n4,5\n")
        with self.assertRaises(RaggedSheetError):
            transpose_data(self.test_file, self.out_file)

    def test_ragged_rows_are_padded_with_fill_value(self):
        # the widest row appears only at the very end
        self.write_file("1,2\n3,4\n5,6,7\n")
        transpose_data(self.test_file, self.out_file, fill_value="")
        data = get_data(self.out_file, keep_trailing_empty_cells=True)
        self.assertEqual(
            list(data[self.out_file]),
            [[1, 3, 5], [2, 4, 6], ["", "", 7]],
        )

    def test_empty_strings_and_empty_rows_survive(self):
        self.write_file("a,,c\n,,\n")
        transpose_data(self.test_file, self.out_file)
        data = get_data(self.out_file, keep_trailing_empty_cells=True)
        self.assertEqual(
            list(data[self.out_file]),
            [["a", ""], ["", ""], ["c", ""]],
        )

    def test_empty_row_is_padded_when_a_fill_value_is_given(self):
        self.write_file("1,2\n\n3,4\n")
        transpose_data(self.test_file, self.out_file, fill_value="")
        data = get_data(self.out_file, keep_trailing_empty_cells=True)
        self.assertEqual(list(data[self.out_file]), [[1, "", 3], [2, "", 4]])

    def test_auto_detect_can_be_turned_off(self):
        self.write_file("1,2\n3,4\n")
        transpose_data(
            self.test_file,
            self.out_file,
            auto_detect_int=False,
            auto_detect_float=False,
            auto_detect_datetime=False,
        )
        data = get_data(
            self.out_file,
            auto_detect_int=False,
            auto_detect_float=False,
            auto_detect_datetime=False,
        )
        self.assertEqual(
            list(data[self.out_file]), [["1", "3"], ["2", "4"]]
        )

    def test_line_terminator_is_forwarded_to_the_writer(self):
        self.write_file("1,2\n3,4\n")
        transpose_data(self.test_file, self.out_file, lineterminator="\n")
        with open(self.out_file, "rb") as afile:
            content = afile.read()
        self.assertEqual(content, b"1,3\n2,4\n")

    def test_wide_table_with_a_tiny_budget(self):
        matrix = [[row * 100 + col for col in range(60)] for row in range(4)]
        save_data(self.test_file, {"sheet1": matrix})
        transpose_data(self.test_file, self.out_file, byte_budget=64)
        data = get_data(self.out_file)
        self.assertEqual(list(data[self.out_file]), naive_transpose(matrix))

    def test_long_table_with_a_tiny_budget(self):
        matrix = [[row, row * 2, row * 3] for row in range(300)]
        save_data(self.test_file, {"sheet1": matrix})
        transpose_data(self.test_file, self.out_file, byte_budget=64)
        data = get_data(self.out_file)
        self.assertEqual(list(data[self.out_file]), naive_transpose(matrix))

    def test_temp_dir_is_empty_afterwards(self):
        matrix = [[row * 100 + col for col in range(60)] for row in range(4)]
        save_data(self.test_file, {"sheet1": matrix})
        temp_dir = tempfile.mkdtemp()
        try:
            transpose_data(
                self.test_file,
                self.out_file,
                byte_budget=64,
                temp_dir=temp_dir,
            )
            self.assertEqual(os.listdir(temp_dir), [])
            data = get_data(self.out_file)
            self.assertEqual(
                list(data[self.out_file]), naive_transpose(matrix)
            )
        finally:
            os.rmdir(temp_dir)

    def test_source_exception_still_cleans_up(self):
        temp_dir = tempfile.mkdtemp()
        stream = ExplodingStream(["1,2,3\n"] * 50, explode_after=10)
        try:
            with self.assertRaises(IOError):
                transpose_data(
                    stream,
                    self.out_file,
                    file_type="csv",
                    byte_budget=16,
                    temp_dir=temp_dir,
                )
            self.assertEqual(os.listdir(temp_dir), [])
        finally:
            os.rmdir(temp_dir)

    def test_unsupported_file_type_is_rejected(self):
        with self.assertRaises(ValueError):
            iget_transposed_data(b"a,b\n", file_type="xlsx")


class TestTransposeTSV(TestCase):
    def setUp(self):
        self.test_file = "transpose_fixture.tsv"
        self.out_file = "transpose_out.tsv"

    def tearDown(self):
        for afile in [self.test_file, self.out_file]:
            if os.path.exists(afile):
                os.unlink(afile)

    def test_transpose_a_tsv_file(self):
        with open(self.test_file, "w") as afile:
            afile.write("a\tb\n1\t2\n")
        transpose_data(self.test_file, self.out_file)
        data = get_data(self.out_file)
        self.assertEqual(list(data[self.out_file]), [["a", 1], ["b", 2]])


class TestTransposeCSVZ(TestCase):
    file_type = "csvz"

    def setUp(self):
        self.test_file = "transpose_fixture." + self.file_type
        self.out_file = "transpose_out." + self.file_type

    def tearDown(self):
        for afile in [self.test_file, self.out_file]:
            if os.path.exists(afile):
                os.unlink(afile)

    def test_transpose_all_sheets(self):
        content = OrderedDict()
        content.update({"sheet1": [[1, 2], [3, 4]]})
        content.update({"sheet2": [["a", "b", "c"]]})
        save_data(self.test_file, content)
        transpose_data(self.test_file, self.out_file)
        data = get_data(self.out_file)
        self.assertEqual(list(data["sheet1"]), [[1, 3], [2, 4]])
        self.assertEqual(list(data["sheet2"]), [["a"], ["b"], ["c"]])

    def test_selected_sheet_only_and_the_rest_is_not_read(self):
        content = OrderedDict()
        # sheet1 is ragged: reading it would raise RaggedSheetError
        content.update({"sheet1": [[1, 2, 3], [4, 5]]})
        content.update({"sheet2": [[1, 2], [3, 4]]})
        save_data(self.test_file, content)
        transpose_data(self.test_file, self.out_file, sheets=["sheet2"])
        data = get_data(self.out_file)
        self.assertEqual(list(data.keys()), ["sheet2"])
        self.assertEqual(list(data["sheet2"]), [[1, 3], [2, 4]])

    def test_selected_sheet_by_index(self):
        content = OrderedDict()
        content.update({"sheet1": [[1, 2, 3], [4, 5]]})
        content.update({"sheet2": [[1, 2], [3, 4]]})
        save_data(self.test_file, content)
        transpose_data(self.test_file, self.out_file, sheets=[1])
        data = get_data(self.out_file)
        self.assertEqual(list(data.keys()), ["sheet2"])
        self.assertEqual(list(data["sheet2"]), [[1, 3], [2, 4]])

    def test_double_transpose_restores_a_rectangle(self):
        matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        save_data(self.test_file, {"sheet1": matrix})
        intermediate = "transpose_intermediate." + self.file_type
        try:
            transpose_data(self.test_file, intermediate)
            transpose_data(intermediate, self.out_file)
            data = get_data(self.out_file)
            self.assertEqual(list(data["sheet1"]), matrix)
        finally:
            if os.path.exists(intermediate):
                os.unlink(intermediate)

    def test_wide_table_with_a_tiny_budget(self):
        matrix = [[row * 100 + col for col in range(60)] for row in range(4)]
        save_data(self.test_file, {"sheet1": matrix})
        transpose_data(self.test_file, self.out_file, byte_budget=64)
        data = get_data(self.out_file)
        self.assertEqual(list(data["sheet1"]), naive_transpose(matrix))

    def test_shared_budget_spills_and_is_cleaned_up(self):
        content = OrderedDict()
        content.update({"sheet1": [[1, 2], [3, 4]]})
        content.update({"sheet2": [[5, 6], [7, 8]]})
        save_data(self.test_file, content)
        temp_dir = tempfile.mkdtemp()
        try:
            # a single byte of budget forces the external storage path
            data, session = iget_transposed_data(
                self.test_file, byte_budget=1, temp_dir=temp_dir
            )
            spill_dir = session.temp_path
            self.assertTrue(len(os.listdir(spill_dir)) > 0)
            self.assertEqual(list(data["sheet1"]), [[1, 3], [2, 4]])
            self.assertEqual(list(data["sheet2"]), [[5, 7], [6, 8]])
            session.close()
            self.assertEqual(os.listdir(temp_dir), [])
        finally:
            os.rmdir(temp_dir)


class TestIGetTransposedData(TestCase):
    def setUp(self):
        self.test_file = "transpose_fixture.csv"

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.unlink(self.test_file)

    def test_streaming_interface_and_session_lifecycle(self):
        with open(self.test_file, "w") as afile:
            afile.write("1,2,3\n4,5,6\n")
        temp_dir = tempfile.mkdtemp()
        try:
            data, session = iget_transposed_data(
                self.test_file, byte_budget=16, temp_dir=temp_dir
            )
            self.assertEqual(
                list(data[self.test_file]), [[1, 4], [2, 5], [3, 6]]
            )
            session.close()
            self.assertEqual(os.listdir(temp_dir), [])
        finally:
            os.rmdir(temp_dir)

    def test_default_fill_value_is_reject(self):
        self.assertTrue(repr(REJECT) == "REJECT")
