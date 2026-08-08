"""Error taxonomy.

LedgerError means the *ledger or environment* is wrong (bad schema, bad
selector, unreadable file) and always maps to exit code 2 — even when it
surfaces while processing an individual claim.  Reconciliation failures
(a number that does not match, a missing anchor, an uncovered token) are
never exceptions; they are reported as records and map to exit code 1.
"""


class LedgerError(ValueError):
    """Configuration error: the ledger cannot be trusted to run."""

    def __init__(self, message: str, path: str = "") -> None:
        self.path = path
        super().__init__(f"{path}: {message}" if path else message)
