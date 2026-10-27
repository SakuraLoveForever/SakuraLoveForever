#!/usr/bin/env node
/**
 * Aggregate DeepSeek token usage out of the local DSH session logs.
 *
 * Tokscale 4.20.0 only decodes the first zstd frame of a DSH .jsonl.zstd file and
 * drops providers it does not price, so it under-reports long sessions and every
 * Alibaba Bailian generation. DSH writes one frame per append, so this reads all
 * of them and groups the per-response usage counters by provider, model and day.
 * Only counters are kept: no prompts, replies, paths or session ids.
 *
 *   node scripts/collect-dsh-usage.js [--out FILE] [dir...]
 */
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

function defaultRoots() {
  const home = process.env.USERPROFILE || process.env.HOME || "";
  const roaming = process.env.APPDATA || path.join(home, "AppData", "Roaming");
  return [path.join(home, ".dsh", "sessions"),
          path.join(roaming, "dsh-desktop", "harness", "sessions")]
    .filter((dir) => fs.existsSync(dir));
}

// Frame bodies can contain the zstd magic by chance, so a frame ends at the first
// following candidate offset that decodes completely; nothing is guessed.
function readFrames(file) {
  const buffer = fs.readFileSync(file);
  const parts = [];
  let offset = 0;
  while (offset < buffer.length) {
    let boundary = null;
    let probe = offset + 1;
    while (probe <= buffer.length) {
      const next = buffer.indexOf(ZSTD_MAGIC, probe + 4);
      const candidate = next < 0 ? buffer.length : next;
      try {
        parts.push(zlib.zstdDecompressSync(buffer.subarray(offset, candidate)));
        boundary = candidate;
        break;
      } catch {
        probe = candidate + 1;
      }
    }
    if (boundary === null) break;
    offset = boundary;
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

function count(usage, key) {
  const value = usage[key];
  return Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

function collect(roots) {
  const groups = new Map();
  const days = new Map();
  let unanswered = 0;
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
        if (!usage || source.kind !== "model") continue;
        const day = shanghaiDay(record.time || created);
        const row = days.get(day) || { date: day, tokens: 0, input: 0, output: 0,
                                       cache_read: 0, cache_write: 0, reasoning: 0 };
        const input = count(usage, "inputTokens");
        const output = count(usage, "outputTokens");
        const cacheRead = count(usage, "cacheReadTokens");
        const tokens = count(usage, "totalTokens") || input + output + cacheRead;
        // Providers without pricing (Bailian) still report counters; keep them all.
        row.tokens += tokens;
        row.input += input;
        row.output += output;
        row.cache_read += cacheRead;
        row.reasoning += count(usage, "reasoningTokens");
        for (const field of ["input", "output", "cache_read"]) {
          if (row[field] !== 0 || tokens !== 0) break;
        }
        days.set(day, row);
        const key = (source.provider || "unknown") + "|" + (source.model || "unknown");
        const group = groups.get(key) || { provider: source.provider || "unknown",
                                           model: source.model || "unknown",
                                           tokens: 0, messages: 0 };
        group.tokens += tokens;
        group.messages += 1;
        groups.set(key, group);
        if (!usage.totalTokens) unanswered += 1;
      }
    }
  }
  // Thinking tokens are reported separately by some providers; they are part of
  // totalTokens but not of input/output/cache_read, so the split is not summed.
  return {
    daily: [...days.values()].sort((a, b) => a.date.localeCompare(b.date)),
    groups: [...groups.values()].sort((a, b) => (a.provider + a.model).localeCompare(b.provider + b.model)),
    models: [...new Set([...groups.values()].map((group) => group.model))].sort(),
    providers: [...new Set([...groups.values()].map((group) => group.provider))].sort(),
    messagesWithoutTotal: unanswered,
  };
}

function isCount(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function byProvider(result) {
  const out = {};
  for (const group of result.groups) {
    out[group.provider] = out[group.provider] || { tokens: 0, models: [], messages: 0 };
    out[group.provider].tokens += group.tokens;
    out[group.provider].messages += group.messages;
    out[group.provider].models.push(group.model);
  }
  return out;
}

function main(argv) {
  const positional = [];
  let out = null;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--out") { out = argv[index + 1]; index += 1; }
    else positional.push(argv[index]);
  }
  const roots = positional.length ? positional : defaultRoots();
  const result = collect(roots);
  for (const row of result.daily) {
    for (const field of ["tokens", "input", "output", "cache_read", "cache_write", "reasoning"]) {
      if (!isCount(row[field])) throw new Error("non-numeric usage counter in " + row.date);
    }
    if (row.input + row.output + row.cache_read > row.tokens) {
      throw new Error("token breakdown exceeds total on " + row.date);
    }
  }
  const sum = result.daily.reduce((total, row) => total + row.tokens, 0);
  if (sum !== result.groups.reduce((total, group) => total + group.tokens, 0)) {
    throw new Error("daily total does not match provider total");
  }
  const payload = { schema_version: 1, timezone: "Asia/Shanghai", source: "DSH session logs",
                    providers: byProvider(result), daily: result.daily };
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
  const summary = Object.entries(payload.providers)
    .map(([provider, entry]) => provider + "=" + entry.tokens).join(", ");
  process.stderr.write(roots.length + " root(s), " + result.daily.length + " day(s), " +
                       sum + " tokens (" + summary + ")\n");
}

module.exports = { collect, byProvider, main, readFrames, shanghaiDay };

if (require.main === module) main(process.argv.slice(2));
