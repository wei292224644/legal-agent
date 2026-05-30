import { useState, useCallback, useEffect, useRef, memo } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useWebSocket, type SuggestionData } from "@/hooks/useWebSocket";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import AudioControls from "@/components/AudioControls";
import {
  Activity,
  MessageSquare,
  ChevronUp,
  ChevronDown,
  BookOpen,
  FileText,
  ShieldAlert,
  User,
  Users,
  HelpCircle,
  CheckCircle2,
} from "lucide-react";

type TranscriptLine = { speaker: string; text: string };
type Analysis = {
  id: string;
  category: "statute" | "contract" | "risk";
  title: string;
  content: string;
  citation?: string;
  level?: string;
};

type Suggestion =
  | {
      kind: "pending";
      requestId: string;
      topic: string;
      rationale: string;
    }
  | {
      kind: "running";
      requestId: string;
      topic: string;
    }
  | {
      kind: "ready";
      id: string;
      requestId?: string;
      text: string;
      topic: string;
    };

type TranscriptData = {
  text: string;
  speaker: string;
  is_final: boolean;
};
type AnalysisData = {
  category: string;
  title: string;
  content: string;
  citation?: string;
  level?: string;
};

const categoryConfig = {
  statute: { label: "法规引用", icon: BookOpen, color: "text-primary" as const, bg: "bg-primary/10" as const, border: "border-primary/20" as const },
  contract: { label: "合同条款", icon: FileText, color: "text-contract" as const, bg: "bg-contract/10" as const, border: "border-contract/20" as const },
  risk: { label: "风险提示", icon: ShieldAlert, color: "text-danger" as const, bg: "bg-danger/10" as const, border: "border-danger/20" as const },
} as const;

const riskLevelColor = { 高: "text-danger", 中: "text-primary", 低: "text-success" } as const;

const emptyAnalysis = (
  <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
    <Activity className="w-8 h-8 opacity-20" />
    <p className="text-sm italic">系统正在监听并分析对话内容…</p>
    <p className="text-xs text-muted-foreground">分析结果将随对话自动呈现</p>
  </div>
);

const emptyTranscript = (
  <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
    <MessageSquare className="w-6 h-6 opacity-20" />
    <p className="text-xs italic">开始说话，转写文本将实时显示…</p>
    <p className="text-xs text-muted-foreground">录音开始后，对话内容将出现在此处</p>
  </div>
);

const TranscriptItem = memo(function TranscriptItem({
  line,
}: {
  line: TranscriptLine;
}) {
  const isLawyer = line.speaker === "律师";
  return (
    <div className="flex gap-3">
      <span
        className={`shrink-0 text-xs font-mono mt-1 px-2 py-0.5 rounded ${
          isLawyer
            ? "bg-primary/10 text-primary border border-primary/20"
            : "bg-muted text-muted-foreground border border-border"
        }`}
      >
        {isLawyer ? <User className="w-3 h-3 inline" /> : <Users className="w-3 h-3 inline" />} {line.speaker}
      </span>
      <p className="text-foreground/90 leading-relaxed text-sm">{line.text}</p>
    </div>
  );
});

const AnalysisItem = memo(function AnalysisItem({
  a,
}: {
  a: Analysis;
}) {
  const cfg = categoryConfig[a.category];
  return (
    <div className="py-3 border-t border-border first:border-t-0">
      <div className="flex items-center gap-2 mb-1">
        <span
          className={`text-xs font-mono uppercase tracking-wide ${cfg.color}`}
        >
          <cfg.icon className="w-3 h-3 inline" /> {cfg.label}
        </span>
        {a.category === "risk" && a.level && (
          <span
            className={`text-xs font-mono uppercase tracking-wide ${riskLevelColor[a.level as keyof typeof riskLevelColor]}`}
          >
            {a.level}
          </span>
        )}
      </div>
      <h3 className="text-sm font-semibold text-foreground mb-1">{a.title}</h3>
      <p className="text-sm text-foreground/80 leading-relaxed">{a.content}</p>
      {a.citation && (
        <p className="text-xs text-primary/80 mt-2 font-mono">{a.citation}</p>
      )}
    </div>
  );
});

const PENDING_TIMEOUT_SECONDS = 30;

