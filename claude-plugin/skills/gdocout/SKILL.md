---
name: gdocout
description: Turn Google Docs, Sheets and Slides into Word, Excel and PowerPoint files without giving anything your Google password: files shared "anyone with the link" come straight from Google, the rest through the user's own signed-in web browser. Works on one link at a time, or on a whole Google Drive saved offline (a Google Drive for desktop folder, where Google files are small .gdoc/.gsheet/.gslides shortcut files), copying everything else as it is and writing a filterable HTML report of every file. Use whenever the user wants Google Docs/Sheets/Slides as Office or PDF files, wants an offline or "leaving Google" copy of a Drive folder, has .gdoc/.gsheet/.gslides files that won't open, or asks which Google files in a folder can't be downloaded.
---

# gdocout: Google files you can open offline

gdocout downloads Google Docs, Sheets and Slides in Office formats through the same links Google's own Download menu uses. Files shared "anyone with the link" need **no sign-in at all**. Files that aren't shared that way can come through the **user's own web browser**, when it's signed in to Google with an account that can open them; gdocout never sees a password or a cookie. Whatever can't be fetched either way is reported, never guessed at. Every download is checked before it counts, because Google answers errors with a web page that can look like a success.

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

Before copying anything, ask the user, unless they already said:

1. **Where the copy should go.** Always ask; never pick a folder yourself. It must be an empty folder (gdocout creates it if it doesn't exist) or a folder gdocout copied into before, to continue that copy. It can't be inside the folder being copied.
2. **Keep the folder structure, or put every file in one folder.** Keeping it is the default and stays the default unless the user asks for one folder (`--flat`). With `--flat`, files with the same name are numbered, " (2)", " (3)".
3. **What to include, only if the user hasn't said "everything".** The default is a full copy: every ordinary file copied as it is, every Google file converted. Offer these as multiple-choice questions where your tools allow it (the user can always type their own answer):
   - Google files as **Office files** (the default), **Office + PDF** (`--pdf also`), **PDF only** (`--pdf only`), or other formats (`--format document=odt,pdf`; Docs also `md`, `epub`, `txt`, `rtf`; Sheets `ods`; Slides `odp`; Drawings `png`, `svg`; My Maps `kml`).
   - Other files: **all** (default), **only some types** (`--only`), **all except some types** (`--skip`), or **none** (`--no-copy`). Types are categories (`documents`, `spreadsheets`, `presentations`, `pdf`, `images`, `video`, `audio`, `archives`, `text`, `ebooks`, `mapfiles`, `other`), Google types (`google-docs`, `google-sheets`, `google-slides`, `google-drawings`, `google-maps`, `google-forms`, `google`), or extensions (`.heic`). A category includes the matching Google files: `--only documents` takes Word files and Google Docs; `--only google-docs` takes only Google Docs. With `--only`, name the Google types the user still wants too.
   - Folders and names: `--include 'Work/'`, `--exclude 'Photos/'`, `--exclude '*.tmp'` (a trailing `/` means a folder and everything in it; `*` matches anything; not case-sensitive). For a hand-picked set of files, write their paths (relative to the source, one per line) to a file and pass `--files-from FILE`.

   Run `gdocout scan SOURCE …` with the same choices to show the user what they'd get before copying. Files left out by a choice are reported as "left out by your choice" and keep their names, so a later run without the rule adds them.

**The user would rather click than chat, or will run gdocout without Claude:** start `gdocout gui --source SOURCE --dest DEST` in the background (both optional). It opens a page in their web browser with every option above, folder pickers that know where Google Drive keeps its files, a live progress view, a Stop button and the equivalent command. It prints its address; give it to the user if no browser window appeared. The page runs on their computer only. Stop it afterwards (Quit in the page, or end the process).

### 3a2. Get the files onto the computer, and the browser signed in

**Files on the computer.** Google Drive for desktop's "stream files" mode keeps only placeholders for files nobody opened, and those can't be copied as they are. Before a big copy, tell the user to make the folders available offline in Google Drive: right-click the folder (or My Drive) › **Offline access** › **Available offline**, and wait for the green ticks; or switch Drive to **Mirror files** (Drive › Settings › Preferences › Folders from Drive › My Drive syncing options). Only the user can change that setting (there's no command for it), unless you can operate their screen and they agree. Google Docs, Sheets and Slides never become real files in Drive either way; gdocout downloads those. As a fallback, `--fetch-placeholders` makes gdocout ask Google Drive to download each placeholder itself while Drive is running and signed in (slower for a whole Drive; each file has a time limit, so a stuck Drive can't hang the copy).

**Browser signed in (recommended).** Ask whether the user is signed in to Google in their web browser with the **same account Google Drive uses**. If so, add `--browser` (or `--browser chrome|safari|edge|firefox|brave|arc`): after the link-shared files, gdocout opens each file that Google refused in that browser, one at a time, using the account recorded in the Drive shortcut file, and moves the download from the browser's download folder into the copy. Tell the user: the browser may ask once to allow downloads from docs.google.com (allow it); a file the account can't open leaves an "Access Denied" tab, and gdocout stops after three such failures in a row; these downloads run at roughly ten a minute. Files the owner shared only with the account, or where the account is the owner, come through this way, including ones whose download is turned off for viewers when the account is the owner or an editor.

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

Exit codes: 0 finished; 1 finished, but some files failed (they are retried on the next run); 2 a problem with the request (paths, permissions, a destination in use for another folder, an unknown type or format); 5 Google kept refusing downloads from this connection, so the copy stopped with everything so far saved (run the same command later, an hour or more, to continue); 130 stopped by hand (same command continues).

### 3d. Tell the user what happened

Summarise from the JSON. **Never list every file.** The report is the place for that.

- One line of totals: converted, copied, extra formats (`extra_formats`), left out by choice, and the total written.
- Then each group in `attention`, with its count and up to five example paths:
  - `download_off`: anyone with the link can view it, but its owner turned off downloading. Only the owner can change that. Say so plainly, and don't try to work around it (no screenshots, printing or copying text from the viewer).
  - `not_shared`: not shared with "anyone with the link". The owner has to share it that way.
  - `not_found`: deleted, or a wrong shortcut.
  - `no_offline_format`: Google Forms and other types with no download. The copy holds a small link page in their place.
  - `not_on_disk`, `unreadable`, `failed` (retried next run), `pending` (not done yet, the next run continues).
- `renamed` and `with_warnings` counts, if not zero.
- The report: `report` is a self-contained HTML page in the destination. It lists every file with a folder tree, status, type and extension filters, search, a CSV download of the filtered list, and a "Copy Google links" button that gives the owner a list of what to re-share. Offer to open it.

After an owner changes sharing, `gdocout copy SOURCE --dest DEST --recheck` asks Google again about the refused files only.

### 3e. When the computer says no

- **"macOS isn't letting this app read …"** (exit 2): the app running gdocout needs permission to read that folder. On macOS that's System Settings → Privacy & Security → Files and Folders (for Google Drive's folder, Desktop, Documents, Downloads or a removable disk), or Full Disk Access, for the app that runs the command (Terminal, Claude, …). Tell the user exactly that; they have to switch it on themselves, then quit and reopen the app.
- **Placeholders** (`not_on_disk`): Google Drive's "stream files" mode keeps only a placeholder for files nobody opened. gdocout never opens them, because reading one makes Drive download it, which needs Drive running and signed in. The user can make the folder available offline in Google Drive first (right-click › Offline access › Available offline, or switch Drive to "Mirror files"), then run the copy again.
- **A company or school Google account** may only allow links that work inside that organisation; those files come back `not_shared`, because gdocout never signs in.

