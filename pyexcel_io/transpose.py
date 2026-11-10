"""
pyexcel_io.transpose
~~~~~~~~~~~~~~~~~~~~

Explicit transpose read/write path for csv, tsv, csvz and tsvz files.

The source is read exactly once, row by row, and the transposed rows
are produced without holding the whole sheet in one giant list: rows
are staged in blocks under a byte budget shared by all sheets and are
spilled to a temporary directory when the budget is exhausted.

:copyright: (c) 2014-2026 by C Wang
:license: New BSD License, see LICENSE for more details
"""

import os
import pickle
import tempfile

from pyexcel_io import constants
from pyexcel_io.io import save_data
from pyexcel_io.reader import Reader
from pyexcel_io._compact import isstream, OrderedDict
from pyexcel_io.exceptions import RaggedSheetError

SUPPORTED_FILE_TYPES = (
    constants.FILE_FORMAT_CSV,
    constants.FILE_FORMAT_TSV,
    constants.FILE_FORMAT_CSVZ,
    constants.FILE_FORMAT_TSVZ,
)

DEFAULT_BYTE_BUDGET = 64 * 1024 * 1024

_BLOCK_FILE_PREFIX = "transpose-"
_BLOCK_FILE_SUFFIX = ".blk"
_PICKLE_PROTOCOL = 4

# those keywords steer the type conversion of the csv readers and
# are not understood by the csv writers
_READER_ONLY_KEYWORDS = frozenset(
    [
        "auto_detect_float",
        "auto_detect_int",
        "auto_detect_datetime",
        "ignore_infinity",
        "ignore_nan_text",
        "default_float_nan",
        "pep_0515_off",
    ]
)


class _Reject(object):
    def __repr__(self):
        return "REJECT"


#: default fill_value: ragged rows are rejected with RaggedSheetError
REJECT = _Reject()


def _cell_footprint(cell):
    """a rough byte estimate of a parsed cell for budget accounting"""
    if cell is None:
        return 8
    if isinstance(cell, str):
        return 16 + len(cell)
    if isinstance(cell, bytes):
        return 16 + len(cell)
    if isinstance(cell, (int, float)):
        return 24
    return 64


def _row_footprint(row):
    return 16 + sum(_cell_footprint(cell) for cell in row)


class _Block(object):
    """a spilled chunk of a sheet, stored column by column on disk"""

    def __init__(self, n_rows, width, path):
        self.n_rows = n_rows
        self.width = width
        self.path = path


class TransposeSession(object):
    """
    Holds the byte budget shared by all staged sheets and the
    temporary directory their spilled blocks live in.
    """

    def __init__(self, byte_budget=DEFAULT_BYTE_BUDGET, temp_dir=None):
        if byte_budget <= 0:
            raise ValueError("byte_budget must be a positive number")
        self.byte_budget = byte_budget
        self._retained_bytes = 0
        self._temp_dir = tempfile.TemporaryDirectory(
            prefix="pyexcel-io-transpose-", dir=temp_dir
        )
        self._closed = False

    @property
    def temp_path(self):
        """the temporary directory used for spilled blocks"""
        return self._temp_dir.name

    def stage_rows(self, rows, fill_value=REJECT):
        """
        Consume a row iterator in one pass and return a staging
        object whose iter_rows() yields the transposed rows.
        """
        if self._closed:
            raise ValueError("the transpose session is closed")
        staging = _SheetStaging(self, fill_value)
        staging.consume(rows)
        return staging

    def has_room_for(self, extra_bytes):
        return self._retained_bytes + extra_bytes <= self.byte_budget

    def retain(self, byte_count):
        self._retained_bytes += byte_count

    def make_block_path(self):
        fd, path = tempfile.mkstemp(
            prefix=_BLOCK_FILE_PREFIX,
            suffix=_BLOCK_FILE_SUFFIX,
            dir=self.temp_path,
        )
        os.close(fd)
        return path

    def close(self):
        if not self._closed:
            self._closed = True
            self._temp_dir.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, a_type, value, traceback):
        self.close()


