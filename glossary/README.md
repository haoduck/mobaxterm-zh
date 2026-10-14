# 内置词表

`translations.zh-CN.json` 就是打包进程序里的那份简体中文词表，
**1,279 条**中英对照。

用户不需要这个文件——它已经编进可执行文件里，界面上「自定义词表」留空即用它。
放在这里是方便查阅、修改和补充译文。

## 两份副本，改哪一份

| 文件 | 作用 |
| --- | --- |
| `glossary/translations.zh-CN.json` | **本目录这份**，供人阅读和编辑 |
| `src/mobaxterm_zh/data/translations.zh-CN.json` | 真正被打包的，PyInstaller 从这里取 |

两份内容必须保持一致。改完之后同步：

```bash
cp glossary/translations.zh-CN.json src/mobaxterm_zh/data/
python -m pytest tests -q          # 确认没破坏格式
python -m PyInstaller --clean --noconfirm mobaxterm-zh.spec
```

`tests/test_glossary.py` 里有一项会检查两份是否同步，改漏了会直接报错。

## 格式

```json
{
  "Cancel": "取消",
  "Sessions": "会话"
}
```

左边是 MobaXterm 界面里的英文原文，右边是译文。**必须有且只有一个词条对应
一个位置**——同一个英文串在界面上出现多次时，它们共用同一条译文。

文件是 UTF-8、保留换行和标记的 JSON。**不要用记事本以外的工具随意重排**：
有 81 条译文含 `\r\n` 换行、67 条含引号、还有 `<b>` `<br>` `<u>` 这类
HTML 标记，重排容易把它们弄坏。

## 关键限制：字节预算

这是加新译文时最容易踩的坑。

每条界面文字在二进制里占固定字节数，**译文必须不超过它**：

- GBK 编码下，一个汉字 2 字节
- 原文 `Settings` 占 8 字节 → 最多放 4 个汉字
- 原文 `OK` 占 2 字节 → 放不下「确定」，所以保持英文

超出预算的译文会被**拒绝**（保持英文），**不会被截断**——截断的界面看起来
就像 bug。想确认某条能放得下，跑：

```bash
mobaxterm-zh patch MobaXterm_Personal_26.5.exe --dry-run --verbose
```

`--verbose` 会列出每一条被拒绝的译文和原因。

若确实需要更长的译文，只能改那个界面元素本身的英文原文（比如把 `Settings`
改成 `Preferences Settings` 来腾出空间），代价是界面上会出现这个更长的英文。

## 不要翻译的东西

| 类型 | 例子 | 原因 |
| --- | --- | --- |
| 协议与技术名 | SSH, VNC, RDP, X11, MobaXterm | 用户习惯看到英文 |
| 工具/组件名 | MobaSFTP, MobaDiff, CygUtils | 同上 |
| 极短标签 | `OK`(2B), `Red`(3B) | 预算放不下汉字 |
| Delphi 组件名 | `BtnOk1`, `CmbCyg` | 界面根本不显示 |
| 文件格式、网址 | `*.mxtpro`, 插件下载链接 | 改了会失效 |

## 想补充新版本的界面文字

MobaXterm 升级后界面会变化。先导出待译清单：

```bash
mobaxterm-zh extract MobaXterm_Personal_27.0.exe \
    -o strings.json --worklist todo.md
```

`todo.md` 会按「字节预算从小到大」列出所有还没译的条目，直接照着往
`translations.zh-CN.json` 里加即可。

## 校验

```bash
# 格式正确 + 两份副本一致
pytest tests/test_glossary.py -v

# 看某个版本下的覆盖率
mobaxterm-zh glossary MobaXterm_Personal_26.5.exe
```
