from hoolint.strategies.local_llm import LocalLLMStrategy
from hoolint.strategies.regex_ import RegexStrategy
from hoolint.strategies.semantic import SemanticStrategy

STRATEGIES = {
    "regex": RegexStrategy(),
    "semantic": SemanticStrategy(),
    "local_llm": LocalLLMStrategy(),
}
