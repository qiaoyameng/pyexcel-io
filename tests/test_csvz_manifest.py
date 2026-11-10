# -*- coding: utf-8 -*-
import csv
import json
import zipfile

import pytest

from pyexcel_io import csvz_manifest
from pyexcel_io.reader import Reader
from pyexcel_io.writer import Writer
from pyexcel_io.exceptions import CSVZManifestError
from pyexcel_io._compact import OrderedDict


def make_demo_book(file_name):
    """a csvz with two encodings and two quoting rules"""
    content = OrderedDict()
    content.update(
        {
            "utf8-minimal": [
                ["name", "note", "score"],
                ["中,文", "plain", 1],
                ['quote "here"', "tail", 2],
            ]
        }
    )
    content.update(
        {
            "utf16-all": [
                ["city", "remark", "rank"],
                ["北京", "semi;colon", 3],
                ["上海", "none", 4],
            ]
        }
    )
    writer = Writer("csvz")
    writer.open(
        file_name,
        write_manifest=True,
        sheet_settings={
            "utf16-all": {
                "encoding": "utf-16",
                "delimiter": ";",
                "quoting": csv.QUOTE_ALL,
            }
        },
    )
    writer.write(content)
    writer.close()
    return content


EXPECTED = {
    "utf8-minimal": [
        ["name", "note", "score"],
        ["中,文", "plain", 1],
        ['quote "here"', "tail", 2],
    ],
    "utf16-all": [
        ["city", "remark", "rank"],
        ["北京", "semi;colon", 3],
        ["上海", "none", 4],
    ],
}


def check_demo_book(reader):
    handle = reader.reader
    assert handle.sheet_names() == ["utf8-minimal", "utf16-all"]

    utf8 = handle.sheet_config("utf8-minimal")
    assert utf8["path"] == "utf8-minimal.csv"
    assert utf8["manifest"] is True
    assert utf8["parameters"]["encoding"] == "utf-8"
    assert utf8["parameters"]["delimiter"] == ","
    assert utf8["parameters"]["quoting"] == csv.QUOTE_MINIMAL
    assert utf8["sources"]["encoding"] == "manifest"
    assert utf8["sources"]["quoting"] == "manifest"

    utf16 = handle.sheet_config("utf16-all")
    assert utf16["path"] == "utf16-all.csv"
    assert utf16["parameters"]["encoding"] == "utf-16"
    assert utf16["parameters"]["delimiter"] == ";"
    assert utf16["parameters"]["quoting"] == csv.QUOTE_ALL
    assert utf16["sources"]["delimiter"] == "manifest"

    data = reader.read_all()
    data = {name: [list(row) for row in rows] for name, rows in data.items()}
    assert data == EXPECTED


def test_manifest_is_written(tmp_path):
    file_name = str(tmp_path / "demo.csvz")
    make_demo_book(file_name)
    archive = zipfile.ZipFile(file_name, "r")
    assert csvz_manifest.MANIFEST_FILE_NAME in archive.namelist()
    manifest = json.loads(
        archive.read(csvz_manifest.MANIFEST_FILE_NAME).decode("utf-8")
    )
    archive.close()
    assert manifest["format"] == csvz_manifest.MANIFEST_FORMAT
    assert manifest["version"] == csvz_manifest.MANIFEST_VERSION
    tables = {table["sheet"]: table for table in manifest["tables"]}
    assert tables["utf8-minimal"]["path"] == "utf8-minimal.csv"
    assert tables["utf8-minimal"]["encoding"] == "utf-8"
    assert tables["utf8-minimal"]["dialect"]["quoting"] == csv.QUOTE_MINIMAL
    assert tables["utf16-all"]["path"] == "utf16-all.csv"
    assert tables["utf16-all"]["encoding"] == "utf-16"
    assert tables["utf16-all"]["dialect"]["delimiter"] == ";"
    assert tables["utf16-all"]["dialect"]["quoting"] == csv.QUOTE_ALL
    assert tables["utf16-all"]["dialect"]["quotechar"] == '"'


def test_demo_book_read_via_file_path(tmp_path):
    file_name = str(tmp_path / "demo.csvz")
    make_demo_book(file_name)
    reader = Reader("csvz")
    reader.open(file_name)
    check_demo_book(reader)
    reader.close()


def test_demo_book_read_via_file_object(tmp_path):
    file_name = str(tmp_path / "demo.csvz")
    make_demo_book(file_name)
    with open(file_name, "rb") as file_object:
        reader = Reader("csvz")
        reader.open_stream(file_object)
        check_demo_book(reader)
        reader.close()


