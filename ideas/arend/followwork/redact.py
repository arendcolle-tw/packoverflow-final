"""Redact personal and secret data from OCR text before it is stored.

Runs on every frame before anything touches disk. Order matters: the most
specific patterns go first so a token is not half-eaten by the card rule.
"""
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Known token shapes, then a generic long mixed string.
TOKENS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\b(?:bearer|token|api[_-]?key|secret|password)\s*[:=]\s*\S{6,}"),
]
GENERIC_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{28,}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
# Belgian rijksregisternummer: YY.MM.DD-XXX.CC, separators optional.
NATIONAL = re.compile(r"\b\d{2}\.?\d{2}\.?\d{2}[- ]?\d{3}\.?\d{2}\b")
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn(digits):
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _generic_token(m):
    s = m.group(0)
    has_digit = any(c.isdigit() for c in s)
    has_alpha = any(c.isalpha() for c in s)
    return "[TOKEN]" if has_digit and has_alpha else s


def _card(m):
    digits = re.sub(r"\D", "", m.group(0))
    return "[CARD]" if 13 <= len(digits) <= 19 and _luhn(digits) else m.group(0)


def _national(m):
    digits = re.sub(r"\D", "", m.group(0))
    if len(digits) != 11:
        return m.group(0)
    s = m.group(0)
    formatted = any(c in s for c in ".- ")
    body, check = int(digits[:9]), int(digits[9:])
    valid = check in (97 - body % 97, 97 - int("2" + digits[:9]) % 97)
    return "[NATIONAL_NUMBER]" if formatted or valid else s


def redact(text):
    if not text:
        return text
    text = EMAIL.sub("[EMAIL]", text)
    for pat in TOKENS:
        text = pat.sub("[TOKEN]", text)
    text = GENERIC_TOKEN.sub(_generic_token, text)
    text = IBAN.sub("[IBAN]", text)
    text = NATIONAL.sub(_national, text)
    text = CARD.sub(_card, text)
    return text


def count_redactions(text):
    return len(re.findall(r"\[(?:EMAIL|TOKEN|IBAN|NATIONAL_NUMBER|CARD)\]", text or ""))
