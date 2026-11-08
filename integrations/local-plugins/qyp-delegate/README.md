# Configurable SSH delegation

Opt-in export of the local delegation adapter. No remote host, user, home,
executable or allowlist is supplied. Configure the settings documented in
`../../README.md` after obtaining explicit approval for the target system.

`auto` selects local inference plus SSH execution. `remote_agent` requires
separate remote model credentials and network permission; reachability is not
authentication. Foreground/background jobs and status/cancel are retained.
Only a delegated child receives `qyp_terminal`. Timeouts are outcome-unknown;
verify effects before retrying. Job specs persist structural child overrides,
not a copy of the inherited credential environment. They are private local state,
never source/publication material.

Workdirs must start inside the configured roots; a physical-cwd shell check
rejects symlink escapes. This is a workdir guard, **not** a remote shell sandbox:
commands can still access anything permitted by the SSH account. Use a genuinely
restricted remote account/container for stronger isolation. Cancelling a worker
is best effort and does not prove cancellation of remote effects. No live remote
execution was used to validate this export.
