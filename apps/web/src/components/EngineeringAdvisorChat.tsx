import {
  HardHat,
  Lightbulb,
  RefreshCw,
  Send,
  User,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { ProjectDetail } from "../lib/types";
import { Badge, Button, inputClass } from "./ui";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  improvements?: string[];
  mode?: string;
  timestamp: string;
}

interface EngineeringAdvisorChatProps {
  detail: ProjectDetail;
  activeSiteId?: string | null;
  isOpen: boolean;
  onClose: () => void;
}

const QUICK_PROMPTS = [
  "What are the top civil and structural risks with this candidate site?",
  "How should we engineer foundations to mitigate high seismic PGA or soft soil?",
  "What cooling architecture is optimal given local water stress and wet-bulb temperatures?",
  "What civil earthwork, grading, and retaining walls will be needed for this parcel?",
  "How do we handle stormwater detention and FEMA 500-year flood elevations?",
  "What are typical lead times and switchyard requirements for a 230kV substation feed?",
];

export function EngineeringAdvisorChat({
  detail,
  activeSiteId,
  isOpen,
  onClose,
}: EngineeringAdvisorChatProps) {
  const [selectedSiteId, setSelectedSiteId] = useState<string | null>(activeSiteId ?? null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome-1",
      role: "assistant",
      content: `**Senior Civil & Structural EPC Advisor Active.**\n\nI am your Principal Critical Infrastructure Engineer (25+ years designing hyperscale Tier III/IV data centers). Ask me about:\n\n* **Geotechnical & Structural:** Foundation piles, allowable soil bearing, seismic PGA anchoring (ASCE 7-22), floor slab live loads.\n* **Civil Earthwork & Hydrology:** Cut/fill grading, retaining walls, stormwater detention basins, FEMA 500-year flood levels (FFE + 3ft).\n* **Power & Substations:** 115kV/230kV ring-bus yards, transformer blast walls, generator fuel storage.\n* **HVAC & Cooling:** Closed-loop adiabatic chillers, evaporative water consumption, ASHRAE TC 9.9 compliance.`,
      improvements: [
        "Check FEMA base flood elevation (BFE) for active site",
        "Verify ASCE 7-22 seismic peak ground acceleration (PGA)",
        "Assess utility substation capacity & 230kV transmission distance",
      ],
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);

  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (activeSiteId) {
      setSelectedSiteId(activeSiteId);
    }
  }, [activeSiteId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const activeSite = detail.sites.find((s) => s.id === selectedSiteId);

  async function handleSend(textToSend?: string) {
    const text = (textToSend ?? input).trim();
    if (!text || busy) return;

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setBusy(true);

    try {
      const siteCtx = activeSite
        ? {
            site_name: activeSite.name,
            address: activeSite.address,
            latitude: activeSite.latitude,
            longitude: activeSite.longitude,
            area_hectares: activeSite.area_hectares,
            notes: activeSite.notes,
          }
        : undefined;

      const history = messages.slice(-6).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const res = await api.advisorChat(detail.project.id, {
        message: text,
        site_id: selectedSiteId,
        site_context: siteCtx,
        history,
      });

      const assistantMsg: Message = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: res.reply,
        improvements: res.suggested_improvements,
        mode: res.mode,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const errorMsg: Message = {
        id: `err-${Date.now()}`,
        role: "assistant",
        content: `⚠️ **Advisory Offline:** Could not communicate with the senior engineering engine (${err?.message || "connection error"}). Please ensure backend API is running.`,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setBusy(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full sm:w-[32rem] md:w-[36rem] bg-white border-l border-ink-200 shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
      {/* Header */}
      <div className="p-4 border-b border-ink-200 bg-ink-900 text-white flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/20 text-amber-400 border border-amber-500/30">
            <HardHat className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-white">Senior Civil EPC Advisor</h2>
              <Badge className="border-amber-400/40 bg-amber-500/20 text-amber-300 text-[10px] py-0 px-1.5">
                Principal PE
              </Badge>
            </div>
            <p className="text-[11px] text-ink-300">25+ Years Hyperscale Data Center Construction</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() =>
              setMessages((prev) => [
                prev[0],
                {
                  id: `clear-${Date.now()}`,
                  role: "assistant",
                  content: "Session reset. What data center civil/structural engineering challenge can I assist with?",
                  timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                },
              ])
            }
            className="p-1.5 text-ink-400 hover:text-white rounded-lg hover:bg-ink-800 transition"
            title="Reset Chat History"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 text-ink-400 hover:text-white rounded-lg hover:bg-ink-800 transition"
            title="Close Advisor"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Site Context Selector Bar */}
      <div className="p-2.5 bg-ink-50 border-b border-ink-200 flex items-center justify-between gap-2 text-xs">
        <span className="text-ink-500 font-medium shrink-0">Consulting on:</span>
        <select
          className="bg-white border border-ink-300 rounded-md px-2 py-1 text-xs text-ink-800 focus:border-signal-600 focus:outline-none max-w-[20rem] truncate"
          value={selectedSiteId ?? ""}
          onChange={(e) => setSelectedSiteId(e.target.value ? e.target.value : null)}
        >
          <option value="">🌐 General Project &amp; Master Plan</option>
          {detail.sites.map((s) => (
            <option key={s.id} value={s.id}>
              📍 {s.name} ({s.address || (s.latitude && s.longitude ? `${s.latitude.toFixed(2)}, ${s.longitude.toFixed(2)}` : "Coordinates pending")})
            </option>
          ))}
        </select>
      </div>

      {/* Message List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/50">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-2.5 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            {msg.role === "assistant" && (
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-100 text-amber-800 shrink-0 border border-amber-200 mt-0.5">
                <HardHat className="h-4 w-4" />
              </div>
            )}

            <div
              className={`max-w-[85%] rounded-2xl p-3.5 text-xs shadow-2xs space-y-2 ${
                msg.role === "user"
                  ? "bg-ink-900 text-white rounded-tr-xs"
                  : "bg-white text-ink-800 border border-ink-200 rounded-tl-xs"
              }`}
            >
              <div className="prose prose-xs max-w-none text-xs leading-relaxed whitespace-pre-wrap">
                {msg.content}
              </div>

              {/* Improvements chips */}
              {msg.improvements && msg.improvements.length > 0 && (
                <div className="pt-2 border-t border-ink-100 space-y-1.5">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-ink-400 flex items-center gap-1">
                    <Lightbulb className="h-3 w-3 text-amber-500" /> Actionable Civil Mitigations
                  </p>
                  <div className="flex flex-col gap-1">
                    {msg.improvements.map((imp, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSend(`How do we implement: "${imp}"?`)}
                        className="text-left text-[11px] bg-ink-50 hover:bg-amber-50 hover:text-amber-900 border border-ink-200 hover:border-amber-300 px-2 py-1 rounded-md transition text-ink-700 flex items-center justify-between group"
                      >
                        <span className="truncate">{imp}</span>
                        <span className="text-[10px] text-ink-400 group-hover:text-amber-700 font-semibold ml-1">
                          Ask →
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between text-[10px] text-ink-400 pt-1">
                <span>{msg.role === "assistant" ? "Senior Civil PE" : "Engineer"}</span>
                <span>{msg.timestamp}</span>
              </div>
            </div>

            {msg.role === "user" && (
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-ink-800 text-white shrink-0 mt-0.5">
                <User className="h-4 w-4" />
              </div>
            )}
          </div>
        ))}

        {busy && (
          <div className="flex gap-2.5 items-start">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-100 text-amber-800 shrink-0 border border-amber-200 mt-0.5">
              <HardHat className="h-4 w-4 animate-bounce" />
            </div>
            <div className="rounded-2xl rounded-tl-xs p-3.5 bg-white border border-ink-200 text-xs text-ink-500 shadow-2xs flex items-center gap-2">
              <RefreshCw className="h-3.5 w-3.5 animate-spin text-signal-600" />
              <span>Analyzing civil geotechnics, substations, and code compliance…</span>
            </div>
          </div>
        )}

        <div ref={endRef} />
      </div>

      {/* Suggested Quick Prompts Carousel */}
      <div className="p-2 bg-ink-100/70 border-t border-ink-200 overflow-x-auto flex gap-1.5 no-scrollbar">
        {QUICK_PROMPTS.map((prompt, idx) => (
          <button
            key={idx}
            onClick={() => handleSend(prompt)}
            disabled={busy}
            className="text-[11px] whitespace-nowrap bg-white hover:bg-ink-50 text-ink-700 border border-ink-200 rounded-full px-2.5 py-1 font-medium shadow-2xs hover:border-signal-500 transition shrink-0"
          >
            {prompt}
          </button>
        ))}
      </div>

      {/* Chat Input Bar */}
      <div className="p-3 border-t border-ink-200 bg-white">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex gap-2"
        >
          <input
            type="text"
            placeholder="Ask about civil grading, soil capacity, 230kV substation, seismic PGA…"
            className={`${inputClass} text-xs py-2`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <Button
            type="submit"
            size="sm"
            variant="primary"
            disabled={!input.trim() || busy}
            className="px-3 bg-ink-900 hover:bg-signal-600 text-white rounded-lg shrink-0"
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        </form>
        <p className="text-[10px] text-ink-400 mt-1.5 text-center">
          Strict Domain: Hyperscale data center civil, structural, mechanical cooling &amp; substation engineering.
        </p>
      </div>
    </div>
  );
}
