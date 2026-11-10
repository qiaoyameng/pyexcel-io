# -*- coding: utf-8 -*-
"""
Demo: one csvz package, two encodings and two quoting rules.

The package is written with a manifest, then read back once by file
path and once by file object. For each table the effective
configuration (and which layer it came from) is printed along with
the resulting cell values.
"""
import csv
import os
import tempfile

from pyexcel_io.reader import Reader
from pyexcel_io.writer import Writer
from pyexcel_io._compact import OrderedDict


def build_package(file_name):
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


def show(title, reader):
    print("== %s ==" % title)
    handle = reader.reader
    data = reader.read_all()
    for name in handle.sheet_names():
        config = handle.sheet_config(name)
        print("sheet: %s (member %s)" % (config["sheet"], config["path"]))
        for key in ("encoding", "delimiter", "quotechar", "quoting"):
            print(
                "  %-10s = %-8r <- %s"
                % (key, config["parameters"][key], config["sources"][key])
            )
        for row in data[name]:
            print("  cells: %r" % list(row))
    print()


def main():
    file_name = os.path.join(tempfile.mkdtemp(), "demo.csvz")
    build_package(file_name)

    reader = Reader("csvz")
    reader.open(file_name)
    show("read via file path", reader)
    reader.close()

    with open(file_name, "rb") as file_object:
        reader = Reader("csvz")
        reader.open_stream(file_object)
        show("read via file object", reader)
        reader.close()


if __name__ == "__main__":
    main()
