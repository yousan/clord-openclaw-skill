# C-lord dispatch skill for OpenClaw

An OpenClaw skill and standard-library Python CLI for handing work to [c-lord](https://github.com/yousan/c-lord), with explicit Discord routes, repository/body separation, startup observation, and private send receipts.

**Status: pre-test implementation. No unit, multi-model, or live dispatch acceptance tests have been run.** Installing this skill is not a claim that dispatch works on a fresh agent. The requested next gate is the test matrix in [docs/acceptance.md](docs/acceptance.md).

## Why

A malformed `repo:` prefix can swallow task text into a repository URL. A successful webhook POST can still fail to create a running C-lord session. An innocent follow-up can interrupt active work. This skill makes those distinctions explicit instead of relying on an agent remembering a local AGENTS.md.

## Included

- [SKILL.md](skills/clord-dispatch/SKILL.md): self-contained agent workflow, no personal AGENTS.md or prior chat required.
- [dispatch.py](skills/clord-dispatch/scripts/dispatch.py): `routes`, `new`, `receipt`, `observe`, `status`, `followup`.
- [Setup](skills/clord-dispatch/references/setup.md) and [example config](examples/config.example.json).
- [Offline test source](tests/test_dispatch.py) and [fresh-agent/model evaluation specification](docs/acceptance.md), both **not executed**.

## Install for one agent

Clone this repository, then copy `skills/clord-dispatch/` to that agent's `<workspace>/skills/clord-dispatch/`. Keep the full scripts/references directory. Do not overwrite unrelated workspace files. Follow the setup reference to configure routes privately; a clone is not a configured Discord connection.

Python 3.10+, Linux/macOS. No third-party Python dependencies. Requires an existing configured c-lord deployment, a C-lord bot token with appropriate Discord permissions, and an existing incoming webhook in each allowed text channel. Only GitHub repository URLs are supported in this initial implementation.

## Local validation (not a delivery test)

```sh
python3 skills/clord-dispatch/scripts/dispatch.py --config /private/config.json new \
  --route demo --repo https://github.com/OWNER/REPO \
  --key demo-task-001 --file /private/order.md \
  --summary 'Demo task' --origin 'original-conversation-url' --dry-run
```

Use unique operation keys for distinct tasks and reuse the same key for retries of the same task. The CLI will not resend a recorded operation. After an uncertain send, inspect the receipt and observe the existing message.

## Boundaries

- No automatic route discovery, new webhook creation, cross-project fallback, or shell execution of task text.
- No automatic follow-up queue; follow-ups hold by default. `--interrupt-approved` requires actual authorization, not an agent's preference to send.
- No claim that a Discord thread implies a live C-lord session. Remote sessions.db inspection is not implemented.
- No credentials, real routes, local host details, or private task bodies in this repo. Credentials stay on the operator's host.
- Tests have not been run. No CI workflow is included, so pushing this pre-test source does not automatically start tests.

Future tests must compare a fresh agent with/without this skill, across models and independent trials, using a dedicated test channel and harmless repository. See the acceptance specification before enabling live test execution.

MIT licensed. Independent of the OpenClaw and c-lord projects; this repository is not a bundled OpenClaw plugin.