class _SheetStaging(object):
    """
    Stages one sheet in blocks under the session's byte budget and
    yields the transposed rows afterwards.
    """

    def __init__(self, session, fill_value):
        self._session = session
        self._fill_value = fill_value
        self._padding = None if fill_value is REJECT else fill_value
        self._buffer = []
        self._buffer_bytes = 0
        self._blocks = []
        self._width = 0
        self._reference_length = None

    def consume(self, rows):
        for row in rows:
            row = list(row)
            self._validate(row)
            if len(row) > self._width:
                self._width = len(row)
            self._buffer.append(row)
            self._buffer_bytes += _row_footprint(row)
            if not self._session.has_room_for(self._buffer_bytes):
                self._flush()
        if self._buffer:
            if self._blocks or not self._session.has_room_for(
                self._buffer_bytes
            ):
                self._flush()
            else:
                self._session.retain(self._buffer_bytes)

    def _validate(self, row):
        if self._reference_length is None:
            self._reference_length = len(row)
        elif (
            len(row) != self._reference_length
            and self._fill_value is REJECT
        ):
            raise RaggedSheetError(
                "Ragged rows cannot be transposed: row of length %d "
                "does not match the first row's length %d. "
                "Pass fill_value to pad short rows instead."
                % (len(row), self._reference_length)
            )

    def _flush(self):
        if not self._buffer:
            return
        columns = []
        for column_index in range(self._width):
            columns.append(
                tuple(
                    row[column_index]
                    if column_index < len(row)
                    else self._padding
                    for row in self._buffer
                )
            )
        path = self._session.make_block_path()
        with open(path, "wb") as block_file:
            pickle.dump(
                (len(self._buffer), self._width),
                block_file,
                protocol=_PICKLE_PROTOCOL,
            )
            for column in columns:
                pickle.dump(column, block_file, protocol=_PICKLE_PROTOCOL)
        self._blocks.append(_Block(len(self._buffer), self._width, path))
        self._buffer = []
        self._buffer_bytes = 0

    def iter_rows(self):
        """yield the transposed rows, one at a time"""
        if not self._blocks:
            return self._iter_from_buffer()
        return self._iter_from_blocks()

    def _iter_from_buffer(self):
        for column_index in range(self._width):
            yield [
                row[column_index]
                if column_index < len(row)
                else self._padding
                for row in self._buffer
            ]

    def _iter_from_blocks(self):
        handles = []
        try:
            for block in self._blocks:
                handle = open(block.path, "rb")
                pickle.load(handle)  # the header, n_rows and width
                handles.append(handle)
            for column_index in range(self._width):
                row = []
                for block, handle in zip(self._blocks, handles):
                    if column_index < block.width:
                        row.extend(pickle.load(handle))
                    else:
                        row.extend([self._padding] * block.n_rows)
                yield row
        finally:
            for handle in handles:
                handle.close()


def _resolve_file_type(afile, file_type):
    if isstream(afile):
        return "stream", file_type or constants.FILE_FORMAT_CSV
    if file_type is None:
        try:
            return "file", afile.split(".")[-1]
        except AttributeError:
            raise Exception(constants.MESSAGE_FILE_NAME_SHOULD_BE_STRING)
    return "content", file_type


def _resolve_sheet_indices(sheets, sheet_names):
    if sheets is None:
        return list(range(len(sheet_names)))
    if isinstance(sheets, (int, str)):
        sheets = [sheets]
    indices = []
    for sheet in sheets:
        if isinstance(sheet, int):
            indices.append(sheet)
        else:
            indices.append(sheet_names.index(sheet))
    return indices


