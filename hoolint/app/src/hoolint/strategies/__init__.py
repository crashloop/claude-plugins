from hoolint.strategies.docs_ import DocLinksStrategy, DocRefsStrategy
from hoolint.strategies.escalate import EscalateStrategy
from hoolint.strategies.local_llm import LocalLLMStrategy
from hoolint.strategies.regex_ import RegexStrategy
from hoolint.strategies.semantic import SemanticStrategy

STRATEGIES = {
    "regex": RegexStrategy(),
    "semantic": SemanticStrategy(),
    "local_llm": LocalLLMStrategy(),
    "escalate": EscalateStrategy(),
    "doc_links": DocLinksStrategy(),
    "doc_refs": DocRefsStrategy(),
}
