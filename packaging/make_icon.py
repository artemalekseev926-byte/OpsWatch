import sys
from pathlib import Path

from opswatch.desktop.icon import save_ico, save_png

if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    save_ico(root / "opswatch.ico")
    save_png(root / "opswatch.png")
    print("icons written to", root)