const SuggestionCard = memo(function SuggestionCard({
  s,
  onConfirm,
  onDismiss,
}: {
  s: Suggestion;
  onConfirm: (requestId: string) => void;
  onDismiss: (requestId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [timeLeft, setTimeLeft] = useState(PENDING_TIMEOUT_SECONDS);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (s.kind !== "pending") {
      const iv = intervalRef.current;
      if (iv) {
        clearInterval(iv);
        intervalRef.current = null;
      }
      return;
    }
    intervalRef.current = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          const current = intervalRef.current;
          if (current) {
            clearInterval(current);
            intervalRef.current = null;
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    const timeout = setTimeout(() => {
      onDismiss(s.requestId);
    }, PENDING_TIMEOUT_SECONDS * 1000);
    return () => {
      clearTimeout(timeout);
      const iv = intervalRef.current;
      if (iv) {
        clearInterval(iv);
        intervalRef.current = null;
      }
    };
  }, [s.kind, s.requestId, onDismiss]);

  if (s.kind === "pending") {
    const progress = (timeLeft / PENDING_TIMEOUT_SECONDS) * 100;
    return (
      <div className="py-3 border-t border-border first:border-t-0">
        <span className="text-xs font-mono uppercase tracking-wide text-primary">
          <HelpCircle className="w-3 h-3 inline" /> {s.topic || "检测到可分析意图"}
        </span>
        {s.rationale && (
          <p className="text-sm text-foreground/80 leading-relaxed my-2">
            {s.rationale}
          </p>
        )}
        <div className="flex items-center gap-2 mb-2">
          <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-1000 ease-linear"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground font-mono w-12 text-right">
            {timeLeft}s
          </span>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => onConfirm(s.requestId)}>
            生成深度分析
          </Button>
          <Button variant="outline" onClick={() => onDismiss(s.requestId)}>
            忽略
          </Button>
        </div>
      </div>
    );
  }
  if (s.kind === "running") {
    return (
      <div className="py-3 border-t border-border first:border-t-0">
        <span className="text-xs font-mono uppercase tracking-wide text-primary motion-safe:animate-pulse">
          <Activity className="w-3 h-3 inline" /> 分析中…{s.topic ? ` · ${s.topic}` : ""}
        </span>
      </div>
    );
  }

  return (
    <div className="py-3 border-t border-border first:border-t-0">
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-mono uppercase tracking-wide text-contract">
            <CheckCircle2 className="w-3 h-3 inline" /> {s.topic || "深度分析"}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-xs h-auto py-1 px-2 shrink-0"
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3 h-3" /> 收起
              </>
            ) : (
              <>
                <ChevronDown className="w-3 h-3" /> 展开
              </>
            )}
          </Button>
        </div>
        <CollapsibleContent>
          <div className="text-sm text-foreground/90 leading-relaxed mt-2 prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {s.text ?? ""}
            </ReactMarkdown>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
});

