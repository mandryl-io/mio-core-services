from __future__ import annotations

import re
from dataclasses import dataclass

_NAME = r"([A-Za-z][A-Za-z'-]{1,30}(?:\s+[A-Za-z][A-Za-z'-]{1,30})?)"
_DENY = frozenset(
    {
        "a",
        "afraid",
        "alone",
        "alright",
        "already",
        "always",
        "an",
        "angry",
        "asking",
        "at",
        "back",
        "bad",
        "being",
        "better",
        "calling",
        "cold",
        "coming",
        "confused",
        "doing",
        "done",
        "feeling",
        "fine",
        "getting",
        "giving",
        "glad",
        "going",
        "good",
        "grateful",
        "happy",
        "having",
        "here",
        "home",
        "hoping",
        "hot",
        "hungry",
        "in",
        "just",
        "leaving",
        "listening",
        "lonely",
        "looking",
        "lost",
        "making",
        "never",
        "next",
        "not",
        "ok",
        "okay",
        "old",
        "on",
        "ready",
        "really",
        "right",
        "sad",
        "scared",
        "sick",
        "sitting",
        "so",
        "sorry",
        "standing",
        "still",
        "sure",
        "taking",
        "talking",
        "telling",
        "the",
        "there",
        "thinking",
        "thirsty",
        "tired",
        "trying",
        "upset",
        "very",
        "waiting",
        "well",
        "worried",
        "worse",
        "wrong",
    }
)

_MY_NAME = re.compile(rf"(?i)(?:my name is|call me)\s+{_NAME}")
_CORRECTION = re.compile(
    rf"(?i)i(?:['’]m| am) not\s+{_NAME},?\s+i(?:['’]m| am)\s+{_NAME}"
)
_IM = re.compile(rf"(?i)^i(?:['’]m| am)\s+{_NAME}[.!?]?$")


@dataclass(frozen=True)
class SpokenName:
    name: str | None = None
    rejected: str | None = None


def _clean_name(raw: str) -> str | None:
    parts = raw.split()
    if any(part.lower() in _DENY for part in parts):
        return None
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def parse_spoken_name(text: str) -> SpokenName | None:
    utterance = " ".join((text or "").strip().split())
    if not utterance:
        return None

    match = _CORRECTION.search(utterance)
    if match:
        rejected = _clean_name(match.group(1))
        name = _clean_name(match.group(2))
        if rejected or name:
            return SpokenName(name=name, rejected=rejected)

    match = _MY_NAME.search(utterance)
    if match:
        name = _clean_name(match.group(1))
        if name:
            return SpokenName(name=name)

    match = _IM.fullmatch(utterance)
    if match:
        name = _clean_name(match.group(1))
        if name:
            return SpokenName(name=name)

    return None
