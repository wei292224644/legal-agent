import { useState, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

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

  return (
    <div className="flex h-screen bg-zinc-950 items-center justify-center">
      <Card className="w-[420px] p-8 bg-zinc-900/80 border-zinc-800 text-center">
        <div className="mb-8">
          <h1 className="font-serif text-2xl tracking-wide text-amber-200/90 mb-2">
            声纹注册
          </h1>
          <p className="text-sm text-zinc-500">
            首次使用前，请朗读以下文本以注册您的声纹
          </p>
        </div>

        <Card className="p-6 mb-6 bg-zinc-950 border-zinc-800">
          <p className="text-lg text-zinc-300 leading-relaxed font-serif">
            "{registerText}"
          </p>
        </Card>

        {state === "idle" && (
          <Button
            size="lg"
            onClick={startRecording}
            className="w-full bg-amber-600 hover:bg-amber-500 text-zinc-900 border-amber-500"
          >
            🎤 开始录音 (15秒)
          </Button>
        )}

        {state === "recording" && (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2">
              <span className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
              <span className="text-red-400 font-mono">
                录音中... {countdown}s
              </span>
            </div>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 transition-all duration-1000 ease-linear"
                style={{ width: `${((15 - countdown) / 15) * 100}%` }}
              />
            </div>
          </div>
        )}

        {state === "done" && (
          <div className="space-y-4">
            <p className="text-green-400 font-serif">✓ 声纹注册成功</p>
            <Button
              variant="outline"
              onClick={() => (window.location.href = "/session/demo")}
              className="w-full border-amber-500/30 text-amber-300"
            >
              进入会谈
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
