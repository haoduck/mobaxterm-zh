"""图形界面版的打包入口。

PyInstaller 执行此文件为顶层 __main__，此处没有父包，因此用绝对导入。
"""
from mobaxterm_zh.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
