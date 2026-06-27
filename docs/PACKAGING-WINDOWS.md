# AI Travel Cut — Windows 便携版 / EXE 打包指南

> 目标：朋友**双击一个启动程序**，自动打开浏览器使用编辑器，无需自己装 Python / Node。

---

## 先说结论

| 方案 | 适合谁 | 体积 | 难度 |
|------|--------|------|------|
| **A. 便携文件夹 + 启动器 exe**（推荐） | 发给朋友本地用 | 约 **3～8 GB** | 中等 |
| **B. 安装包 Setup.exe**（Inno Setup） | 正式分发 | 同上 | 中等 |
| **C. 云服务器 + 网址** | 不想打包 | 服务器费用 | 最低 |
| **D. 单个 exe 全塞进一个文件** | ❌ 不推荐 | 超大且易失败 | 极高 |

本项目含 **PyTorch、Whisper、OCR、ffmpeg**，无法做成 50MB 的单文件 exe。  
实际做法是：**一个小启动器 exe + 一个文件夹**，朋友解压后双击 `AITravelCut.exe` 即可。

---

## 方案 A：一键打包（推荐）

### 1. 你的电脑需要

- Windows 10/11 64 位
- 已安装 Node 18+、Python 3.11、ffmpeg（打包机用）
- 项目已在本地能正常 `restart-all.ps1` 跑起来

### 2. 执行打包脚本

```powershell
cd E:\ai-travel-cutbackend
powershell -ExecutionPolicy Bypass -File .\scripts\build-portable.ps1
```

完成后得到：

```
dist\AITravelCut-Portable\
  AITravelCut.exe      ← 朋友双击这个
  app\
    backend\           ← 后端 + venv
    frontend\          ← Next standalone
    node\node.exe      ← 便携 Node（脚本尝试自动复制）
    ffmpeg\            ← 需手动放入 ffmpeg.exe（见下）
  data\                ← 首次运行生成，存项目/模板
```

### 3. 补充 ffmpeg（必做）

从 https://www.gyan.dev/ffmpeg/builds/ 下载 **ffmpeg-release-essentials.zip**  
解压后将 `bin\ffmpeg.exe` 和 `bin\ffprobe.exe` 复制到：

```
dist\AITravelCut-Portable\app\ffmpeg\
```

### 4. 发给朋友

1. 把整个 `AITravelCut-Portable` 文件夹打成 **zip**（约 3～8GB）
2. 朋友解压到任意路径（**路径不要有中文/空格**更稳）
3. 双击 `AITravelCut.exe`
4. 等待 10～30 秒，浏览器自动打开 http://127.0.0.1:3000/editor

### 5. 可选：DeepSeek API

若需要 AI 字幕/画面理解，在朋友电脑上编辑：

```
app\backend\.env
```

填入：

```
DEEPSEEK_API_KEY=sk-xxx
```

没有 Key 也能用基础功能（模板、时间轴、导出等会受限）。

---

## 方案 B：做成安装程序 Setup.exe

便携包打好后，用 [Inno Setup](https://jrsoftware.org/isinfo.php) 做安装向导：

1. 安装 Inno Setup
2. 新建脚本，把 `dist\AITravelCut-Portable` 整目录打进安装包
3. 创建桌面快捷方式指向 `AITravelCut.exe`
4. 编译得到 `AITravelCut-Setup.exe`

朋友体验：下载 Setup → 安装 → 桌面图标双击。

---

## 方案 C：不打包，直接给网址（最省事）

买一台云服务器（2核4G 起），部署 backend + frontend，朋友浏览器打开：

```
https://你的域名/editor
```

适合多人用、你不想到处发几个 G 的 zip。

---

## 常见问题

### Q: 双击 exe 闪退？

- 用 **cmd** 进入目录，运行 `AITravelCut.exe` 看报错
- 检查是否缺 `app\node\node.exe` 或 `app\backend\venv`
- 检查是否缺 ffmpeg

### Q: 杀毒软件报毒？

PyInstaller 打的 exe 常被误报。可：
- 添加信任
- 或不用 exe，直接双击同目录下的 `启动.bat`

### Q: 剪映导出能用吗？

需要朋友电脑额外安装 **剪映 PC 版**，并单独启动 CapCut Mate（`capcut-mate` 服务）。  
便携包**默认不包含** CapCut Mate；MP4 导出不依赖剪映。

### Q: 体积能缩小吗？

在 `app\backend\.env` 设置：

```
PROCESSING_PRESET=budget
```

打包前可删除 venv 里不必要的测试缓存；**不要删** torch / whisper / paddle 相关包（字幕功能需要）。

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `scripts/launcher.py` | 启动器源码 |
| `scripts/build-portable.ps1` | 打包脚本 |
| `scripts/AITravelCut.spec` | PyInstaller 配置（可选） |

---

## 开发机自测启动器（不打包）

```powershell
# 先构建 frontend standalone
cd frontend
npm run build

# 再运行启动器
cd ..
python scripts/launcher.py
```
