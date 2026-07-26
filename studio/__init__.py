"""Studio — backend API + storage for the Elenchus verification stack.

Per Rules.md:
- Rule 6: Studio does NOT get to import soteria/lethe. Those live in their
  own integrations subpackage and are wired up only when the user supplies
  source files.
- Rule 7: Studio consumes the Elenchus library through its public API
  (elenchus.verifier, elenchus.streaming), not internal helpers.
- Rule 2: Output gate policy is configuration, not hardcoded behavior.
"""
