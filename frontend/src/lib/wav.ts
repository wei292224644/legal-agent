export interface WavOptions {
  sampleRate: number
  channels: number
}

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i))
  }
}

export function encodePcmChunk(samples: Float32Array): Uint8Array {
  const buffer = new ArrayBuffer(samples.length * 2)
  const view = new DataView(buffer)
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(i * 2, Math.round(clamped * 32767), true)
  }
  return new Uint8Array(buffer)
}

export function encodeWavChunk(
  samples: Float32Array,
  options: WavOptions,
): Uint8Array {
  const { sampleRate, channels } = options
  const bytesPerSample = 2
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
  view.setUint16(34, 16, true)          // bits per sample

  // data sub-chunk
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  // PCM samples
  bytes.set(encodePcmChunk(samples), headerSize)

  return bytes
}
