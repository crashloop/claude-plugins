from hoolint.strategies.changeset_ import ChangeSizeStrategy, CompanionStrategy
from hoolint.strategies.docs_ import (DocLinksStrategy, DocRefsStrategy,
                                      ProsePatternStrategy)
from hoolint.strategies.escalate import EscalateStrategy
from hoolint.strategies.githist_ import ChurnStrategy, CommitMetaStrategy
from hoolint.strategies.local_llm import LocalLLMStrategy
from hoolint.strategies.pyast_ import (MockEchoAssertStrategy,
                                       PermissiveRecoveryStrategy)
from hoolint.strategies.regex_ import RegexStrategy
from hoolint.strategies.semantic import SemanticStrategy

STRATEGIES = {
    "change_size": ChangeSizeStrategy(),
    "churn": ChurnStrategy(),
    "commit_meta": CommitMetaStrategy(),
    "companion": CompanionStrategy(),
    "doc_links": DocLinksStrategy(),
    "doc_refs": DocRefsStrategy(),
    "prose_pattern": ProsePatternStrategy(),
    "escalate": EscalateStrategy(),
    "local_llm": LocalLLMStrategy(),
    "mock_echo_assert": MockEchoAssertStrategy(),
    "permissive_recovery": PermissiveRecoveryStrategy(),
    "regex": RegexStrategy(),
    "semantic": SemanticStrategy(),
}
