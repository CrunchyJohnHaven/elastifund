# Support

## Before opening an issue

Run these from the repo root:

```bash
make bootstrap
make doctor
make hygiene
make test
```

If the problem is specific to the standalone bot package, also run:

```bash
make test-polymarket
```

## Where to ask what

- Setup trouble or unexpected behavior: open a GitHub issue
- Security-sensitive reports: follow [SECURITY.md](SECURITY.md)
- General project context: start with [README.md](README.md), [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md), and [docs/REPO_MAP.md](docs/REPO_MAP.md)

## Good issue reports include

- exact command run
- exact error output
- whether Docker is installed and working
- whether the failure is in the root stack or `polymarket-bot/`
- what you already tried
