
from django import forms


class DocumentUploadForm(forms.Form):
    file = forms.FileField(
        label="Choose a document",
        help_text="Allowed: PDF, CSV, Excel, PNG, JPG"
    )

    ALLOWED_EXTENSIONS = {
        ".pdf", ".csv", ".xls", ".xlsx", ".png", ".jpg", ".jpeg"
    }

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        file_name = uploaded_file.name
        extension = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

        if extension not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                "Unsupported file type. Upload PDF, CSV, Excel, or an image."
            )

        if uploaded_file.size > self.MAX_FILE_SIZE:
            raise forms.ValidationError(
                "File size must not exceed 10 MB."
            )

        return uploaded_file
