"""The four requests to Google Cloud Storage: upload, download, list and delete
(DESIGN_miniapp_storage.md §5, §12). The tests replace `Bucket`.

`requests` and the Google libraries are imported inside the methods that use them, to keep
them off the CLI's startup path (ARCHITECTURE.md §14) and because the Google libraries take
about 0.3 s to import (§6).
"""
from typing import List, Optional
from urllib.parse import quote

# What the service account may do in the bucket: upload, replace, list and delete (§11).
SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"

JSON_API = "https://storage.googleapis.com/storage/v1/b"
XML_API = "https://storage.googleapis.com"

# How long a request of `sm data publish` may take. The step after a command passes its own.
SECONDS = 60.0


class BucketError(Exception):
    """A request Google refused, named by its HTTP status only (see `describe`)."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def describe(exc: BaseException) -> str:
    """An error as the journal, the record and the commands name it: its HTTP status, or
    its type, never its text, which can quote the file's address (§8, §10)."""
    if isinstance(exc, BucketError):
        return str(exc)
    return type(exc).__name__


def _check(response) -> None:
    if not response.ok:
        raise BucketError(response.status_code)


def download_url(bucket: str, folder: str, name: str) -> str:
    """The address the page downloads a file from. Google answers a page from another site
    on this one without any rule on the bucket (§5)."""
    return f"{JSON_API}/{bucket}/o/{quote(folder + '/' + name, safe='')}?alt=media"


class Bucket:
    """This bot's folder in the operator's bucket."""

    def __init__(self, name: str, folder: str):
        self.name = name
        self.folder = folder
        self._session = None

    def _authorized(self):
        """A session that signs every request with the service account's token."""
        if self._session is None:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account
            from stamind.config import config
            credentials = service_account.Credentials.from_service_account_file(
                config.service_account_file, scopes=[SCOPE]
            )
            self._session = AuthorizedSession(credentials)
        return self._session

    def sign_in(self) -> None:
        """Asks Google for a token now, so a missing file or a revoked key fails here
        (§9.2, check 2)."""
        from google.auth.transport.requests import Request
        self._authorized().credentials.refresh(Request())

    def upload(self, name: str, data: bytes, seconds: float = SECONDS) -> None:
        """Writes `data` under `name` with "do not cache", in one request (§6, §15).
        `seconds` bounds the whole request, the token included."""
        response = self._authorized().request(
            "PUT", f"{XML_API}/{self.name}/{self.folder}/{name}", data=data,
            headers={"Cache-Control": "no-store", "Content-Type": "application/octet-stream"},
            timeout=seconds, max_allowed_time=seconds,
        )
        _check(response)

    def download(self, name: str, origin: str):
        """The file as a page from `origin` downloads it: no credential (§9.2, check 4)."""
        import requests
        return requests.get(download_url(self.name, self.folder, name),
                            headers={"Origin": origin}, timeout=SECONDS)

    def names(self) -> List[str]:
        """The names in this bot's folder. The listing asks for the folder's name followed
        by a slash, so the folder `123` never lists the files of `1234` (§9.2)."""
        prefix = self.folder + "/"
        found: List[str] = []
        page: Optional[str] = None
        while True:
            params = {"prefix": prefix, "fields": "items(name),nextPageToken"}
            if page:
                params["pageToken"] = page
            response = self._authorized().get(
                f"{JSON_API}/{self.name}/o", params=params, timeout=SECONDS
            )
            _check(response)
            body = response.json()
            found += [item["name"][len(prefix):] for item in body.get("items", [])]
            page = body.get("nextPageToken")
            if not page:
                return found

    def open_to_listing(self) -> bool:
        """Whether Google answers a listing with no credential (§9.2, check 5)."""
        import requests
        response = requests.get(f"{JSON_API}/{self.name}/o",
                                params={"prefix": self.folder + "/"}, timeout=SECONDS)
        return response.ok

    def delete(self, name: str) -> None:
        """Deletes `name`. A file already gone counts as deleted."""
        response = self._authorized().delete(
            f"{JSON_API}/{self.name}/o/{quote(self.folder + '/' + name, safe='')}",
            timeout=SECONDS,
        )
        if response.status_code == 404:
            return
        _check(response)
