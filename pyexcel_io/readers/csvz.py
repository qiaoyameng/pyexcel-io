"""
pyexcel_io.fileformat.csvz
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The lower level csvz file format handler.

:copyright: (c) 2014-2026 by C Wang
:license: New BSD License, see LICENSE for more details
"""

import codecs
import io
import zipfile
from io import BytesIO

try:
    import chardet
except ImportError:
    print("Please install chardet so as to use csvz")
    raise
from pyexcel_io import constants
from pyexcel_io.sheet import NamedContent
from pyexcel_io._compact import StringIO
from pyexcel_io.readers.csv_sheet import CSVinMemoryReader, CSVSheetReader
from pyexcel_io.plugin_api.abstract_reader import IReader


# UTF-32 BOMs must be checked before UTF-16 BOMs because the UTF-16 LE
# BOM is a prefix of the UTF-32 LE BOM.
_BOM_ENCODINGS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _detect_encoding(prefix):
    """detect the encoding from a bounded byte prefix

    BOM is honored first. chardet is only consulted on the given prefix,
    so no more than ``detect_prefix_size`` bytes are buffered ahead of
    line iteration.
    """
    for bom, bom_encoding in _BOM_ENCODINGS:
        if prefix.startswith(bom):
            return bom_encoding
    detected = chardet.detect(prefix)
    encoding = detected.get("encoding")
    if not encoding:
        raise ValueError(
            "Failed to detect the encoding of the csvz member from its "
            "first %d byte(s). Please specify an explicit encoding."
            % len(prefix)
        )
    return encoding


class _PrefixedZipBinaryReader(io.BufferedIOBase):
    """binary view over a ZipExtFile that replays a buffered prefix

    The bytes already consumed for encoding detection are replayed first,
    so no decompressed byte is lost. All further reads are delegated to
    the ZipExtFile incrementally.
    """

    def __init__(self, zip_ext_file, prefix):
        super().__init__()
        self._zip_ext_file = zip_ext_file
        self._prefix = prefix

    def readable(self):
        return True

    def read1(self, size=-1):
        return self.read(size)

    def read(self, size=-1):
        if self._prefix:
            if size is None or size < 0:
                chunk = self._prefix + self._zip_ext_file.read()
                self._prefix = b""
                return chunk
            take = min(len(self._prefix), size)
            chunk = self._prefix[:take]
            self._prefix = self._prefix[take:]
            if take == size:
                return chunk
            return chunk + self._zip_ext_file.read(size - take)
        return self._zip_ext_file.read(size)

    def close(self):
        if not self.closed:
            super().close()
            self._zip_ext_file.close()


def _open_zip_member_text_stream(
    zip_file, member_name, encoding, detect_prefix_size
):
    """open one zip member as an incrementally decoded text stream"""
    zip_ext_file = zip_file.open(member_name, "r")
    try:
        prefix = zip_ext_file.read(detect_prefix_size)
    except BaseException:
        zip_ext_file.close()
        raise
    if encoding is None:
        encoding = _detect_encoding(prefix)
    binary_reader = _PrefixedZipBinaryReader(zip_ext_file, prefix)
    return io.TextIOWrapper(
        binary_reader,
        encoding=encoding,
        errors="strict",
        newline="",
    )


class CSVZipSheetReader(CSVSheetReader):
    """stream one csvz/tsvz member line by line

    The zip member is decompressed incrementally. The encoding is decided
    once, from either the explicit ``encoding`` keyword or the bounded
    prefix detection, and never revisited: later illegal bytes raise
    ``UnicodeDecodeError`` under strict error handling.
    """

    def __init__(
        self,
        sheet,
        zip_file,
        member_name,
        detect_prefix_size=constants.DEFAULT_CSVZ_DETECT_PREFIX_SIZE,
        **keywords
    ):
        explicit_encoding = keywords.pop("encoding", None)
        super().__init__(
            sheet, encoding=explicit_encoding or "utf-8", **keywords
        )
        self._text_stream = _open_zip_member_text_stream(
            zip_file,
            member_name,
            explicit_encoding,
            detect_prefix_size,
        )

    def get_file_handle(self):
        return self._text_stream

    def close(self):
        try:
            super().close()
        finally:
            self._text_stream.close()


def _ensure_unique_sheet_names(sheets):
    seen = set()
    duplicates = []
    for sheet in sheets:
        if sheet.name in seen and sheet.name not in duplicates:
            duplicates.append(sheet.name)
        seen.add(sheet.name)
    if duplicates:
        raise ValueError(
            "Duplicate sheet names found in the csvz archive: %s. "
            "Streaming mode requires unique sheet names."
            % ", ".join(duplicates)
        )


class FileReader(IReader):
    def __init__(self, file_alike_object, file_type, **keywords):
        self.content_array = []
        self.handles = []
        self.streaming = keywords.pop(constants.KEYWORD_STREAMING, False)
        self.detect_prefix_size = keywords.pop(
            constants.KEYWORD_DETECT_PREFIX_SIZE,
            constants.DEFAULT_CSVZ_DETECT_PREFIX_SIZE,
        )
        try:
            self.zipfile = zipfile.ZipFile(file_alike_object, "r")
            sheets = [
                NamedContent(_get_sheet_name(name), name)
                for name in self.zipfile.namelist()
            ]
            if self.streaming:
                try:
                    _ensure_unique_sheet_names(sheets)
                except ValueError:
                    self.zipfile.close()
                    raise
            self.content_array = sheets
            self.keywords = keywords
            if file_type == constants.FILE_FORMAT_TSVZ:
                self.keywords["dialect"] = constants.KEYWORD_TSV_DIALECT

        except zipfile.BadZipfile:
            print("StringIO instance was passed by any chance?")
            raise

    def read_sheet(self, index):
        named_content = self.content_array[index]
        if self.streaming:
            reader = CSVZipSheetReader(
                named_content,
                self.zipfile,
                named_content.payload,
                detect_prefix_size=self.detect_prefix_size,
                **self.keywords
            )
            self.handles.append(reader)
            return reader

        name = named_content.name
        content = self.zipfile.read(named_content.payload)
        encoding_guess = chardet.detect(content)
        sheet = StringIO(content.decode(encoding_guess["encoding"]))

        return CSVinMemoryReader(NamedContent(name, sheet), **self.keywords)

    def close(self):
        for reader in self.handles:
            reader.close()
        self.handles = []
        if self.zipfile:
            self.zipfile.close()


class ContentReader(FileReader):
    def __init__(self, file_content, file_type, **keywords):
        io = BytesIO(file_content)
        super().__init__(io, file_type, **keywords)


def _get_sheet_name(filename):
    len_of_a_dot = 1
    len_of_csv_word = 3
    name_len = len(filename) - len_of_a_dot - len_of_csv_word
    return filename[:name_len]
