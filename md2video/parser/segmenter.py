from __future__ import annotations

import re


def custom_sentence_split(text: str, max_len: int = 12) -> list[str]:
    stripped = text.strip()
    # 声明和标记直接透传
    if _is_declaration_or_marker(stripped):
        return [stripped]

    sentence_enders = re.compile(r'(。|！|？|；|…{1,2})(?!(」|"))')
    parts = sentence_enders.split(text)

    grouped: list[str] = []
    i = 0
    while i < len(parts):
        if parts[i] and re.fullmatch(r'[。！？，；…——]', parts[i].strip()):
            grouped.append(parts[i].strip())
            i += 1
        elif i + 1 < len(parts):
            grouped.append((parts[i] or "").strip() + (parts[i + 1] or "").strip())
            i += 2
        else:
            if parts[i]:
                grouped.append(parts[i].strip())
            i += 1

    final_sentences: list[str] = []
    buffer = ""
    for sent in grouped:
        for part in re.split(r'(，|、|——)', sent):
            buffer += part
            if len(buffer) >= max_len:
                if not re.fullmatch(r'[。！？，；…——]', buffer.strip()):
                    final_sentences.append(buffer.strip())
                buffer = ""
        if buffer:
            if not re.fullmatch(r'[。！？，；…——]', buffer.strip()):
                final_sentences.append(buffer.strip())
            buffer = ""

    return [re.sub(r'^[^\w\u300c\u300a\u300e\uff08]*|[^\w%\u300d\u300b\u300f\uff09]*$', '', s) for s in final_sentences]


def _is_declaration_or_marker(text: str) -> bool:
    s = text.strip()
    if re.match(r'^\[music:\s*.+\]$', s, re.IGNORECASE):
        return True
    if re.match(r'^[\[\<]\s*music_(start|end)\s+.+[\]\>]$', s, re.IGNORECASE):
        return True
    if re.match(r'^\[image:\s*.+\]$', s, re.IGNORECASE):
        return True
    if re.match(r'^[\[\<]\s*image_(start|end)\s+.+[\]\>]$', s, re.IGNORECASE):
        return True
    return False
