# gdocout plugin for Claude

Turns Google Docs, Sheets and Slides into Word, Excel and PowerPoint files without signing in to Google, for files shared "anyone with the link". Give Claude one link, or point it at a whole Google Drive saved offline: it copies everything, converts every Google file it can, and tells you which ones it couldn't save and why (download turned off by the owner, not shared by link, deleted, or a type like Google Forms that has no download). A self-contained HTML report lists every file, with filters and a folder tree.

## Requirements

- Python 3.9 or newer, to install the `gdocout` command. It has no other dependencies.
- A place where Claude can run commands: Claude Code on macOS, Windows or Linux.
- Internet access to Google.
- For files that aren't shared "anyone with the link": your web browser signed in to Google with an account that can open them (recommended: the account Google Drive uses).

## What the plugin runs and connects to

- **The plugin is one skill**: instructions that tell Claude how to use the `gdocout` command. It has no hooks, no MCP servers and no background processes.
- **It runs one command, `gdocout`**: Python, standard library only, MIT licensed, source at [github.com/RazorII/gdocout](https://github.com/RazorII/gdocout). If it isn't installed, Claude installs the release this plugin belongs to, pinned to its tag (`git+https://github.com/RazorII/gdocout@v0.1.0`), with uv, pipx or pip.
- **It connects to these sites and no others:**
  - `docs.google.com`: Google's own download links for Docs, Sheets, Slides and Drawings, and, when Google refuses one, that file's view page once, to tell "download turned off" from "not shared".
  - `*.googleusercontent.com`: where Google serves those downloads from (it redirects there).
  - `www.google.com/maps`: the download link for Google My Maps.
  - `github.com`: only to install the command.
  No telemetry, no analytics, no other servers ([privacy policy](https://github.com/RazorII/gdocout/blob/main/PRIVACY.md)).
- **It never handles a Google password, token or cookie.** Files shared "anyone with the link" are fetched without signing in. For the rest, with the user's OK, gdocout opens Google's download link in the user's own web browser (`--browser`), which downloads it with the user's own sign-in; gdocout then moves the finished file from the browser's download folder into the copy.
- **It reads the folder the user names and writes only into the destination the user names.** Claude asks for the destination every time.
- **`gdocout gui`** serves its window to the user's own browser at `127.0.0.1` (this computer only, with a random secret in the address).
- With `--fetch-placeholders`, it reads files that Google Drive for desktop keeps only as placeholders, so that Drive downloads them, each read with a time limit.

## Examples

- "Save this Google Doc as a Word file: https://docs.google.com/document/d/…" Claude downloads it as .docx and checks it.
- "My friend's whole Google Drive is in this folder. Make a copy I can open without Google." Claude asks where to put it, looks through the folder, tries a sample to check the files really are shared by link, copies everything, then summarises what needs the owner's attention and opens the report.
- "Copy only the Google Docs and the PDFs, and give me a PDF of each Doc too." Claude sets the choices, shows what that would include, then copies.
- "I'd rather pick the options myself." Claude opens gdocout's own window in your browser, with every option and a Start button. It works without Claude too.
- "These are all my own files, and I'm signed in to Google in Safari." Claude adds the browser route, so files that aren't shared by link come through your own browser too.
- "Which of these Google files can't be downloaded?" Claude runs a copy and lists them by reason.
- "The owner re-shared some files. Try those again." Claude asks Google again about only the refused files.

## Install

```
claude plugin marketplace add RazorII/claude-plugins
claude plugin install gdocout@razorii
```

Source, issues and the full documentation: [github.com/RazorII/gdocout](https://github.com/RazorII/gdocout). MIT licensed.
