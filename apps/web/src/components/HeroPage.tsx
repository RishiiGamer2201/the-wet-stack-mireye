import {
  ArrowRight,
  Building2,
  CheckCircle2,
  HardHat,
  Layers,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";

import { Badge, Button } from "./ui";

interface HeroPageProps {
  onStart: () => void;
}

export function HeroPage({ onStart }: HeroPageProps) {
  return (
    <div className="min-h-screen bg-ink-50 text-ink-900 flex flex-col justify-between">
      {/* Subtle geometric ambient lighting */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[45rem] h-[30rem] bg-signal-500/10 rounded-full blur-[140px]" />
        <div className="absolute top-1/3 -left-40 w-96 h-96 bg-sky-500/5 rounded-full blur-[120px]" />
        <div className="absolute bottom-10 -right-40 w-96 h-96 bg-amber-500/5 rounded-full blur-[120px]" />
      </div>

      {/* Main Hero Container */}
      <main className="relative z-10 max-w-6xl mx-auto px-6 py-16 sm:py-24 flex-1 flex flex-col items-center justify-center text-center space-y-10">
        {/* Top Tag Badge */}
        <div className="inline-flex items-center gap-2 rounded-full border border-signal-500/30 bg-signal-500/10 px-4 py-1.5 text-xs font-semibold text-signal-600 shadow-xs">
          <Sparkles className="h-3.5 w-3.5 text-signal-600" />
          <span>Next-Generation EPC Intelligence Platform</span>
        </div>

        {/* Hero Title */}
        <div className="space-y-3 max-w-4xl">
          <h1 className="text-4xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight text-ink-900 leading-tight">
            The Wet Stack{" "}
            <span className="text-signal-600 font-extrabold">
              - Mireye
            </span>
          </h1>
          <p className="text-lg sm:text-xl text-ink-600 font-medium tracking-wide">
            Data-Center Construction &amp; EPC Intelligence
          </p>
        </div>

        {/* Short Platform Description */}
        <p className="text-sm sm:text-base text-ink-600 max-w-2xl mx-auto leading-relaxed">
          An engineering decision engine connecting physical-world geospatial telemetry from
          Mireye with deterministic mathematical gates, multi-dimensional candidate site scoring,
          and in-flight equipment substitution impact tracing.
        </p>

        {/* Primary Call to Action Button */}
        <div className="pt-2 flex flex-col sm:flex-row items-center gap-4">
          <Button
            onClick={onStart}
            size="md"
            variant="primary"
            className="px-8 py-3.5 text-base font-bold bg-ink-900 hover:bg-signal-600 text-white rounded-xl shadow-md transition-all scale-100 hover:scale-105"
          >
            Get Started &amp; Create Project
            <ArrowRight className="h-5 w-5 ml-2" />
          </Button>
        </div>

        {/* Dual Core Workflows Cards Preview */}
        <div className="grid md:grid-cols-2 gap-6 w-full text-left pt-6">
          {/* Phase 1: Before Construction */}
          <div className="relative group rounded-2xl border border-ink-200 bg-white p-7 shadow-xs hover:shadow-md hover:border-signal-500/60 transition-all">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-sky-50 text-sky-600 border border-sky-200">
                  <Building2 className="h-5 w-5" />
                </div>
                <Badge className="border-sky-300 bg-sky-50 text-sky-800 font-semibold text-xs px-2.5 py-0.5">
                  Phase 1 · Site Selection
                </Badge>
              </div>

              <div>
                <h2 className="text-xl font-bold text-ink-900 group-hover:text-signal-600 transition-colors">
                  Before Construction
                </h2>
                <p className="text-xs text-ink-500 mt-1 font-medium">
                  Site Screening, Decision Gates &amp; Business Cost
                </p>
              </div>

              <p className="text-xs text-ink-600 leading-relaxed">
                Compare candidate locations with Mireye context, while keeping deliverable power
                and government approval as explicit authority-confirmed gates.
              </p>

              <ul className="space-y-2 pt-2 text-xs text-ink-700 border-t border-ink-100">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 shrink-0" />
                  <span>8-Dimensional Site Scoring (Power, Water, Climate, Seismic)</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 shrink-0" />
                  <span>Interactive Geospatial Leaflet Map with candidate coordinates</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 shrink-0" />
                  <span>What-If weight tuning &amp; traceable user-confirmed evidence</span>
                </li>
              </ul>
            </div>
          </div>

          {/* Phase 2: During Construction */}
          <div className="relative group rounded-2xl border border-ink-200 bg-white p-7 shadow-xs hover:shadow-md hover:border-signal-500/60 transition-all">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-50 text-amber-600 border border-amber-200">
                  <HardHat className="h-5 w-5" />
                </div>
                <Badge className="border-amber-300 bg-amber-50 text-amber-800 font-semibold text-xs px-2.5 py-0.5">
                  Phase 2 · Execution &amp; EPC
                </Badge>
              </div>

              <div>
                <h2 className="text-xl font-bold text-ink-900 group-hover:text-signal-600 transition-colors">
                  During Construction
                </h2>
                <p className="text-xs text-ink-500 mt-1 font-medium">
                  Change Intelligence &amp; Impact Graphs
                </p>
              </div>

              <p className="text-xs text-ink-600 leading-relaxed">
                Verify equipment submittals, compute deterministic physical and electrical deltas
                with Pint dimensional analysis, and trace downstream impacts across 6 disciplines.
              </p>

              <ul className="space-y-2 pt-2 text-xs text-ink-700 border-t border-ink-100">
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 shrink-0" />
                  <span>9 Verification Gates (Model comparability, weight basis, MCA/MOCP)</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 shrink-0" />
                  <span>13 Engineering Deltas &amp; multi-discipline impact propagation</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-signal-500 shrink-0" />
                  <span>3-Tier Decision Engine with automated RFI drafting</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Feature Badges Footer */}
        <div className="flex flex-wrap items-center justify-center gap-4 text-xs text-ink-500 pt-4">
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="h-4 w-4 text-signal-600" />
            <span>Deterministic Tested Python</span>
          </div>
          <span>•</span>
          <div className="flex items-center gap-1.5">
            <Layers className="h-4 w-4 text-sky-600" />
            <span>SQLite Local Persistence</span>
          </div>
          <span>•</span>
          <div className="flex items-center gap-1.5">
            <Zap className="h-4 w-4 text-amber-600" />
            <span>Deterministic Context Scoring</span>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-ink-200 bg-white py-4 px-6 text-center text-xs text-ink-500">
        <p>The Wet Stack - Mireye · Data-Center Construction &amp; EPC Intelligence</p>
      </footer>
    </div>
  );
}
