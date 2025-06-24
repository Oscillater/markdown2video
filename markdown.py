from pathlib import Path

def parse_markdown_by_order(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for idx, line in enumerate(lines):
        lineno = idx + 1
        stripped = line.strip()

        if stripped.startswith("# "):
            print(f"行 {lineno} [H1] {stripped[2:].strip()}")
        elif stripped.startswith("## "):
            print(f"行 {lineno} [H2] {stripped[3:].strip()}")
        elif stripped.startswith("### "):
            print(f"行 {lineno} [H3] {stripped[4:].strip()}")
        elif stripped == "---":
            print(f"行 {lineno} [HR]")
        elif stripped == "":
            print(f"行 {lineno} [EMPTY]")
        else:
            print(f"行 {lineno} [TEXT] {stripped}")

# 示例用法
if __name__ == "__main__":
    parse_markdown_by_order("example.md")  # 修改为你的文件路径
