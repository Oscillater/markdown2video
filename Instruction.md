# 工程实践手册：Markdown 驱动视频生成 Agent

## 1. 架构设计：混合开发模式

为了兼顾开发体验（Windows 图形界面）和运行稳定性（Linux 环境），我们采用如下架构：

*   **编辑侧 (Windows)**：负责代码编写、Git 管理、文件查看。代码存储在非系统盘（如 D 盘）。
*   **运行侧 (Docker 容器)**：负责执行代码、渲染视频。容器内部是纯 Linux 环境，预装了 Manim 和所有系统依赖。
*   **连接桥梁**：通过 Docker 的 Volume（挂载卷）技术，将 Windows 的代码目录实时映射到容器内部。

---

## 2. 核心技术栈

| 模块         | 工具               | 作用与说明                                                   |
| :----------- | :----------------- | :----------------------------------------------------------- |
| **容器化**   | **Docker Desktop** | 提供隔离的 Linux 运行环境。**镜像存储需配置到 D/E 盘**。     |
| **依赖管理** | **uv**             | 替代 pip。速度极快，生成 `uv.lock` 锁定版本，保证环境一致性。 |
| **语言**     | **Python 3.10+**   | 项目核心语言。                                               |
| **数据校验** | **Pydantic**       | 定义 Manifest 数据结构，强制校验 LLM 输出的 JSON 格式。      |
| **测试框架** | **Pytest**         | 用于测试解析器（Parser）和 Agent 逻辑，**不**用于测试视频渲染。 |
| **AI 辅助**  | **Claude Code**    | 运行在 Windows PowerShell 中，辅助架构设计与重构。           |

---

## 3. 项目目录结构

建议在 D 盘或 E 盘建立如下结构，严禁放在 C 盘桌面。

```text
D:\Code\auto-director\
├── .git/                  # Git 版本控制目录
├── .gitignore             # 忽略文件配置 (.venv, *.mp4, __pycache__)
├── .env                   # 环境变量 (存放 OPENAI_API_KEY，严禁提交)
├── pyproject.toml         # 依赖声明文件 (人类可读)
├── uv.lock                # 依赖锁定文件 (机器可读，需提交)
├── Dockerfile             # 镜像构建脚本
├── run.ps1                # Windows 启动容器的快捷脚本
├── src/                   # 源代码目录
│   ├── main.py            # 程序入口
│   ├── core/              # 核心逻辑 (Parser, Agent)
│   ├── models/            # Pydantic 数据模型
│   └── renderers/         # 渲染实现 (Manim, Stock)
└── tests/                 # 测试代码
```

---

## 4. 关键配置文件

### 4.1 Dockerfile
位于项目根目录，定义运行环境。
```dockerfile
FROM manimcommunity/manim:stable
USER root
# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
# 优先安装依赖（利用缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --system
# 复制源码
COPY src/ src/
CMD ["/bin/bash"]
```

### 4.2 启动脚本 (run.ps1)
位于项目根目录，用于一键进入 Linux 环境。
```powershell
# 将当前 Windows 目录挂载到容器内的 /app
docker run --rm -it -v "${PWD}:/app" auto-director
```

---

## 5. 标准工作流 (Workflow)

### 阶段一：环境初始化 (仅一次)
1.  **Docker 设置**：将 Docker Desktop 的 "Disk image location" 修改为 D 盘路径。
2.  **Git 初始化**：`git init`，创建 `.gitignore`。
3.  **uv 初始化**：`uv init`，然后用 `uv add manim openai ...` 添加依赖。
4.  **构建镜像**：`docker build -t auto-director .`

### 阶段二：日常开发 (循环)
1.  **写代码**：在 Windows 下用 VS Code 编辑代码。
2.  **启动容器**：在 VS Code 终端运行 `./run.ps1`，进入 `root@...:/app#` 终端。
3.  **运行/测试**：
    *   渲染视频：`python src/main.py`
    *   运行单元测试：`pytest`
4.  **查看结果**：视频生成后，直接在 Windows 文件夹中打开观看。

### 阶段三：添加新依赖
1.  **Windows 侧**：`uv add some-package` (更新 `pyproject.toml` 和 `uv.lock`)。
2.  **容器侧**：
    *   如果只是临时用：在容器内运行 `uv sync --system`。
    *   如果为了稳固：在 Windows 侧重新运行 `docker build -t auto-director .`。

---

## 6. 避坑指南 (Best Practices)

1.  **依赖管理**：
    *   ❌ **禁止** 使用 `pip freeze > requirements.txt`。
    *   ✅ **必须** 提交 `pyproject.toml` 和 `uv.lock` 到 Git。
    *   ✅ Windows 本地只需安装 `uv`，无需安装复杂的 Manim 环境（VS Code 飘红没关系，容器里能跑就行）。

2.  **Git 规范**：
    *   ❌ **禁止** 直接在 `main` 分支开发。
    *   ✅ **必须** 建立新分支（如 `feat/parser-logic`），开发完成后合并。
    *   ✅ 确保 `.env` 文件在 `.gitignore` 中，防止 API Key 泄露。

3.  **数据安全与校验**：
    *   ❌ **禁止** 信任 LLM 返回的字符串。
    *   ✅ **必须** 使用 Pydantic 解析 JSON，确保数据类型（如 `duration` 必须是 float）正确。

4.  **Docker 使用**：
    *   Docker 容器是“用完即焚”的 (`--rm`)。不要在容器里保存重要文件，除非文件保存在 `/app` 目录下（因为 `/app` 挂载到了 Windows 硬盘）。

遵循这套规范，你的项目将具备良好的可维护性和扩展性，从一个简单的 Demo 蜕变为一个标准的软件工程项目。