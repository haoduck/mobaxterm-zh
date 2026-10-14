"""Localize a stock MobaXterm Windows build into Simplified Chinese.

The approach is in-place rewriting of two string storage formats, always
byte-exact:

  * Delphi DFM form resources in the .rsrc section, and
  * runtime ``AnsiString`` constants in the code image.

Neither the file size nor any offset in the stream changes, so the executable
stays structurally valid.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
