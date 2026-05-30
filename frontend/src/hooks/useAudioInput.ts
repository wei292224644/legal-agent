import { useState, useCallback, useRef, useEffect } from 'react'
import { encodePcmChunk } from '@/lib/wav'

export type AudioMode = 'idle' | 'mic' | 'file'

export interface UseAudioInputOptions {
  onChunk: (chunk: Uint8Array) => void
  onAudioEnd?: () => void
  chunkIntervalMs?: number
}

export interface UseAudioInputReturn {
  mode: AudioMode
  isActive: boolean
  progress: number | null
  error: string | null
  clearError: () => void
  startRecording: () => Promise<void>
  startFile: (file: File) => Promise<void>
  stop: () => void
}

const DEFAULT_CHUNK_MS = 300
const MAX_FILE_SIZE = 100 * 1024 * 1024 // 100MB
const SAMPLE_RATE = 16000

export function useAudioInput(
  options: UseAudioInputOptions,
): UseAudioInputReturn {
  const { onChunk, chunkIntervalMs = DEFAULT_CHUNK_MS } = options
  const [mode, setMode] = useState<AudioMode>('idle')
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const modeRef = useRef(mode)
  const chunkTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const sourceNodeRef = useRef<AudioBufferSourceNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const samplesRef = useRef<Float32Array[]>([])
  const readIdxRef = useRef(0)
  const totalSamplesRef = useRef(0)
  const onChunkRef = useRef(onChunk)
  const onAudioEndRef = useRef(options.onAudioEnd)

  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  useEffect(() => {
    onChunkRef.current = onChunk
  }, [onChunk])

  useEffect(() => {
    onAudioEndRef.current = options.onAudioEnd
  }, [options.onAudioEnd])

  const reset = useCallback(() => {
    if (chunkTimerRef.current) clearInterval(chunkTimerRef.current)
    chunkTimerRef.current = null

    if (sourceNodeRef.current) {
      try { sourceNodeRef.current.stop() } catch { /* noop */ }
      sourceNodeRef.current = null
    }
    if (workletNodeRef.current) {
      try { workletNodeRef.current.disconnect() } catch { /* noop */ }
      workletNodeRef.current = null
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close() } catch { /* noop */ }
      audioContextRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    samplesRef.current.length = 0
    readIdxRef.current = 0
    totalSamplesRef.current = 0
    setProgress(null)
    setError(null)
  }, [])

  const stop = useCallback(() => {
    onAudioEndRef.current?.()
    reset()
    setMode('idle')
  }, [reset])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      reset()
    }
  }, [reset])

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  const setErrorAndAutoClear = useCallback((message: string | null) => {
    setError(message)
  }, [])

  const emitWavChunk = useCallback(
    (samples: Float32Array) => {
      const pcm = encodePcmChunk(samples)
      onChunkRef.current(pcm)
    },
    [],
  )

  const startRecording = useCallback(async () => {
    if (modeRef.current !== 'idle') throw new Error('Audio input already active')
    setErrorAndAutoClear(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE })
      audioContextRef.current = audioContext

      // Inject AudioWorklet processor as inline blob
      const workletCode = `
        class PCMProcessor extends AudioWorkletProcessor {
          process(inputs) {
            const input = inputs[0]
            if (input && input[0]) {
              this.port.postMessage(input[0])
            }
            return true
          }
        }
        registerProcessor('pcm-processor', PCMProcessor)
      `
      const blob = new Blob([workletCode], { type: 'application/javascript' })
      const url = URL.createObjectURL(blob)
      await audioContext.audioWorklet.addModule(url)
      URL.revokeObjectURL(url)

      const source = audioContext.createMediaStreamSource(stream)
      const workletNode = new AudioWorkletNode(audioContext, 'pcm-processor')
      workletNodeRef.current = workletNode

      workletNode.port.onmessage = (e) => {
        samplesRef.current.push(e.data)
      }

      source.connect(workletNode)

      // Emit chunks on interval
      const chunkSamples = Math.floor((SAMPLE_RATE * chunkIntervalMs) / 1000)
      chunkTimerRef.current = setInterval(() => {
        const allSamples = samplesRef.current
        const startIdx = readIdxRef.current
        if (allSamples.length === 0 || startIdx >= allSamples.length) return

        // Flatten accumulated samples
        let totalLen = 0
        for (let i = startIdx; i < allSamples.length; i++) totalLen += allSamples[i].length
        if (totalLen < chunkSamples) return

        const flat = new Float32Array(chunkSamples)
        let written = 0
        let readIdx = startIdx
        while (written < chunkSamples && readIdx < allSamples.length) {
          const s = allSamples[readIdx]
          const need = chunkSamples - written
          const take = Math.min(need, s.length)
          flat.set(s.subarray(0, take), written)
          written += take
          if (take === s.length) {
            readIdx++
          } else {
            allSamples[readIdx] = s.subarray(take)
          }
        }
        readIdxRef.current = readIdx
        emitWavChunk(flat)
      }, chunkIntervalMs)

      setMode('mic')
    } catch (err) {
      reset()
      let message = '启动录音失败'
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        message = '麦克风权限被拒绝，请在浏览器设置中允许访问'
      } else if (err instanceof Error) {
        message = err.message
      }
      setErrorAndAutoClear(message)
      throw err
    }
  }, [chunkIntervalMs, emitWavChunk, reset, setErrorAndAutoClear])

  const startFile = useCallback(
    async (file: File) => {
      if (modeRef.current !== 'idle') throw new Error('Audio input already active')
      setErrorAndAutoClear(null)

      if (file.size > MAX_FILE_SIZE) {
        const msg = '文件过大，请上传 100MB 以内的音频'
        setErrorAndAutoClear(msg)
        throw new Error(msg)
      }

      try {
        const arrayBuffer = await file.arrayBuffer()
        const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE })
        audioContextRef.current = audioContext

        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer)
        console.log('sampleRate:', audioBuffer.sampleRate)
        const channelData = audioBuffer.getChannelData(0)
        totalSamplesRef.current = channelData.length

        // Start local playback
        const sourceNode = audioContext.createBufferSource()
        sourceNode.buffer = audioBuffer
        sourceNode.connect(audioContext.destination)
        sourceNode.start()
        sourceNodeRef.current = sourceNode

        // Emit chunks on interval
        const chunkSamples = Math.floor((SAMPLE_RATE * chunkIntervalMs) / 1000)
        let offset = 0

        chunkTimerRef.current = setInterval(() => {
          if (offset >= channelData.length) {
            stop()
            return
          }
          const end = Math.min(offset + chunkSamples, channelData.length)
          const slice = channelData.slice(offset, end)
          emitWavChunk(slice)
          offset = end
          setProgress(Math.round((offset / channelData.length) * 100))
        }, chunkIntervalMs)

        // Handle natural end
        sourceNode.onended = () => {
          if (modeRef.current === 'file') {
            stop()
          }
        }

        setMode('file')
      } catch (err) {
        reset()
        let message = '文件处理失败'
        if (err instanceof DOMException && err.name === 'NotSupportedError') {
          message = '无法解析该音频文件，请尝试 MP3 或 WAV 格式'
        } else if (err instanceof Error) {
          message = err.message
        }
        setErrorAndAutoClear(message)
        throw err
      }
    },
    [chunkIntervalMs, emitWavChunk, reset, stop, setErrorAndAutoClear],
  )

  return {
    mode,
    isActive: mode !== 'idle',
    progress,
    error,
    startRecording,
    startFile,
    stop,
    clearError,
  }
}
