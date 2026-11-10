"""
pyexcel_io.csvz_manifest
~~~~~~~~~~~~~~~~~~~~~~~~~

Optional manifest for csvz/tsvz packages.

A manifest is a JSON member inside the zip archive that describes,
for every table, its member path, sheet name, encoding and full CSV
dialect. It only describes data formats: it never executes code and
never names plugins or dialects to be imported.

:copyright: (c) 2014-2026 by C Wang
:license: New BSD License, see LICENSE for more details
"""

import csv
import json
import codecs

from pyexcel_io.exceptions import CSVZManifestError

MANIFEST_FILE_NAME = "pyexcel_csvz_manifest.json"
MANIFEST_FORMAT = "pyexcel-io-csvz-manifest"
MANIFEST_VERSION = 1

DIALECT_KEYS = (
    "delimiter",
    "quotechar",
    "escapechar",
    "doublequote",
    "skipinitialspace",
    "lineterminator",
    "quoting",
)

DEFAULT_DIALECT = {
    "delimiter": ",",
    "quotechar": '"',
    "escapechar": None,
    "doublequote": True,
    "skipinitialspace": False,
    "lineterminator": "\r\n",
    "quoting": csv.QUOTE_MINIMAL,
}

CONFIG_KEYS = ("encoding", "dialect") + DIALECT_KEYS

SOURCE_OVERRIDE = "override"
SOURCE_MANIFEST = "manifest"
SOURCE_GLOBAL = "global"
SOURCE_DEFAULT = "default"

_TOP_LEVEL_KEYS = ("format", "version", "tables")
_TABLE_KEYS = ("path", "sheet", "encoding", "dialect")
_REQUIRED_TABLE_KEYS = ("path", "sheet")

_VALID_QUOTING = {
    csv.QUOTE_MINIMAL,
    csv.QUOTE_ALL,
    csv.QUOTE_NONNUMERIC,
    csv.QUOTE_NONE,
}
for _name in ("QUOTE_NOTNULL", "QUOTE_STRINGS"):
    if hasattr(csv, _name):
        _VALID_QUOTING.add(getattr(csv, _name))


def build_manifest(tables):
    """assemble a manifest document out of table records"""
    return {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "tables": list(tables),
    }


def dump_manifest(tables):
    """serialize table records into manifest json text"""
    return json.dumps(build_manifest(tables), ensure_ascii=False, indent=2)


