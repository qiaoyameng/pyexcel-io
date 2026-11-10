"""
Regression tests for CSVMemoryMapIterator.

The mmap backed reader must yield the same csv cells as the regular text
file and BytesIO based readers, including for utf-16/utf-32 data where a
0x0A byte may belong to a character instead of being a line feed.
"""

import csv
import io
import mmap
import os

import pytest

from pyexcel_io import get_data
from pyexcel_io.readers.csv_sheet import (
    CSVMemoryMapIterator,
    MMAP_READ_CHUNK_SIZE,
)

ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
)

# U+0A00 and U+0A0A carry 0x0A bytes in every utf-16/utf-32 byte layout.
# They must never be treated as line feed bytes by the mmap reader.
ROWS = [
    ["normal", "਀embedded-line-feed-byte", "one"],
    ["ਊ second row", "quoted\r\nnewline", "two"],
    ["trailing space ", "trailing tab\t", "  both  "],
    ["last row", "no terminator after this", "end"],
]


def make_csv_bytes(rows, encoding, lineterminator="\r\n"):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=lineterminator)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode(encoding)


def make_csv_text(rows, lineterminator="\r\n"):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=lineterminator)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


@pytest.fixture
def workspace(tmp_path):
    return str(tmp_path)


def read_from_file(path, encoding):
    sheet_name = os.path.basename(path)
    return get_data(path, encoding=encoding)[sheet_name]


def read_from_bytesio(raw, encoding):
    return get_data(
        io.BytesIO(raw), file_type="csv", encoding=encoding
    )["csv"]


def read_from_mmap(path, encoding):
    with open(path, "r+b") as csv_file:
        memory_map = mmap.mmap(
            csv_file.fileno(), 0, access=mmap.ACCESS_READ
        )
        try:
            return get_data(
                memory_map, file_type="csv", encoding=encoding
            )["csv"]
        finally:
            memory_map.close()


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_mmap_matches_file_and_bytesio(workspace, encoding):
    raw = make_csv_bytes(ROWS, encoding)
    path = os.path.join(workspace, "mmap-%s.csv" % encoding)
    with open(path, "wb") as csv_file:
        csv_file.write(raw)

    file_cells = read_from_file(path, encoding)
    bytesio_cells = read_from_bytesio(raw, encoding)
    mmap_cells = read_from_mmap(path, encoding)

    expected_in_memory = list(csv.reader(io.StringIO(make_csv_text(ROWS))))
    expected_from_file = list(
        csv.reader(io.StringIO(make_csv_text(ROWS).replace("\r\n", "\n")))
    )
    assert file_cells == expected_from_file
    assert bytesio_cells == expected_in_memory
    assert mmap_cells == expected_in_memory


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_mmap_preserves_trailing_whitespace(workspace, encoding):
    rows = [["x", "y "], ["z", "\tq\t"], [" keep ", "tab\there\t"]]
    raw = make_csv_bytes(rows, encoding)
    path = os.path.join(workspace, "whitespace-%s.csv" % encoding)
    with open(path, "wb") as csv_file:
        csv_file.write(raw)

    assert read_from_mmap(path, encoding) == rows
    assert read_from_bytesio(raw, encoding) == rows


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_mmap_handles_quoted_newlines(workspace, encoding):
    rows = [["a", "line1\nline2", "b"], ["c", "x\r\ny", "d"]]
    raw = make_csv_bytes(rows, encoding)
    path = os.path.join(workspace, "quoted-%s.csv" % encoding)
    with open(path, "wb") as csv_file:
        csv_file.write(raw)

    assert read_from_bytesio(raw, encoding) == rows
    assert read_from_mmap(path, encoding) == rows


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_mmap_handles_characters_split_across_chunks(workspace, encoding):
    rows = []
    for index in range(300):
        rows.append(
            [
                "row%d" % index,
                "਀ਊ" + "中" * (index % 11),
                "tail ",
            ]
        )
    raw = make_csv_bytes(rows, encoding)
    assert len(raw) > MMAP_READ_CHUNK_SIZE * 10
    path = os.path.join(workspace, "chunks-%s.csv" % encoding)
    with open(path, "wb") as csv_file:
        csv_file.write(raw)

    assert read_from_mmap(path, encoding) == rows
    assert read_from_bytesio(raw, encoding) == rows
    assert read_from_file(path, encoding) == rows


def test_mmap_handles_crlf_split_across_chunks(workspace):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for index in range(400):
        writer.writerow(["x" * (MMAP_READ_CHUNK_SIZE // 3), "y"])
    raw = buffer.getvalue().encode("utf-16-le")
    path = os.path.join(workspace, "crlf-split.csv")
    with open(path, "wb") as csv_file:
        csv_file.write(raw)

    assert len(read_from_mmap(path, "utf-16-le")) == 400
    assert read_from_bytesio(raw, "utf-16-le") == read_from_mmap(
        path, "utf-16-le"
    )


@pytest.mark.parametrize("encoding", ("utf-8", "utf-16", "utf-32"))
def test_empty_file_on_file_and_bytesio_paths(workspace, encoding):
    raw = "".encode(encoding)
    path = os.path.join(workspace, "empty-%s.csv" % encoding)
    with open(path, "wb") as csv_file:
        csv_file.write(raw)

    assert read_from_file(path, encoding) == []
    assert read_from_bytesio(raw, encoding) == []


@pytest.mark.parametrize("encoding", ("utf-16", "utf-32"))
def test_bom_only_mmap_decodes_to_no_rows(workspace, encoding):
    # A zero byte file cannot be mmap-ed on every platform, so the mmap
    # path is exercised with a BOM only file, which decodes to empty text.
    raw = "".encode(encoding)
    path = os.path.join(workspace, "bom-only-%s.csv" % encoding)
    with open(path, "wb") as csv_file:
        csv_file.write(raw)

    with open(path, "r+b") as csv_file:
        memory_map = mmap.mmap(
            csv_file.fileno(), 0, access=mmap.ACCESS_READ
        )
        iterator = CSVMemoryMapIterator(memory_map, encoding)
        assert list(iterator) == []
        iterator.close()
        assert not memory_map.closed
        memory_map.close()


def test_close_releases_wrapper_without_closing_external_mmap(workspace):
    path = os.path.join(workspace, "ownership.csv")
    with open(path, "wb") as csv_file:
        csv_file.write("a,b\r\n".encode("utf-16"))

    with open(path, "r+b") as csv_file:
        memory_map = mmap.mmap(
            csv_file.fileno(), 0, access=mmap.ACCESS_READ
        )
        cells = get_data(
            memory_map, file_type="csv", encoding="utf-16"
        )["csv"]
        assert cells == [["a", "b"]]
        assert not memory_map.closed
        memory_map.close()


def test_unsupported_encoding_is_rejected():
    with pytest.raises(Exception):
        CSVMemoryMapIterator(None, "latin-1")
