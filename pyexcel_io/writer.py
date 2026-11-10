from pyexcel_io.plugins import NEW_WRITERS


class Writer(object):
    def __init__(self, file_type, library=None, context=None):
        self.file_type = file_type
        self.library = library
        self.context = context
        self.keyboards = None
        # if you know which reader class to use, this attribute allows
        # you to set reader class externally. Since there is no
        # so call private field in Python, I am not going to create
        # useless setter and getter functions like Java.
        # in pyexcel, this attribute is mainly used for testing
        self.writer_class = None

    def open(self, file_name, **keywords):
        if self.writer_class is None:
            self.writer_class = self._get_writer_class("file")
        self.writer = self.writer_class(file_name, self.file_type, **keywords)

    def open_content(self, file_stream, **keywords):
        if self.writer_class is None:
            self.writer_class = self._get_writer_class("content")
        self.writer = self.writer_class(
            file_stream, self.file_type, **keywords
        )

    def open_stream(self, file_stream, **keywords):
        if self.writer_class is None:
            self.writer_class = self._get_writer_class("memory")
        self.writer = self.writer_class(
            file_stream, self.file_type, **keywords
        )

    def _get_writer_class(self, location):
        if self.context is None:
            return NEW_WRITERS.get_a_plugin(
                self.file_type, library=self.library, location=location
            )
        return self.context.get_a_plugin(location=location)

    def write(self, incoming_dict):
        self.writer.write(incoming_dict)

    def close(self):
        self.writer.close()

    def __enter__(self):
        return self

    def __exit__(self, a_type, value, traceback):
        self.close()
