# Security Policy

## Safety Model

`qlab-sync` is designed to operate safely alongside live theatrical and concert QLab systems:

- **Strictly read-only QLab OSC client**: Only 4 non-mutating OSC paths are allowlisted at the serialization boundary.
- **No inbound network ports**: `qlab-sync` only initiates outbound TCP connections to the configured QLab host (`53000`) and (when `--live` is explicitly enabled) outbound HTTPS POST requests to the user's webhook endpoint.
- **Credential handling**: Pass webhook tokens via the `QLAB_SYNC_TOKEN` environment variable or a `chmod 600` local file rather than committing secrets to JSON configs.
- **QLab View-only passcodes**: Where supported by your QLab version, configure a **View** passcode (rather than Edit/Control) for `qlab-sync`.

## Reporting a Vulnerability or Safety Regression

If you find any way for `qlab-sync` to emit a non-allowlisted OSC message, violate any TLA+ safety invariant, or leak credentials, please open a GitHub Security Advisory or issue with a minimal reproduction case.
