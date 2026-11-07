"""Mechanical stop-slop checks on page text.

Counts the patterns the stop-slop editing checklist names: filler phrases, adverbs, binary
contrasts, lazy extremes, passive voice, Wh- openers, three-item lists, em-dashes, rhythm.
It measures writing patterns, not authorship: a person can write every pattern it flags.

Usage:
    python -I slop_check.py page.html [more.html ...]        # human-readable report
    python -I slop_check.py --json page.html                 # one JSON object per file
"""
import argparse
import json
import re
import sys
from html.parser import HTMLParser

PHRASES = [
    "here's", "here is the thing", "the uncomfortable truth", "it turns out", "the real ",
    "let me be clear", "the truth is", "i'll say it again", "i'm going to be honest",
    "can we talk about", "full stop", "let that sink in", "this matters because",
    "make no mistake", "navigate", "unpack", "lean into", "landscape", "game-changer",
    "double down", "deep dive", "take a step back", "moving forward", "circle back",
    "on the same page", "at its core", "in today's", "it's worth noting",
    "at the end of the day", "when it comes to", "in a world where", "the reality is",
    "hint:", "plot twist", "spoiler", "you already know", "a feature, not a bug",
    "dressed up as", "let me walk you", "in this section", "as we'll see", "i want to explore",
    "creeps in", "i promise", "the stakes are", "the implications are", "the reasons are",
    "the consequences are", "think about it", "what if", "and that's okay",
    "here's what i mean", "leverage", "seamless", "unlock", "empower", "elevate",
]
ADVERBS = [
    "really", "just", "literally", "genuinely", "honestly", "simply", "actually", "deeply",
    "truly", "fundamentally", "inherently", "inevitably", "interestingly", "importantly",
    "crucially",
]
NOT_ADVERBS = {"only", "reply", "apply", "supply", "italy", "family", "early", "july",
               "comply", "fly", "rely", "ally", "daily", "weekly", "monthly", "yearly"}
EXTREMES = ["every", "always", "never", "everyone", "everybody", "nobody"]
WH = ("What", "When", "Where", "Which", "Who", "Why", "How")
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "td", "th", "blockquote", "figcaption"}
SKIP_TAGS = {"script", "style", "svg", "noscript", "template"}
PUNCHY_MAX_WORDS = 8

_PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b",
                      re.I)
_CONTRAST = re.compile(
    r"[^.!?]*(?:, not (?:to |a |an |the )?\w+|\bnot just\b|\bisn't\b[^.!?]*\bit's\b"
    r"|\bit's not\b[^.!?]*\bit's\b|\bnot\b[^.!?]*\bbut\b)[^.!?]*[.!?]?", re.I)
_THREE_LIST = re.compile(r"\b\w+(?: \w+){0,3}, \w+(?: \w+){0,3},? (?:and|or) \w+(?: \w+){0,2}")


class _Blocks(HTMLParser):
    """Collects visible text per block-level element."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self._cur, self._skip = [], None, 0

    def handle_starttag(self, tag, attrs):
        del attrs
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS and self._cur is None:
            self._cur = [tag, ""]
        elif tag == "br" and self._cur:
            self._cur[1] += " "

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif self._cur and tag == self._cur[0]:
            text = re.sub(r"\s+", " ", self._cur[1]).strip()
            if text:
                self.blocks.append((tag, text))
            self._cur = None

    def handle_data(self, data):
        if self._cur and not self._skip:
            self._cur[1] += data


def extract_blocks(html):
    """Return visible text blocks of an HTML document.

    Args:
        html: The document source.

    Returns:
        A list of (tag, text) tuples in document order, scripts and styles excluded.
    """
    parser = _Blocks()
    parser.feed(html)
    return parser.blocks


def sentences(text):
    """Split text into sentences, keeping abbreviations such as P.S. intact."""
    text = re.sub(r"\b(P\.S|e\.g|i\.e|etc)\.", lambda m: m.group(1).replace(".", ""), text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(])", text)
    return [p.strip() for p in parts if p.strip()]


def _word_count(sentence):
    return len(re.findall(r"[\w'’+°-]+", sentence))


def check_text(text):
    """Run every stop-slop check on plain text.

    Args:
        text: Prose to check.

    Returns:
        A dict of findings; list values hold the matched evidence.
    """
    low = text.lower()
    words = re.findall(r"[A-Za-z'’]+", text)
    sents = sentences(text)
    return {
        "words": len(words),
        "phrases": [p for p in PHRASES if p in low],
        "adverbs": [w for w in ADVERBS if re.search(rf"\b{w}\b", low)],
        "ly_words": sorted({w.lower() for w in words
                            if w.lower().endswith("ly") and len(w) > 4
                            and w.lower() not in NOT_ADVERBS}),
        "extremes": [w for w in EXTREMES if re.search(rf"\b{w}\b", low)],
        "contrasts": [m.group(0).strip() for m in _CONTRAST.finditer(text)],
        "passives": _PASSIVE.findall(text),
        "wh_starts": [s for s in sents if s.startswith(WH)],
        "so_look_starts": [s for s in sents if s.startswith(("So ", "Look,"))],
        "three_lists": _THREE_LIST.findall(text),
        "em_dashes": text.count("\u2014"),
        "en_dashes": text.count("\u2013"),
    }


def check_blocks(blocks):
    """Run text checks over blocks, plus rhythm checks that need block boundaries.

    Args:
        blocks: (tag, text) tuples from extract_blocks.

    Returns:
        check_text findings plus sentence lengths per block, matched-length runs, and
        punchy_endings as [blocks ending on a short line, multi-sentence blocks].
    """
    result = check_text(" ".join(t for _, t in blocks))
    lengths, runs, punchy, multi = [], [], 0, 0
    for tag, text in blocks:
        sents = sentences(text)
        counts = [_word_count(s) for s in sents]
        if len(sents) > 1:
            multi += 1
            punchy += counts[-1] <= PUNCHY_MAX_WORDS
            lengths.append({"tag": tag, "lengths": counts})
        for i in range(len(counts) - 2):
            window = counts[i:i + 3]
            if max(window) - min(window) <= 1:
                runs.append(sents[i:i + 3])
    result.update(sentence_lengths=lengths, matched_runs=runs, punchy_endings=[punchy, multi])
    return result


def check_file(path):
    """Check one HTML or text file and label the result with its path."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        source = fh.read()
    blocks = extract_blocks(source) if "<" in source else [("p", source)]
    return {"file": path, "blocks": len(blocks), **check_blocks(blocks)}


def _print_human(res):
    print(f"\n=== {res['file']}: {res['blocks']} blocks, {res['words']} words")
    for key in ("phrases", "adverbs", "ly_words", "extremes", "contrasts", "passives",
                "wh_starts", "so_look_starts", "three_lists"):
        print(f"{key:15}: {res[key] or 'none'}")
    print(f"{'dashes':15}: em {res['em_dashes']}, en {res['en_dashes']}")
    for item in res["sentence_lengths"]:
        print(f"  [{item['tag']}] sentence lengths {item['lengths']}")
    for run in res["matched_runs"]:
        print("  ! three matched lengths:", run)
    print(f"{'punchy endings':15}: {res['punchy_endings'][0]} of {res['punchy_endings'][1]} "
          f"multi-sentence blocks end on <= {PUNCHY_MAX_WORDS} words")


def main(argv=None):
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description="Mechanical stop-slop checks on page text.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true", help="print a JSON list")
    args = ap.parse_args(argv)
    results = [check_file(f) for f in args.files]
    if args.json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        for res in results:
            _print_human(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
