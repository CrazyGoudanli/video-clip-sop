import { useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";

// Persistent 9:16 packaging: dark top/bottom panels,
// (no issue number / date — avoids breaking account rhythm) big white title with 【gold】 key part, spaced English subtitle line.
// The video window (between winTop and winBottom) stays transparent.
const FONT = '"Noto Sans SC", sans-serif';
const GOLD = "#E9B949";
function rich(text, goldColor) {
  const parts = String(text || "").split(/(【[^】]*】)/g).filter(Boolean);
  return parts.map((p, i) =>
    p.startsWith("【") ? <span key={i} style={{ color: goldColor }}>{p.slice(1, -1)}</span> : <span key={i}>{p}</span>
  );
}
export default function Packaging({ item }) {
  const p = (item && item.props) || {};
  const title = p.title ?? "联想那么贵\n为什么【还有人买】";
  const english = p.english ?? "WHY PEOPLE STILL BUY LENOVO";
  const winTop = Number(p.winTop ?? 600);
  const winBottom = Number(p.winBottom ?? 1268);
  const gold = p.accentColor ?? GOLD;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const ease = Easing.out(Easing.cubic);
  const k = (a, b) => interpolate(t, [a, b], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const titleIn = k(0.1, 0.55), enIn = k(0.3, 0.75), lineIn = k(0.2, 0.9);
  const lines = String(title).split("\n");
  return (
    <div style={{ position: "absolute", inset: 0, background: "transparent" }}>
      {/* top panel */}
      <div style={{ position: "absolute", left: 0, top: 0, width: 1080, height: winTop,
        background: "linear-gradient(180deg, #08080B 0%, #0E0E13 70%, #15151B 100%)" }} />
      {/* bottom panel */}
      <div style={{ position: "absolute", left: 0, top: winBottom, width: 1080, height: 1920 - winBottom,
        background: "linear-gradient(180deg, #15151B 0%, #0E0E13 35%, #08080B 100%)" }} />
      {/* gold hairlines framing the video */}
      <div style={{ position: "absolute", left: 540 - 500 * lineIn, top: winTop - 3, width: 1000 * lineIn, height: 3,
        background: `linear-gradient(90deg, rgba(233,185,73,0) 0%, ${gold} 50%, rgba(233,185,73,0) 100%)` }} />
      <div style={{ position: "absolute", left: 540 - 500 * lineIn, top: winBottom, width: 1000 * lineIn, height: 3,
        background: `linear-gradient(90deg, rgba(233,185,73,0) 0%, ${gold} 50%, rgba(233,185,73,0) 100%)` }} />
      {/* title */}
      <div style={{ position: "absolute", left: 50, top: 60, width: 980, height: winTop - 60 - 30,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 22 }}>
        <div style={{ opacity: titleIn, transform: `translateY(${(1 - titleIn) * 24}px)`, display: "flex", flexDirection: "column", alignItems: "center" }}>
          {lines.map((ln, i) => (
            <div key={i} style={{ fontFamily: FONT, fontWeight: 900, fontSize: 96, lineHeight: 1.18, color: "#FFFFFF",
              textAlign: "center", letterSpacing: "0.02em", whiteSpace: "nowrap",
              textShadow: "0 6px 24px rgba(0,0,0,0.6)" }}>{rich(ln, gold)}</div>
          ))}
        </div>
        <div style={{ opacity: enIn * 0.85, fontFamily: '"Montserrat", "Noto Sans SC", sans-serif', fontWeight: 600, fontSize: 26,
          letterSpacing: "0.32em", color: "rgba(255,255,255,0.7)", textTransform: "uppercase", textAlign: "center", whiteSpace: "nowrap" }}>{english}</div>
      </div>
    </div>
  );
}
