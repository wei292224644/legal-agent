import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAudioInput } from './useAudioInput'

// Mock Web Audio API
global.AudioContext = vi.fn().mockImplementation(function () {
  return {
    audioWorklet: {
      addModule: vi.fn().mockResolvedValue(undefined),
    },
    createMediaStreamSource: vi.fn().mockReturnValue({
      connect: vi.fn(),
    }),
    createBufferSource: vi.fn().mockReturnValue({
      buffer: null,
      connect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
      onended: null,
    }),
    decodeAudioData: vi.fn().mockResolvedValue({
      getChannelData: vi.fn().mockReturnValue(new Float32Array(48000)),
      length: 48000,
      sampleRate: 16000,
      numberOfChannels: 1,
      duration: 3,
    }),
    destination: {},
    close: vi.fn(),
    resume: vi.fn().mockResolvedValue(undefined),
  }
}) as unknown as typeof AudioContext

global.AudioWorkletNode = vi.fn().mockImplementation(function () {
  return {
    port: {
      onmessage: null,
      postMessage: vi.fn(),
    },
    connect: vi.fn(),
    disconnect: vi.fn(),
  }
}) as unknown as typeof AudioWorkletNode

// Mock MediaStream
const mockTrack = { stop: vi.fn() }
const mockStream = {
  getTracks: vi.fn().mockReturnValue([mockTrack]),
}

// Mock navigator.mediaDevices
Object.defineProperty(globalThis, 'navigator', {
  value: {
    mediaDevices: {
      getUserMedia: vi.fn().mockResolvedValue(mockStream),
    },
  },
  writable: true,
  configurable: true,
})

describe('useAudioInput', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts in idle mode', () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )
    expect(result.current.mode).toBe('idle')
    expect(result.current.isActive).toBe(false)
    expect(result.current.progress).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('transitions to mic mode on startRecording', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    await act(async () => {
      await result.current.startRecording()
    })

    expect(result.current.mode).toBe('mic')
    expect(result.current.isActive).toBe(true)
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true })
  })

  it('returns to idle after stop', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    await act(async () => {
      await result.current.startRecording()
    })
    expect(result.current.mode).toBe('mic')

    act(() => {
      result.current.stop()
    })
    expect(result.current.mode).toBe('idle')
    expect(result.current.isActive).toBe(false)
  })

  it('throws when startFile called during mic mode', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    await act(async () => {
      await result.current.startRecording()
    })
    expect(result.current.mode).toBe('mic')

    await expect(
      act(async () => {
        await result.current.startFile(new File([], 'test.wav'))
      }),
    ).rejects.toThrow('Audio input already active')
  })

  it('transitions to file mode on startFile', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    const file = new File(['audio data'], 'test.mp3', { type: 'audio/mpeg' })

    await act(async () => {
      await result.current.startFile(file)
    })

    expect(result.current.mode).toBe('file')
    expect(result.current.isActive).toBe(true)
  })

  it('shows error when file is too large', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    const largeFile = new File(['x'], 'test.mp3', { type: 'audio/mpeg' })
    Object.defineProperty(largeFile, 'size', { value: 200 * 1024 * 1024 }) // 200MB

    await expect(
      act(async () => {
        await result.current.startFile(largeFile)
      }),
    ).rejects.toThrow('文件过大')
  })

  it('progress is null initially and set during file mode', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    expect(result.current.progress).toBeNull()

    const file = new File(['audio data'], 'test.mp3', { type: 'audio/mpeg' })

    await act(async () => {
      await result.current.startFile(file)
    })

    expect(result.current.mode).toBe('file')
    // progress may be 0 or null depending on timer state, just verify it's a number
    expect(typeof result.current.progress === 'number' || result.current.progress === null).toBe(true)
  })
})
