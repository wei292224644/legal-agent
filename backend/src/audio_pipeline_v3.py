from dataclasses import dataclass

import numpy as np

_model = None


def _ensure_model():
    global _model
    if _model is not None:
        return
    from funasr import AutoModel

    _model = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        spk_model="cam++",
        disable_update=True,
    )
    _model.vad_model.vad_opts.max_single_segment_time = 10000


def _process(audio):
    """audio: file path (str) or numpy array (16kHz float32 mono)."""
    _ensure_model()

    if isinstance(audio, str):
        from scipy.io import wavfile
        import soxr

        sr, data = wavfile.read(audio)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            data = soxr.resample(data.astype(np.float32), sr, 16000)
            sr = 16000
        audio = data.astype(np.float32) / 32768.0

    return _model.generate(input=audio)
