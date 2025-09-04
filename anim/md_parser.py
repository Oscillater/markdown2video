from pathlib import Path
import re

# ========== 辅助解析函数（音乐） ==========
def _parse_music_declaration(line):
    line = line.strip()
    m = re.match(r'^\[music:\s*(.+)\]\s*$', line, re.IGNORECASE)
    body = None
    if m:
        body = m.group(1)
    else:
        m2 = re.match(r'^(?:music|音乐)\s*[:：]\s*(.+)$', line, re.IGNORECASE)
        if m2:
            body = m2.group(1)
    if not body:
        return None
    name, src = None, None
    for part in re.split(r'\s*,\s*', body):
        kv = re.match(r'^\s*name\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))$', part, re.IGNORECASE)
        if kv:
            name = (kv.group(1) or kv.group(2) or kv.group(3)).strip()
            continue
        kv2 = re.match(r'^\s*src\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))$', part, re.IGNORECASE)
        if kv2:
            src = (kv2.group(1) or kv2.group(2) or kv2.group(3)).strip()
    if name and src:
        return name, src
    return None

def _parse_music_marker(line):
    s = line.strip()
    m = re.match(r'^[\[\<]\s*music_(start|end)\s+(?:"([^"]+)"|\'([^\']+)\'|([^\]\>]+))[\]\>]\s*$', s, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or m.group(3) or m.group(4)).strip()


# ========== 辅助解析函数（图片） ==========
def _parse_image_declaration(line):
    """
    支持格式：
      [image: name="logo", src="assets/logo.png"]
      image: name=logo, src=/path/to/logo.png
    返回 (name, src) 或 None
    """
    line = line.strip()
    m = re.match(r'^\[image:\s*(.+)\]\s*$', line, re.IGNORECASE)
    body = None
    if m:
        body = m.group(1)
    else:
        m2 = re.match(r'^(?:image|图片)\s*[:：]\s*(.+)$', line, re.IGNORECASE)
        if m2:
            body = m2.group(1)
    if not body:
        return None
    name, src = None, None
    for part in re.split(r'\s*,\s*', body):
        kv = re.match(r'^\s*name\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))$', part, re.IGNORECASE)
        if kv:
            name = (kv.group(1) or kv.group(2) or kv.group(3)).strip()
            continue
        kv2 = re.match(r'^\s*src\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))$', part, re.IGNORECASE)
        if kv2:
            src = (kv2.group(1) or kv2.group(2) or kv2.group(3)).strip()
    if name and src:
        return name, src
    return None

def _parse_image_marker(line):
    """
    支持格式：
      [image_start logo]
      [image_end "logo"]
    返回 (kind, name) 或 None
    """
    s = line.strip()
    m = re.match(r'^[\[\<]\s*image_(start|end)\s+(?:"([^"]+)"|\'([^\']+)\'|([^\]\>]+))[\]\>]\s*$', s, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or m.group(3) or m.group(4)).strip()


# ========== 分句函数 ==========
def custom_sentence_split(text, max_len=12):
    stripped = text.strip()
    if _parse_music_declaration(stripped) or _parse_music_marker(stripped):
        return [stripped]
    if _parse_image_declaration(stripped) or _parse_image_marker(stripped):
        return [stripped]

    sentence_enders = re.compile(r'(。|！|？|；|…{1,2})(?!(」|”))')
    parts = sentence_enders.split(text)

    grouped, i = [], 0
    while i < len(parts):
        if parts[i] and re.fullmatch(r'[。！？，；…——]', parts[i].strip()):
            grouped.append(parts[i].strip())
            i += 1
        elif i + 1 < len(parts):
            grouped.append((parts[i] or "").strip() + (parts[i+1] or "").strip())
            i += 2
        else:
            if parts[i]:
                grouped.append(parts[i].strip())
            i += 1

    final_sentences, buffer = [], ""
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

    return [re.sub(r'^[^\w“《「（]*|[^\w%”》」）]*$', '', s) for s in final_sentences]


# ========== Markdown解析函数 ==========
def parse_markdown_sections(text):
    lines = text.splitlines()
    sections = {
        "h1": None,
        "h2": None,
        "contents": [],
        "appendix": [],
        "music": {},   # name -> src
        "images": {}   # name -> src
    }

    # 顶部声明区（music / image）
    idx = 0
    while idx < len(lines):
        raw = lines[idx].strip()
        if not raw:
            idx += 1
            continue
        parsed_m = _parse_music_declaration(raw)
        parsed_i = _parse_image_declaration(raw)
        if parsed_m:
            name, src = parsed_m
            sections["music"][name] = src
            lines[idx] = ""
            idx += 1
            continue
        if parsed_i:
            name, src = parsed_i
            sections["images"][name] = src
            lines[idx] = ""
            idx += 1
            continue
        break

    current_h3, current_text_block, is_appendix = None, [], False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _parse_music_marker(stripped) or _parse_image_marker(stripped):
            (sections["appendix"] if is_appendix else current_text_block).append(stripped)
            continue

        if stripped.startswith("# "):
            sections["h1"] = stripped[2:].strip()
        elif stripped.startswith("## "):
            sections["h2"] = stripped[3:].strip()
        elif stripped.startswith("### "):
            if current_h3:
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(p) for p in current_text_block]
                })
            current_h3, current_text_block = stripped[4:].strip(), []
        elif stripped == "---":
            is_appendix = True
            if current_h3:
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(p) for p in current_text_block]
                })
                current_h3, current_text_block = None, []
        else:
            (sections["appendix"] if is_appendix else current_text_block).append(stripped)

    if current_h3 and current_text_block:
        sections["contents"].append({
            "h3": current_h3,
            "text": [custom_sentence_split(p) for p in current_text_block]
        })

    return sections


# ========== 读取文件并解析 ==========
def parse_markdown_file(md_path):
    path = Path(md_path)
    if not path.exists():
        print(f"❌ 找不到文件: {md_path}")
        return None
    text = path.read_text(encoding="utf-8")
    sections = parse_markdown_sections(text)
    print(sections)
    return sections


if __name__ == "__main__":
    print(parse_markdown_file("example.md"))
