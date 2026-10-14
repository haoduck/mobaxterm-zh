# mobaxterm-zh

把官方原版 MobaXterm（Windows）汉化成简体中文。

传入官方下载的 `MobaXterm_Personal_XX.X.exe`，输出一份界面为中文的可执行文件，
**文件大小与原版完全一致**。

```
mobaxterm-zh patch MobaXterm_Personal_26.5.exe
# -> MobaXterm_Personal_26.5_zh.exe
```

---

## 下载即用（无需安装 Python）

从 [Releases](https://github.com/haoduck/mobaxterm-zh/releases) 下载自带的二进制：

### 图形界面（推荐）

| 平台 | 文件 |
| --- | --- |
| Windows x64 | `mobaxterm-zh-gui-windows-x64.exe` |
| Linux x64 | `mobaxterm-zh-gui-linux-x64` |
| macOS arm64 | `mobaxterm-zh-gui-macos-arm64` |

打开窗口 → 「浏览…」选择（或直接把文件**拖进窗口**）→ 「开始汉化」。
界面会显示完整的中文日志与校验结果。也有「试运行」勾选框，只看不写。

### 命令行

| 平台 | 文件 |
| --- | --- |
| Windows x64 | `mobaxterm-zh-cli-windows-x64.exe` |
| Linux x64 | `mobaxterm-zh-cli-linux-x64` |
| macOS arm64 | `mobaxterm-zh-cli-macos-arm64` |

```bash
mobaxterm-zh-cli-windows-x64.exe patch MobaXterm_Personal_26.5.exe
```

这些是单文件程序，无需 Python、无需安装依赖。Windows 首次运行可能提示
「未知发布者」（未签名），选「更多信息 → 仍要运行」即可。

> **注意**：无论在哪个平台运行本工具，**输出永远是 Windows `.exe`** ——
> 它处理的是 PE 格式。Linux/macOS 版本用于在非 Windows 机器上汉化。

界面与命令行调用的是**同一段处理逻辑**（`mobaxterm_zh/pipeline.py`），
所以两者行为完全一致。

### 从源码安装

```bash
git clone git@github.com:haoduck/mobaxterm-zh.git
cd mobaxterm-zh
pip install -e .
mobaxterm-zh patch MobaXterm_Personal_26.5.exe
mobaxterm-zh gui            # 图形界面
```

需要 Python 3.9+，**零运行时依赖**（只用标准库，GUI 用的 tkinter 也自带）。

拖放功能需要可选依赖；不装也能用「浏览」按钮：

```bash
pip install -e ".[gui]"
```

---

## 汉化效果

以 MobaXterm 26.5 个人版为例：已汉化 **1,279** 条唯一文本、**2,000** 处界面实例。
菜单栏、会话编辑框、设置对话框、长帮助说明全部翻译；协议名与工具名
（SSH、VNC、RDP、MobaXterm…）按惯例保留英文。

---

## 它是怎么工作的

Delphi 程序的界面文字存在两个地方，这个工具两处都改：

**1. DFM 窗体资源**（`.rsrc` 段的 `RT_RCDATA`）。一个属性在流里的样子是

```
<名字长度><属性名><值类型><长度><文字>
```

例如 `Caption`（类型 6，1 字节长度）后面直接跟 `Sessions` 和长度 8。

**2. 运行期 AnsiString 常量**（代码段）。Delphi 这样排布它们：

```
ff ff ff ff  <长度:4 字节>  <文字>  00
```

工具栏标题（Session / Servers / Tools…）就属于这一类。

### 关键约束：长度必须逐字节一致

两种格式都把长度写进了数据流，所以**译文必须正好占和原文一样多的字节**。

- 中文比英文短时，用**空格补齐**（标签上的行尾空格不可见）
- 中文比英文长时，**拒绝写入并报告**，绝不截断 —— 截断的标签看起来就像 bug

这就是为什么 `OK`（2 字节）、`Red`（3 字节）这类极短标签会保持英文：
GBK 下每个汉字 2 字节，2 字节只放得下 1 个字，而单字按钮读起来很怪。

### 为什么用「模式扫描」而不是完整解析 DFM

完整的 DFM 解析需要认识每一种 `TValueType`，而这个版本把 **LZMA 压缩的皮肤资源**
塞在属性里，严格解析器会在那里卡住（开发过程中确实如此：64 个窗体只解析成功 49 个）。
但我们要找的字符串是**自我标识**的 —— 属性名加上长度前缀就是完整签名 ——
所以直接扫描反而更稳、更简单。扫描方式与解析器得到的字符串集合一致。

---

## 命令

```bash
# 查看可执行文件里有什么
mobaxterm-zh inspect MobaXterm.exe

# 导出全部可翻译字符串 + 给译者的工作清单
mobaxterm-zh extract MobaXterm.exe -o strings.json --worklist todo.md

# 审查某个词表在这个版本里的覆盖率
mobaxterm-zh glossary MobaXterm.exe -o 对照表.md

# 汉化（先 --dry-run 看看会改什么）
mobaxterm-zh patch MobaXterm.exe --dry-run
mobaxterm-zh patch MobaXterm.exe -o MobaXterm_zh.exe

# 独立复核：确认改动只落在字符串里
mobaxterm-zh verify original.exe MobaXterm_zh.exe

# 确认词表可用（打包后自检用）
mobaxterm-zh selfcheck
```

`patch` 每次都会自动跑一遍校验并打印结果：

```
总体结论        ：通过
文件大小未变    ：是
改动字节数      ：72113
  位于字符串内  ：72113
  位于字符串外  ：0
长度字段完好    ：2000 条正常 / 0 条损坏
PE 头未改动     ：是
资源目录未改动  ：是
签名块未改动    ：是
```

`位于字符串外` 必须是 0 —— 这意味着**一个字节都没动到程序逻辑**。

---

## 自己改译文

内置词表 `translations.zh-CN.json` 已经打包进程序，界面「自定义词表」留空即用它。

想调整或补充译文时，仓库里有两份副本：

| 文件 | 说明 |
| --- | --- |
| [`glossary/translations.zh-CN.json`](glossary/translations.zh-CN.json) | **供人阅读和编辑** |
| `src/mobaxterm_zh/data/translations.zh-CN.json` | 真正被打包的那份 |

改完记得同步，然后重新打包：

```bash
cp glossary/translations.zh-CN.json src/mobaxterm_zh/data/
pytest tests/test_glossary.py -v     # 校验格式与两份一致性
python -m PyInstaller --clean --noconfirm mobaxterm-zh.spec
```

详细的编写规则（**字节预算**是关键限制）、不宜翻译的内容、以及如何为新版本补充译文，都写在 [`glossary/README.md`](glossary/README.md)。

不想重新打包的话，也可以直接指定词表文件：

```bash
mobaxterm-zh patch MobaXterm.exe --table my_terms.json
```

想补翻新版本新增的界面：

```bash
mobaxterm-zh extract MobaXterm_27.0.exe --worklist todo.md
# todo.md 按「字节预算从小到大」列出所有还没译的条目
```

---

## 安全设计

| 保障 | 做法 |
| --- | --- |
| 不改文件大小 | 每处替换都补齐/拒绝到与原文等长 |
| 不动程序逻辑 | 写之前核对当前字节仍等于索引时的原文，不符就拒绝 |
| 不破坏长度字段 | 校验阶段逐条复核长度字段与终止符 |
| 不破坏 PE 结构 | PE 头、节表、资源目录、签名块全部逐字节比对 |
| UTF-8 字段 | `vaUTF8String` 里写 GBK 会变乱码，这类目标直接拒绝并报告 |
| 纯 ASCII 译文 | 比原文短的纯 ASCII 值视为「没翻」，丢弃 |

---

## 已知限制

- **只支持 GBK（简体中文）**。其他语种需要各自的词表；`--encoding` 可换编码，
  但非 CJK 语言的字长普遍超过原文，几乎都会被预算拒绝。
- **MobaXterm 升级后必须重新汉化**，官方更新会覆盖这个文件。
- 词表是针对 **26.5** 做的。新版本的界面文字有增删，词表能覆盖多少取决于重合度 ——
  `glossary` 命令可以量化这一点。
- 极短英文标签（`OK`、`Red`、`ms`）会保持英文，这是字节预算的硬限制。

---

## ⚠️ 关于签名与授权

**签名失效。** MobaXterm 官方发行版带 Mobatek 的 EV 代码签名。修改任意字节都会使
签名失效，Windows 首次运行会弹出「Windows 已保护你的电脑」提示，
点「更多信息 → 仍要运行」即可。这是二进制汉化的固有代价，不是缺陷。

**授权。** MobaXterm 是 MobaTech 的**商业闭源软件**，个人版免费但非开源。
本项目只修改界面文字字符串，不涉及反编译算法、不移除任何功能、不绕过授权校验。
请自行确认你的使用方式符合 Mobatek 的许可条款。

本项目按 MIT 许可发布。

---

## 开发

```bash
pip install -e ".[dev]"
pytest -q          # 34 个单元测试，用合成 PE 样本，不碰真实可执行文件
```

自行构建单文件二进制：

```bash
pip install pyinstaller
python -m PyInstaller --clean --noconfirm mobaxterm-zh.spec
dist/mobaxterm-zh selfcheck    # 确认打包后仍能读到词表
```

CI（`.github/workflows/build.yml`）在 push `v*` 标签时，
于 Windows / Linux / macOS 三个平台各构建一次（无法交叉编译），
先跑测试，再把二进制附到 GitHub Release。

代码结构：

| 模块 | 职责 |
| --- | --- |
| `pe.py` | 最小 PE 读取器：节表、资源目录、签名表 |
| `extract.py` | 定位所有可翻译字符串及其字节偏移 |
| `glossary.py` | 词表加载、预算审查、覆盖率统计 |
| `patch.py` | 逐字节等长替换，含全部拒绝规则 |
| `verify.py` | 独立复核改动是否只落在字符串内 |
| `pipeline.py` | **命令行与图形界面共用的处理流程** |
| `gui.py` | tkinter 图形界面 |
| `report.py` | 生成工作清单与中英对照表 |
| `cli.py` | 命令行入口 |
| `src/cli_entry.py` | CLI 版打包入口 |
| `src/gui_entry.py` | GUI 版打包入口 |

### 关于「多平台」

代码本身跨平台：39 KB 源码、只用标准库、**没有任何 Windows 专属模块**
（没有 `winreg`、没有 `ctypes.wintypes`）。它只做字节处理，所以可以在
Linux/macOS 上运行来处理 Windows 版 exe。

唯一与打包相关的适配在 `glossary.py::bundled_glossary_text()`：
PyInstaller 不会自动收集数据文件，冻结后的二进制需要显式去
`sys._MEIPASS` 找词表 —— `mobaxterm-zh.spec` 负责把它打进去，
这段代码负责找到它。`selfcheck` 命令就是为此存在的回归测试。

