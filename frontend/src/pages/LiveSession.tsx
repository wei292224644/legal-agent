import { useState, useCallback, memo } from "react";
import { useWebSocket, type SuggestionData } from "@/hooks/useWebSocket";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  Circle,
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
      intentType: string;
      lawDomain: string | null;
    }
  | {
      kind: "ready";
      id: string;
      requestId?: string;
      text: string;
      intentType: string;
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
  statute: {
    label: "法规引用",
    icon: BookOpen,
    border: "border-[#d4a853]/30",
    bg: "bg-[#d4a853]/5",
  },
  contract: {
    label: "合同条款",
    icon: FileText,
    border: "border-[#6b8ec4]/30",
    bg: "bg-[#6b8ec4]/5",
  },
  risk: {
    label: "风险提示",
    icon: ShieldAlert,
    border: "border-[#c45c5c]/40",
    bg: "bg-[#c45c5c]/5",
  },
} as const;

const riskLevelClass = {
  高: "border-[#c45c5c]/50 text-[#c45c5c]",
  中: "border-[#d4a853]/50 text-[#d4a853]",
  低: "border-[#6b8f6b]/50 text-[#6b8f6b]",
} as const;

const riskLevelIcon = { 高: Circle, 中: Circle, 低: Circle } as const;
const riskLevelColor = { 高: "text-[#c45c5c]", 中: "text-[#d4a853]", 低: "text-[#6b8f6b]" } as const;

const emptyAnalysis = (
  <div className="flex flex-col items-center justify-center h-full text-[#525252] gap-2">
    <Activity className="w-8 h-8 opacity-20" />
    <p className="text-sm italic">系统正在监听并分析对话内容…</p>
    <p className="text-xs text-[#525252]">分析结果将随对话自动呈现</p>
  </div>
);

const emptyTranscript = (
  <div className="flex flex-col items-center justify-center h-full text-[#525252] gap-2">
    <MessageSquare className="w-6 h-6 opacity-20" />
    <p className="text-xs italic">开始说话，转写文本将实时显示…</p>
    <p className="text-[10px] text-[#525252]">录音开始后，对话内容将出现在此处</p>
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
            ? "bg-[#d4a853]/10 text-[#d4a853] border border-[#d4a853]/20"
            : "bg-[#1e1b15] text-[#8a8a8a] border border-[rgba(255,255,255,0.08)]"
        }`}
      >
        {isLawyer ? <User className="w-3 h-3" /> : <Users className="w-3 h-3" />} {line.speaker}
      </span>
      <p className="text-[#a3a3a3] leading-relaxed text-sm">{line.text}</p>
    </div>
  );
});

const AnalysisCard = memo(function AnalysisCard({ a }: { a: Analysis }) {
  const cfg = categoryConfig[a.category];
  return (
    <Card
      className={`p-4 ${cfg.bg} ${cfg.border} border rounded-lg transition-all duration-300`}
    >
      <div className="flex items-center gap-2 mb-2">
        <Badge
          variant="outline"
          className={`text-xs ${cfg.border} text-[#e5e5e5] rounded`}
        >
          <cfg.icon className="w-3 h-3" /> {cfg.label}
        </Badge>
        {a.category === "risk" && a.level && (
          <Badge
            variant="outline"
            className={`text-xs ${
              riskLevelClass[a.level as keyof typeof riskLevelClass] ?? ""
            } rounded`}
          >
            {a.level && (() => {
              const Icon = riskLevelIcon[a.level as keyof typeof riskLevelIcon];
              const color = riskLevelColor[a.level as keyof typeof riskLevelColor];
              return <Icon className={`w-3 h-3 ${color}`} />;
            })()}{" "}
            {a.level}
          </Badge>
        )}
      </div>
      <h3 className="text-sm font-medium text-[#e5e5e5] mb-1">
        {a.title}
      </h3>
      <p className="text-xs text-[#8a8a8a] leading-relaxed">{a.content}</p>
      {a.citation && (
        <p className="text-xs text-[#d4a853]/70 mt-2 font-mono">{a.citation}</p>
      )}
    </Card>
  );
});

