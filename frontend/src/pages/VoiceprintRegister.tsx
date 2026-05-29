import { useState, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Mic, CheckCircle2 } from "lucide-react";

const registerText =
  "今天天气很好，我们在这里进行法律咨询。" +
  "根据中华人民共和国相关法律法规，" +
  "我将为您提供专业的法律服务和建议。";

export default function VoiceprintRegister() {
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [countdown, setCountdown] = useState(15);
  const timerRef = useRef<ReturnType<typeof setInterval>>(null);

  const startRecording = useCallback(() => {
    setState("recording");
    setCountdown(15);
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timerRef.current);
          setState("done");
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  const primaryBtn =
    "bg-gradient-to-b from-[#e0b86a] to-[#c9a04a] text-[#0d0b08] " +
    "border-t border-b border-t-white/15 border-b-black/20 " +
    "hover:from-[#e8c47a] hover:to-[#d4a853] " +
    "active:from-[#c9a04a] active:to-[#b08d3f] " +
    "transition-all";

  return (
    <div className="flex h-screen bg-[#0d0b08] items-center justify-center">
      <Card className="w-[420px] p-8 bg-[#17140f]/80 border border-[rgba(255,255,255,0.04)] text-center rounded-lg">
        <div className="mb-8">
          <h1 className="text-2xl tracking-wide text-[#d4a853] mb-2">
            声纹注册
          </h1>
          <p className="text-sm text-[#525252]">
            首次使用前，请朗读以下文本以注册您的声纹
          </p>
        </div>

        <Card className="p-6 mb-6 bg-[#0d0b08] border border-[rgba(255,255,255,0.04)] rounded-lg">
          <p className="text-lg text-[#a3a3a3] leading-relaxed">
            "{registerText}"
          </p>
        </Card>

        {state === "idle" && (
          <Button
            size="lg"
            onClick={startRecording}
            className={`w-full ${primaryBtn}`}
          >
            <Mic className="w-4 h-4" />
            开始录音 (15秒)
          </Button>
        )}

        {state === "recording" && (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2">
              <span className="w-3 h-3 bg-[#c45c5c] rounded-full animate-pulse" />
              <span className="text-[#c45c5c] font-mono">
                录音中… {countdown}s
              </span>
            </div>
            <div className="h-2 bg-[#1e1b15] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#d4a853] transition-all duration-1000 ease-linear"
                style={{ width: `${((15 - countdown) / 15) * 100}%` }}
              />
            </div>
          </div>
        )}

        {state === "done" && (
          <div className="space-y-4">
            <p className="text-[#6b8f6b] flex items-center justify-center gap-1">
              <CheckCircle2 className="w-4 h-4" />
              声纹注册成功
            </p>
            <Button
              variant="outline"
              onClick={() => (window.location.href = "/session/demo")}
              className="w-full border border-[rgba(255,255,255,0.08)] text-[#d4a853] hover:bg-[rgba(255,255,255,0.04)] hover:border-[rgba(255,255,255,0.12)] transition-colors"
            >
              进入会谈
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
