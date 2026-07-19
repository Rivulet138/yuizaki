# Security Policy

## Supported version

Security fixes are applied to the current `main` branch. Historical snapshots
and locally modified builds are not supported.

## Reporting a vulnerability

Do not open a public issue containing credentials, private memory, captured
screen content, exploit details, or personal data.

Use GitHub private vulnerability reporting when it is enabled for this
repository. Otherwise contact the repository owner through a private GitHub
channel and include:

- affected commit and platform;
- minimal reproduction steps;
- expected and observed security boundary;
- whether credentials, local files, memory, audio, or screen content are at
  risk;
- suggested mitigation, when known.

The maintainer should acknowledge a complete report within seven days. Do not
publish the issue until a fix is available or coordinated disclosure has been
agreed.

## Security boundaries

- Backend and Electron control APIs bind to loopback by default and require
  per-run authentication tokens.
- Plugins are untrusted input and must stay within declared routes, tool
  scopes, model scopes, filesystem roots, and process limits.
- Local databases, generated audio, screenshots, settings, credentials, and
  downloaded models must never be committed.
- Destructive memory and storage operations are permanent and require explicit
  user intent.
- Screen capture on Linux follows the desktop portal or compositor permission
  model and must not bypass the user's selection.
