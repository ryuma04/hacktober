# DepExit for VS Code

Brings the DepExit **Dependency Exit Capsule** into the editor:

- **Diagnostics** on every manifest line and usage location (`file:line`) of an at-risk dependency. Private-API use
  and monkeypatching are called out.
- **Hover:** risk indicators, the Gemma 4 rationale and proposal, migration steps and the test gaps measured in Docker.
- **Quick fix:** "replace file with its migrated version". Opens a diff against the version that was tested in the
  sandbox, then applies it only after you confirm.
- **Status bar:** the at-risk count and verdict. Click it to open `CAPSULE.md` as a Markdown preview.

## Use
1. Start DepExit (`run.ps1` or `make dev` in the repo root) so the API is on `http://localhost:8080`.
2. Open the analysed project (for example a clone of LinkWatch) as the workspace.
3. Run **DepExit: Analyze This Workspace** (the repo URL is taken from `git remote origin`), or
   **DepExit: Load Analysis by ID** for an existing run.

Settings: `depexit.apiUrl`, `depexit.minLevel`.

## Run from source
Open this folder in VS Code and press **F5** (Extension Development Host). Packaging: `npx @vscode/vsce package`.
