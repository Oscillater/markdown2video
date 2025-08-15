from pathlib import Path
import re

# ========== 分句函数 ==========
def custom_sentence_split(text, max_len=12):
    sentence_enders = re.compile(r'(。|！|？|；|…{1,2})(?!(」|”))')
    parts = sentence_enders.split(text)

    grouped = []
    i = 0
    while i < len(parts):
        if parts[i] and re.fullmatch(r'[。！？，；…——]', parts[i].strip()):
            grouped.append(parts[i].strip())
            i += 1
            continue
        if i + 1 < len(parts):
            first = parts[i] or ""
            second = parts[i+1] or ""
            grouped.append(first.strip() + second.strip())
            i += 2
        else:
            if parts[i]:
                grouped.append(parts[i].strip())
            i += 1

    final_sentences = []
    for sent in grouped:
        buffer = ""
        soft_parts = re.split(r'(，|、|——)', sent)
        for part in soft_parts:
            buffer += part
            if len(buffer) >= max_len:
                if not re.fullmatch(r'[。！？，；…——]', buffer.strip()):
                    final_sentences.append(buffer.strip())
                buffer = ""
        if buffer:
            if not re.fullmatch(r'[。！？，；…——]', buffer.strip()):
                final_sentences.append(buffer.strip())
    cleaned_sentences = []
    for sentence in final_sentences:
        cleaned_sentence = re.sub(r'^[^\w“《「（]*|[^\w%”》」）]*$', '', sentence)
        cleaned_sentences.append(cleaned_sentence)

    return cleaned_sentences

# ========== Markdown解析函数 ==========
def parse_markdown_sections(text):
    lines = text.splitlines()
    sections = {
        "h1": None,
        "h2": None,
        "contents": [],
        "appendix": []
    }

    current_h3 = None
    current_text_block = []
    is_appendix = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            sections["h1"] = stripped[2:].strip()
        elif stripped.startswith("## "):
            sections["h2"] = stripped[3:].strip()
        elif stripped.startswith("### "):
            if current_h3:
                # 将当前 h3 和正文存储为字典，正文为分句后的嵌套列表
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(paragraph) for paragraph in current_text_block]
                })
            current_h3 = stripped[4:].strip()
            current_text_block = []
        elif stripped == "---":
            is_appendix = True
            if current_h3:
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(paragraph) for paragraph in current_text_block]
                })
                current_h3 = None
                current_text_block = []
        else:
            if is_appendix:
                if stripped:  # 忽略空行
                    sections["appendix"].append(stripped)
            else:
                if stripped:  # 忽略空行
                    current_text_block.append(stripped)

    if current_h3 and current_text_block:
        sections["contents"].append({
            "h3": current_h3,
            "text": [custom_sentence_split(paragraph) for paragraph in current_text_block]
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

parse_markdown_file("example.md")

