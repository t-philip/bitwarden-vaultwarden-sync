# Security Policy

This tool handles password-vault credentials. A vulnerability here has a higher cost
than in most hobby projects, so please report one privately rather than in public.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting:

**[Report a vulnerability →](https://github.com/t-philip/bitwarden-vaultwarden-sync/security/advisories/new)**

That opens a private advisory visible only to the maintainer. Please **do not** open a
public issue for anything security-relevant — a public issue is world-readable and
indexed immediately.

Helpful to include, as far as you can:

- What the issue is and roughly how it could be exploited
- Which file or step is involved
- Anything that changes the severity (does it need local access? a compromised LAN?)

No bug bounty is offered — this is a personal project maintained in spare time — but
reports are genuinely welcome and will be credited if you'd like.

## Scope

In scope: anything in this repository that could expose vault contents, credentials,
backup encryption keys, or the Vaultwarden instance.

Out of scope: vulnerabilities in Bitwarden, Vaultwarden, or the `bw` CLI themselves.
Report those to their own projects — they each have a security process.

## Using this tool safely

A few things worth knowing regardless of any vulnerability:

- Keep `.env` out of version control. The repository's `.gitignore` covers it; verify
  before your first commit if you fork this.
- The encrypted backups are only as strong as the passphrase you choose.
- Nothing here should be exposed to the internet. It is designed to run on a trusted
  host on a private network.
- If you paste logs into an issue, check them for tokens first.
