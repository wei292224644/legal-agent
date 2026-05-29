import { useRef } from 'react'
import { Button } from '@/components/ui/button'
import { useAudioInput } from '@/hooks/useAudioInput'
import { Mic, Upload, Square, Play, X } from 'lucide-react'

interface AudioControlsProps {
  onChunk: (chunk: Uint8Array) => void
}

export default function AudioControls({ onChunk }: AudioControlsProps) {
  const { mode, progress, error, startRecording, startFile, stop, clearError } =
    useAudioInput({ onChunk })
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      startFile(file)
    }
    e.target.value = ''
  }

  return (
    <div className="flex items-center gap-3">
      {mode === 'idle' ? (
        <>
          <Button
            size="sm"
            onClick={startRecording}
            className="bg-[#d4a853] hover:bg-[#e0b86a] text-[#0d0b08] border-[#d4a853]"
          >
            <Mic className="w-4 h-4" />
            开始录音
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            className="border-[rgba(255,255,255,0.08)] text-[#e5e5e5] hover:bg-[#1e1b15]"
          >
            <Upload className="w-4 h-4" />
            上传音频
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*"
            className="hidden"
            onChange={handleFileChange}
          />
        </>
      ) : null}

      {mode === 'mic' ? (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            onClick={stop}
            className="border-[#c45c5c]/50 text-[#c45c5c] hover:bg-[#c45c5c]/10 hover:text-[#c45c5c]"
          >
            <Square className="w-4 h-4" />
            停止
          </Button>
          <span className="flex items-center gap-2 text-sm text-[#c45c5c]">
            <span className="w-2 h-2 bg-[#c45c5c] rounded-full animate-pulse" />
            录音中…
          </span>
        </div>
      ) : null}

      {mode === 'file' ? (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            onClick={stop}
            className="border-[rgba(255,255,255,0.08)] text-[#e5e5e5] hover:bg-[#1e1b15]"
          >
            <Square className="w-4 h-4" />
            停止
          </Button>
          <span className="flex items-center gap-2 text-sm text-[#e5e5e5]">
            <Play className="w-4 h-4" />
            播放中…
          </span>
          {progress !== null ? (
            <div className="w-32 h-1.5 bg-[#1e1b15] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#d4a853] transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          ) : null}
          {progress !== null ? (
            <span className="text-xs text-[#525252] font-mono w-10 text-right">
              {progress}%
            </span>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <div className="flex items-center gap-2 text-xs text-[#c45c5c] animate-in fade-in slide-in-from-top-1">
          <span>{error}</span>
          <button
            onClick={clearError}
            className="p-0.5 hover:text-[#e5e5e5] transition-colors"
            aria-label="关闭错误提示"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      ) : null}
    </div>
  )
}
