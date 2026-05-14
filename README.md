# 图片识别自动点击器

基于 OpenCV 模板匹配和 Win32 API 的桌面自动化工具，通过图像识别自动定位目标并执行点击操作。

## 功能特性

- **图像识别**：基于 OpenCV 模板匹配，支持多目标检测
- **自动点击**：Win32 API 模拟鼠标点击，精准高效
- **多步骤脚本**：支持配置多个识别+点击步骤，按顺序执行
- **动作组循环**：支持循环执行、轮次间隔、失败重试等策略
- **完成度检查**：主循环结束后自动检测遗漏目标并补漏
- **脚本管理**：保存/加载/删除脚本配置，一键复用
- **实时预览**：选择目标窗口后可预览识别匹配结果
- **快捷键**：F6 开始 / F7 暂停恢复 / F8 停止
- **打包分发**：支持 PyInstaller 打包为 exe，无需 Python 环境

## 项目结构

```
PictureRecognition/
├── main.py                 # 程序入口
├── build.bat               # 打包脚本
├── requirements.txt        # 依赖清单
├── ui/
│   └── main_window.py      # PyQt5 主界面
├── core/
│   ├── window_manager.py   # 窗口枚举与管理
│   ├── image_matcher.py    # OpenCV 模板匹配引擎
│   ├── auto_clicker.py     # Win32 自动点击
│   ├── execution_engine.py # 脚本执行引擎
│   └── script_manager.py   # 脚本序列化与管理
├── templates/              # 模板图片目录
├── scripts/                # 保存的脚本配置
├── resources/              # 资源文件
├── logs/                   # 运行日志
└── debug_screenshots/      # 调试截图
```

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+
- 依赖：PyQt5, OpenCV, NumPy, pywin32, Pillow

### 安装

```bash
git clone https://github.com/your-username/PictureRecognition.git
cd PictureRecognition
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

### 使用步骤

1. **选择目标窗口**：从右侧「目标窗口」下拉列表中选择要操作的窗口
2. **添加步骤**：点击「添加图片」，选择模板截图（要识别的目标图案）
3. **配置步骤参数**：点击次数、匹配阈值、点击间隔等
4. **配置动作组**：循环次数、失败策略、完成度检查等
5. **识别预览**：点击「识别预览」按钮验证匹配效果
6. **开始执行**：点击「▶ 开始执行」或按 F6

### 打包为 exe

双击 `build.bat` 或手动执行：

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --name PictureRecognition --windowed --add-data "templates;templates" --add-data "scripts;scripts" --add-data "resources;resources" main.py
```

输出在 `dist/PictureRecognition/` 目录，将整个文件夹分发即可，无需安装 Python。

## 配置说明

### 步骤参数

| 参数 | 说明 |
|------|------|
| 点击次数 | 每个匹配点的点击次数 |
| 点击间隔 | 多匹配点之间的点击间隔（秒） |
| 匹配阈值 | OpenCV 模板匹配阈值（0.1~1.0），越高越严格 |
| 多匹配 | 「逐个点击」匹配所有目标 / 「仅点击第一个」只点第一个 |
| 执行后等待 | 步骤执行完成后等待时间（秒） |

### 动作组参数

| 参数 | 说明 |
|------|------|
| 循环次数 | 整组步骤的循环执行次数 |
| 轮次间隔 | 每轮循环之间的间隔（秒） |
| 失败策略 | 跳过继续 / 重试3次 / 终止执行 |
| 完成度检查 | 主循环结束后检测步骤1是否有遗漏目标并补上 |

## 依赖

```
PyQt5>=5.15
opencv-python>=4.10
numpy>=2.1
pywin32>=306
Pillow>=10.0
```

## License

MIT
