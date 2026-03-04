# markdown2video

A simple text-based video maker that converts Markdown styled text into a basic video. It supports inserting images and music, and can read the text you write.

**Note:** This project is still in its early stages and hasn't been fully tested. There may be bugs. It will be polished at some point in the future.

## Environment Setup

To run this project, you need to set up the following environment variables:

```powershell
$env:PATH += ";D:\ffmpeg\bin"
$env:PATH += ";D:\sox\sox-14-4-2"
```

## How to Run

To generate a video, run the following command:

```bash
manim -pql main.py Demo
```

## Markdown Features

### Title and Subtitle

```markdown
# Title
## Subtitle
```

- These can only be used once per file.
- They will appear at the beginning of the video as the title and subtitle.

### Section Titles

```markdown
### H3 Title
```

- Use this to divide your content into sections.

### Content and Appendix

```markdown
---
```

- This line separates the main content from the appendix.
- Only the main content will be read aloud.

### Music and Images

```markdown
[music:name="222",src="./music.mp3"]
[music_start 222]
你问我要去向何方
我指着大海的方向
[music_end 222]
```

- Use this format to insert and control music playback.

## Contributing

Feel free to contribute by reporting issues or submitting pull requests. Any help is appreciated!