"""Studio SQLite-backed persistence layer.

Per Schema.md, the store keeps three things:
- Project: identity + name + creation timestamp.
- SourceDocument: content + content_sha256 + monotonically-bumping version.
- VerificationRun: candidate answer, verdicts, gate result, and — crucially
  — the version of every source document the run was actually checked
  against. That pinned version set is what makes "edit a source and the
  old run still reproduces" possible.
"""
