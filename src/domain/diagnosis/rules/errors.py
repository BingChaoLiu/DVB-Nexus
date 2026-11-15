"""SPEC-307 §8 fail-fast error for rule declarations (ticket #55).

Deliberately NOT a ``ValueError`` subclass: pydantic wraps ValueError
raised inside validators into a ``ValidationError``, and this error must
propagate unwrapped — startup composition code (and the tests pinning the
fail-fast matrix) needs to catch exactly the rule-definition violation,
distinct from structural pydantic typing failures.
"""


class RuleDefinitionError(Exception):
    """A rule declaration violates the SPEC-307 declarative contract.

    Raised at REGISTRATION time (startup load / parse) per SPEC-307 §8
    rows 1-2: a rule JSON that fails validation or a match referencing an
    unregistered event type fails the startup — never a silent skip.
    """


__all__ = ["RuleDefinitionError"]
