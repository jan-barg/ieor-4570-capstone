"""The two Google Cloud calls the deploy needs, with no extra library (google-auth's AuthorizedSession):
put a file in a Cloud Storage bucket, and start a run of the Cloud Run job that makes one video.

    cloud.upload("stringer-videos", "videos/<id>/video.mp4", Path("video.mp4"))
    cloud.open_object("stringer-videos", "videos/<id>/video.mp4", "bytes=0-")     # streamed back, for /media
    cloud.start_job("<project>", "us-east1", "stringer-make", ["<event id>"])     # -> the execution's name

Settings on Cloud Run (cloudbuild.yaml sets them): STRINGER_PROJECT, STRINGER_REGION, STRINGER_JOB,
STRINGER_VIDEO_BUCKET (finished videos and posters; private, the website streams them to signed-in
Columbia accounts, Jan Nov 27) and STRINGER_PRIVATE_BUCKET (story folders; the Gate's records live
there too, under gate/, through GATE_STORE)."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

UPLOAD = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
OBJECT = "https://storage.googleapis.com/storage/v1/b/{bucket}/o/{name}"
PUBLIC = "https://storage.googleapis.com/{bucket}/{name}"
RUN_JOB = "https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}:run"
_session = None


def session():
    global _session
    if _session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _session = AuthorizedSession(creds)
    return _session


def setting(name: str, default: str | None = None) -> str:
    v = os.environ.get(name) or default
    if not v:
        raise RuntimeError(f"{name} is not set")
    return v


def upload(bucket: str, name: str, path: Path, content_type: str | None = None, cache: str = "public, max-age=3600",
           timeout: float = 120.0) -> str:
    """Puts one file at gs://bucket/name and returns its storage.googleapis.com URL (it opens in a browser
    only if the bucket is public; the video bucket isn't, so the website streams from it instead)."""
    ctype = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    with open(path, "rb") as f:
        r = session().post(UPLOAD.format(bucket=bucket), params={"uploadType": "media", "name": name},
                           data=f, headers={"Content-Type": ctype, "Cache-Control": cache}, timeout=timeout)
    r.raise_for_status()
    return PUBLIC.format(bucket=bucket, name=quote(name))


def open_object(bucket: str, name: str, range_header: str | None = None, timeout: float = 60.0):
    """One object, streamed (requests' stream=True), passing a browser's Range header through so videos
    can seek. The caller reads .status_code, .headers and .iter_content(), then .close()."""
    headers = {"Range": range_header} if range_header else {}
    return session().get(OBJECT.format(bucket=bucket, name=quote(name, safe="")), params={"alt": "media"},
                         headers=headers, stream=True, timeout=timeout)


def start_job(project: str, region: str, job: str, args: list[str], timeout: float = 30.0) -> str:
    """Starts one execution of a Cloud Run job with these arguments; returns the operation's name."""
    body = {"overrides": {"containerOverrides": [{"args": [str(a) for a in args]}]}}
    r = session().post(RUN_JOB.format(project=project, region=region, job=job), json=body, timeout=timeout)
    r.raise_for_status()
    return r.json().get("name", "")