def test_demo_book_read_via_content(tmp_path):
    file_name = str(tmp_path / "demo.csvz")
    make_demo_book(file_name)
    with open(file_name, "rb") as file_object:
        content = file_object.read()
    reader = Reader("csvz")
    reader.open_content(content)
    check_demo_book(reader)
    reader.close()


def write_manifest_package(file_name, manifest, members):
    archive = zipfile.ZipFile(file_name, "w")
    for name, payload in members.items():
        archive.writestr(name, payload)
    if manifest is not None:
        archive.writestr(
            csvz_manifest.MANIFEST_FILE_NAME,
            json.dumps(manifest)
            if not isinstance(manifest, str)
            else manifest,
        )
    archive.close()


def valid_manifest(tables):
    return {
        "format": csvz_manifest.MANIFEST_FORMAT,
        "version": csvz_manifest.MANIFEST_VERSION,
        "tables": tables,
    }


def test_missing_member_rejected_before_reading(tmp_path):
    file_name = str(tmp_path / "bad.csvz")
    manifest = valid_manifest([{"path": "ghost.csv", "sheet": "Ghost"}])
    write_manifest_package(file_name, manifest, {"real.csv": "a,b\n"})
    with pytest.raises(CSVZManifestError, match="does not exist"):
        Reader("csvz").open(file_name)


def test_duplicate_path_rejected(tmp_path):
    file_name = str(tmp_path / "bad.csvz")
    manifest = valid_manifest(
        [
            {"path": "a.csv", "sheet": "One"},
            {"path": "a.csv", "sheet": "Two"},
        ]
    )
    write_manifest_package(file_name, manifest, {"a.csv": "a,b\n"})
    with pytest.raises(CSVZManifestError, match="Duplicate member path"):
        Reader("csvz").open(file_name)


def test_duplicate_sheet_name_rejected(tmp_path):
    file_name = str(tmp_path / "bad.csvz")
    manifest = valid_manifest(
        [
            {"path": "a.csv", "sheet": "Same"},
            {"path": "b.csv", "sheet": "Same"},
        ]
    )
    write_manifest_package(
        file_name, manifest, {"a.csv": "a\n", "b.csv": "b\n"}
    )
    with pytest.raises(CSVZManifestError, match="Duplicate sheet name"):
        Reader("csvz").open(file_name)


def test_unknown_fields_rejected(tmp_path):
    members = {"a.csv": "a\n"}
    manifests = (
        valid_manifest([{"path": "a.csv", "sheet": "A", "module": "os"}]),
        valid_manifest(
            [{"path": "a.csv", "sheet": "A", "dialect": {"plugin": "x"}}]
        ),
        dict(valid_manifest([{"path": "a.csv", "sheet": "A"}]), code="1+1"),
    )
    for manifest in manifests:
        file_name = str(tmp_path / "bad.csvz")
        write_manifest_package(file_name, manifest, members)
        with pytest.raises(CSVZManifestError, match="Unknown field"):
            Reader("csvz").open(file_name)


def test_missing_required_field_rejected(tmp_path):
    file_name = str(tmp_path / "bad.csvz")
    manifest = valid_manifest([{"path": "a.csv"}])
    write_manifest_package(file_name, manifest, {"a.csv": "a\n"})
    with pytest.raises(CSVZManifestError, match="Missing required field"):
        Reader("csvz").open(file_name)


def test_unsupported_version_rejected(tmp_path):
    file_name = str(tmp_path / "bad.csvz")
    manifest = valid_manifest([{"path": "a.csv", "sheet": "A"}])
    manifest["version"] = 99
    write_manifest_package(file_name, manifest, {"a.csv": "a\n"})
    with pytest.raises(CSVZManifestError, match="version"):
        Reader("csvz").open(file_name)


def test_dialect_name_is_not_imported(tmp_path):
    file_name = str(tmp_path / "bad.csvz")
    manifest = valid_manifest(
        [{"path": "a.csv", "sheet": "A", "dialect": "excel-tab"}]
    )
    write_manifest_package(file_name, manifest, {"a.csv": "a\n"})
    with pytest.raises(CSVZManifestError, match="not a name"):
        Reader("csvz").open(file_name)


