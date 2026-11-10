# -*- coding: utf-8 -*-
"""tests for the incremental streaming mode of the csvz/tsvz reader"""
import io
import zipfile

import pytest

from pyexcel_io.constants import KEYWORD_DETECT_PREFIX_SIZE, KEYWORD_STREAMING
from pyexcel_io.reader import Reader
from pyexcel_io.readers.csvz import FileReader
from pyexcel_io._compact import BytesIO


def _write_zip(path, members):
    """create a small zip on disk with STORED members for byte accounting"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for member_name, content in members.items():
            archive.writestr(member_name, content)


def _open_streaming_reader(path, file_type="csvz", **keywords):
    reader = Reader(file_type)
    reader.open(path, **{KEYWORD_STREAMING: True, **keywords})
    return reader


def _rows(sheet):
    return [
        list(sheet.column_iterator(row))
        for row in sheet.row_iterator()
    ]


def _iter_rows(sheet):
    for row in sheet.row_iterator():
        yield list(sheet.column_iterator(row))


def test_streaming_matches_non_streaming(tmp_path):
    file_name = tmp_path / "book.csvz"
    _write_zip(
        file_name,
        {
            "Sheet 1.csv": b"a,b,c\r\n1,2,3\r\n4,5,6\r\n",
            "Sheet 2.csv": b"x,y\r\n8,9\r\n",
        },
    )
    eager_reader = Reader("csvz")
    eager_reader.open(str(file_name))
    expected = eager_reader.read_all()
    eager_reader.close()

    streaming_reader = _open_streaming_reader(str(file_name))
    actual = streaming_reader.read_all()
    actual_rows = (
        list(actual["Sheet 1"]),
        list(actual["Sheet 2"]),
    )
    streaming_reader.close()
    assert actual_rows == (
        list(expected["Sheet 1"]),
        list(expected["Sheet 2"]),
    )


def test_first_row_does_not_decompress_the_whole_member(tmp_path):
    file_name = tmp_path / "large.csvz"
    row = b",".join([b"v%d" % index for index in range(20)]) + b"\r\n"
    big_content = row * 500
    _write_zip(
        file_name,
        {"big.csv": big_content, "untouched.csv": b"a,b\r\n1,2\r\n"},
    )

    class CountingExtFile:
        read_bytes = 0

        def __init__(self, real_ext_file):
            self._real_ext_file = real_ext_file

        def read(self, size=-1):
            chunk = self._real_ext_file.read(size)
            CountingExtFile.read_bytes += len(chunk)
            return chunk

        def close(self):
            self._real_ext_file.close()

    native_reader = FileReader(
        str(file_name), "csvz", **{KEYWORD_STREAMING: True}
    )
    opened_members = []
    original_open = native_reader.zipfile.open

    def tracking_open(member_name, *args, **keywords):
        opened_members.append(member_name)
        return CountingExtFile(original_open(member_name, *args, **keywords))

    native_reader.zipfile.open = tracking_open
    try:
        sheet_reader = native_reader.read_sheet(0)
        iterator = _iter_rows(sheet_reader)
        first_row = next(iterator)
        assert first_row == ["v%d" % index for index in range(20)]
        # only the detect prefix plus the first buffered lines are touched
        assert CountingExtFile.read_bytes < len(big_content) // 2
        assert opened_members == ["big.csv"]
        # draining the rest eventually reads every byte
        remaining = list(iterator)
        assert len(remaining) == 499
        assert CountingExtFile.read_bytes == len(big_content)
    finally:
        native_reader.close()


def test_interleaved_sheets_stay_independent(tmp_path):
    file_name = tmp_path / "interleaved.csvz"
    sheet_one = "".join(
        "a%d,b%d\r\n" % (index, index) for index in range(20)
    ).encode("utf-8")
    sheet_two = "".join(
        "x%d,y%d\r\n" % (index, index) for index in range(30)
    ).encode("utf-8")
    _write_zip(
        file_name,
        {"one.csv": sheet_one, "two.csv": sheet_two},
    )

    streaming_reader = _open_streaming_reader(str(file_name))
    first = streaming_reader.reader.read_sheet(0)
    second = streaming_reader.reader.read_sheet(1)

    first_rows = _rows(first)
    second_rows = _rows(second)
    assert first_rows == [
        ["a%d" % index, "b%d" % index] for index in range(20)
    ]
    assert second_rows == [
        ["x%d" % index, "y%d" % index] for index in range(30)
    ]

    first.close()
    second.close()
    streaming_reader.close()


def test_closing_one_sheet_keeps_the_other_open(tmp_path):
    file_name = tmp_path / "independent_close.csvz"
    _write_zip(
        file_name,
        {
            "one.csv": b"a\r\n1\r\n2\r\n",
            "two.csv": b"b\r\n3\r\n4\r\n",
        },
    )
    streaming_reader = _open_streaming_reader(str(file_name))
    first = streaming_reader.reader.read_sheet(0)
    second = streaming_reader.reader.read_sheet(1)

    first_iter = _iter_rows(first)
    second_iter = _iter_rows(second)
    assert next(first_iter) == ["a"]
    assert next(second_iter) == ["b"]
    first.close()
    assert next(second_iter) == [3]
    assert list(second_iter) == [[4]]
    second.close()
    streaming_reader.close()


def test_parent_reader_closes_sheet_streams(tmp_path):
    file_name = tmp_path / "parent_close.csvz"
    _write_zip(file_name, {"one.csv": b"a\r\n1\r\n", "two.csv": b"b\r\n2\r\n"})
    streaming_reader = _open_streaming_reader(str(file_name))
    first = streaming_reader.reader.read_sheet(0)
    second = streaming_reader.reader.read_sheet(1)
    _rows(first)
    _rows(second)
    text_stream = first._text_stream
    assert not text_stream.closed
    streaming_reader.close()
    assert text_stream.closed
    assert second._text_stream.closed


def test_external_container_stream_is_not_owned(tmp_path):
    file_name = tmp_path / "memory.csvz"
    _write_zip(file_name, {"one.csv": b"a,b\r\n1,2\r\n"})
    container = BytesIO(file_name.read_bytes())
    streaming_reader = Reader("csvz")
    streaming_reader.open_stream(container, **{KEYWORD_STREAMING: True})
    data = streaming_reader.read_all()
    rows = list(data["one"])
    streaming_reader.close()
    assert rows == [["a", "b"], [1, 2]]
    assert not container.closed
    container.close()


def test_duplicate_sheet_names_are_rejected_at_open(tmp_path):
    file_name = tmp_path / "duplicates.csvz"
    _write_zip(
        file_name,
        {"same.csv": b"a\r\n", "same.tsv": b"b\r\n"},
    )
    with pytest.raises(ValueError, match="Duplicate sheet names"):
        _open_streaming_reader(str(file_name))

    # the legacy eager path keeps its previous behavior
    eager_reader = Reader("csvz")
    eager_reader.open(str(file_name))
    assert eager_reader.reader.sheet_names() == ["same", "same"]
    eager_reader.close()


def test_unselected_sheet_is_never_opened(tmp_path):
    file_name = tmp_path / "selective.csvz"
    _write_zip(
        file_name,
        {"picked.csv": b"a\r\n1\r\n", "skipped.csv": b"b\r\n2\r\n"},
    )
    native_reader = FileReader(
        str(file_name), "csvz", **{KEYWORD_STREAMING: True}
    )
    opened_members = []
    original_open = native_reader.zipfile.open

    def tracking_open(member_name, *args, **keywords):
        opened_members.append(member_name)
        return original_open(member_name, *args, **keywords)

    native_reader.zipfile.open = tracking_open
    try:
        sheet = native_reader.read_sheet(0)
        assert _rows(sheet) == [["a"], [1]]
        assert opened_members == ["picked.csv"]
    finally:
        native_reader.close()


def test_explicit_encoding_is_strict_and_never_revisited(tmp_path):
    file_name = tmp_path / "strict.csvz"
    good_rows = "".join(
        "好,的\r\n" for _ in range(2000)
    ).encode("gbk")
    bad_tail = b"\xff\xfe\x80\r\n"
    _write_zip(file_name, {"strict.csv": good_rows + bad_tail})
    streaming_reader = _open_streaming_reader(
        str(file_name), encoding="gbk", **{KEYWORD_DETECT_PREFIX_SIZE: 30}
    )
    sheet_reader = streaming_reader.reader.read_sheet(0)
    iterator = _iter_rows(sheet_reader)
    assert next(iterator) == ["好", "的"]
    assert next(iterator) == ["好", "的"]
    consumed = 2
    with pytest.raises(UnicodeDecodeError):
        for _ in iterator:
            consumed += 1
    assert consumed < 2000
    streaming_reader.close()


def test_detection_failure_raises_value_error(tmp_path):
    file_name = tmp_path / "undetectable.csvz"
    _write_zip(file_name, {"empty.csv": b""})
    streaming_reader = _open_streaming_reader(str(file_name))
    with pytest.raises(ValueError, match="Failed to detect the encoding"):
        _rows(streaming_reader.reader.read_sheet(0))
    streaming_reader.close()


def test_bom_based_detection_does_not_lose_bytes(tmp_path):
    file_name = tmp_path / "bom.csvz"
    content = "中,文\r\n1,2\r\n".encode("utf-8-sig")
    _write_zip(file_name, {"bom.csv": content})
    streaming_reader = _open_streaming_reader(
        str(file_name), **{KEYWORD_DETECT_PREFIX_SIZE: 4}
    )
    data = streaming_reader.read_all()
    rows = list(data["bom"])
    streaming_reader.close()
    assert rows == [["中", "文"], [1, 2]]


def test_prefix_boundary_inside_multibyte_character(tmp_path):
    file_name = tmp_path / "boundary.csvz"
    content = "中文,数据\r\n第二,行\r\n".encode("utf-8")
    _write_zip(file_name, {"boundary.csv": content})
    streaming_reader = _open_streaming_reader(
        str(file_name), **{KEYWORD_DETECT_PREFIX_SIZE: 7}
    )
    data = streaming_reader.read_all()
    rows = list(data["boundary"])
    streaming_reader.close()
    assert rows == [["中文", "数据"], ["第二", "行"]]


def test_utf16_and_utf32_boms(tmp_path):
    for encoding in ("utf-16", "utf-32"):
        file_name = tmp_path / ("wide_%s.csvz" % encoding.replace("-", "_"))
        content = "中,文\r\n1,2\r\n".encode(encoding)
        _write_zip(file_name, {"wide.csv": content})
        streaming_reader = _open_streaming_reader(str(file_name))
        data = streaming_reader.read_all()
        rows = list(data["wide"])
        streaming_reader.close()
        assert rows == [["中", "文"], [1, 2]]


def test_chardet_detection_without_bom(tmp_path):
    file_name = tmp_path / "gbk.csvz"
    content = "中文,数值\r\n数据,1\r\n".encode("gbk")
    _write_zip(file_name, {"gbk.csv": content})
    streaming_reader = _open_streaming_reader(str(file_name))
    data = streaming_reader.read_all()
    rows = list(data["gbk"])
    streaming_reader.close()
    assert rows == [["中文", "数值"], ["数据", 1]]


def test_tsv_streaming_uses_tab_dialect(tmp_path):
    file_name = tmp_path / "book.tsvz"
    _write_zip(file_name, {"sheet.tsv": "a\tb\r\n1\t2\r\n".encode("utf-8")})
    streaming_reader = _open_streaming_reader(str(file_name), "tsvz")
    data = streaming_reader.read_all()
    rows = list(data["sheet"])
    streaming_reader.close()
    assert rows == [["a", "b"], [1, 2]]


def test_quoted_newlines_blank_lines_and_filters(tmp_path):
    file_name = tmp_path / "quoted.csvz"
    content = (
        b'a,b\r\n'
        b'"line1\nline2",x\r\n'
        b'\r\n'
        b'1,2\r\n'
        b'3,4\r\n'
    )
    _write_zip(file_name, {"quoted.csv": content})
    streaming_reader = _open_streaming_reader(
        str(file_name),
        start_row=1,
        row_limit=3,
        start_column=1,
        skip_empty_rows=True,
    )
    data = streaming_reader.read_all()
    rows = list(data["quoted"])
    streaming_reader.close()
    assert rows == [["x"], [2]]


def test_auto_detect_and_keep_trailing_empty_cells(tmp_path):
    file_name = tmp_path / "types.csvz"
    _write_zip(
        file_name,
        {"types.csv": b"1,2.5,text,\r\n2026-11-10,2,\r\n"},
    )
    streaming_reader = _open_streaming_reader(
        str(file_name), keep_trailing_empty_cells=True
    )
    data = streaming_reader.read_all()
    rows = list(data["types"])
    streaming_reader.close()
    assert rows[0] == [1, 2.5, "text", ""]
    assert rows[1][0] is not None


def test_crc_error_at_the_tail_is_reported(tmp_path):
    file_name = tmp_path / "broken.csvz"
    content = b"a,b\r\n" + b"1,2\r\n" * 2000
    _write_zip(file_name, {"broken.csv": content})
    raw = bytearray(file_name.read_bytes())
    with zipfile.ZipFile(io.BytesIO(bytes(raw)), "r") as archive:
        info = archive.getinfo("broken.csv")
        local_header_offset = info.header_offset
    # corrupt a byte in the local file data, not in its zip metadata
    data_offset = local_header_offset + 30 + len("broken.csv")
    assert info.file_size > 4096
    corrupt_offset = data_offset + info.file_size - 4
    assert corrupt_offset - data_offset > 4096
    raw[corrupt_offset] ^= 0xFF
    file_name.write_bytes(bytes(raw))

    streaming_reader = _open_streaming_reader(str(file_name))
    sheet = streaming_reader.reader.read_sheet(0)
    # the prefix read succeeds; the failure only surfaces at the tail
    iterator = _iter_rows(sheet)
    assert next(iterator) == ["a", "b"]
    with pytest.raises(zipfile.BadZipFile):
        list(iterator)
    streaming_reader.close()


def test_legacy_mode_remains_eager(tmp_path):
    file_name = tmp_path / "legacy.csvz"
    _write_zip(file_name, {"legacy.csv": b"a,b\r\n1,2\r\n"})
    eager_reader = Reader("csvz")
    eager_reader.open(str(file_name))
    data = eager_reader.read_all()
    assert list(data["legacy"]) == [["a", "b"], [1, 2]]
    eager_reader.close()
