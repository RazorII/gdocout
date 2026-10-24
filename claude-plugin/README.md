# gdocout plugin for Claude

Turns Google Docs, Sheets and Slides into Word, Excel and PowerPoint files without signing in to Google, for files shared "anyone with the link". Give Claude one link, or point it at a whole Google Drive saved offline: it copies everything, converts every Google file it can, and tells you which ones it couldn't save and why (download turned off by the owner, not shared by link, deleted, or a type like Google Forms that has no download). A self-contained HTML report lists every file, with filters and a folder tree.

## Requirements

- Python 3.9 or newer, to install the `gdocout` command. It has no other dependencies.
- A place where Claude can run commands: Claude Code on macOS, Windows or Linux.
- Internet access to Google.

## What the plugin runs and downloads

- The plugin itself is one skill: instructions that tell Claude how to use the `gdocout` command. It has no hooks, no MCP servers and no background processes.
- If `gdocout` isn't installed, Claude installs the release this plugin belongs to from [github.com/RazorII/gdocout](https://github.com/RazorII/gdocout), pinned to its version tag, with uv, pipx or pip.
- gdocout downloads from Google's own download links, without an account or cookies, and copies files on your computer. It sends nothing anywhere else and has no telemetry ([privacy policy](https://github.com/RazorII/gdocout/blob/main/PRIVACY.md)).
- Claude always asks you where the copy should go before writing anything.

## Examples

- "Save this Google Doc as a Word file: https://docs.google.com/document/d/…" Claude downloads it as .docx and checks it.
- "My friend's whole Google Drive is in this folder. Make a copy I can open without Google." Claude asks where to put it, looks through the folder, tries a sample to check the files really are shared by link, copies everything, then summarises what needs the owner's attention and opens the report.
- "Which of these Google files can't be downloaded?" Claude runs a copy and lists them by reason.
- "The owner re-shared some files. Try those again." Claude asks Google again about only the refused files.

## Install

```
claude plugin marketplace add RazorII/claude-plugins
claude plugin install gdocout@razorii
```

Source, issues and the full documentation: [github.com/RazorII/gdocout](https://github.com/RazorII/gdocout). MIT licensed.
