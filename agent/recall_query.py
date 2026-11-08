"""Lexical corroboration for automatic recall, not explicit memory discovery.

Control speech is not a historical subject. Opaque object identities are exact
constraints; model/metric labels are qualifiers when a subject is also present.
No project-name allowlist, service calls, or prior-task inference lives here.
"""
from __future__ import annotations

import re
from collections.abc import Set as AbstractSet

_CONTROL_RE = re.compile(
    r"\b(?:(?:i\s+)?hereby\s+|настоящим\s+)?(?:"
    r"(?:сам\s+)?(?:можешь|можете)\s+[а-яё]+(?:ть|ти|чь)|"
    r"(?:can|could|would)\s+you\s+[a-z]+|"
    r"you have my permission|(?:i\s+)?give my consent|go ahead|do it|carry on|"
    r"(?:i\s+)?(?:authorize|authorise|approve|consent)(?:\s+(?:it|you))?(?:\s+to)?|approved|"
    r"(?:я\s+)?(?:разрешаю|согласен|согласна|одобряю)|даю согласие|"
    r"(?:можешь\s+)?(?:продолжать|сделать)|"
    r"continue|proceed|resume|finish|делай|доделывай|доделай|продолжайте|продолжай|"
    r"(?:fix|repair)(?:\s+it)?|чини|почини|исправляй|"
    r"продолжи|заверши|закончи)\b", re.IGNORECASE,
)
_DEICTIC_RE = re.compile(
    r"\b(?:for\s+(?:this|the current)\s+task(?:\s+only)?|"
    r"(?:только\s+)?для\s+(?:этой|текущей)\s+задачи|"
    r"(?:только\s+)?в\s+рамках\s+(?:этой|текущей)\s+задачи)\b", re.IGNORECASE,
)
# Paths retain directory identity; device revision suffixes stay on the model.
_WORD_RE = re.compile(r"(?<![\w])(?:/[\w.-]+){2,}|[^\W_]+(?:[_.-][^\W_]+)*(?:/\d+)?")
_QUALIFIER_RE = re.compile(
    r"(?:latest|last|schedules?|checks?|checking|results?|runs?|"
    r"како[а-яё]*|последн[а-яё]*|расписан[а-яё]*|проверк[а-яё]*|"
    r"результат[а-яё]*|установили|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"январ[а-яё]*|феврал[а-яё]*|март[а-яё]*|апрел[а-яё]*|ма[йяе]|ию[нл][а-яё]*|"
    r"август[а-яё]*|сентябр[а-яё]*|октябр[а-яё]*|ноябр[а-яё]*|декабр[а-яё]*|\d+)"
)
_UUID_RE = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
# Bind a separate follow-up clause to the explicit object in the first clause,
# rather than treating its progress/request words as alternative topics.
_COMPLEMENT_RE = re.compile(r"\b(?:with|с|со)\s+([^.!?;,\n]+)", re.IGNORECASE)
_TRANSFER_RE = re.compile(
    r"\b(?:from|с|со)\s+([\w.-]+)\s+(?:to|на)\s+([\w.-]+)", re.IGNORECASE,
)


def _words(text: str) -> list[str]:
    return list(dict.fromkeys(word.rstrip('.') for word in _WORD_RE.findall(text.casefold())))


def _opaque(word: str) -> bool:
    """Structural object IDs, not every alphanumeric/underscore label."""
    if word.startswith('/') or _UUID_RE.fullmatch(word):
        return True
    base = word.split('/')[0]
    if len(base) >= 8 and re.fullmatch(r"[a-z]+\d+[a-z]+\d+[a-z0-9]*", base):
        return True  # multi-segment device/object code, e.g. SN66M051EU
    # Namespaced run IDs with an opaque suffix, e.g. export-run-AX29.
    suffix = base.rsplit('-', 1)[-1]
    return ('-' in base and len(suffix) >= 4
            and (suffix.isdigit() or (any(c.isalpha() for c in suffix)
                                     and sum(c.isdigit() for c in suffix) >= 2)))


def is_continuation_prompt(text: str | None) -> bool:
    """Recognize subject-free continuation/consent, never infer a prior task."""
    text = text or ''
    if not _CONTROL_RE.search(text):
        return False
    residue = _DEICTIC_RE.sub(' ', _CONTROL_RE.sub(' ', text))
    return set(_words(residue)) <= {'yes', 'okay', 'ok', 'please', 'да', 'хорошо', 'пожалуйста'}


def automatic_recall_terms(query: str, stopwords: AbstractSet[str]) -> list[str]:
    """Return exact object constraints, otherwise subject anchors before labels."""
    if is_continuation_prompt(query):
        return []
    subject = _DEICTIC_RE.sub(' ', _CONTROL_RE.sub(' ', query))
    words = _words(subject)
    identifiers = [word for word in words if _opaque(word)]
    if identifiers:
        return identifiers
    # Transfer endpoints can be short (PC -> TV). The connecting preposition
    # must never become corroboration simply because short endpoints are valid.
    endpoints = [word.casefold() for pair in _TRANSFER_RE.findall(subject) for word in pair]
    if endpoints and all(word not in stopwords and not word.isdigit() for word in endpoints):
        return list(dict.fromkeys(endpoints))
    clauses = re.split(r"[.!?;]\s+", subject, maxsplit=1)
    # A modifier in a single noun phrase ("telescope with coated optics")
    # must not displace the main subject. Focus only a multi-clause request.
    complements = _words(' '.join(_COMPLEMENT_RE.findall(clauses[0]))) if len(clauses) > 1 else []
    focus = [word for word in complements if len(word) >= 3 and word not in stopwords
             and not _QUALIFIER_RE.fullmatch(word) and '_' not in word
             and not any(c.isdigit() for c in word)]
    if focus:
        return focus
    # Request operators with a numeric rank (top-10/топ-10) are not IDs.
    terms = [word for word in words if len(word) >= 3 and word not in stopwords
             and not (re.fullmatch(r'.+-\d+', word) and word.rsplit('-', 1)[0] in stopwords)]
    anchors = [word for word in terms if not _QUALIFIER_RE.fullmatch(word)]
    # A metric/model label may be the only subject, but must not displace or
    # independently certify another subject such as certificate renewal.
    subjects = [word for word in anchors if '_' not in word
                and not (any(c.isalpha() for c in word) and any(c.isdigit() for c in word))]
    return subjects or anchors or terms


def recall_has_topic(text: str, terms: list[str]) -> bool:
    """Use the same atomic/path/device rules at candidate and body boundaries."""
    words = set(_words(text))

    def matches(term: str) -> bool:
        if term in words:
            return True
        if _opaque(term):
            # A base device code supports its revision, never another model.
            return (not term.startswith('/') and '/' not in term
                    and any(re.fullmatch(re.escape(term) + r'/\d+', word) for word in words))
        if len(term) >= 5 and re.fullmatch(r'[а-яё]+', term):
            return any(len(word) >= 5 and word[:5] == term[:5] for word in words)
        return False

    exact = [term for term in terms if _opaque(term)]
    return all(matches(term) for term in exact) if exact else any(matches(term) for term in terms)
