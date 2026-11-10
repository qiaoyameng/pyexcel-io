====================================
File formats: .csvz and .tsvz
====================================

.. _csvz:

Introduction
-------------

'csvz' and 'tsvz' are newly invented excel file formats by pyexcel. Simply put, 'csvz' is the zipped content of one or more csv file(s). 'tsvz' is the twin brother of 'csvz'. They are similiar to the implementation of xlsx format, which is a zip of excel content in xml format.

The obvious tangile benefit of zipped csv over normal csv is the reduced file size. However, the drawback is the need of unzipping software.

Single Sheet
------------

When a single sheet is to be saved, the resulting csvz file will be a zip file that contains one csv file bearing the name of :class:`~pyexcel.Sheet`.

    >>> from pyexcel_io import save_data
    >>> data = [[1,2,3]]
    >>> save_data("myfile.csvz", data)
    >>> import zipfile
    >>> zip = zipfile.ZipFile("myfile.csvz", 'r')
    >>> zip.namelist()
    ['pyexcel_sheet1.csv']
    >>> zip.close()


And it can be read out as well and can be saved in any other supported format.

    >>> from pyexcel_io import get_data
    >>> data = get_data("myfile.csvz")
    >>> import json
    >>> json.dumps(data)
    '{"pyexcel_sheet1": [[1, 2, 3]]}'
    

Multiple Sheet Book
-------------------

When multiple sheets are to be saved as a book, the resulting csvz file will be a zip file that contains each sheet as a csv file named after corresponding sheet name.
    >>> from pyexcel_io._compact import OrderedDict
    >>> content = OrderedDict()
    >>> content.update({
    ...     'Sheet 1': 
    ...         [
    ...             [1.0, 2.0, 3.0], 
    ...             [4.0, 5.0, 6.0], 
    ...             [7.0, 8.0, 9.0]
    ...         ]
    ... })
    >>> content.update({
    ...     'Sheet 2': 
    ...         [
    ...             ['X', 'Y', 'Z'], 
    ...             [1.0, 2.0, 3.0], 
    ...             [4.0, 5.0, 6.0]
    ...         ]
    ... })
    >>> content.update({
    ...     'Sheet 3': 
    ...         [
    ...             ['O', 'P', 'Q'], 
    ...             [3.0, 2.0, 1.0], 
    ...             [4.0, 3.0, 2.0]
    ...         ] 
    ... })
    >>> save_data("mybook.csvz", content)
    >>> import zipfile
    >>> zip = zipfile.ZipFile("mybook.csvz", 'r')
    >>> zip.namelist()
    ['Sheet 1.csv', 'Sheet 2.csv', 'Sheet 3.csv']
    >>> zip.close()


The csvz book can be read back with two lines of code. And once it is read out, it can be saved in any other supported format.

    >>> book2 = get_data("mybook.csvz")
    >>> json.dumps(book2)
    '{"Sheet 1": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]], "Sheet 2": [["X", "Y", "Z"], [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], "Sheet 3": [["O", "P", "Q"], [3.0, 2.0, 1.0], [4.0, 3.0, 2.0]]}'


Open csvz without pyexcel-io
----------------------------

All you need is a unzipping software. I would recommend 7zip which is open source and is available on all available OS platforms.

On latest Windows platform (windows 8), zip file is supported so just give the "csvz" file a file extension as ".zip". The file can be opened by File Explorer.


Manifest for mixed encodings and dialects
-----------------------------------------

A single encoding or delimiter parameter cannot describe a package in
which one table is UTF-8 comma separated and another is UTF-16
semicolon separated. For such packages, the writer can record an
optional manifest member, ``pyexcel_csvz_manifest.json``, which
describes every table: its member path, sheet name, encoding and full
csv dialect (delimiter, quotechar, escapechar, doublequote,
skipinitialspace, lineterminator, quoting). The manifest carries a
format version and only describes data formats: it never executes
code and never names plugins or dialects to be imported.

    >>> from pyexcel_io import save_data
    >>> content = {'utf16 sheet': [[1, 2], [3, 4]]}
    >>> save_data("mixed.csvz", content, write_manifest=True,
    ...           sheet_settings={'utf16 sheet': {'encoding': 'utf-16',
    ...                                           'delimiter': ';'}})

Per sheet encoding and dialect parameters are given through
``sheet_settings``, a dictionary keyed by sheet name. Global
parameters apply to all sheets unless a sheet overrides them.

When a manifest is present, the reader validates it before any data
is read: unknown manifest versions, missing members, duplicate member
paths, duplicate sheet names and unknown fields are rejected up
front. Only the members listed in the manifest are treated as tables;
unrelated files in the archive are left alone. A package without a
manifest behaves exactly as before, and an ordinary file that merely
shares the manifest file name is not mistaken for a manifest.

Parameter precedence is: explicit per sheet overrides (given through
``sheet_overrides``) beat the manifest, the manifest beats global
parameters, and global parameters are only defaults for values the
manifest does not declare. The effective configuration of each sheet,
including which layer each value came from, can be queried:

    >>> from pyexcel_io.reader import Reader
    >>> reader = Reader("csvz")
    >>> handle = reader.open("mixed.csvz")
    >>> config = handle.sheet_config("utf16 sheet")
    >>> config["parameters"]["encoding"]
    'utf-16'
    >>> config["sources"]["encoding"]
    'manifest'
    >>> reader.close()


.. testcode::
   :hide:

    >>> import os
    >>> os.unlink("myfile.csvz")
    >>> os.unlink("mybook.csvz")
    >>> os.unlink("mixed.csvz")
