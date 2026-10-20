
import hashlib
import uuid

from django.core.files.storage import FileSystemStorage
from django.conf import settings
from pathlib import Path


PRIVATE_UPLOAD_ROOT = Path(settings.BASE_DIR) / "private_uploads"

private_storage = FileSystemStorage(
    location=PRIVATE_UPLOAD_ROOT,
    base_url=None,
)


def store_medical_report(upload):
    sha256 = hashlib.sha256()
    for chunk in upload.chunks():
        sha256.update(chunk)

    upload.seek(0)
    storage_key = f"medical_reports/{uuid.uuid4().hex}"

    saved_name = private_storage.save(storage_key, upload)

    return {
        "storage_key": saved_name,
        "sha256": sha256.hexdigest(),
        "size_bytes": upload.size,
    }

