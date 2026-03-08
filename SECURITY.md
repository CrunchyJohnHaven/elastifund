# Security Policy

## Scope

Elastifund contains trading logic, automation infrastructure, and coordination tooling. Security issues can affect live funds, credentials, or private research workflows. Treat potential vulnerabilities seriously.

## Supported review surface

The public repository is reviewed on a best-effort basis for:

- secret exposure
- unsafe defaults in onboarding or deployment
- auth or registration issues in the hub layer
- dependency or supply-chain risks that materially affect local operators

## Reporting

Do not open a public issue for a suspected security problem.

Use GitHub's private vulnerability reporting flow if it is enabled for the repository. If that is unavailable, contact the maintainer privately through the contact path listed on the GitHub profile or [elastifund.io](https://elastifund.io) before public disclosure.

Include:

- what you found
- how to reproduce it
- what versions or paths are affected
- whether credentials or funds could be exposed

## Secrets handling

- Never commit `.env`, wallet keys, `.pem` files, or local database exports.
- Run `make hygiene` before opening a PR.
- Treat all bootstrap tokens as secrets when operating a shared hub.

## Disclosure expectations

We prefer coordinated disclosure. Once a fix or mitigation exists, public writeups are welcome.
