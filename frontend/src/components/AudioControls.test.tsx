import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import AudioControls from './AudioControls'

// Mock useAudioInput hook
const mockStartRecording = vi.fn()
const mockStartFile = vi.fn()
const mockStop = vi.fn()
const mockClearError = vi.fn()

vi.mock('@/hooks/useAudioInput', () => ({
  useAudioInput: vi.fn(() => ({
    mode: 'idle',
    isActive: false,
    progress: null,
    error: null,
    startRecording: mockStartRecording,
    startFile: mockStartFile,
    stop: mockStop,
    clearError: mockClearError,
  })),
}))

import { useAudioInput } from '@/hooks/useAudioInput'

const mockedUseAudioInput = vi.mocked(useAudioInput)

describe('AudioControls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedUseAudioInput.mockReturnValue({
      mode: 'idle',
      isActive: false,
      progress: null,
      error: null,
      startRecording: mockStartRecording,
      startFile: mockStartFile,
      stop: mockStop,
      clearError: mockClearError,
    })
  })

  it('renders record and upload buttons in idle state', () => {
    render(<AudioControls onChunk={vi.fn()} />)
    expect(screen.getByText('开始录音')).toBeDefined()
    expect(screen.getByText('上传音频')).toBeDefined()
  })

  it('calls startRecording when record button clicked', () => {
    render(<AudioControls onChunk={vi.fn()} />)
    fireEvent.click(screen.getByText('开始录音'))
    expect(mockStartRecording).toHaveBeenCalledTimes(1)
  })

  it('shows stop button in mic mode', () => {
    mockedUseAudioInput.mockReturnValue({
      mode: 'mic',
      isActive: true,
      progress: null,
      error: null,
      startRecording: mockStartRecording,
      startFile: mockStartFile,
      stop: mockStop,
      clearError: mockClearError,
    })

    render(<AudioControls onChunk={vi.fn()} />)
    expect(screen.getByText('停止')).toBeDefined()
    expect(screen.queryByText('开始录音')).toBeNull()
  })

  it('shows progress in file mode', () => {
    mockedUseAudioInput.mockReturnValue({
      mode: 'file',
      isActive: true,
      progress: 45,
      error: null,
      startRecording: mockStartRecording,
      startFile: mockStartFile,
      stop: mockStop,
      clearError: mockClearError,
    })

    render(<AudioControls onChunk={vi.fn()} />)
    expect(screen.getByText('停止')).toBeDefined()
    expect(screen.getByText('播放中…')).toBeDefined()
    expect(screen.getByText('45%')).toBeDefined()
  })

  it('shows error message', () => {
    mockedUseAudioInput.mockReturnValue({
      mode: 'idle',
      isActive: false,
      progress: null,
      error: '测试错误信息',
      startRecording: mockStartRecording,
      startFile: mockStartFile,
      stop: mockStop,
      clearError: mockClearError,
    })

    render(<AudioControls onChunk={vi.fn()} />)
    expect(screen.getByText('测试错误信息')).toBeDefined()
  })

  it('calls stop when stop button clicked', () => {
    mockedUseAudioInput.mockReturnValue({
      mode: 'mic',
      isActive: true,
      progress: null,
      error: null,
      startRecording: mockStartRecording,
      startFile: mockStartFile,
      stop: mockStop,
      clearError: mockClearError,
    })

    render(<AudioControls onChunk={vi.fn()} />)
    fireEvent.click(screen.getByText('停止'))
    expect(mockStop).toHaveBeenCalledTimes(1)
  })
})
