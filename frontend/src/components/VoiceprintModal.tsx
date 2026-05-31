import { useState, useRef, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Mic, Upload, CheckCircle2, Loader2 } from "lucide-react";
import { encodeWavChunk } from "@/lib/wav";

const registerText =
  "今天天气很好，我们在这里进行法律咨询。" +
  "根据中华人民共和国相关法律法规，" +
  "我将为您提供专业的法律服务和建议。";

interface VoiceprintModalProps {
  sessionId: string;
  onComplete: () => void;
  onError: (message: string) => void;
}

type Phase = "idle" | "recording" | "uploading" | "done";

export default function VoiceprintModal({
  sessionId,
  onComplete,
  onError,
}: VoiceprintModalProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [countdown, setCountdown] = useState(15);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const samplesRef = useRef<Float32Array[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const cleanup = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (workletNodeRef.current) {
      try { workletNodeRef.current.disconnect(); } catch { /* noop */ }
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch { /* noop */ }
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
    }
    samplesRef.current = [];
  }, []);

  useEffect(() => {
    return () => cleanup();
  }, [cleanup]);

  const buildWavBlob = useCallback((): Blob => {
    const all = samplesRef.current;
    if (all.length === 0) return new Blob();
    const totalLen = all.reduce((sum, arr) => sum + arr.length, 0);
    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const arr of all) {
      merged.set(arr, offset);
      offset += arr.length;
    }
    const wavBytes = encodeWavChunk(merged, { sampleRate: 16000, channels: 1 });
    return new Blob([wavBytes], { type: "audio/wav" });
  }, []);

  const doUpload = useCallback(
    async (blob: Blob) => {
      setPhase("uploading");
      try {
        const { uploadEnrollment } = await import("@/api/sessions");
        await uploadEnrollment(sessionId, blob);
        setPhase("done");
        setTimeout(() => onComplete(), 500);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "上传失败";
        setErrorMsg(msg);
        setPhase("idle");
        onError(msg);
      }
    },
    [sessionId, onComplete, onError]
  );

  const startRecording = useCallback(async () => {
    setErrorMsg(null);
    setPhase("recording");
    setCountdown(15);
    samplesRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;

      const workletCode = `
        class PCMProcessor extends AudioWorkletProcessor {
          process(inputs) {
            const input = inputs[0];
            if (input && input[0]) {
              this.port.postMessage(input[0]);
            }
            return true;
          }
        }
        registerProcessor('pcm-processor', PCMProcessor)
      `;
      const blob = new Blob([workletCode], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      await audioContext.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      const source = audioContext.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioContext, "pcm-processor");
      workletNodeRef.current = workletNode;

      workletNode.port.onmessage = (e) => {
        samplesRef.current.push(e.data);
      };

      source.connect(workletNode);

      timerRef.current = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            if (timerRef.current) clearInterval(timerRef.current);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);

      timeoutRef.current = setTimeout(() => {
        cleanup();
        const blob = buildWavBlob();
        doUpload(blob);
      }, 15000);
    } catch (err) {
      cleanup();
      let msg = "启动录音失败";
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        msg = "麦克风权限被拒绝，请在浏览器设置中允许访问";
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setErrorMsg(msg);
      setPhase("idle");
      onError(msg);
    }
  }, [cleanup, buildWavBlob, doUpload, onError]);

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setErrorMsg(null);
      await doUpload(file);
    },
    [doUpload]
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[420px] max-w-[90vw] rounded-xl bg-bg-primary p-8 text-center shadow-lg border border-border-color">
        <div className="mb-6">
          <h2 className="text-xl font-semibold text-ink-primary mb-2">
            请先录制声纹
          </h2>
          <p className="text-sm text-ink-secondary">
            系统需要您的声纹来区分律师与当事人
          </p>
        </div>

        <div className="p-5 mb-6 bg-bg-secondary border border-border-color rounded-lg">
          <p className="text-base text-ink-primary leading-relaxed">
            &ldquo;{registerText}&rdquo;
          </p>
        </div>

        {phase === "idle" && (
          <div className="space-y-3">
            <Button size="lg" onClick={startRecording} className="w-full">
              <Mic className="w-4 h-4 mr-2" />
              开始录音 (15秒)
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*"
              onChange={handleFileUpload}
              className="hidden"
              id="enroll-file-input"
            />
            <Button
              variant="outline"
              size="lg"
              className="w-full"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="w-4 h-4 mr-2" />
              上传音频文件
            </Button>
          </div>
        )}

        {phase === "recording" && (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2">
              <span className="w-3 h-3 bg-danger rounded-full motion-safe:animate-pulse" />
              <span className="text-danger font-mono">
                录音中… {countdown}s
              </span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-1000 ease-linear"
                style={{ width: `${((15 - countdown) / 15) * 100}%` }}
              />
            </div>
          </div>
        )}

        {phase === "uploading" && (
          <div className="flex items-center justify-center gap-2 text-ink-secondary">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>正在处理声纹…</span>
          </div>
        )}

        {phase === "done" && (
          <div className="flex items-center justify-center gap-2 text-success">
            <CheckCircle2 className="w-5 h-5" />
            <span>声纹上传成功</span>
          </div>
        )}

        {errorMsg && (
          <p className="mt-4 text-sm text-danger">{errorMsg}</p>
        )}
      </div>
    </div>
  );
}