## 3f. Where this works

- **Claude Code** (the Code tab of Claude Desktop, or `claude` in a terminal) on the user's computer: everything above.
- **Without Claude**: the `gdocout` command and `gdocout gui` do all of it on their own.
- **Claude Cowork**: the plugin installs there, but Cowork runs commands inside its own Linux virtual machine that sees only the folders the user attached, with filtered network access. The copy itself can work there if the user attaches both the Drive folder and the destination and Cowork's network setting allows docs.google.com and googleusercontent.com. What needs the computer itself doesn't: `gdocout gui` (the browser can't reach the virtual machine), `--browser` (the virtual machine can't open the user's browser), and spotting or fetching placeholders (macOS's placeholder marks aren't visible from Linux). So in Cowork, have the user make the Drive available offline first, and use Claude Code or `gdocout gui` for files that aren't shared by link. Cowork hasn't been tested.

## 4. How the files are checked

If the user asks whether the converted files can be trusted: every download must be the right kind of file (Office files are ZIP archives whose every part passes its checksum, with the parts Word, Excel or PowerPoint needs, and well-formed XML); a web page or an empty answer is never kept. The report shows what was read from each file (words and pictures in a document, sheet names, slide count). Ordinary files are copied and their SHA-256 compared with the original. Nothing is half-written: files are written under a temporary name and renamed only once they pass.

## 5. Status words

`converted`, `copied`, `download_off` ("download turned off"), `not_shared` ("not shared by link"), `not_found`, `no_offline_format`, `not_on_disk` ("not on this computer"), `unreadable`, `failed`, `pending` ("not done yet"), `ignored` (system files such as .DS_Store), `source_gone`.

## Don't

- Don't sign in to Google yourself, read browser cookies, or ask for the user's Google password. Signed-in downloads go through the user's own browser (`--browser`), never through gdocout.
- Don't choose the destination folder yourself.
- Don't delete or change anything in the source folder.
- Don't paste the whole file list into the conversation; point to the report.
