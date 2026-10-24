---
name: gdocout
description: Turn Google Docs, Sheets and Slides into Word, Excel and PowerPoint files without signing in to Google, for files shared "anyone with the link". Works on one link at a time, or on a whole Google Drive saved offline (a Google Drive for desktop folder, where Google files are small .gdoc/.gsheet/.gslides shortcut files), copying everything else as it is and writing a filterable HTML report of every file. Use whenever the user wants Google Docs/Sheets/Slides as Office or PDF files, wants an offline or "leaving Google" copy of a Drive folder, has .gdoc/.gsheet/.gslides files that won't open, or asks which Google files in a folder can't be downloaded.
---

# gdocout: Google files you can open offline

gdocout downloads Google Docs, Sheets and Slides in Office formats through the same links Google's own Download menu uses, so it needs **no Google account and no sign-in**. That only works for files shared "anyone with the link"; everything else is reported, never guessed at. Every download is checked before it counts, because Google answers errors with a web page that can look like a success.

This skill needs **gdocout 0.1.0 or newer**. gdocout has no dependencies beyond Python 3.9+.

## 1. Find gdocout, or install it

uv and pipx put the command in `~/.local/bin`, which often isn't on the shell's PATH. So look before installing:

1. `gdocout --version`
2. If that's not found: `~/.local/bin/gdocout --version` (on Windows, `%USERPROFILE%\.local\bin\gdocout.exe --version`), or `"$(uv tool dir --bin)/gdocout" --version` when uv is installed.

Use whichever works for everything below. If it reports a version older than 0.1.0, reinstall this release over it: `uv tool install --force git+https://github.com/RazorII/gdocout@v0.1.0` (or the same with `pipx install --force`).

Only if none of them works, install this release. Prefer uv, then pipx, then pip:

```
uv tool install git+https://github.com/RazorII/gdocout@v0.1.0
pipx install git+https://github.com/RazorII/gdocout@v0.1.0
python3 -m pip install --user git+https://github.com/RazorII/gdocout@v0.1.0
```

## 2. One link, or a few

```
gdocout link URL [URL ...] --dest FOLDER [--format pdf] --json
```

Docs become .docx, Sheets .xlsx, Slides .pptx unless `--format` says otherwise (`pdf`, `odt`, `md`, `epub` for Docs; `pdf`, `ods` for Sheets; `pdf`, `odp` for Slides). Ask where to save if the user hasn't said. Report each result's `status` in plain words (section 5).

## 3. A whole offline Google Drive folder

### 3a. Ask first, every time

Before copying anything, ask the user two things, unless they already said:

1. **Where the copy should go.** Always ask; never pick a folder yourself. It must be an empty folder (gdocout creates it if it doesn't exist) or a folder gdocout copied into before, to continue that copy. It can't be inside the folder being copied.
2. **Keep the folder structure (the default), or put every file in one folder** (`--flat`). With `--flat`, files with the same name are numbered, " (2)", " (3)".

### 3b. Look before copying

```
gdocout scan SOURCE --json
```

Offline and writes nothing. Tell the user, in a few lines: how many files and folders, how many ordinary files to copy and their total size, how many Google files to download and of which kinds, the time estimate (`estimate_note`), and anything in `attention` (files with no offline format such as Google Forms, placeholders that aren't on this computer, unreadable shortcuts). Placeholders (`not_on_disk`) mean the Drive folder isn't fully downloaded: the user should make it available offline first, or accept that those files will be missing.

### 3c. Try a sample, then the whole thing

When there are more than about 20 Google files, check the "everything is shared by link" assumption cheaply first:

```
gdocout copy SOURCE --dest DEST --limit 20 --google-only --json
```

If most of the sample comes back `not_shared` or `download_off`, tell the user before going on; the full copy would mostly produce link pages. Then run the full copy into the **same** destination; finished files are not downloaded again:

```
gdocout copy SOURCE --dest DEST --json
```

gdocout paces itself. It starts with 2 downloads at once and works up to 8 (about 140 files a minute overall, measured), halves and pauses when Google pushes back, and stops after about half an hour of refusals. It prints progress to stderr. A copy of more than a few hundred Google files takes minutes to an hour, so run it in the background where you can, check on it, and tell the user when it finishes. Never run two copies into the same destination at once.

Exit codes: 0 finished; 1 finished, but some files failed (they are retried on the next run); 2 a problem with the request (paths, a destination in use for another folder); 5 Google kept refusing downloads from this connection, so the copy stopped with everything so far saved (run the same command later, an hour or more, to continue); 130 stopped by hand (same command continues).

### 3d. Tell the user what happened

Summarise from the JSON. **Never list every file.** The report is the place for that.

- One line of totals: converted, copied, and the total written.
- Then each group in `attention`, with its count and up to five example paths:
  - `download_off`: anyone with the link can view it, but its owner turned off downloading. Only the owner can change that. Say so plainly, and don't try to work around it (no screenshots, printing or copying text from the viewer).
  - `not_shared`: not shared with "anyone with the link". The owner has to share it that way.
  - `not_found`: deleted, or a wrong shortcut.
  - `no_offline_format`: Google Forms and other types with no download. The copy holds a small link page in their place.
  - `not_on_disk`, `unreadable`, `failed` (retried next run), `pending` (not done yet, the next run continues).
- `renamed` and `with_warnings` counts, if not zero.
- The report: `report` is a self-contained HTML page in the destination. It lists every file with a folder tree, status, type and extension filters, search, a CSV download of the filtered list, and a "Copy Google links" button that gives the owner a list of what to re-share. Offer to open it.

After an owner changes sharing, `gdocout copy SOURCE --dest DEST --recheck` asks Google again about the refused files only.

## 4. How the files are checked

If the user asks whether the converted files can be trusted: every download must be the right kind of file (Office files are ZIP archives whose every part passes its checksum, with the parts Word, Excel or PowerPoint needs, and well-formed XML); a web page or an empty answer is never kept. The report shows what was read from each file (words and pictures in a document, sheet names, slide count). Ordinary files are copied and their SHA-256 compared with the original. Nothing is half-written: files are written under a temporary name and renamed only once they pass.

## 5. Status words

`converted`, `copied`, `download_off` ("download turned off"), `not_shared` ("not shared by link"), `not_found`, `no_offline_format`, `not_on_disk` ("not on this computer"), `unreadable`, `failed`, `pending` ("not done yet"), `ignored` (system files such as .DS_Store), `source_gone`.

## Don't

- Don't sign in to Google, use browser cookies, or ask the user for their Google password. gdocout works without them by design.
- Don't choose the destination folder yourself.
- Don't delete or change anything in the source folder.
- Don't paste the whole file list into the conversation; point to the report.