export default function LiveSession() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [activeTab, setActiveTab] = useState<"analysis" | "transcript">(
    "analysis"
  );

  const onTranscript = useCallback((data: TranscriptData) => {
    setTranscript((prev) => [
      ...prev,
      { speaker: data.speaker, text: data.text },
    ]);
  }, []);

  const onAnalysis = useCallback((data: AnalysisData) => {
    setAnalyses((prev) => [
      {
        id: crypto.randomUUID(),
        category: data.category as Analysis["category"],
        title: data.title,
        content: data.content,
        citation: data.citation,
        level: data.level,
      },
      ...prev,
    ]);
  }, []);

  const onSuggestion = useCallback((data: SuggestionData) => {
    setSuggestions((prev) => {
      if (data.type === "suggestion.pending") {
        const pending: Suggestion = {
          kind: "pending",
          requestId: data.meta.request_id ?? "",
          topic: data.meta.preview?.topic ?? "",
          rationale: data.meta.preview?.rationale ?? "",
        };
        return [pending, ...prev];
      }
      const rid = data.meta.request_id;
      if (rid) {
        return prev.map((s) => {
          if ((s.kind !== "pending" && s.kind !== "running") || s.requestId !== rid) return s;
          const ready: Suggestion = {
            kind: "ready",
            id: crypto.randomUUID(),
            requestId: rid,
            text: data.text ?? "",
            topic: s.topic,
          };
          return ready;
        });
      }
      const ready: Suggestion = {
        kind: "ready",
        id: crypto.randomUUID(),
        text: data.text ?? "",
        topic: "",
      };
      return [ready, ...prev];
    });
  }, []);

  const { isConnected, error: wsError, sendAudioChunk, confirmIntent, dismissIntent, notifyAudioEnd } =
    useWebSocket(sessionId ?? "", {
      onTranscript,
      onAnalysis,
      onSuggestion,
      onConfirmAck: ({ ok, request_id }) => {
        if (!ok) {
          setSuggestions((prev) =>
            prev.filter(
              (s) => !((s.kind === "pending" || s.kind === "running") && s.requestId === request_id)
            )
          );
        }
      },
    });

  const handleConfirm = useCallback(
    (requestId: string) => {
      confirmIntent(requestId);
      setSuggestions((prev) =>
        prev.map((s) =>
          s.kind === "pending" && s.requestId === requestId
            ? { kind: "running" as const, requestId, topic: s.topic }
            : s
        )
      );
    },
    [confirmIntent]
  );

  const handleDismiss = useCallback(
    (requestId: string) => {
      dismissIntent(requestId);
      setSuggestions((prev) =>
        prev.filter(
          (s) => !(s.kind === "pending" && s.requestId === requestId)
        )
      );
    },
    [dismissIntent]
  );

  const analysisContent =
    suggestions.length === 0 && analyses.length === 0 ? (
      emptyAnalysis
    ) : (
      <div className="divide-y divide-border">
        {suggestions.map((s) => (
          <SuggestionCard
            key={s.kind === "running" ? `running-${s.requestId}` : s.kind === "pending" ? s.requestId : s.id}
            s={s}
            onConfirm={handleConfirm}
            onDismiss={handleDismiss}
          />
        ))}
        {analyses.map((a) => (
          <AnalysisItem key={a.id} a={a} />
        ))}
      </div>
    );

  const transcriptContent =
    transcript.length === 0 ? (
      emptyTranscript
    ) : (
      <div className="space-y-4">
        {transcript.map((line, i) => (
          <TranscriptItem key={i} line={line} />
        ))}
      </div>
    );

  return (
    <div className="flex flex-col h-screen bg-background text-foreground">
      {/* Desktop header */}
      <header className="hidden md:flex items-center justify-between px-6 py-3 border-b border-border bg-background shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-foreground">
            实时会谈
          </h1>
          <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wide">
            <span
              className={`w-2 h-2 rounded-full ${
                wsError
                  ? "bg-danger"
                  : isConnected
                  ? "bg-success"
                  : "bg-primary"
              }`}
            />
            <span
              className={
                wsError
                  ? "text-danger"
                  : isConnected
                  ? "text-success"
                  : "text-primary"
              }
            >
              {wsError ? `连接失败:${wsError}` : isConnected ? "已连接" : "连接中…"}
            </span>
          </div>
        </div>
        <AudioControls onChunk={sendAudioChunk} onAudioEnd={notifyAudioEnd} />
      </header>

      {/* Mobile header */}
      <header className="flex md:hidden items-center justify-between px-4 py-3 border-b border-border bg-background shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-foreground">
            实时会谈
          </h1>
          <span
            className={`w-2 h-2 rounded-full ${
              wsError
                ? "bg-danger"
                : isConnected
                ? "bg-success"
                : "bg-primary"
            }`}
            title={wsError ?? (isConnected ? "已连接" : "连接中…")}
          />
        </div>
        <AudioControls onChunk={sendAudioChunk} onAudioEnd={notifyAudioEnd} />
      </header>

      {/* Desktop layout: Transcript left, Analysis right */}
      <div className="hidden md:flex flex-1 overflow-hidden">
        {/* Left: Transcript (dominant, 60%) */}
        <div className="w-3/5 flex flex-col">
          <div className="px-6 py-3 border-b border-border shrink-0 flex items-center justify-between">
            <h2 className="text-base font-semibold text-foreground">
              转写记录
            </h2>
            <span className="text-xs text-muted-foreground font-mono uppercase tracking-wide">
              {transcript.length} 条
            </span>
          </div>
          <ScrollArea className="flex-1 px-4 py-4">
            {transcriptContent}
          </ScrollArea>
        </div>

        {/* Right: Analysis (sidebar, 40%) */}
        <div className="w-2/5 flex flex-col bg-card border-l border-border">
          <div className="px-6 py-3 border-b border-border shrink-0">
            <h2 className="text-base font-semibold text-primary">
              实时洞察
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5 font-mono uppercase tracking-wide">
              {suggestions.length + analyses.length} 条分析结果
            </p>
          </div>
          <ScrollArea className="flex-1 px-5 py-6">
            {analysisContent}
          </ScrollArea>
        </div>
      </div>

      {/* Mobile layout: Tab-based */}
      <div className="flex md:hidden flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-hidden">
          {activeTab === "analysis" ? (
            <ScrollArea className="h-full px-4 py-4 bg-card">
              {analysisContent}
            </ScrollArea>
          ) : (
            <ScrollArea className="h-full px-4 py-4">
              {transcriptContent}
            </ScrollArea>
          )}
        </div>

        {/* Mobile bottom tab bar */}
        <nav className="flex border-t border-border bg-card shrink-0">
          <Button
            variant="ghost"
            onClick={() => setActiveTab("analysis")}
            className={`flex-1 flex items-center justify-center gap-2 py-3 h-auto rounded-none text-sm ${
              activeTab === "analysis"
                ? "text-primary bg-muted"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Activity className="w-4 h-4" />
            洞察
            {suggestions.length + analyses.length > 0 && (
              <span className="text-xs bg-primary/20 text-primary px-1.5 py-0.5 rounded">
                {suggestions.length + analyses.length}
              </span>
            )}
          </Button>
          <Button
            variant="ghost"
            onClick={() => setActiveTab("transcript")}
            className={`flex-1 flex items-center justify-center gap-2 py-3 h-auto rounded-none text-sm ${
              activeTab === "transcript"
                ? "text-primary bg-muted"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <MessageSquare className="w-4 h-4" />
            转写
            {transcript.length > 0 && (
              <span className="text-xs bg-muted text-muted-foreground px-1.5 py-0.5 rounded">
                {transcript.length}
              </span>
            )}
          </Button>
        </nav>
      </div>
    </div>
  );
}
