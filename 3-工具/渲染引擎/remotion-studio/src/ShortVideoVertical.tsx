import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { PackagingProps, QuoteCard, SubtitleLine } from "./types";

const FONT_STACK =
  '"PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, sans-serif';

const THEMES = {
  "obsidian-gold": {
    bgTop: "#090D16",
    bgBottom: "#04060B",
    orbA: "rgba(245, 158, 11, 0.22)",
    orbB: "rgba(56, 189, 248, 0.14)",
    accent: "#FBBF24",
    accentSoft: "rgba(251, 191, 36, 0.16)",
    accentBorder: "rgba(251, 191, 36, 0.38)",
    accentGrad: "linear-gradient(95deg, #FEF3C7 0%, #FBBF24 45%, #F59E0B 100%)",
    progressGrad: "linear-gradient(90deg, #38BDF8 0%, #FBBF24 65%, #FEF08A 100%)",
  },
  "cyber-cyan": {
    bgTop: "#06101D",
    bgBottom: "#03060C",
    orbA: "rgba(56, 189, 248, 0.24)",
    orbB: "rgba(129, 140, 248, 0.18)",
    accent: "#38BDF8",
    accentSoft: "rgba(56, 189, 248, 0.16)",
    accentBorder: "rgba(56, 189, 248, 0.42)",
    accentGrad: "linear-gradient(95deg, #E0F2FE 0%, #38BDF8 50%, #818CF8 100%)",
    progressGrad: "linear-gradient(90deg, #38BDF8 0%, #818CF8 100%)",
  },
  "editorial-warm": {
    bgTop: "#130F0C",
    bgBottom: "#070606",
    orbA: "rgba(251, 146, 60, 0.20)",
    orbB: "rgba(250, 204, 21, 0.12)",
    accent: "#FB923C",
    accentSoft: "rgba(251, 146, 60, 0.16)",
    accentBorder: "rgba(251, 146, 60, 0.38)",
    accentGrad: "linear-gradient(95deg, #FFEDD5 0%, #FB923C 55%, #F97316 100%)",
    progressGrad: "linear-gradient(90deg, #FB923C 0%, #FACC15 100%)",
  },
} as const;

const CARD_ACCENTS = {
  gold: {
    color: "#FCD34D",
    soft: "rgba(251, 191, 36, 0.16)",
    border: "rgba(251, 191, 36, 0.36)",
    bar: "linear-gradient(90deg, transparent, #FBBF24, transparent)",
  },
  cyan: {
    color: "#7DD3FC",
    soft: "rgba(56, 189, 248, 0.16)",
    border: "rgba(56, 189, 248, 0.38)",
    bar: "linear-gradient(90deg, transparent, #38BDF8, transparent)",
  },
  coral: {
    color: "#FCA5A5",
    soft: "rgba(248, 113, 113, 0.16)",
    border: "rgba(248, 113, 113, 0.38)",
    bar: "linear-gradient(90deg, transparent, #F87171, transparent)",
  },
} as const;

