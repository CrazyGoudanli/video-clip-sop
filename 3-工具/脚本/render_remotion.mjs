#!/usr/bin/env node
/**
 * Remotion 竖屏动效包装一键渲染器 (video-clip-sop)
 *
 * 用法:
 *   node 3-工具/脚本/render_remotion.mjs \
 *     --video 工作区/<素材ID>/剪辑/01/cut.mp4 \
 *     --props 工作区/<素材ID>/剪辑/01/packaging.json \
 *     --out 成片/<ID>_<标题>/<ID>_<标题>.mp4 \
 *     [--clip-id 课-20261127-01] \
 *     [--frames-out 工作区/<素材ID>/剪辑/01/六帧自检_remotion.png]
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

function runAsync(bin, args, opts) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, opts);
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${bin} exited with code ${code}`));
    });
  });
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../..");
const STUDIO_DIR = path.join(ROOT, "3-工具", "渲染引擎", "remotion-studio");

function startVideoServer(videoAbs) {
  const stat = fs.statSync(videoAbs);
  const size = stat.size;
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const range = req.headers.range;
      res.setHeader("Accept-Ranges", "bytes");
      res.setHeader("Content-Type", "video/mp4");
      res.setHeader("Access-Control-Allow-Origin", "*");
      if (range) {
        const m = /^bytes=(\d*)-(\d*)$/.exec(range);
        const start = m && m[1] ? parseInt(m[1], 10) : 0;
        const end = m && m[2] ? Math.min(size - 1, parseInt(m[2], 10)) : size - 1;
        res.writeHead(206, {
          "Content-Range": `bytes ${start}-${end}/${size}`,
          "Content-Length": end - start + 1,
        });
        if (req.method === "HEAD") return res.end();
        fs.createReadStream(videoAbs, { start, end }).pipe(res);
      } else {
        res.writeHead(200, { "Content-Length": size });
        if (req.method === "HEAD") return res.end();
        fs.createReadStream(videoAbs).pipe(res);
      }
    });
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolve({ server, url: `http://127.0.0.1:${addr.port}/source.mp4` });
    });
  });
}

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      out[a.slice(2)] = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : true;
    }
  }
  return out;
}

function probeDuration(videoPath) {
  const raw = execFileSync(
    "ffprobe",
    ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", videoPath],
    { encoding: "utf8" }
  ).trim();
  const d = parseFloat(raw);
  if (!Number.isFinite(d) || d <= 0) {
    throw new Error(`无法读取视频时长: ${videoPath}`);
  }
  return d;
}

function findChrome() {
  const candidates = [
    process.env.REMOTION_CHROME_EXECUTABLE,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  ].filter(Boolean);
  return candidates.find((p) => fs.existsSync(p)) || null;
}

function makeSixFrameSheet(mp4Path, sheetPath, dur) {
  const stamps = [0.6, dur * 0.18, dur * 0.36, dur * 0.56, dur * 0.78, Math.max(0.5, dur - 0.8)];
  const tmpDir = fs.mkdtempSync("/tmp/remotion-frames-");
  try {
    const imgs = [];
    stamps.forEach((t, idx) => {
      const f = path.join(tmpDir, `f${idx}.jpg`);
      execFileSync(
        "ffmpeg",
        ["-nostdin", "-v", "error", "-ss", t.toFixed(2), "-i", mp4Path, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "2", "-y", f],
        { stdio: "inherit" }
      );
      imgs.push(f);
    });
    fs.mkdirSync(path.dirname(sheetPath), { recursive: true });
    execFileSync(
      "ffmpeg",
      [
        "-nostdin",
        "-v",
        "error",
        ...imgs.flatMap((f) => ["-i", f]),
        "-filter_complex",
        "[0:v][1:v][2:v]hstack=inputs=3[top];[3:v][4:v][5:v]hstack=inputs=3[bot];[top][bot]vstack=inputs=2",
        "-y",
        sheetPath,
      ],
      { stdio: "inherit" }
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.video || !args.props || !args.out) {
    console.error("用法: node 3-工具/脚本/render_remotion.mjs --video <cut.mp4> --props <packaging.json> --out <out.mp4> [--clip-id ID] [--frames-out sheet.png]");
    process.exit(1);
  }

  const videoAbs = path.resolve(ROOT, args.video);
  const propsAbs = path.resolve(ROOT, args.props);
  const outAbs = path.resolve(ROOT, args.out);
  if (!fs.existsSync(videoAbs)) throw new Error(`找不到源视频: ${videoAbs}`);
  if (!fs.existsSync(propsAbs)) throw new Error(`找不到包装参数: ${propsAbs}`);
  if (!fs.existsSync(path.join(STUDIO_DIR, "node_modules", "remotion"))) {
    throw new Error(`Remotion 依赖未安装，请先运行: npm --prefix "${STUDIO_DIR}" install`);
  }

  const rawProps = JSON.parse(fs.readFileSync(propsAbs, "utf8"));
  const durationSec = Number(rawProps.durationSec) || probeDuration(videoAbs);
  const clipId = args["clip-id"] || rawProps.clipId || "";

  fs.mkdirSync(path.dirname(outAbs), { recursive: true });

  const { server, url: videoUrl } = await startVideoServer(videoAbs);
  const tmpProps = path.join("/tmp", `remotion_props_${Date.now()}.json`);
  const tmpRawOut = path.join("/tmp", `remotion_raw_${Date.now()}.mp4`);

  const mergedProps = {
    ...rawProps,
    clipId,
    videoFile: videoUrl,
    durationSec,
    fps: rawProps.fps || 30,
  };
  fs.writeFileSync(tmpProps, JSON.stringify(mergedProps, null, 2));

  try {
    const remotionBin = path.join(STUDIO_DIR, "node_modules", ".bin", "remotion");
    const chrome = findChrome();
    const cmdArgs = [
      "render",
      "src/index.ts",
      "ShortVideoVertical",
      tmpRawOut,
      "--props",
      tmpProps,
      "--concurrency",
      String(args.concurrency || "50%"),
      "--gl=angle",
    ];
    if (chrome) {
      cmdArgs.push("--browser-executable", chrome);
    }
    console.log(`[Remotion] 开始渲染 ${durationSec.toFixed(2)}s 竖屏动效视频 (${chrome ? "使用本机 Chrome" : "默认浏览器"})...`);
    await runAsync(remotionBin, cmdArgs, {
      cwd: STUDIO_DIR,
      stdio: "inherit",
    });

    // 写入元数据 comment + 广播级音量归一 (loudnorm) + faststart 输出到目标路径
    const ffArgs = [
      "-nostdin",
      "-v",
      "error",
      "-i",
      tmpRawOut,
      "-c:v",
      "copy",
      "-af",
      "loudnorm=I=-16:TP=-1.5:LRA=11",
      "-c:a",
      "aac",
      "-b:a",
      "128k",
      "-movflags",
      "+faststart",
    ];
    if (clipId) ffArgs.push("-metadata", `comment=${clipId}`);
    ffArgs.push("-y", outAbs);
    execFileSync("ffmpeg", ffArgs, { stdio: "inherit" });

    const finalDur = probeDuration(outAbs);
    console.log(`[Remotion] 渲染完成: ${path.relative(ROOT, outAbs)} (${finalDur.toFixed(2)}s)`);

    if (args["frames-out"]) {
      const sheetAbs = path.resolve(ROOT, args["frames-out"]);
      makeSixFrameSheet(outAbs, sheetAbs, finalDur);
      console.log(`[Remotion] 已生成六帧视觉自检图: ${path.relative(ROOT, sheetAbs)}`);
    }
  } finally {
    server.close();
    fs.rmSync(tmpProps, { force: true });
    fs.rmSync(tmpRawOut, { force: true });
  }
}

main().catch((err) => {
  console.error(`[Remotion] 失败:`, err.message || err);
  process.exit(1);
});
