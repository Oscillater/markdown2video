import re
from pathlib import Path
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


# ========== 主入口 ==========
def main(input_path="word.md"):
    path = Path(input_path)
    if not path.exists():
        print(f"❌ 找不到文件: {input_path}")
        return

    text = path.read_text(encoding="utf-8")
    sentences = custom_sentence_split(text)

    print("📘 分句结果如下：")
    for i, s in enumerate(sentences, 1):
        print(f"{i:02d}. {s}")

# ========== CLI ==========
if __name__ == "__main__":
   
    input_file = "word.md"
    main(input_file)