def iget_transposed_data(
    afile,
    file_type=None,
    sheets=None,
    fill_value=REJECT,
    byte_budget=DEFAULT_BYTE_BUDGET,
    temp_dir=None,
    library=None,
    **keywords
):
    """Get transposed data from a csv, tsv, csvz or tsvz source

    The source is read exactly once. The returned sheet content stays
    a generator; the sheets are staged in blocks under a byte budget
    shared by all sheets and spilled to a temporary directory when the
    budget is exhausted.

    :param afile: a file name, a file stream or actual content
    :param file_type: used only when afile is not a physical file name
    :param sheets: a sheet name, a sheet index or a list of them.
                   Unselected sheets are not read at all.
    :param fill_value: by default ragged rows are rejected with
                       RaggedSheetError. Pass a value here to pad
                       short rows with it instead.
    :param byte_budget: the number of bytes all staged sheets may
                        share in memory before spilling to disk
    :param temp_dir: where to spill. A dedicated temporary directory
                     is created when not given.
    :param library: explicitly name a library for use.
    :param keywords: any other parameters for the underlying csv
                     reader, e.g. auto_detect_int, encoding, delimiter
    :returns: an ordered dictionary and the transpose session. Close
              the session once the data has been consumed.
    """
    location, file_type = _resolve_file_type(afile, file_type)
    if file_type.lower() not in SUPPORTED_FILE_TYPES:
        raise ValueError(
            "Transpose is supported for %s files only, not for '%s'"
            % (", ".join(SUPPORTED_FILE_TYPES), file_type)
        )
    reader = Reader(file_type, library=library)
    session = TransposeSession(byte_budget=byte_budget, temp_dir=temp_dir)
    try:
        if location == "stream":
            reader.open_stream(afile, **keywords)
        elif location == "content":
            reader.open_content(afile, **keywords)
        else:
            reader.open(afile, **keywords)
        plugin = reader.reader
        sheet_names = plugin.sheet_names()
        data = OrderedDict()
        for index in _resolve_sheet_indices(sheets, sheet_names):
            sheet = plugin.read_sheet(index)
            rows = (
                sheet.column_iterator(row)
                for row in sheet.row_iterator()
            )
            staging = session.stage_rows(rows, fill_value=fill_value)
            data[sheet_names[index]] = staging.iter_rows()
    except Exception:
        session.close()
        raise
    finally:
        if getattr(reader, "reader", None) is not None:
            reader.close()
    return data, session


def transpose_data(
    afile,
    output,
    file_type=None,
    output_file_type=None,
    sheets=None,
    fill_value=REJECT,
    byte_budget=DEFAULT_BYTE_BUDGET,
    temp_dir=None,
    library=None,
    **keywords
):
    """Transpose a csv, tsv, csvz or tsvz source into a new file

    The transposed sheets are written with the existing writers, so
    the usual writer parameters such as encoding and lineterminator
    keep working.

    :param afile: a file name, a file stream or actual content
    :param output: a file name or a file stream to write to
    :param file_type: used only when afile is not a physical file name
    :param output_file_type: used only when output is not a physical
                             file name
    :param sheets: a sheet name, a sheet index or a list of them.
                   Unselected sheets are not read at all.
    :param fill_value: by default ragged rows are rejected with
                       RaggedSheetError. Pass a value here to pad
                       short rows with it instead.
    :param byte_budget: the number of bytes all staged sheets may
                        share in memory before spilling to disk
    :param temp_dir: where to spill. A dedicated temporary directory
                     is created when not given.
    :param library: explicitly name a library for use.
    :param keywords: any other parameters for the underlying csv
                     reader and writer
    """
    writer_keywords = {
        key: value
        for key, value in keywords.items()
        if key not in _READER_ONLY_KEYWORDS
    }
    data, session = iget_transposed_data(
        afile,
        file_type=file_type,
        sheets=sheets,
        fill_value=fill_value,
        byte_budget=byte_budget,
        temp_dir=temp_dir,
        library=library,
        **keywords
    )
    try:
        save_data(
            output,
            data,
            file_type=output_file_type,
            library=library,
            **writer_keywords
        )
    finally:
        session.close()
