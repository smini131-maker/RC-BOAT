"""Run pinned YOLOv5 without modifying vendor source; bridge Pillow 10's font API."""
from pathlib import Path
import runpy
import sys
import warnings
from PIL import ImageFont

if not hasattr(ImageFont.FreeTypeFont, "getsize"):
    def getsize(self, text, *args, **kwargs):
        box = self.getbbox(text, *args, **kwargs)
        return box[2]-box[0], box[3]-box[1]
    ImageFont.FreeTypeFont.getsize = getsize

if __name__ == "__main__":
    script = Path(sys.argv[1]).resolve()
    sys.argv = [str(script)]+sys.argv[2:]
    sys.path.insert(0, str(script.parent))
    warnings.filterwarnings("ignore", category=FutureWarning)
    runpy.run_path(str(script), run_name="__main__")
