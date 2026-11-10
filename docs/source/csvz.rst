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


Streaming row by row
---------------------

By default, reading a csvz/tsvz member decompresses the whole member into
memory before the first row is yielded. For large members, pass
``streaming=True`` so that the selected zip member is decompressed
incrementally from its ``ZipExtFile`` and rows are produced one at a time
through the same reader, auto-detection and row/column filter interfaces.

    >>> from pyexcel_io.reader import Reader
    >>> reader = Reader("csvz")
    >>> reader.open("mybook.csvz", streaming=True)
    >>> data = reader.read_sheet_by_index(0)
    >>> list(data["Sheet 1"])
    [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    >>> reader.close()

Only the sheets that are actually read are opened inside the zip. Two
opened sheets can be consumed interleaved, each with its own independent
stream, and closing the parent reader closes all of them. When a zip file
stream is supplied by the caller, the caller still owns that outer stream.

Encoding handling
********************************************************************************

An explicit ``encoding`` keyword always wins. Without it, only the first
``detect_prefix_size`` bytes (default 4096) are buffered for detection: a
BOM is honored first, otherwise chardet is consulted on that prefix, and a
failed detection raises ``ValueError``. The probed bytes are replayed, so no
data is lost. Once the encoding is decided it is never revisited; later
illegal bytes raise ``UnicodeDecodeError`` under strict error handling.

Streaming mode requires unique sheet names, because no archive member
identity is exposed. Duplicate sheet names raise ``ValueError`` while the
book is opened. A CRC error that the zip format can only verify at the end
of a member is raised when that point is reached, so a partially read sheet
is never reported as fully verified.


Open csvz without pyexcel-io
----------------------------

All you need is a unzipping software. I would recommend 7zip which is open source and is available on all available OS platforms.

On latest Windows platform (windows 8), zip file is supported so just give the "csvz" file a file extension as ".zip". The file can be opened by File Explorer.


.. testcode::
   :hide:

    >>> import os
    >>> os.unlink("myfile.csvz")
    >>> os.unlink("mybook.csvz")
