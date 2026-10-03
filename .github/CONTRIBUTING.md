# Contributing

Contributions are welcome. For anything bigger than a small fix, open an issue
first so we can align before you spend time on it.

Please follow the [code of conduct][code-of-conduct] in all your interactions
with the project.

AI tools are welcome as an aid, but you are responsible for everything you
submit: review and understand it before opening a pull request. Autonomous
agents are not allowed, and unreviewed AI output will be closed. Read the
[AI policy][ai-policy] before contributing.

## Issues and feature requests

Found a bug, a mistake in the documentation, or want a new feature? Open an
issue on the [GitHub repository][github]. Search the existing issues first,
your question may already be answered.

Found a security vulnerability? Do not open a public issue; follow the
[security policy][security] instead.

Real device data helps a lot. The JSON your device serves at
`http://<your-device>/json` is exactly what the tests under `tests/fixtures`
are built from.

## Development

The full setup, dependencies, and check/test commands live in the
[README](../README.md#setting-up-development-environment). In short: this is a
[Poetry][poetry] project that also uses NodeJS for some checks.

```bash
npm install
poetry install --extras cli
poetry run prek run --all-files   # lint + format + type + test hooks
poetry run pytest                 # just the tests
```

Every change is linted, type-checked, and tested in CI, which must be green
before a pull request can merge. Keep coverage up and match the surrounding
style (clear names, why-comments, no silent failures).

## Pull requests

1. Search for open or closed [pull requests][prs] that relate to yours, so you
   don't duplicate effort.
1. Keep the change focused and describe what it does and why.
1. Make sure tests cover your change and the full check suite passes locally.

[ai-policy]: https://github.com/frenck/python-wled/blob/main/AI_POLICY.md
[code-of-conduct]: https://github.com/frenck/python-wled/blob/main/.github/CODE_OF_CONDUCT.md
[github]: https://github.com/frenck/python-wled/issues
[poetry]: https://python-poetry.org
[prs]: https://github.com/frenck/python-wled/pulls
[security]: https://github.com/frenck/python-wled/blob/main/.github/SECURITY.md
