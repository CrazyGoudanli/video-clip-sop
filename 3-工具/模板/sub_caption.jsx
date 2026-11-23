// Bottom subtitle: one line, white, soft shadow; manually emphasized keywords in gold.
const OUT = "0 0 2px rgba(0,0,0,0.9), 0 3px 10px rgba(0,0,0,0.75)";
export default function SubCaption({ item }) {
  let cap = null;
  try { cap = typeof useSpecialEffects === "function" ? useSpecialEffects().caption_v1 : null; } catch (e) { cap = null; }
  let words = [], text = "";
  if (cap && cap.content) { words = (cap.content.words || []).filter(w => w.visible !== false); text = cap.content.text || ""; }
  else if (item && item.props && item.props.caption) { const c = item.props.caption; words = (c.words || []).filter(w => w.visible !== false); text = c.visibleText || c.text || ""; }
  if (!words.length && text) words = [{ text }];
  // strip trailing sentence punctuation for a cleaner subtitle look
  const clean = words.map((w, i) => ({ ...w, text: i === words.length - 1 ? String(w.text || "").replace(/[，。,.、；;：:]+$/, "") : String(w.text || "").replace(/[，。]/g, " ") }));
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ fontFamily: '"Noto Sans SC", sans-serif', fontSize: 56, fontWeight: 700, lineHeight: 1.2, whiteSpace: "pre", color: "#FFFFFF", textShadow: OUT, textAlign: "center", letterSpacing: "0.02em" }}>
        {clean.map((w, i) => {
          const emph = w.emphasis === true && w.emphasisSource === "manual";
          return <span key={i} style={emph ? { color: "#F2B33D", fontWeight: 900 } : null}>{w.text}</span>;
        })}
      </div>
    </div>
  );
}