def try_load_manifest(raw_bytes):
    """
    Return a validated manifest dict, or None when the member is an
    ordinary file which merely shares the manifest file name.

    A member is only a manifest when it is a json object carrying our
    format marker. Anything else is not guessed to be a manifest.
    """
    try:
        document = json.loads(raw_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    if document.get("format") != MANIFEST_FORMAT:
        return None
    return document


def validate_manifest(manifest, member_names):
    """
    Validate a manifest against the zip member names.

    All problems are reported before any data is read.
    """
    version = manifest.get("version")
    if version != MANIFEST_VERSION:
        raise CSVZManifestError(
            "Unsupported csvz manifest version: %r. "
            "This reader supports version %d." % (version, MANIFEST_VERSION)
        )
    for key in manifest:
        if key not in _TOP_LEVEL_KEYS:
            raise CSVZManifestError(
                "Unknown field %r in csvz manifest" % key
            )
    tables = manifest.get("tables")
    if not isinstance(tables, list):
        raise CSVZManifestError("csvz manifest 'tables' must be a list")
    seen_paths = set()
    seen_sheets = set()
    for table in tables:
        if not isinstance(table, dict):
            raise CSVZManifestError(
                "csvz manifest table entries must be objects"
            )
        for key in table:
            if key not in _TABLE_KEYS:
                raise CSVZManifestError(
                    "Unknown field %r in csvz manifest table" % key
                )
        for key in _REQUIRED_TABLE_KEYS:
            if key not in table:
                raise CSVZManifestError(
                    "Missing required field %r in csvz manifest table" % key
                )
        path = table["path"]
        sheet = table["sheet"]
        if not isinstance(path, str) or not isinstance(sheet, str):
            raise CSVZManifestError(
                "csvz manifest 'path' and 'sheet' must be strings"
            )
        if path not in member_names:
            raise CSVZManifestError(
                "csvz manifest member %r does not exist in the archive"
                % path
            )
        if path in seen_paths:
            raise CSVZManifestError(
                "Duplicate member path %r in csvz manifest" % path
            )
        if sheet in seen_sheets:
            raise CSVZManifestError(
                "Duplicate sheet name %r in csvz manifest" % sheet
            )
        seen_paths.add(path)
        seen_sheets.add(sheet)
        encoding = table.get("encoding")
        if encoding is not None:
            if not isinstance(encoding, str):
                raise CSVZManifestError(
                    "csvz manifest 'encoding' must be a string"
                )
            try:
                codecs.lookup(encoding)
            except LookupError:
                raise CSVZManifestError(
                    "Unknown encoding %r in csvz manifest" % encoding
                )
        dialect = table.get("dialect")
        if dialect is not None:
            _validate_dialect(dialect)
    return tables


def _validate_dialect(dialect):
    if not isinstance(dialect, dict):
        raise CSVZManifestError(
            "csvz manifest 'dialect' must be an object of explicit "
            "csv parameters, not a name to look up"
        )
    for key, value in dialect.items():
        if key not in DIALECT_KEYS:
            raise CSVZManifestError(
                "Unknown field %r in csvz manifest dialect" % key
            )
        if key in ("delimiter", "quotechar", "escapechar"):
            if value is not None and not (
                isinstance(value, str) and len(value) == 1
            ):
                raise CSVZManifestError(
                    "csv dialect field %r must be a one character string"
                    % key
                )
        elif key in ("doublequote", "skipinitialspace"):
            if not isinstance(value, bool):
                raise CSVZManifestError(
                    "csv dialect field %r must be a boolean" % key
                )
        elif key == "lineterminator":
            if not isinstance(value, str):
                raise CSVZManifestError(
                    "csv dialect field %r must be a string" % key
                )
        elif key == "quoting":
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value not in _VALID_QUOTING
            ):
                raise CSVZManifestError(
                    "csv dialect field 'quoting' must be one of %r"
                    % sorted(_VALID_QUOTING)
                )


def resolve_writer_dialect(keywords):
    """work out the full csv dialect a sheet writer actually uses"""
    dialect = dict(DEFAULT_DIALECT)
    dialect_name = keywords.get("dialect")
    if dialect_name:
        named = csv.get_dialect(dialect_name)
        for key in DIALECT_KEYS:
            dialect[key] = getattr(named, key)
    for key in DIALECT_KEYS:
        if key in keywords:
            dialect[key] = keywords[key]
    return dialect


def resolve_table_config(manifest_entry, overrides, global_keywords):
    """
    Resolve the effective configuration of one table.

    Priority: explicit per-table overrides beat the manifest, the
    manifest beats global parameters, and global parameters are only
    defaults for values the manifest does not declare.

    Returns a (parameters, sources) pair where sources tells, for
    every parameter, which layer won: "override", "manifest",
    "global" or "default".
    """
    overrides = overrides or {}
    global_keywords = global_keywords or {}
    manifest_values = {}
    if manifest_entry:
        if manifest_entry.get("encoding") is not None:
            manifest_values["encoding"] = manifest_entry["encoding"]
        for key, value in (manifest_entry.get("dialect") or {}).items():
            manifest_values[key] = value
    parameters = {}
    sources = {}
    for key in CONFIG_KEYS:
        if key in overrides:
            parameters[key] = overrides[key]
            sources[key] = SOURCE_OVERRIDE
        elif key in manifest_values:
            parameters[key] = manifest_values[key]
            sources[key] = SOURCE_MANIFEST
        elif key in global_keywords:
            parameters[key] = global_keywords[key]
            sources[key] = SOURCE_GLOBAL
        elif key in DIALECT_KEYS and global_keywords.get("dialect"):
            named = csv.get_dialect(global_keywords["dialect"])
            parameters[key] = getattr(named, key)
            sources[key] = SOURCE_GLOBAL
        elif key in DEFAULT_DIALECT:
            parameters[key] = DEFAULT_DIALECT[key]
            sources[key] = SOURCE_DEFAULT
        else:
            parameters[key] = None
            sources[key] = SOURCE_DEFAULT
    return parameters, sources