def test_legacy_package_without_manifest_unchanged(tmp_path):
    file_name = str(tmp_path / "legacy.csvz")
    archive = zipfile.ZipFile(file_name, "w")
    archive.writestr("notes.txt", "中,文,1")
    archive.writestr("data.csv", "x,y,z")
    archive.close()
    reader = Reader("csvz")
    handle = reader.open(file_name)
    assert handle.sheet_names() == ["notes", "data"]
    assert handle.manifest is None
    config = handle.sheet_config("data")
    assert config["manifest"] is False
    assert config["sources"]["encoding"] == "default"
    data = reader.read_all()
    reader.close()
    assert list(data["notes"]) == [["中", "文", 1]]
    assert list(data["data"]) == [["x", "y", "z"]]


def test_same_named_ordinary_file_is_not_a_manifest(tmp_path):
    file_name = str(tmp_path / "ordinary.csvz")
    archive = zipfile.ZipFile(file_name, "w")
    archive.writestr(csvz_manifest.MANIFEST_FILE_NAME, "just,text,1")
    archive.writestr("data.csv", "x,y,z")
    archive.close()
    reader = Reader("csvz")
    handle = reader.open(file_name)
    assert handle.manifest is None
    # the ordinary file keeps being treated as a normal sheet
    assert handle.sheet_names() == [
        csvz_manifest.MANIFEST_FILE_NAME[:-4],
        "data",
    ]
    reader.close()


def test_unrelated_files_are_not_tables_when_manifest_present(tmp_path):
    file_name = str(tmp_path / "mixed.csvz")
    manifest = valid_manifest([{"path": "tables/a.csv", "sheet": "A"}])
    write_manifest_package(
        file_name,
        manifest,
        {"tables/a.csv": "1,2\n", "readme.txt": "not,a,table"},
    )
    reader = Reader("csvz")
    handle = reader.open(file_name)
    assert handle.sheet_names() == ["A"]
    data = reader.read_all()
    reader.close()
    assert list(data["A"]) == [[1, 2]]


def test_override_beats_manifest_and_manifest_beats_global(tmp_path):
    file_name = str(tmp_path / "prio.csvz")
    make_demo_book(file_name)
    reader = Reader("csvz")
    # the global delimiter is only a default for undeclared values
    handle = reader.open(
        file_name,
        delimiter=":",
        sheet_overrides={"utf8-minimal": {"delimiter": ","}},
    )
    utf8 = handle.sheet_config("utf8-minimal")
    assert utf8["parameters"]["delimiter"] == ","
    assert utf8["sources"]["delimiter"] == "override"
    utf16 = handle.sheet_config("utf16-all")
    assert utf16["parameters"]["delimiter"] == ";"
    assert utf16["sources"]["delimiter"] == "manifest"
    # the writer records the full dialect, so the global delimiter
    # never leaks into any declared value
    assert utf8["parameters"]["escapechar"] is None
    assert utf8["sources"]["escapechar"] == "manifest"
    data = reader.read_all()
    reader.close()
    for name, rows in EXPECTED.items():
        assert [list(row) for row in data[name]] == rows


def test_global_parameters_are_defaults_for_undeclared_values(tmp_path):
    file_name = str(tmp_path / "partial.csvz")
    manifest = valid_manifest(
        [{"path": "a.csv", "sheet": "A", "dialect": {"delimiter": ";"}}]
    )
    write_manifest_package(
        file_name, manifest, {"a.csv": "1;2\n".encode("utf-16")}
    )
    reader = Reader("csvz")
    handle = reader.open(file_name, encoding="utf-16", quoting=csv.QUOTE_ALL)
    config = handle.sheet_config("A")
    assert config["sources"]["encoding"] == "global"
    assert config["parameters"]["encoding"] == "utf-16"
    assert config["sources"]["delimiter"] == "manifest"
    assert config["sources"]["quoting"] == "global"
    assert config["sources"]["quotechar"] == "default"
    data = reader.read_all()
    reader.close()
    assert [list(row) for row in data["A"]] == [[1, 2]]


def test_sheet_config_is_queryable_by_name_and_index(tmp_path):
    file_name = str(tmp_path / "demo.csvz")
    make_demo_book(file_name)
    reader = Reader("csvz")
    handle = reader.open(file_name)
    by_name = handle.sheet_config("utf16-all")
    by_index = handle.sheet_config(1)
    reader.close()
    assert by_name == by_index
    assert set(by_name["sources"]) == set(csvz_manifest.CONFIG_KEYS)
    assert set(by_name["sources"].values()) <= {
        "override",
        "manifest",
        "global",
        "default",
    }
