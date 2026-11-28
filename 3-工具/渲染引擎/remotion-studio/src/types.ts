export interface QuoteCard {
  startSec: number;
  endSec: number;
  tag: string;
  line1: string;
  line2: string;
  accent?: "gold" | "cyan" | "coral";
}

export interface SubtitleLine {
  startSec: number;
  endSec: number;
  text: string;
  highlight?: string;
}

export type PackagingProps = {
  clipId: string;
  videoFile: string;
  durationSec: number;
  fps?: number;
  style?: "obsidian-gold" | "cyber-cyan" | "editorial-warm";
  badgeText?: string;
  titleLine1: string;
  titleLine2: string;
  subtitleEn: string;
  quoteCards: QuoteCard[];
  subtitles: SubtitleLine[];
};

export const DEFAULT_PROPS: PackagingProps = {
  clipId: "DEMO-01",
  videoFile: "",
  durationSec: 10,
  fps: 30,
  style: "obsidian-gold",
  badgeText: "核心干货",
  titleLine1: "写不出AI视频剧本？",
  titleLine2: "先别想【宏大故事】",
  subtitleEn: "START WITH A CORE VALUE",
  quoteCards: [
    {
      startSec: 0,
      endSec: 3.8,
      tag: "换个起点",
      line1: "好故事可以先从",
      line2: "【一个词】开始",
      accent: "gold",
    },
  ],
  subtitles: [
    {
      startSec: 0,
      endSec: 2.7,
      text: "它甚至只需要从一个词开始",
      highlight: "一个词",
    },
  ],
};
