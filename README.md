# gdocout

Turn Google Docs, Sheets and Slides into Word, Excel and PowerPoint files **without giving anything your Google password**. Give it one link, or a whole Google Drive saved offline, and it saves every file in a format you can open on any computer, offline, for good. Then it tells you which files it couldn't save, and why.

Files shared **"anyone with the link"** come straight from Google, many at a time. The rest can come **through your own web browser**, signed in to Google with the account that can open them (`--browser`): gdocout opens each one there, like you clicking Download, and moves the download into the copy. Anything neither route can fetch is reported, never guessed at.

```
gdocout copy ~/Google\ Drive/My\ Drive --dest ~/Drive-offline
```

## What it does with a Drive folder

On a computer with Google Drive for desktop, a Google Doc isn't really on the disk. It's a 172-byte shortcut file (`.gdoc`, `.gsheet`, `.gslides`) that only holds the file's ID. Copy the folder somewhere else and you've copied the shortcuts, not the documents. gdocout copies the real thing:

- **Ordinary files** (PDFs, photos, Word files…) are copied as they are, and each copy's SHA-256 is checked against the original.
- **Google files** are downloaded from Google in an offline format: Docs → .docx, Sheets → .xlsx (every tab), Slides → .pptx, Drawings → .pdf, My Maps → .kmz. Add a PDF of each (`--pdf also`), save only PDFs (`--pdf only`), or choose others (`--format document=odt,pdf`, `md`, `epub`…).
- **Files it can't save** get a small `.html` link page in their place, saying why, so the copy still shows where they were:
  - **Download turned off**: anyone with the link can view it, but its owner turned off downloading.
  - **Not shared by link**: the file is private or shared only with certain people.
  - **No offline format**: Google Forms and a few other types have no download at all.
- **The folder structure is kept** (or `--flat` puts everything in one folder, numbering any names that clash).
- **Nothing is overwritten.** A converted `Report.docx.gdoc` next to a real `Report.docx` becomes `Report (from Google Docs).docx`.

Then it writes **`gdocout-report.html`** into the copy: one self-contained page (no internet needed, works on a phone) listing every file, with a folder tree, filters by status, type and extension, search, a CSV download of what you're looking at, and a button that copies the Google links of the files that need their owner's attention.

## Install

```
uv tool install git+https://github.com/RazorII/gdocout@v0.1.1
```

(or `pipx install …`, or `python3 -m pip install --user …`). Python 3.9 or newer, no other dependencies. macOS, Windows and Linux.

There's also a [Claude plugin](claude-plugin/README.md) that runs all of this for you.

## Use

```
gdocout gui                              # a window in your browser with every option
gdocout scan  FOLDER                     # what a copy would do; offline, writes nothing
gdocout copy  FOLDER --dest NEW_FOLDER   # copy and convert; run it again to continue
gdocout link  URL [URL…] --dest FOLDER   # just these Google links
gdocout report NEW_FOLDER                # rebuild the HTML report
```

`gdocout gui` opens a page in your web browser, served by gdocout on your own computer: folder pickers that know where Google Drive keeps its files, every option below as a choice with room for your own, a live progress view, and the equivalent command, so whatever you set up there can also be run from a script. `--source` and `--dest` open it with those folders already chosen.

Options for `copy` (and `scan`, to preview them):

| Option | What it does |
|---|---|
| `--flat` | every file in one folder instead of the original structure (the default keeps it) |
| `--pdf also` / `--pdf only` | a PDF of every Google Doc, Sheet, Slides file and Drawing as well, or instead |
| `--format KIND=FMT[,FMT]` | e.g. `document=docx,pdf`, `spreadsheet=ods`, `presentation=pdf`, `document=md` |
| `--only TYPES` / `--skip TYPES` | e.g. `--only pdf,images,google-docs` or `--skip video,.heic` (types below) |
| `--include PATTERN` / `--exclude PATTERN` | folders or names, e.g. `--include 'Work/'`, `--exclude 'Photos/'`, `--exclude '*.tmp'` |
| `--files-from LIST` | only the paths in a text file, one per line (a folder takes everything in it) |
| `--no-copy` / `--no-convert` | only Google files, or only ordinary files, this run |
| `--limit N` | download only N Google files this run: a sample, to check they're really shared by link |
| `--recheck` | after an owner changed sharing, ask Google again about the refused files |
| `--browser [NAME]` | for files that aren't shared by link: download them through your browser (default, `chrome`, `safari`, `edge`, `firefox`, `brave`, `arc`), signed in to Google as the account Google Drive uses. Recommended for your own Drive |
| `--downloads DIR` | where that browser saves downloads, if gdocout guesses wrong |
| `--fetch-placeholders` | ask Google Drive to download files that are only placeholders (Drive running and signed in) |
| `--no-links` | don't leave link pages for files that couldn't be saved |
| `--json` | print the summary as JSON |

Types are categories (`documents`, `spreadsheets`, `presentations`, `pdf`, `images`, `video`, `audio`, `archives`, `text`, `ebooks`, `mapfiles`, `other`), Google types (`google`, `google-docs`, `google-sheets`, `google-slides`, `google-drawings`, `google-maps`, `google-forms`) or extensions (`.heic`). A category includes the matching Google files: `documents` means Word files and Google Docs.

Files left out by a choice are listed in the report as "left out by your choice", and they keep their names: run again without the rule, into the same folder, and they're added. The destination must be empty, or a folder gdocout copied into before (to continue that copy).

## What it needs

- **Python 3.9 or newer.** Nothing else to install, and no administrator rights.
- **Either the files shared "anyone with the link"** (Viewer is enough, downloading allowed), **or your web browser signed in to Google** with an account that can open them, used with `--browser`. Recommended for your own Drive: sign in to the browser with the same account Google Drive uses. Your browser may ask once to allow downloads from docs.google.com. A company or school account may only allow links inside the organisation; the browser route still works for its members.
- **The files really on the disk.** Google Drive for desktop's "stream files" mode keeps placeholders for files you haven't opened. Make the folders available offline in Google Drive first: right-click the folder › Offline access › Available offline, and wait for the green ticks, or switch Drive to "Mirror files" (Settings › Preferences › Folders from Drive). Only you can change that setting. `--fetch-placeholders` makes gdocout ask Drive for the stragglers itself. Google Docs, Sheets and Slides are never real files in Drive; gdocout downloads those either way.
- **Permission to read the folder.** On macOS, the app you run gdocout from (Terminal, Claude…) needs access to Google Drive's folder, granted in System Settings › Privacy & Security › Files and Folders (or Full Disk Access). gdocout says so plainly when that's what's in the way.
- **Room for the copy** and permission to write to the destination; `gdocout scan` tells you how much it will copy.
- **Internet access to Google**: `docs.google.com`, `*.googleusercontent.com` (where the downloads come from) and `www.google.com` for My Maps.

gdocout never handles a Google password, API key or browser cookie.

## Where it runs

- **On its own**, from a terminal or `gdocout gui`, on macOS, Windows or Linux.
- **Claude Code** with the plugin: everything.
- **Claude Cowork**: the plugin installs, but Cowork runs commands in its own Linux virtual machine with only the folders you attach and filtered network access. The copy can work there (attach the Drive folder and the destination, and allow docs.google.com and googleusercontent.com in Cowork's network setting); the window, the browser route and placeholder handling need your computer itself and don't. Not tested.

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
