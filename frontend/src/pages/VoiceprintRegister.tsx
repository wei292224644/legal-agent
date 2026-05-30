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
          if (timerRef.current) clearInterval(timerRef.current);
          setState("done");
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  return (
    <div className="flex h-screen bg-background items-center justify-center">
      <Card className="w-[420px] p-8 text-center">
        <div className="mb-8">
          <h1 className="text-2xl tracking-wide text-primary mb-2">
            声纹注册
          </h1>
          <p className="text-sm text-foreground/70">
            首次使用前，请朗读以下文本以注册您的声纹
          </p>
        </div>

        <div className="p-6 mb-6 bg-secondary border border-border rounded-lg">
          <p className="text-lg text-foreground/90 leading-relaxed">
            "{registerText}"
          </p>
        </div>

        {state === "idle" && (
          <Button size="lg" onClick={startRecording} className="w-full">
            <Mic className="w-4 h-4" />
            开始录音 (15秒)
          </Button>
        )}

        {state === "recording" && (
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

        {state === "done" && (
          <div className="space-y-4">
            <p className="text-success font-medium flex items-center justify-center gap-2">
              <CheckCircle2 className="w-5 h-5" />
              声纹注册成功
            </p>
            <Button
              size="lg"
              onClick={() => (window.location.href = "/session/demo")}
              className="w-full"
            >
              进入会谈
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