const SuggestionCard = memo(function SuggestionCard({
  s,
  onConfirm,
  onDismiss,
}: {
  s: Suggestion;
  onConfirm: (requestId: string) => void;
  onDismiss: (requestId: string) => void;
}) {
  if (s.kind === "pending") {
    return (
      <Card className="p-4 bg-[#d4a853]/5 border-[#d4a853]/30 border rounded-lg transition-all duration-300">
        <Badge
          variant="outline"
          className="text-xs border-[#d4a853]/30 text-[#d4a853] mb-2 rounded"
        >
          <HelpCircle className="w-3 h-3" /> 检测到可分析意图
        </Badge>
        <p className="text-xs text-[#8a8a8a] leading-relaxed mb-3">
          {s.intentType}
          {s.lawDomain ? ` · ${s.lawDomain}` : ""}
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            className="bg-gradient-to-b from-[#e0b86a] to-[#c9a04a] text-[#0d0b08] border-t border-b border-t-white/15 border-b-black/20 hover:from-[#e8c47a] hover:to-[#d4a853] active:from-[#c9a04a] active:to-[#b08d3f] transition-all"
            onClick={() => onConfirm(s.requestId)}
          >
            生成深度分析
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border border-[rgba(255,255,255,0.08)] text-[#8a8a8a] hover:bg-[rgba(255,255,255,0.04)] hover:border-[rgba(255,255,255,0.12)] transition-colors"
            onClick={() => onDismiss(s.requestId)}
          >
            忽略
          </Button>
        </div>
      </Card>
    );
  }
  return (
    <Card className="p-4 bg-[#6b8ec4]/5 border-[#6b8ec4]/30 border rounded-lg transition-all duration-300">
      <Badge
        variant="outline"
        className="text-xs border-[#6b8ec4]/30 text-[#e5e5e5] mb-2 rounded"
      >
        <CheckCircle2 className="w-3 h-3" /> {s.intentType}
      </Badge>
      <p className="text-xs text-[#e5e5e5] leading-relaxed whitespace-pre-wrap">
        {s.text}
      </p>
    </Card>
  );
});

export default function LiveSession() {
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [status, setStatus] = useState("待连接…");
  const [activeTab, setActiveTab] = useState<"analysis" | "transcript">(
    "analysis"
  );
  const [isTranscriptExpanded, setIsTranscriptExpanded] = useState(false);

  const onTranscript = useCallback((data: TranscriptData) => {
    setTranscript((prev) => [
      ...prev,
      { speaker: data.speaker, text: data.text },
    ]);
    setStatus("正在听…");
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
          intentType: data.meta.intent_type,
          lawDomain: data.meta.law_domain,
        };
        return [pending, ...prev];
      }
      const ready: Suggestion = {
        kind: "ready",
        id: crypto.randomUUID(),
        requestId: data.meta.request_id,
        text: data.text ?? "",
        intentType: data.meta.intent_type,
      };
      if (data.meta.request_id) {
        return prev.map((s) =>
          s.kind === "pending" && s.requestId === data.meta.request_id
            ? ready
            : s
        );
      }
      return [ready, ...prev];
    });
  }, []);

  const { isConnected, sendAudioChunk, confirmIntent, dismissIntent } =
    useWebSocket("ws://localhost:8000/ws/demo-session", {
      onTranscript,
      onAnalysis,
      onSuggestion,
    });

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

  const recentTranscript = transcript.slice(-3);

  const analysisContent =
    suggestions.length === 0 && analyses.length === 0 ? (
      emptyAnalysis
    ) : (
      <div className="space-y-3">
        {suggestions.map((s) => (
          <SuggestionCard
            key={s.kind === "pending" ? s.requestId : s.id}
            s={s}
            onConfirm={confirmIntent}
            onDismiss={handleDismiss}
          />
        ))}
        {analyses.map((a) => (
          <AnalysisCard key={a.id} a={a} />
        ))}
      </div>
    );

  const transcriptContent =
    transcript.length === 0 ? (
      emptyTranscript
    ) : (
      <div className="space-y-4">
        {(isTranscriptExpanded ? transcript : recentTranscript).map(
          (line, i) => (
            <TranscriptItem
              key={isTranscriptExpanded ? i : `recent-${i}`}
              line={line}
            />
          )
        )}
        {!isTranscriptExpanded && transcript.length > 3 && (
          <button
            onClick={() => setIsTranscriptExpanded(true)}
            className="w-full py-2 text-xs text-[#525252] hover:text-[#8a8a8a] transition-colors flex items-center justify-center gap-1"
          >
            <ChevronDown className="w-3 h-3" />
            展开全部 {transcript.length} 条记录
          </button>
        )}
        {isTranscriptExpanded && (
          <button
            onClick={() => setIsTranscriptExpanded(false)}
            className="w-full py-2 text-xs text-[#525252] hover:text-[#8a8a8a] transition-colors flex items-center justify-center gap-1"
          >
            <ChevronUp className="w-3 h-3" />
            收起
          </button>
        )}
      </div>
    );

  return (
    <div className="flex flex-col h-screen bg-[#0d0b08] text-[#e5e5e5]">
      {/* Desktop header */}
      <header className="hidden md:flex items-center justify-between px-6 py-3 border-b border-[rgba(255,255,255,0.08)] bg-[#0d0b08] shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-medium tracking-wide text-[#525252]">
            实时会谈
          </h1>
          <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wide">
            <span
              className={`w-2 h-2 rounded-full ${
                isConnected ? "bg-[#6b8f6b]" : "bg-[#d4a853]"
              }`}
            />
            <span className={isConnected ? "text-[#6b8f6b]" : "text-[#d4a853]"}>
              {isConnected ? "已连接" : "连接中…"}
            </span>
            <span className="text-[#525252]">·</span>
            <span className="text-[#8a8a8a]">{status}</span>
          </div>
        </div>
        <AudioControls onChunk={sendAudioChunk} />
      </header>

      {/* Mobile header */}
      <header className="flex md:hidden items-center justify-between px-4 py-3 border-b border-[rgba(255,255,255,0.08)] bg-[#0d0b08] shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-medium tracking-wide text-[#525252]">
            实时会谈
          </h1>
          <span
            className={`w-2 h-2 rounded-full ${
              isConnected ? "bg-[#6b8f6b]" : "bg-[#d4a853]"
            }`}
          />
        </div>
        <AudioControls onChunk={sendAudioChunk} />
      </header>

      {/* Desktop layout: Analysis left, Transcript right */}
      <div className="hidden md:flex flex-1 overflow-hidden">
        {/* Left: Analysis (dominant, 40%) */}
        <div className="w-[40%] flex flex-col border-r border-[rgba(255,255,255,0.08)]">
          <div className="px-6 py-3 border-b border-[rgba(255,255,255,0.08)] shrink-0">
            <h2 className="text-lg font-medium tracking-wide text-[#d4a853]">
              实时洞察
            </h2>
            <p className="text-xs text-[#525252] mt-0.5 font-mono uppercase tracking-wide">
              {suggestions.length + analyses.length} 条分析结果
            </p>
          </div>
          <ScrollArea className="flex-1 px-4 py-4">{analysisContent}</ScrollArea>
        </div>

        {/* Right: Transcript (secondary, 60%) */}
        <div className="flex-1 flex flex-col">
          <div className="px-6 py-3 border-b border-[rgba(255,255,255,0.08)] shrink-0 flex items-center justify-between">
            <h2 className="text-lg font-medium tracking-wide text-[#8a8a8a]">
              转写记录
            </h2>
            <span className="text-xs text-[#525252] font-mono uppercase tracking-wide">
              {transcript.length} 条
            </span>
          </div>
          <ScrollArea className="flex-1 px-4 py-4">
            {transcriptContent}
          </ScrollArea>
        </div>
      </div>

      {/* Mobile layout: Tab-based */}
      <div className="flex md:hidden flex-1 flex-col overflow-hidden">
        <div className="flex-1 overflow-hidden">
          {activeTab === "analysis" ? (
            <ScrollArea className="h-full px-4 py-4">{analysisContent}</ScrollArea>
          ) : (
            <ScrollArea className="h-full px-4 py-4">
              {transcriptContent}
            </ScrollArea>
          )}
        </div>

        {/* Mobile bottom tab bar */}
        <nav className="flex border-t border-[rgba(255,255,255,0.08)] bg-[#17140f] shrink-0">
          <button
            onClick={() => setActiveTab("analysis")}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors ${
              activeTab === "analysis"
                ? "text-[#d4a853] bg-[#1e1b15]"
                : "text-[#525252] hover:text-[#8a8a8a]"
            }`}
          >
            <Activity className="w-4 h-4" />
            洞察
            {suggestions.length + analyses.length > 0 && (
              <span className="text-xs bg-[#d4a853]/20 text-[#d4a853] px-1.5 py-0.5 rounded">
                {suggestions.length + analyses.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("transcript")}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors ${
              activeTab === "transcript"
                ? "text-[#d4a853] bg-[#1e1b15]"
                : "text-[#525252] hover:text-[#8a8a8a]"
            }`}
          >
            <MessageSquare className="w-4 h-4" />
            转写
            {transcript.length > 0 && (
              <span className="text-xs bg-[#1e1b15] text-[#8a8a8a] px-1.5 py-0.5 rounded">
                {transcript.length}
              </span>
            )}
          </button>
        </nav>
      </div>
    </div>
  );
}
