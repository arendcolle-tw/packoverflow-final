import json
from pathlib import Path


class GcsMirror:
    """Copies the graph's SQLite file to a Cloud Storage bucket so it survives Cloud Run restarts."""

    def __init__(self, bucket_name: str | None = None):
        import google.auth
        from google.cloud import storage

        _, project = google.auth.default()
        self.client = storage.Client(project=project)
        name = bucket_name or f"{project}-knowledge-graph"
        self.bucket = self.client.lookup_bucket(name) or self.client.create_bucket(name, location="us-central1")

    def load_members(self) -> dict[str, str]:
        """token hash -> person, kept as its own small blob so a redeploy race cannot drop a member."""
        blob = self.bucket.blob("members.json")
        return json.loads(blob.download_as_text()) if blob.exists() else {}

    def save_members(self, members: dict[str, str]) -> None:
        self.bucket.blob("members.json").upload_from_string(json.dumps(members), content_type="application/json")

    def upload(self, path: Path) -> None:
        self.bucket.blob(path.name).upload_from_filename(str(path))

    def download(self, path: Path) -> None:
        """Restore `path` from the bucket when a copy exists there."""
        blob = self.bucket.blob(path.name)
        if blob.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(path))
