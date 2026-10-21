# Setup and operation

## Host setup

1. Use Python 3.10+ on Linux or macOS; the receipt lock uses `fcntl`. No pip dependencies.
2. Initialize C-lord for the intended Discord text channel using the deployment's documented procedure (`/clord-init repo:...` where applicable). This CLI does not initialize channels, install C-lord, create webhooks, or infer other channels.
3. Prepare an existing incoming webhook for each allowed channel. The configured C-lord bot token must be able to read those channels/threads and list existing webhooks. Set the exact webhook ID when multiple hooks exist. Ask before creating a new webhook; this CLI never creates one.
4. Copy the repository's `examples/config.example.json` outside the checkout and set real IDs/repo. Keep that file private (`chmod 600`). The default path is chosen in this order:
   1. `CLORD_DISPATCH_CONFIG`, if set.
   2. When the skill is installed under `~/.openclaw-<profile>/` (one OpenClaw profile per agent): `~/.config/clord-dispatch/<profile>.json`. Give each agent only the routes it may use. If that file is missing, the CLI stops; it does not fall back to another agent's config.
   3. Otherwise `~/.config/clord-dispatch/config.json`.
5. Set the named token environment variable on the gateway process. Alternatively, a private `bot_token_env_file` config field may reference an existing file with `KEY=value` lines; `bot_token_env` is also the key to read from it. This is a small parser, not shell execution; do not use variable expansion. Never place tokens, webhook token URLs, or real private config in this repository.
6. Install the `skills/clord-dispatch` directory under the intended agent's `<workspace>/skills/clord-dispatch`. Copy the complete directory, not just SKILL.md. Keep installed files matched to one source commit. This does not change other agents' skill directories or require a gateway restart in versions with skill refresh.

## Commands

`python3 /path/to/clord-dispatch/scripts/dispatch.py --config /private/config.json routes`

`--config` is global and comes before the subcommand. `--file` is UTF-8 task text, not shell code. Do not interpolate task text into shell commands. Use `new --repo URL` separately from the body file. The CLI inserts a literal space after repo URL (including when task text starts with a newline).

Operations:

- `routes`: list configured destinations (local only).
- `new --route NAME --repo URL --key KEY --file FILE --summary TEXT --origin URL [--dry-run] [--wait 0..30]`.
- `receipt --key KEY`: read an existing private receipt, including uncertain sends.
- `observe --route NAME --key KEY [--wait 0..30]`: read Discord and update an existing receipt; does not resend.
- `status --route NAME --thread ID`: validate the thread's parent/guild and read recognized C-lord status.
- `followup --route NAME --thread ID --key KEY --file FILE --origin URL [--dry-run] [--interrupt-approved]`: defaults to holding, not sending. The override records a deliberate decision by the operator; it is not evidence of session liveness.

Use one stable key per logical operation. Never rotate keys to bypass a pending/uncertain receipt. New and follow-up operations need distinct keys. The local receipt lock prevents concurrent operations in this state directory; it does not coordinate independent hosts.

## What the evidence means

- `dry_run=true`: input validated; no network calls and no delivery claim.
- `state=sending`: receipt written before POST; the outcome may be uncertain. Inspect Discord before any recovery.
- `state=sent_unconfirmed`: Discord accepted a webhook message; C-lord execution is NOT confirmed.
- `state=started`: a matching Dispatch-ID was found in a C-lord-authored thread message, and a recognized running status was observed. Not proof of task completion.
- `state=thread_observed`: the thread was matched, but read `observation`; it can be unknown, error, or finished. In particular an error is not success.
- `held=true`: no follow-up sent. There is no automatic queue in this version.
- `duplicate_blocked=true`: an operation with that key already has a receipt. Read it; do not assume completion.

Recognized status strings are intentionally narrow. Status output `unknown` is expected when a deployment uses other messages; it never means idle. Startup observation is bounded and read-only polling can be repeated. Correlation currently searches only the latest 100 parent/thread messages: very busy or old threads may remain unconfirmed. Do not weaken correlation or resend simply to obtain a success label.

The CLI does not inspect a remote C-lord sessions database. Use a deployment-supported read-only liveness check before an authorized follow-up. On an unfamiliar host without such a check, hold and report that limitation. Task results and original private task text remain outside this repository. Report via OpenClaw to the recorded origin, not through a newly chosen Discord destination.
