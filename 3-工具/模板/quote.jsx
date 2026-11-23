import { useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";

// Mid-screen key-quote card: small white lead-in line + big two-line bold text,
// 【key words】 rendered in gold/amber. Sits in the band under the video window.
const FONT = '"Noto Sans SC", sans-serif';
function rich(text, gold) {
  const parts = String(text || "").split(/(【[^】]*】)/g).filter(Boolean);
  return parts.map((p, i) =>
    p.startsWith("【") ? <span key={i} style={{ color: gold }}>{p.slice(1, -1)}</span> : <span key={i}>{p}</span>
  );
}
export default function Quote({ item }) {
  const p = (item && item.props) || {};
  const lead = p.lead ?? "划重点";
  const main = p.main ?? "最大的区别不是性能\n而是【稳定性】";
  const top = Number(p.top ?? 1300);
  const gold = p.accentColor ?? "#F2B33D";
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = frame / fps, dur = durationInFrames / fps;
  const ease = Easing.out(Easing.back(1.4));
  const inP = interpolate(t, [0, 0.35], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const fadeIn = interpolate(t, [0, 0.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const out = interpolate(t, [dur - 0.25, dur], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const leadIn = interpolate(t, [0.05, 0.4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const lines = String(main).split("\n");
  const size = lines.some(l => Array.from(l.replace(/[【】]/g, "")).length > 9) ? 76 : 88;
  return (
    <div style={{ position: "absolute", inset: 0, background: "transparent", opacity: out }}>
      <div style={{ position: "absolute", left: 60, top, width: 960, display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, opacity: leadIn }}>
          <div style={{ width: 46, height: 3, background: gold, opacity: 0.85 }} />
          <div style={{ fontFamily: FONT, fontWeight: 600, fontSize: 34, color: "rgba(255,255,255,0.9)", letterSpacing: "0.12em" }}>{lead}</div>
          <div style={{ width: 46, height: 3, background: gold, opacity: 0.85 }} />
        </div>
        <div style={{ opacity: fadeIn, transform: `scale(${0.86 + 0.14 * inP})`, display: "flex", flexDirection: "column", alignItems: "center" }}>
          {lines.map((ln, i) => (
            <div key={i} style={{ fontFamily: FONT, fontWeight: 900, fontSize: size, lineHeight: 1.2, color: "#FFFFFF", textAlign: "center",
              whiteSpace: "nowrap", letterSpacing: "0.02em", textShadow: "0 4px 18px rgba(0,0,0,0.65)" }}>{rich(ln, gold)}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
