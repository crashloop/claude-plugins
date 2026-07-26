from hoolint.strategies.changeset_ import ChangeSizeStrategy, CompanionStrategy
from hoolint.strategies.docs_ import DocLinksStrategy, DocRefsStrategy
from hoolint.strategies.escalate import EscalateStrategy
from hoolint.strategies.local_llm import LocalLLMStrategy
from hoolint.strategies.regex_ import RegexStrategy
from hoolint.strategies.semantic import SemanticStrategy

STRATEGIES = {
    "change_size": ChangeSizeStrategy(),
    "companion": CompanionStrategy(),
    "doc_links": DocLinksStrategy(),
    "doc_refs": DocRefsStrategy(),
    "escalate": EscalateStrategy(),
    "local_llm": LocalLLMStrategy(),
    "regex": RegexStrategy(),
    "semantic": SemanticStrategy(),
}
