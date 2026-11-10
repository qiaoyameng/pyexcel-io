"""
pyexcel_io.fileformat.csvz
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The lower level csvz file format handler.

:copyright: (c) 2014-2026 by C Wang
:license: New BSD License, see LICENSE for more details
"""

import zipfile
from io import BytesIO

try:
    import chardet
except ImportError:
    print("Please install chardet so as to use csvz")
    raise
from pyexcel_io import constants
from pyexcel_io import csvz_manifest
from pyexcel_io.sheet import NamedContent
from pyexcel_io._compact import StringIO
from pyexcel_io.readers.csv_sheet import CSVinMemoryReader
from pyexcel_io.plugin_api.abstract_reader import IReader


class FileReader(IReader):
    def __init__(self, file_alike_object, file_type, **keywords):
        self.content_array = []
        try:
            self.zipfile = zipfile.ZipFile(file_alike_object, "r")
            self.keywords = keywords
            if file_type == constants.FILE_FORMAT_TSVZ:
                self.keywords["dialect"] = constants.KEYWORD_TSV_DIALECT
            self.sheet_overrides = self.keywords.pop("sheet_overrides", None)
            if self.sheet_overrides is None:
                self.sheet_overrides = {}
            self.manifest = None
            self._tables = None
            self._resolved = []
            member_names = self.zipfile.namelist()
            if csvz_manifest.MANIFEST_FILE_NAME in member_names:
                manifest = csvz_manifest.try_load_manifest(
                    self.zipfile.read(csvz_manifest.MANIFEST_FILE_NAME)
                )
                if manifest is not None:
                    self.manifest = manifest
                    self._tables = csvz_manifest.validate_manifest(
                        manifest, member_names
                    )
            if self._tables is not None:
                # with a manifest, only declared members are tables;
                # unrelated files in the archive are left alone.
                self.content_array = [
                    NamedContent(table["sheet"], table["path"])
                    for table in self._tables
                ]
            else:
                self.content_array = [
                    NamedContent(_get_sheet_name(name), name)
                    for name in member_names
                ]
            for index, content in enumerate(self.content_array):
                entry = self._tables[index] if self._tables else None
                self._resolved.append(
                    csvz_manifest.resolve_table_config(
                        entry,
                        self.sheet_overrides.get(content.name),
                        self.keywords,
                    )
                )

        except zipfile.BadZipfile:
            print("StringIO instance was passed by any chance?")
            raise

    def close(self):
        if self.zipfile:
            self.zipfile.close()

    def sheet_config(self, sheet):
        """
        Query the effective configuration of a sheet.

        Accepts a sheet name or an index and reports every resolved
        parameter along with the layer it came from: "override",
        "manifest", "global" or "default".
        """
        if isinstance(sheet, int):
            index = sheet
        else:
            index = self.sheet_names().index(sheet)
        parameters, sources = self._resolved[index]
        return {
            "sheet": self.content_array[index].name,
            "path": self.content_array[index].payload,
            "manifest": self.manifest is not None,
            "parameters": dict(parameters),
            "sources": dict(sources),
        }

    def read_sheet(self, index):
        name = self.content_array[index].name
        content = self.zipfile.read(self.content_array[index].payload)
        parameters, sources = self._resolved[index]
        encoding = parameters.get("encoding")
        declared = sources["encoding"] in (
            csvz_manifest.SOURCE_OVERRIDE,
            csvz_manifest.SOURCE_MANIFEST,
        ) or (self.manifest is not None and encoding)
        if declared:
            sheet = StringIO(content.decode(encoding))
        else:
            # legacy packages keep the original auto detection
            encoding_guess = chardet.detect(content)
            sheet = StringIO(content.decode(encoding_guess["encoding"]))
        keywords = dict(self.keywords)
        for key in csvz_manifest.DIALECT_KEYS:
            if sources[key] in (
                csvz_manifest.SOURCE_OVERRIDE,
                csvz_manifest.SOURCE_MANIFEST,
            ):
                keywords[key] = parameters[key]

        return CSVinMemoryReader(NamedContent(name, sheet), **keywords)


class ContentReader(FileReader):
    def __init__(self, file_content, file_type, **keywords):
        io = BytesIO(file_content)
        super().__init__(io, file_type, **keywords)


def _get_sheet_name(filename):
    len_of_a_dot = 1
    len_of_csv_word = 3
    name_len = len(filename) - len_of_a_dot - len_of_csv_word
    return filename[:name_len]
