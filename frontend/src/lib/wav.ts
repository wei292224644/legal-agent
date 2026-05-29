export interface WavOptions {
  sampleRate: number
  channels: number
}

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i))
  }
}

function float32ToInt16Bytes(samples: Float32Array): Uint8Array {
  const buffer = new ArrayBuffer(samples.length * 2)
  const view = new DataView(buffer)
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    const int16 = Math.round(clamped * 32767)
    view.setInt16(i * 2, int16, true)
  }
  return new Uint8Array(buffer)
}

export function encodePcmChunk(samples: Float32Array): Uint8Array {
  return float32ToInt16Bytes(samples)
}

export function encodeWavChunk(
  samples: Float32Array,
  options: WavOptions,
): Uint8Array {
  const { sampleRate, channels } = options
  const bitsPerSample = 16
  const bytesPerSample = bitsPerSample / 8
  const byteRate = sampleRate * channels * bytesPerSample
  const blockAlign = channels * bytesPerSample
  const dataSize = samples.length * channels * bytesPerSample
  const headerSize = 44
  const buffer = new ArrayBuffer(headerSize + dataSize)
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)

  // RIFF header
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(view, 8, 'WAVE')

  // fmt sub-chunk
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)           // subchunk size
  view.setUint16(20, 1, true)           // audio format: PCM
  view.setUint16(22, channels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, bitsPerSample, true)

  // data sub-chunk
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  // PCM samples: Float32 [-1, 1] -> Int16
  const pcmBytes = float32ToInt16Bytes(samples)
  bytes.set(pcmBytes, headerSize)

  return bytes
}
