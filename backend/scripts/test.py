import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from audio_pipeline_v3 import _process
import numpy as np



def test_process():
    result = _process("scripts/律师声音片段.wav")
    print(result)

if __name__ == "__main__":
    test_process()
