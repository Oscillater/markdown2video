import edge_tts
import asyncio
import os

TEXT = "一个人的发展啊，既要考虑个人的奋斗，也要考虑时代的进程。"   # 你要测试的文本
OUTPUT_DIR = "voices_cn"       # 保存目录

async def main():
    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    voices = await edge_tts.list_voices()
    cn_voices = [v for v in voices if v["Locale"].startswith("zh-CN")]

    print(f"共找到 {len(cn_voices)} 个 zh-CN 语音，将生成测试文件到 {OUTPUT_DIR} 文件夹中...")

    for i, v in enumerate(cn_voices):
        short_name = v["ShortName"]
        filename = os.path.join(OUTPUT_DIR, f"{short_name}.mp3")

        communicate = edge_tts.Communicate(TEXT, short_name)
        await communicate.save(filename)

        print(f"[{i+1}/{len(cn_voices)}] 已生成: {filename}")

asyncio.run(main())
