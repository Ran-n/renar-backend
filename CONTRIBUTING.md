# Contributing

Thank you for your interest in contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Submitting Changes](#submitting-changes)
- [Commit Style](#commit-style)
- [License](#license)

---

## Code of Conduct

Be respectful. Harassment, discrimination, and bad-faith participation are not tolerated.

---

## Reporting Bugs

Open an issue with:

- A clear, descriptive title
- Steps to reproduce
- Expected vs. actual behavior
- Environment details (OS, Python version, etc.)

---

## Suggesting Features

Open an issue with:

- The problem you're trying to solve
- Your proposed solution
- Any alternatives you considered

---

## Submitting Changes

1. Fork the repository
2. Branch from `main`
3. Make your change
4. Commit following the [Commit Style](#commit-style) below
5. Open a pull request against `main`
6. Describe why the change is needed, not just what it does

Keep one concern per pull request.

---

## Commit Style

Title uses a bracket prefix, body follows [Conventional Commits](https://www.conventionalcommits.org/), lowercase imperative verb.

| Prefix | Meaning    |
|--------|------------|
| `[A]`  | feat       |
| `[R]`  | refactor   |
| `[F]`  | fix        |
| `[D]`  | docs       |
| `[T]`  | test       |
| `[C]`  | chore      |
| `[P]`  | perf       |
| `[B]`  | build      |
| `[S]`  | style      |

Example:

```
[R] Proxy→ProxyClient
refactor: split into proxy.py / proxy_client.py
```

- Breaking changes: use `feat!`/`fix!` or a `BREAKING CHANGE:` footer in the body
- Scope is optional

---

## License

This project is licensed under the [PayBack License (PBL)](LICENSE). It is free for personal and non-commercial use; commercial use requires a revenue-share agreement with the Founder.

Contributing does not transfer copyright. Non-trivial contributions may entitle you to a revenue share, pending listing in the [CONTRIBUTORS](CONTRIBUTORS) file and a quorum vote of the project's ownership holders.
