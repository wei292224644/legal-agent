import { describe, it, expect } from 'vitest'
import { encodeWavChunk } from './wav'

describe('encodeWavChunk', () => {
  it('encodes Float32Array mono to WAV with correct header', () => {
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1])
    const chunk = encodeWavChunk(samples, { sampleRate: 16000, channels: 1 })

    expect(chunk).toBeInstanceOf(Uint8Array)
    expect(chunk.length).toBe(44 + 5 * 2) // header + 5 samples * 2 bytes

    // Check WAV header: "RIFF" at offset 0
    const riff = String.fromCharCode(...chunk.slice(0, 4))
    expect(riff).toBe('RIFF')

    // Check "WAVE" at offset 8
    const wave = String.fromCharCode(...chunk.slice(8, 12))
    expect(wave).toBe('WAVE')

    // Check sample rate at offset 24 (little-endian uint32)
    const view = new DataView(chunk.buffer)
    expect(view.getUint32(24, true)).toBe(16000)

    // Check channels at offset 22
    expect(view.getUint16(22, true)).toBe(1)

    // Check bits per sample at offset 34
    expect(view.getUint16(34, true)).toBe(16)

    // Check first sample value (0 -> 0, 0.5 -> 16384, -0.5 -> -16384)
    expect(view.getInt16(44, true)).toBe(0)
    expect(view.getInt16(46, true)).toBeCloseTo(16384, -1)
    expect(view.getInt16(48, true)).toBeCloseTo(-16384, -1)
  })

  it('handles empty samples', () => {
    const samples = new Float32Array(0)
    const chunk = encodeWavChunk(samples, { sampleRate: 16000, channels: 1 })
    expect(chunk.length).toBe(44) // just header
  })

  it('clamps values outside [-1, 1]', () => {
    const samples = new Float32Array([2, -2])
    const chunk = encodeWavChunk(samples, { sampleRate: 16000, channels: 1 })
    const view = new DataView(chunk.buffer)
    expect(view.getInt16(44, true)).toBe(32767)
    expect(view.getInt16(46, true)).toBe(-32767)
  })
})
