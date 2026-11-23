#!/usr/bin/env python3
"""空库表结构。供 db.py init 使用。不含任何业务数据。"""

SCHEMA = """
CREATE TABLE sources (
  source_id TEXT PRIMARY KEY,      -- 如 课-20261119、直-20261119
  来源 TEXT NOT NULL,              -- 课程 / 直播 / 访谈 / 论坛 / ...(可扩展)
  日期 TEXT, 标题 TEXT, 时长 TEXT, 原片位置 TEXT, 本地文件夹 TEXT,
  摘要 TEXT, 评分 TEXT, 状态 TEXT, 备注 TEXT,
  扩展 TEXT,                       -- JSON:各来源特有的字段
  notion_page_id TEXT
);
CREATE TABLE clips (
  clip_id TEXT PRIMARY KEY,        -- 如 课-20261119-08
  来源 TEXT NOT NULL, source_id TEXT REFERENCES sources(source_id),
  原编号 TEXT,                     -- 旧系统里的编号,如 20261119-08(课程和直播会重号)
  标题 TEXT, 开头钩子 TEXT, 概要 TEXT, 理由 TEXT,
  起始 TEXT, 结束 TEXT, 原始时长_秒 REAL, 成片时长_秒 REAL,
  优先级 TEXT, 选题类型 TEXT, 钩子类型 TEXT, 时效性 TEXT,
  状态 TEXT,                       -- 候选/待剪/剪辑中/已剪辑(等看片)/已通过/放弃/需人工
  本地文件夹 TEXT, 备注 TEXT,
  扩展 TEXT, notion_page_id TEXT
);
CREATE TABLE publishes (
  publish_id TEXT PRIMARY KEY,     -- 如 课-20261119-08@抖音
  clip_id TEXT REFERENCES clips(clip_id), 来源 TEXT NOT NULL,
  平台 TEXT NOT NULL, 状态 TEXT,   -- 草稿/待发布/已定时/已发布/已撤回/需人工
  标题 TEXT, 简介 TEXT, 标签 TEXT, 封面 TEXT,
  候选标题 TEXT,                   -- JSON 数组
  推荐 TEXT, 选用 TEXT, 标题句式 TEXT, 封面类型 TEXT, 文案标准版本 TEXT,
  发布时间 TEXT, 作品链接 TEXT,
  评论摘要 TEXT, 复盘结论 TEXT, 备注 TEXT,
  扩展 TEXT, notion_page_id TEXT
);
CREATE TABLE metrics (
  publish_id TEXT REFERENCES publishes(publish_id),
  时间档 TEXT,                     -- 24h / 72h / 7d / 未标注
  播放 REAL, 完播率 REAL, 平均播放时长 REAL, 点赞 REAL, 评论 REAL, 收藏 REAL, 转发 REAL, 涨粉 REAL,
  采集时间 TEXT,
  PRIMARY KEY (publish_id, 时间档)
);
CREATE VIEW v_performance AS
SELECT p.publish_id, p.来源, p.平台, p.状态, p.标题, p.标题句式, p.封面类型, p.发布时间, p.作品链接,
       c.clip_id, c.选题类型, c.钩子类型, c.成片时长_秒,
       m.时间档, m.播放, m.完播率, m.平均播放时长, m.点赞, m.评论, m.收藏, m.转发, m.涨粉
FROM publishes p
LEFT JOIN clips c ON c.clip_id = p.clip_id
LEFT JOIN metrics m ON m.publish_id = p.publish_id;
"""
