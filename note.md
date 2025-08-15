目标：制作一个可以解析markdown（or其他的语言）并生成符合我个人美学的视频的程序
分为三个部分
- 解析，获得语句段
- 根据语句段的不同生成动画与语音
- 插入音乐（与字幕）

---
首先需要决定，有哪些动画
- 开头动画
- 小标题
- 图片
- 正常的文字
- 一个不断变动但是又不失规律的动画

首先要做出这些demo
目前：这部分demo做差不多了
指令 manim -pql/h main.py Demo
下面需要调研的是manim voice的一个库
https://voiceover.manim.community/en/stable/services.html