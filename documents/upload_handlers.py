
from django.core.files.uploadhandler import FileUploadHandler, StopUpload

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB


class LimitUploadSizeHandler(FileUploadHandler):
    """Stop processing an individual file after 10 MiB."""

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_size = 0

    def receive_data_chunk(self, raw_data, start):
        self.file_size += len(raw_data)

        if self.file_size > MAX_FILE_SIZE:
            # Communicate the rejection to the view.
            self.request.upload_too_large = True
            raise StopUpload(connection_reset=False)

        return raw_data

    def file_complete(self, file_size):
        return None
