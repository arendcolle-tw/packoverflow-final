from pathlib import Path


class GcsMirror:
    """Copies the store's SQLite file to a Cloud Storage bucket so it survives Cloud Run restarts."""

    def __init__(self, bucket_name: str):
        import google.auth
        from google.cloud import storage

        _, project = google.auth.default()
        self.client = storage.Client(project=project)
        self.bucket = self.client.lookup_bucket(bucket_name) or self.client.create_bucket(bucket_name, location="us-central1")

    def upload(self, path: Path) -> None:
        self.bucket.blob(path.name).upload_from_filename(str(path))

    def download(self, path: Path) -> None:
        blob = self.bucket.blob(path.name)
        if blob.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(path))
