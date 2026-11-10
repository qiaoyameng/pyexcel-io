import zipfile

from pyexcel_io import constants
from pyexcel_io import csvz_manifest
from pyexcel_io.plugin_api import IWriter
from pyexcel_io.writers.csvz_sheet import CSVZipSheetWriter


class CsvZipWriter(IWriter):
    """
    csvz writer

    It is better to store csv files as a csvz as it saves your disk space.
    Pyexcel-io had the facility to unzip it for you or you could use
    any other unzip software.

    When write_manifest is switched on, a manifest member is added to
    the archive, recording each table's member path, sheet name,
    encoding and full csv dialect. Per sheet settings, e.g. encoding
    or dialect parameters, can be given through sheet_settings, a
    dictionary keyed by sheet name.
    """

    def __init__(
        self,
        file_name,
        file_type,
        write_manifest=False,
        sheet_settings=None,
        **keywords
    ):
        self._file_type = file_type
        self.zipfile = zipfile.ZipFile(file_name, "w", zipfile.ZIP_DEFLATED)
        self._keywords = keywords
        if file_type == constants.FILE_FORMAT_TSVZ:
            self._keywords["dialect"] = constants.KEYWORD_TSV_DIALECT
        self._write_manifest = write_manifest
        self._sheet_settings = sheet_settings or {}
        self._manifest_tables = []

    def create_sheet(self, name):
        given_name = name
        if given_name is None:
            given_name = constants.DEFAULT_SHEET_NAME
        keywords = dict(self._keywords)
        keywords.update(self._sheet_settings.get(given_name, {}))
        writer = CSVZipSheetWriter(
            self.zipfile, given_name, self._file_type[:3], **keywords
        )
        if self._write_manifest:
            writer.manifest_recorder = self._record_table
        return writer

    def _record_table(self, path, sheet, encoding, dialect):
        self._manifest_tables.append(
            {
                "path": path,
                "sheet": sheet,
                "encoding": encoding,
                "dialect": dialect,
            }
        )

    def close(self):
        if self.zipfile:
            if self._write_manifest:
                self.zipfile.writestr(
                    csvz_manifest.MANIFEST_FILE_NAME,
                    csvz_manifest.dump_manifest(self._manifest_tables),
                )
            self.zipfile.close()
