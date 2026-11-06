# Contributing to gdocout

Fixes and improvements are welcome. Here's how a change gets in.

## Before you start

- A small fix (a typo, a bug with an obvious fix): open a pull request straight away.
- Anything bigger, or a change to how gdocout behaves: open an issue first, so we agree on it before you write the code.
- Questions go to [Discussions](https://github.com/RazorII/gdocout/discussions/categories/q-a).
- A security problem goes through [SECURITY.md](SECURITY.md), never a public issue or pull request.

## Making the change

1. Fork the repository and create a branch from `main`.
2. Set up and run the tests:

   ```
   uv venv && uv pip install -e ".[test]"
   pytest
   ```

3. Add a test for what you changed. Tests use made-up values only (example.com addresses, 555-01xx phone numbers, invented names), never a real person's name or document.
4. Open the pull request against `main`, and say what it fixes and how you tested it.

CI runs the tests on macOS, Windows and Linux. GitHub holds the first run for every new contributor until I approve it.

## How your change lands

Once CI passes and I've reviewed it, I merge your pull request with a merge commit, so your commits land exactly as you pushed them, under your name. If something needs changing, I'll ask in the pull request rather than edit your branch.

A release follows separately: the plugin installs a tagged version, so a merged change reaches users with the next release.

## License

By contributing you agree that your work is released under the [MIT License](LICENSE), like the rest of gdocout.
