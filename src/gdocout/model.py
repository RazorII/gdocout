"""The record kept for every file, and what each outcome is called."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

PENDING = "pending"
COPIED = "copied"
CONVERTED = "converted"
DOWNLOAD_OFF = "download_off"
NOT_SHARED = "not_shared"
NOT_FOUND = "not_found"
NO_FORMAT = "no_offline_format"
NOT_ON_DISK = "not_on_disk"
UNREADABLE = "unreadable"
IGNORED = "ignored"
FAILED = "failed"
SOURCE_GONE = "source_gone"
SKIPPED = "skipped"

# Order is the order the report and summaries list them in.
LABELS: Dict[str, str] = {
    CONVERTED: "Converted",
    COPIED: "Copied",
    DOWNLOAD_OFF: "Download turned off",
    NOT_SHARED: "Not shared by link",
    NOT_FOUND: "Not found",
    NO_FORMAT: "No offline format",
    NOT_ON_DISK: "Not on this computer",
    UNREADABLE: "Couldn't read",
    FAILED: "Failed",
    PENDING: "Not done yet",
    SOURCE_GONE: "Gone from the source",
    SKIPPED: "Left out by your choice",
    IGNORED: "System file, skipped",
}

EXPLAIN: Dict[str, str] = {
    CONVERTED: "Downloaded from Google in an offline format and checked.",
    COPIED: "Copied as it is; the copy's SHA-256 matches the original's.",
    DOWNLOAD_OFF: "Anyone with the link can view it, but its owner turned off downloading. "
    "Only the owner can change that (Share > settings > 'Viewers and commenters can see the option to download').",
    NOT_SHARED: "Google wants a sign-in: the file isn't shared with 'anyone with the link'. Ask its owner to share it that way.",
    NOT_FOUND: "Google has no file with this ID any more: deleted, or the shortcut is wrong.",
    NO_FORMAT: "This type of Google file has no download that works offline.",
    NOT_ON_DISK: "Only a placeholder is on this computer; the file itself was never downloaded. "
    "Make it available offline in Google Drive, then run gdocout again.",
    UNREADABLE: "The file couldn't be read.",
    FAILED: "Something went wrong; the details say what. Running gdocout again retries it.",
    PENDING: "The run stopped before this file's turn. Running gdocout again continues.",
    SOURCE_GONE: "It was in the folder during an earlier run, but isn't any more.",
    SKIPPED: "A rule chosen for this copy left it out: a type, folder or name rule, or a list of files.",
    IGNORED: "A file the operating system or a sync app keeps for itself; not part of the library.",
}

DONE = {COPIED, CONVERTED}
# Outcomes a plain re-run retries; the sharing ones need --recheck, since
# nothing changes until the owner changes the file's sharing.
RETRY = {PENDING, FAILED}
RECHECK = {DOWNLOAD_OFF, NOT_SHARED, NOT_FOUND}


@dataclass
class Entry:
    rel: str  # path inside the source, "/"-separated
    kind: str  # "file", or a Google kind such as "document"
    ext: str  # lower-case extension of the original, ".pdf", ".gdoc"
    size: int = 0
    mtime: float = 0.0
    gid: str = ""  # Google file ID
    key: str = ""  # resource key of an older link-shared file
    account: str = ""  # the Google account the shortcut file belongs to (Drive for desktop records it)
    fmt: str = ""  # format exported to
    status: str = PENDING
    out_rel: str = ""  # path inside the destination, "/"-separated
    extra: Dict[str, Dict[str, object]] = field(default_factory=dict)  # more formats of a Google file: fmt -> {o, st, s, n, f}
    link_rel: str = ""  # a small .html page pointing at the Google file, when it couldn't be saved
    renamed: bool = False
    note: str = ""  # why, in plain words
    facts: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    out_size: Optional[int] = None
    attempts: int = 0
    seconds: float = 0.0

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def parent(self) -> str:
        return self.rel.rsplit("/", 1)[0] if "/" in self.rel else ""

    @property
    def is_google(self) -> bool:
        return self.kind != "file"
