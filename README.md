# gdocout

Turn Google Docs, Sheets and Slides into Word, Excel and PowerPoint files **without signing in to Google**. Give it one link, or a whole Google Drive saved offline, and it saves every file in a format you can open on any computer, offline, for good. Then it tells you which files it couldn't save, and why.

It works for files shared **"anyone with the link"**. Anything else is reported, never guessed at.

```
gdocout copy ~/Google\ Drive/My\ Drive --dest ~/Drive-offline
```

## What it does with a Drive folder

On a computer with Google Drive for desktop, a Google Doc isn't really on the disk. It's a 172-byte shortcut file (`.gdoc`, `.gsheet`, `.gslides`) that only holds the file's ID. Copy the folder somewhere else and you've copied the shortcuts, not the documents. gdocout copies the real thing:

- **Ordinary files** (PDFs, photos, Word files…) are copied as they are, and each copy's SHA-256 is checked against the original.
- **Google files** are downloaded from Google in an offline format: Docs → .docx, Sheets → .xlsx (every tab), Slides → .pptx, Drawings → .pdf, My Maps → .kmz. You can choose others (`--format document=pdf`, `md`, `odt`…).
- **Files it can't save** get a small `.html` link page in their place, saying why, so the copy still shows where they were:
  - **Download turned off**: anyone with the link can view it, but its owner turned off downloading.
  - **Not shared by link**: the file is private or shared only with certain people.
  - **No offline format**: Google Forms and a few other types have no download at all.
- **The folder structure is kept** (or `--flat` puts everything in one folder, numbering any names that clash).
- **Nothing is overwritten.** A converted `Report.docx.gdoc` next to a real `Report.docx` becomes `Report (from Google Docs).docx`.

Then it writes **`gdocout-report.html`** into the copy: one self-contained page (no internet needed, works on a phone) listing every file, with a folder tree, filters by status, type and extension, search, a CSV download of what you're looking at, and a button that copies the Google links of the files that need their owner's attention.

## Install

```
uv tool install git+https://github.com/RazorII/gdocout@v0.1.0
```

(or `pipx install …`, or `python3 -m pip install --user …`). Python 3.9 or newer, no other dependencies. macOS, Windows and Linux.

There's also a [Claude plugin](claude-plugin/README.md) that runs all of this for you.

## Use

```
gdocout scan  FOLDER                     # what a copy would do; offline, writes nothing
gdocout copy  FOLDER --dest NEW_FOLDER   # copy and convert; run it again to continue
gdocout link  URL [URL…] --dest FOLDER   # just these Google links
gdocout report NEW_FOLDER                # rebuild the HTML report
```

Useful options for `copy`:

| Option | What it does |
|---|---|
| `--flat` | every file in one folder instead of the original structure |
| `--format KIND=FMT` | e.g. `document=pdf`, `spreadsheet=ods`, `presentation=pdf`, `document=md` |
| `--limit N --google-only` | try N Google files first, to check they're really shared by link |
| `--recheck` | after an owner changed sharing, ask Google again about the refused files |
| `--no-links` | don't leave link pages for files that couldn't be saved |
| `--json` | print the summary as JSON |

The destination must be empty, or a folder gdocout copied into before (to continue that copy).

## How fast, and Google's limits

Google publishes no limit for these download links, so gdocout finds a safe pace as it goes. It starts with 2 downloads at once and adds one after every 12 clean answers, up to 8. Any sign of throttling (HTTP 429, Google's "unusual traffic" page) halves that and pauses: 30 seconds, doubling each time, up to 15 minutes. After about half an hour of refusals it stops. Everything finished so far is saved, and running the same command later continues where it left off.

Measured on a home connection (October 2026): about 1.8 s per Doc or Sheet, 4 s for a 3 MB deck; 200 Google files in 86 s, about 140 a minute including the slow start, and up to about 220 a minute at 8 at once. A few hundred files take minutes; thousands take tens of minutes. A 17 MB Word export downloaded fine (the 10 MB limit you may read about is the Drive API's, which gdocout doesn't use).

## How it knows a file is good

Google answers many errors with a web page, often with "200 OK", so a download that "worked" proves nothing. Before a file counts:

1. It isn't empty and isn't a web page.
2. Its first bytes match the format (ZIP for Office files, `%PDF-` for PDF…).
3. For Office files: every part inside passes its checksum, the parts Word, Excel or PowerPoint need are there, and the main XML parses.
4. Facts are read out of it for the report: words and pictures in a document, sheet names, slide count, PDF pages. A valid but empty-looking file gets a warning.

Files are written under a temporary name and only renamed into place after they pass, so a stopped run never leaves a half-written file behind.

## What Google's answers mean

| Download link | View page | gdocout says |
|---|---|---|
| 200 and a valid file | – | converted |
| 401 | 200 | download turned off by the owner |
| 401 | 401 | not shared by link |
| 404 | – | not found (deleted, or a wrong shortcut) |
| 403 | – | failed, retried next run (can be a temporary limit on a busy file) |
| 429 / "unusual traffic" | – | slow down and try again |

Older files shared by link before Google's 2021 security update carry a *resource key* in their shortcut file; gdocout sends it along, both in the link and in the header Google documents for it.

## Privacy

gdocout talks only to Google, sends only the IDs of the files it downloads, keeps no cookies and needs no account. See [PRIVACY.md](PRIVACY.md).

## License

MIT. Made by RazorII.
