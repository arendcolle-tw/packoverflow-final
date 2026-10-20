from pathlib import Path


class GcsMirror:
    """Copies the store's files to a Cloud Storage bucket so they survive Cloud Run restarts."""

    def __init__(self, bucket_name: str | None = None):
        import google.auth
        from google.cloud import storage

        _, project = google.auth.default()
        self.client = storage.Client(project=project)
        name = bucket_name or f"{project}-knowledge-mcp"
        self.bucket = self.client.lookup_bucket(name) or self.client.create_bucket(name, location="us-central1")

    def upload(self, path: Path) -> None:
        self.bucket.blob(path.name).upload_from_filename(str(path))

    def download_all(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        for blob in self.bucket.list_blobs():
            blob.download_to_filename(str(data_dir / blob.name))
