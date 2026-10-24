# Privacy

gdocout and its Claude plugin collect no data.

- **gdocout talks only to Google, and only to download.** For each Google file it asks Google's own download link for that file (`docs.google.com`, or `google.com/maps` for My Maps), and, when Google refuses, the file's view page once, to tell "download turned off" from "not shared". Google sees those requests the way it sees anyone downloading a link-shared file: the file's ID and your IP address. Google's [privacy policy](https://policies.google.com/privacy) covers that.
- **No account, no sign-in, no cookies.** gdocout never asks for a Google password, never reads your browser's cookies, and keeps no cookies between requests.
- **With `--browser`, your browser does the signed-in part.** For files that aren't shared by link, gdocout opens Google's download link in your own browser, which downloads the file with your Google sign-in as when you click Download. gdocout then moves the finished file from your downloads folder into the copy. It names the Google account from the Drive shortcut file in the link (`authuser=`), so the browser picks the right one if you're signed in to several.
- **Your files stay on your computer.** Ordinary files are copied from one folder to another on your machine. The report, the copies and gdocout's own record of the run stay in the destination folder.
- **What that record holds.** For every file: its path, size and status, the Google file ID, and the Google account email address that Google Drive wrote into the file's shortcut (used to tell your browser which account to download with). It's kept in the destination's `.gdocout` folder on your computer and goes nowhere else; delete that folder to remove it.
- **gdocout sends nothing anywhere else.** No telemetry, no analytics, no crash reports.
- **The window (`gdocout gui`) stays on your computer.** It's a page gdocout serves to your own browser at 127.0.0.1, which other computers can't reach. It lists folder names so you can choose folders, and runs the copy you set up there.
- **Installing it** downloads gdocout from [GitHub](https://github.com/RazorII/gdocout); it has no dependencies to fetch.
- **Claude itself is covered by Anthropic's privacy policy.** When you use gdocout through Claude, what Claude does with your conversation falls under [Anthropic's privacy policy](https://www.anthropic.com/legal/privacy), not this one.

Questions go to the repository's Discussions.
