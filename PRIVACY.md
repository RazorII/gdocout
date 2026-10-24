# Privacy

gdocout and its Claude plugin collect no data.

- **gdocout talks only to Google, and only to download.** For each Google file it asks Google's own download link for that file (`docs.google.com`, or `google.com/maps` for My Maps), and, when Google refuses, the file's view page once, to tell "download turned off" from "not shared". Google sees those requests the way it sees anyone downloading a link-shared file: the file's ID and your IP address. Google's [privacy policy](https://policies.google.com/privacy) covers that.
- **No account, no sign-in, no cookies.** gdocout never asks for a Google password, never reads your browser's cookies, and keeps no cookies between requests.
- **Your files stay on your computer.** Ordinary files are copied from one folder to another on your machine. The report, the copies and gdocout's own record of the run stay in the destination folder.
- **gdocout sends nothing anywhere else.** No telemetry, no analytics, no crash reports.
- **Installing it** downloads gdocout from [GitHub](https://github.com/RazorII/gdocout); it has no dependencies to fetch.
- **Claude itself is covered by Anthropic's privacy policy.** When you use gdocout through Claude, what Claude does with your conversation falls under [Anthropic's privacy policy](https://www.anthropic.com/legal/privacy), not this one.

Questions go to the repository's Discussions.
