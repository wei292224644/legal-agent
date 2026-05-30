import { useRef } from 'react'
import { Button } from '@/components/ui/button'
import { useAudioInput } from '@/hooks/useAudioInput'
import { Mic, Upload, Square, Play, X } from 'lucide-react'

interface AudioControlsProps {
  onChunk: (chunk: Uint8Array) => void
  onAudioEnd?: () => void
}

export default function AudioControls({ onChunk, onAudioEnd }: AudioControlsProps) {
  const { mode, progress, error, startRecording, startFile, stop, clearError } =
    useAudioInput({ onChunk, onAudioEnd })
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
          <Button onClick={startRecording}>
            <Mic className="w-4 h-4" />
            开始录音
          </Button>
          <Button
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
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
          <Button variant="destructive" onClick={stop}>
            <Square className="w-4 h-4" />
            停止
          </Button>
          <span className="flex items-center gap-2 text-sm text-danger">
            <span className="w-2 h-2 bg-danger rounded-full motion-safe:animate-pulse" />
            录音中…
          </span>
        </div>
      ) : null}

      {mode === 'file' ? (
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={stop}>
            <Square className="w-4 h-4" />
            停止
          </Button>
          <span className="flex items-center gap-2 text-sm text-foreground">
            <Play className="w-4 h-4" />
            播放中…
          </span>
          {progress !== null ? (
            <div className="w-32 h-1.5 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          ) : null}
          {progress !== null ? (
            <span className="text-xs text-muted-foreground font-mono w-10 text-right">
              {progress}%
            </span>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <div className="flex items-center gap-2 text-xs text-danger animate-in fade-in slide-in-from-top-1">
          <span>{error}</span>
          <Button
            variant="ghost"
            size="icon"
            onClick={clearError}
            aria-label="关闭错误提示"
          >
            <X className="w-3 h-3" />
          </Button>
        </div>
      ) : null}
    </div>
  )
}
