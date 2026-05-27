"""
Integration smoke-test: downloads funASR models on first run, then processes
a synthetic 2-speaker audio to print the actual sentence_info structure.

Run: uv run python scripts/verify_funasr_pipeline.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def make_test_wav(path: Path, duration_s: float = 4.0, sr: int = 16000) -> None:
    """Write a simple sine-wave WAV (no real speech, just checks pipeline init)."""
    t = np.linspace(0, duration_s, int(sr * duration_s))
    # Two alternating tones to simulate speaker change
    audio = np.where(t < duration_s / 2, np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 880 * t))
    sf.write(path, audio.astype(np.float32), sr)


def main():
    from funasr import AutoModel

    print("Loading models (will download on first run)...")
    model = AutoModel(
        model="iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
        spk_model="iic/speech_campplus_sv_zh-cn_16k-common",
    )
    print("Models loaded.")

    wav_path = Path("/tmp/test_two_speaker.wav")
    make_test_wav(wav_path)
    print(f"Test audio written to {wav_path}")

    res = model.generate(
        input=str(wav_path),
        batch_size_s=300,
        preset_spk_num=2,
    )

    print("\n=== Raw output ===")
    print(json.dumps(res, default=str, indent=2))

    print("\n=== sentence_info fields ===")
    for item in res:
        for sent in item.get("sentence_info", []):
            print(f"  keys: {list(sent.keys())}")
            print(f"  spk type: {type(sent.get('spk')).__name__}, value: {sent.get('spk')}")
            if "spk_embedding" in sent:
                print(f"  spk_embedding shape: {np.array(sent['spk_embedding']).shape}")
            break  # print only first sentence to check structure


if __name__ == "__main__":
    main()