function renderBracketHighlight(
  text: string,
  highlightStyle: React.CSSProperties
): React.ReactNode {
  const parts = text.split(/(【[^】]+】)/g);
  return parts.map((part, idx) => {
    if (part.startsWith("【") && part.endsWith("】")) {
      const clean = part.slice(1, -1);
      return (
        <span key={idx} style={highlightStyle}>
          {clean}
        </span>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

const AmbientBackdrop: React.FC<{
  frame: number;
  theme: (typeof THEMES)[keyof typeof THEMES];
}> = ({ frame, theme }) => {
  const driftX = Math.sin(frame / 90) * 45;
  const driftY = Math.cos(frame / 110) * 32;

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${theme.bgTop} 0%, ${theme.bgBottom} 55%, ${theme.bgTop} 100%)`,
        overflow: "hidden",
      }}
    >
      {/* Subtle architectural dot matrix */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(rgba(255,255,255,0.06) 1.5px, transparent 1.5px)",
          backgroundSize: "36px 36px",
          opacity: 0.45,
        }}
      />
      {/* Top ambient aura */}
      <div
        style={{
          position: "absolute",
          top: -140 + driftY,
          left: 140 + driftX,
          width: 800,
          height: 620,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${theme.orbA} 0%, transparent 68%)`,
          filter: "blur(40px)",
        }}
      />
      {/* Bottom ambient aura */}
      <div
        style={{
          position: "absolute",
          bottom: -120 - driftY,
          right: 60 - driftX,
          width: 780,
          height: 640,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${theme.orbB} 0%, transparent 70%)`,
          filter: "blur(45px)",
        }}
      />
    </AbsoluteFill>
  );
};

const TitleHeader: React.FC<{
  frame: number;
  fps: number;
  badgeText?: string;
  line1: string;
  line2: string;
  subtitleEn: string;
  theme: (typeof THEMES)[keyof typeof THEMES];
}> = ({ frame, fps, badgeText, line1, line2, subtitleEn, theme }) => {
  const enter = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120, mass: 0.9 },
  });
  const translateY = interpolate(enter, [0, 1], [-36, 0]);
  const opacity = interpolate(enter, [0, 0.7], [0, 1], {
    extrapolateRight: "clamp",
  });
  const dividerW = interpolate(enter, [0, 1], [24, 168]);
  // Periodic soft shimmer pulse on golden accent every ~6s
  const pulse = 0.85 + 0.15 * Math.sin(frame / 28);

  const goldSpanStyle: React.CSSProperties = {
    backgroundImage: theme.accentGrad,
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
    filter: `drop-shadow(0 0 18px ${theme.orbA})`,
    opacity: pulse,
  };

  return (
    <div
      style={{
        position: "absolute",
        top: 132,
        left: 64,
        right: 64,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        textAlign: "center",
        transform: `translateY(${translateY}px)`,
        opacity,
        fontFamily: FONT_STACK,
      }}
    >
      {badgeText ? (
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            padding: "8px 22px",
            borderRadius: 999,
            background: theme.accentSoft,
            border: `1.5px solid ${theme.accentBorder}`,
            color: theme.accent,
            fontSize: 24,
            fontWeight: 600,
            letterSpacing: "0.08em",
            marginBottom: 24,
          }}
        >
          <span
            style={{
              width: 9,
              height: 9,
              borderRadius: "50%",
              background: theme.accent,
              boxShadow: `0 0 12px ${theme.accent}`,
            }}
          />
          <span>{badgeText}</span>
        </div>
      ) : null}

      <div
        style={{
          fontSize: 70,
          fontWeight: 800,
          lineHeight: 1.24,
          letterSpacing: "-0.015em",
          color: "#F8FAFC",
          textShadow: "0 8px 32px rgba(0,0,0,0.65)",
        }}
      >
        {renderBracketHighlight(line1, goldSpanStyle)}
      </div>

      <div
        style={{
          fontSize: 76,
          fontWeight: 900,
          lineHeight: 1.24,
          letterSpacing: "-0.01em",
          color: "#FFFFFF",
          marginTop: 6,
          textShadow: "0 10px 36px rgba(0,0,0,0.7)",
        }}
      >
        {renderBracketHighlight(line2, goldSpanStyle)}
      </div>

      <div
        style={{
          marginTop: 22,
          display: "flex",
          alignItems: "center",
          gap: 18,
        }}
      >
        <div
          style={{
            width: dividerW * 0.45,
            height: 2,
            background: `linear-gradient(90deg, transparent, ${theme.accent})`,
            borderRadius: 2,
          }}
        />
        <span
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "0.24em",
            color: "rgba(226, 232, 240, 0.56)",
            textTransform: "uppercase",
          }}
        >
          {subtitleEn}
        </span>
        <div
          style={{
            width: dividerW * 0.45,
            height: 2,
            background: `linear-gradient(90deg, ${theme.accent}, transparent)`,
            borderRadius: 2,
          }}
        />
      </div>
    </div>
  );
};

const QuoteCardOverlay: React.FC<{
  cards: QuoteCard[];
  currentSec: number;
  frame: number;
  fps: number;
}> = ({ cards, currentSec, frame, fps }) => {
  const activeIdx = cards.findIndex(
    (c) => currentSec >= c.startSec && currentSec <= c.endSec
  );
  if (activeIdx < 0) return null;
  const card = cards[activeIdx];
  const startFrame = Math.round(card.startSec * fps);
  const endFrame = Math.round(card.endSec * fps);
  const localFrame = Math.max(0, frame - startFrame);
  const framesLeft = Math.max(0, endFrame - frame);

  const pop = spring({
    frame: localFrame,
    fps,
    config: { damping: 14, stiffness: 170, mass: 0.8 },
  });
  const exitOpacity = interpolate(framesLeft, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const enterOpacity = interpolate(localFrame, [0, 6], [0, 1], {
    extrapolateRight: "clamp",
  });
  const opacity = Math.min(enterOpacity, exitOpacity);
  const translateY = interpolate(pop, [0, 1], [34, 0]);
  const scale = interpolate(pop, [0, 1], [0.94, 1]);

  const palette = CARD_ACCENTS[card.accent || "gold"];
  const highlightStyle: React.CSSProperties = {
    color: palette.color,
    textShadow: `0 0 24px ${palette.soft}`,
  };

  return (
    <div
      style={{
        position: "absolute",
        top: 1272,
        left: 72,
        right: 72,
        display: "flex",
        justifyContent: "center",
        fontFamily: FONT_STACK,
        opacity,
        transform: `translateY(${translateY}px) scale(${scale})`,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 920,
          position: "relative",
          borderRadius: 28,
          padding: "28px 40px 30px",
          background:
            "linear-gradient(155deg, rgba(18, 24, 38, 0.92) 0%, rgba(10, 14, 23, 0.94) 100%)",
          border: `1.5px solid ${palette.border}`,
          boxShadow:
            "0 24px 60px rgba(0, 0, 0, 0.58), inset 0 1px 0 rgba(255, 255, 255, 0.1)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          overflow: "hidden",
        }}
      >
        {/* Top shimmer accent line */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: "12%",
            right: "12%",
            height: 3,
            background: palette.bar,
          }}
        />

        {/* Eyebrow tag + step indicator */}
        <div
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 14,
          }}
        >
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "5px 16px",
              borderRadius: 999,
              background: palette.soft,
              border: `1px solid ${palette.border}`,
              color: palette.color,
              fontSize: 24,
              fontWeight: 700,
              letterSpacing: "0.06em",
            }}
          >
            <span>{card.tag}</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            {cards.map((_, i) => (
              <div
                key={i}
                style={{
                  width: i === activeIdx ? 22 : 7,
                  height: 7,
                  borderRadius: 99,
                  background:
                    i === activeIdx
                      ? palette.color
                      : "rgba(255, 255, 255, 0.22)",
                }}
              />
            ))}
          </div>
        </div>

        <div
          style={{
            fontSize: 48,
            fontWeight: 700,
            lineHeight: 1.32,
            color: "#E2E8F0",
          }}
        >
          {renderBracketHighlight(card.line1, highlightStyle)}
        </div>
        <div
          style={{
            fontSize: 56,
            fontWeight: 900,
            lineHeight: 1.28,
            color: "#FFFFFF",
            marginTop: 4,
          }}
        >
          {renderBracketHighlight(card.line2, highlightStyle)}
        </div>
      </div>
    </div>
  );
};

const KineticSubtitle: React.FC<{
  subtitles: SubtitleLine[];
  currentSec: number;
  frame: number;
  fps: number;
  theme: (typeof THEMES)[keyof typeof THEMES];
}> = ({ subtitles, currentSec, frame, fps, theme }) => {
  const active = subtitles.find(
    (s) => currentSec >= s.startSec && currentSec <= s.endSec
  );
  if (!active) return null;

  const startFrame = Math.round(active.startSec * fps);
  const localFrame = Math.max(0, frame - startFrame);
  const durSec = Math.max(0.15, active.endSec - active.startSec);
  const progress = Math.min(1, Math.max(0, (currentSec - active.startSec) / durSec));

  const pop = spring({
    frame: localFrame,
    fps,
    config: { damping: 18, stiffness: 260, mass: 0.5 },
  });
  const scale = interpolate(pop, [0, 1], [0.92, 1]);
  const translateY = interpolate(pop, [0, 1], [12, 0]);

  const chars = Array.from(active.text);
  const activeCharIdx = Math.floor(progress * chars.length);

  // Determine keyword character range if highlight is specified
  let hlStart = -1;
  let hlEnd = -1;
  if (active.highlight) {
    const idx = active.text.indexOf(active.highlight);
    if (idx >= 0) {
      hlStart = Array.from(active.text.slice(0, idx)).length;
      hlEnd = hlStart + Array.from(active.highlight).length;
    }
  }

  return (
    <div
      style={{
        position: "absolute",
        top: 1624,
        left: 52,
        right: 52,
        display: "flex",
        justifyContent: "center",
        fontFamily: FONT_STACK,
        transform: `translateY(${translateY}px) scale(${scale})`,
      }}
    >
      <div
        style={{
          maxWidth: 976,
          padding: "16px 32px",
          borderRadius: 18,
          background: "rgba(6, 9, 16, 0.82)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          boxShadow: "0 12px 32px rgba(0, 0, 0, 0.55)",
          textAlign: "center",
          fontSize: 48,
          fontWeight: 800,
          lineHeight: 1.3,
          letterSpacing: "0.02em",
          whiteSpace: "nowrap",
        }}
      >
        {chars.map((ch, idx) => {
          const isKeyword = idx >= hlStart && idx < hlEnd;
          const isSpoken = idx <= activeCharIdx;
          const color = isKeyword
            ? theme.accent
            : isSpoken
            ? "#FFFFFF"
            : "rgba(226, 232, 240, 0.52)";
          return (
            <span
              key={idx}
              style={{
                color,
                textShadow: isKeyword
                  ? `0 0 16px ${theme.orbA}, 0 3px 10px rgba(0,0,0,0.85)`
                  : "0 3px 10px rgba(0,0,0,0.85)",
              }}
            >
              {ch}
            </span>
          );
        })}
      </div>
    </div>
  );
};

export const ShortVideoVertical: React.FC<PackagingProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const currentSec = frame / fps;
  const totalProgress = Math.min(1, frame / Math.max(1, durationInFrames - 1));
  const theme = THEMES[props.style || "obsidian-gold"];

  // Subtle keynote breathing zoom on the speaker viewport (1.0 -> 1.035)
  const gentleZoom = 1 + 0.03 * Math.sin((frame / Math.max(1, durationInFrames)) * Math.PI);
  const frameEnter = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const frameScale = interpolate(frameEnter, [0, 1], [0.96, 1]);

  return (
    <AbsoluteFill style={{ backgroundColor: "#04060B" }}>
      <AmbientBackdrop frame={frame} theme={theme} />

      {/* Top Animated Title Header */}
      <TitleHeader
        frame={frame}
        fps={fps}
        badgeText={props.badgeText}
        line1={props.titleLine1}
        line2={props.titleLine2}
        subtitleEn={props.subtitleEn}
        theme={theme}
      />

      {/* Center 16:9 Speaker Viewport with Glass Frame + Progress Bar */}
      <div
        style={{
          position: "absolute",
          top: 572,
          left: 28,
          width: 1024,
          height: 576,
          borderRadius: 28,
          overflow: "hidden",
          border: "1.5px solid rgba(255, 255, 255, 0.16)",
          boxShadow: `0 28px 72px rgba(0, 0, 0, 0.72), 0 0 42px ${theme.orbA}`,
          backgroundColor: "#000000",
          transform: `scale(${frameScale})`,
        }}
      >
        {props.videoFile ? (
          <OffthreadVideo
            src={
              props.videoFile.startsWith("http://") ||
              props.videoFile.startsWith("https://")
                ? props.videoFile
                : staticFile(props.videoFile)
            }
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              transform: `scale(${gentleZoom})`,
            }}
          />
        ) : null}

        {/* Bottom subtle gradient inside video edge */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            height: 44,
            background: "linear-gradient(180deg, transparent, rgba(0,0,0,0.55))",
          }}
        />

        {/* Retention Progress Bar */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            height: 6,
            background: "rgba(255, 255, 255, 0.16)",
          }}
        >
          <div
            style={{
              width: `${totalProgress * 100}%`,
              height: "100%",
              background: theme.progressGrad,
              boxShadow: `0 0 14px ${theme.accent}`,
            }}
          />
        </div>
      </div>

      {/* Animated Spring Quote Cards */}
      <QuoteCardOverlay
        cards={props.quoteCards}
        currentSec={currentSec}
        frame={frame}
        fps={fps}
      />

      {/* Progressive Highlight Subtitles */}
      <KineticSubtitle
        subtitles={props.subtitles}
        currentSec={currentSec}
        frame={frame}
        fps={fps}
        theme={theme}
      />
    </AbsoluteFill>
  );
};
