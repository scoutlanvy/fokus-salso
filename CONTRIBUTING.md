# Contributing to FokusSaldo

Bug reports, feature suggestions, and pull requests are welcome.

## Before opening an issue

- Search existing issues to avoid duplicates.
- For bugs, include the Windows version, Python version, steps to reproduce,
  expected behavior, and actual behavior.
- Do not attach your SQLite database, `subjects.json`, or other personal data.
  Use a fresh test database when preparing a reproduction.

## Pull requests

1. Open an issue first for substantial changes so the scope can be discussed.
2. Keep changes focused and preserve existing timer, recovery, and storage behavior.
3. Run the tests from the project root:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   ```

   Some GUI tests require a Windows desktop session.
4. Describe the user-visible change and the checks you ran in the pull request.

By submitting a contribution, you confirm that you have the right to submit it
and that it may be distributed under the project's MIT License.
