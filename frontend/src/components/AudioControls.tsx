import { useRef } from 'react'
import { Button } from '@/components/ui/button'
import { useAudioInput } from '@/hooks/useAudioInput'

interface AudioControlsProps {
  onChunk: (chunk: Uint8Array) => void
}

export default function AudioControls({ onChunk }: AudioControlsProps) {
  const { mode, progress, error, startRecording, startFile, stop } =
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
      {mode === 'idle' && (
        <>
          <Button
            size="sm"
            onClick={() => startRecording()}
            className="bg-amber-600 hover:bg-amber-500 text-zinc-900 border-amber-500"
          >
            🎤 开始录音
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            className="border-zinc-700 text-zinc-300 hover:bg-zinc-800"
          >
            📁 上传音频
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*"
            className="hidden"
            onChange={handleFileChange}
          />
        </>
      )}

      {mode === 'mic' && (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="destructive"
            onClick={stop}
            className="bg-red-900 hover:bg-red-800 text-red-200 border-red-700"
          >
            ⏹ 停止
          </Button>
          <span className="flex items-center gap-2 text-sm text-red-400">
            <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
            录音中...
          </span>
        </div>
      )}

      {mode === 'file' && (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="destructive"
            onClick={stop}
            className="bg-red-900 hover:bg-red-800 text-red-200 border-red-700"
          >
            ⏹ 停止
          </Button>
          <span className="text-sm text-zinc-300">▶️ 播放中...</span>
          {progress !== null && (
            <div className="w-32 h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}
          {progress !== null && (
            <span className="text-xs text-zinc-500 font-mono w-10 text-right">
              {progress}%
            </span>
          )}
        </div>
      )}

      {error && (
        <span className="text-xs text-red-400 animate-in fade-in slide-in-from-top-1">
          {error}
        </span>
      )}
    </div>
  )
}
