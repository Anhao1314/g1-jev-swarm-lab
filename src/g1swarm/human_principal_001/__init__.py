"""TEST_ONLY explicit principal confirmation; no production identity adapter."""
from .contract import Confirmation, Presentation, TestPrincipalAuthority, TestSession

__all__ = ["Confirmation", "Presentation", "TestPrincipalAuthority", "TestSession"]
