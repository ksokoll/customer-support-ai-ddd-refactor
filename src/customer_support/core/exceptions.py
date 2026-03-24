# core/exceptions.py
"""Domain exception classes for all bounded contexts.

Convention: when adding a new bounded context, register its exception
here — not locally in the context module.
"""


class ClassificationError(Exception):
    """Raised when intent classification fails."""


class RetrievalError(Exception):
    """Raised when knowledge base retrieval fails."""


class GenerationError(Exception):
    """Raised when response generation fails."""


class QualityAssuranceError(Exception):
    """Raised when the quality assurance evaluation fails."""