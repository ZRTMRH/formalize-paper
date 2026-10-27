# Security

formalize-paper runs AI agents that execute code in your Lean project. Its permission list saves
prompts; it is **not a sandbox** (INSTALL.md, "Permissions"). Run formalizations under a dedicated
user account or on a dedicated machine or VM that holds no credentials you are not willing to
expose. The protocol's integrity checks detect tampering with the audit record after the fact; they
do not prevent it (KNOWN_LIMITATIONS.md, "The record proves consistency, not provenance").

## Reporting a vulnerability

Please report a security problem privately, through GitHub's "Report a vulnerability" button on
the repository's Security tab, rather than in a public issue. Examples: a way for a reviewer agent
to change the record undetected, a permission rule that allows more than INSTALL.md says, or an
installer step that writes outside the paths INSTALL.md, "Uninstall", lists.
