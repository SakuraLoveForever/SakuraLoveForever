#!/usr/bin/env node
/**
 * Aggregate DeepSeek API generations that DSH routed to Alibaba Bailian
 * (provider "aliyun-bailian") out of the local DSH session logs.
 * Reads only the per-response usage counters: no prompts, replies or ids.
 *
 *   node scripts/collect-aliyun-usage.js [--out FILE] [--day YYYY-MM-DD] [dir...]
 */
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const PROVIDER = "aliyun-bailian";
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

function defaultRoots() {
  const home = process.env.USERPROFILE || process.env.HOME || "";
  const roaming = process.env.APPDATA || path.join(home, "AppData", "Roaming");
  return [path.join(home, ".dsh", "sessions"),
          path.join(roaming, "dsh-desktop", "harness", "sessions")]
    .filter((dir) => fs.existsSync(dir));
}

// DSH appends one zstd frame per write; concat-decompress only reads the first.
function readFrames(file) {
  const buffer = fs.readFileSync(file);
  const parts = [];
  let offset = 0;
  while (offset < buffer.length) {
    const next = buffer.indexOf(ZSTD_MAGIC, offset + 4);
    const end = next < 0 ? buffer.length : next;
    try {
      parts.push(zlib.zstdDecompressSync(buffer.subarray(offset, end)));
    } catch {
      break;
    }
    offset = end;
  }
  return Buffer.concat(parts).toString("utf8");
}

function walk(dir, files) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, files);
    else if (full.endsWith(".zstd")) files.push(full);
  }
  return files;
}

function shanghaiDay(milliseconds) {
  return new Date(milliseconds).toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
}

function collect(roots) {
  const daily = new Map();
  const models = new Set();
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    for (const file of walk(root, [])) {
      let created;
      try { created = fs.statSync(file).birthtimeMs || fs.statSync(file).mtimeMs; } catch { continue; }
      let text;
      try { text = readFrames(file); } catch { continue; }
      for (const line of text.split("\n")) {
        if (!line) continue;
        let record;
        try { record = JSON.parse(line); } catch { continue; }
        if (record.type === "session" && record.createdAt) { created = record.createdAt; continue; }
        if (record.type !== "assistant/message") continue;
        const usage = record.data && record.data.usage;
        const source = (record.data.message && record.data.message.source) || {};
        if (!usage || source.provider !== PROVIDER) continue;
        if (source.model) models.add(source.model);
        const day = shanghaiDay(record.time || created);
        const row = daily.get(day) || { date: day, tokens: 0, input: 0, output: 0,
                                        cache_read: 0, cache_write: 0, reasoning: 0 };
        const input = usage.inputTokens || 0;
        const output = usage.outputTokens || 0;
        const cacheRead = usage.cacheReadTokens || 0;
        row.input += input;
        row.output += output;
        row.cache_read += cacheRead;
        row.tokens += usage.totalTokens || input + output + cacheRead;
        daily.set(day, row);
      }
    }
  }
  return { daily: [...daily.values()].sort((a, b) => a.date.localeCompare(b.date)),
           models: [...models].sort() };
}

function isCount(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function main(argv) {
  const roots = [];
  const positional = [];
  let out = "--out";
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--out") { out = argv[i + 1]; i += 1; }
    else positional.push(argv[i]);
  }
  roots.push(...(positional.length ? positional : defaultRoots()));
  const result = collect(roots);
  for (const row of result.daily) {
    if (![row.tokens, row.input, row.output, row.cache_read].every(isCount)) {
      throw new Error("non-numeric usage counter in " + row.date);
    }
    if (row.input + row.output + row.cache_read !== row.tokens) {
      throw new Error("token breakdown does not match daily total on " + row.date);
    }
  }
  const payload = { schema_version: 1, timezone: "Asia/Shanghai", provider: PROVIDER,
                    models: result.models, daily: result.daily };
  const text = JSON.stringify(payload, null, 2) + "\n";
  if (out) {
    const target = path.resolve(out);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const staged = target + ".tmp";
    fs.writeFileSync(staged, text);
    fs.renameSync(staged, target);
  } else {
    process.stdout.write(text);
  }
  const total = result.daily.reduce((sum, row) => sum + row.tokens, 0);
  process.stderr.write(roots.length + " root(s), " + result.daily.length + " day(s), " +
                       total + " Tokens (incl. cache)\n");
}

module.exports = { collect, main, readFrames, shanghaiDay };

if (require.main === module) main(process.argv.slice(2));
