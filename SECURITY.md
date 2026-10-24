# Security

Please report a security problem privately, not in a public issue: open the repository's **Security** tab and choose **Report a vulnerability**. Only the maintainer sees the report, and you'll get a reply there.

gdocout reads a folder, writes into another, and downloads from Google without signing in (see [PRIVACY.md](PRIVACY.md)). Worth reporting: a shortcut file or a file name that makes gdocout write outside the destination or request something other than a Google download, a report page that runs code from a file name, a way for another web page or program to drive the `gdocout gui` window (it listens on 127.0.0.1 only and needs a random secret in the address and a header), or a problem with how the plugin installs gdocout.

Fixes go out as a new release, and the plugin's skill installs that release.
