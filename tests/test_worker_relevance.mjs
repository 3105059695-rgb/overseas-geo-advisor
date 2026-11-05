import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import worker, {DATA_BASE, queryIntent, passageRelevance} from '../remote-server/worker.mjs';

// Synthetic evidence distinguishes answering-engine sources from SEO tools and wishes.
// All assertions exercise the public MCP tool path, including versioned source reads.
const sha = text => createHash('sha256').update(text).digest('hex');
const fixtures = [
  ['domestic', '官媒信源清单：豆包元宝', '国内官媒信源清单有很多来源；豆包元宝的引用来源与权威信源。'],
  ['claude', 'Claude web search documentation', 'Claude searches the web and includes citations to original sources in answers.'],
  ['grok', 'Grok search tools documentation', 'Grok searches public web pages and X posts; search results include source citations.'],
  ['operator', 'Claude SEO writing workflow', 'Use Claude to write SEO articles and generate a list of source links.'],
  ['wish', '建议 Grok 开放搜索引擎', 'I wish Grok would launch a search engine with sources and citations.'],
  ['other', 'ChatGPT Gemini citation statistics', 'ChatGPT and Gemini search sources have different citation shares in a small study.'],
  ['mixed', 'Claude and Grok notes', 'Claude searches the web and cites sources.\nUse Grok to write SEO articles and produce source links.'],
  ['kimi', 'Kimi content workflow', 'Use Kimi to write SEO articles and generate source lists.'],
];
const assets = new Map(), documents = {}, chunks = [], index = {};
function tokens(text) {
  const out = [];
  for (const part of text.toLowerCase().match(/[a-zA-Z][a-zA-Z0-9_-]*|\d+(?:\.\d+)?|[\u3400-\u9fff]+/g) || []) {
    if (/^[\u3400-\u9fff]+$/.test(part)) {
      for (let i = 0; i < part.length - 1; i++) out.push(part.slice(i, i + 2));
      if (part.length >= 2 && part.length <= 6) out.push(part);
    } else if (part.length > 1) out.push(part);
  }
  return out;
}
for (const [key, title, body] of fixtures) {
  const text = `# ${title}\n\n${body}\n`, id = `doc-${sha(key).slice(0, 20)}`, version = sha(text);
  const metadata = {title, source_type: 'archived_article', published_at: '2026-01-01', work_id: key, original_url: `https://example.org/${key}`, group: 'sources', topic: '信源'};
  const lineCount = text.trimEnd().split('\n').length;
  const d = {document_id: id, source_version: version, metadata, text, line_count: lineCount, reviewed_claims: []};
  documents[id] = {...metadata, versions: {[version]: {}}};
  assets.set(`/data/documents/${id}/${version}.json`, d);
  const chunk = {id: chunks.length + 1, document_id: id, source_version: version, line_start: 1, line_end: lineCount, heading: title, snippet: text.slice(0, 20), content_hash: sha(text), token_count: tokens(text).length};
  chunks.push(chunk);
  const bodyTokens = tokens(text), titleTokens = tokens(title);
  for (const token of new Set([...bodyTokens, ...titleTokens])) (index[token] ??= []).push(chunk.id, bodyTokens.filter(x => x === token).length, titleTokens.filter(x => x === token).length);
}
assets.set('/data/catalog.json', {schema_version: 1, knowledge_version: 'fixture-v04', built_at: '2026-01-01', documents, groups: {sources: fixtures.length}, counts: {documents: fixtures.length, chunks: chunks.length, independent_sources: fixtures.length}, tokenizer: {stop_words: [], expansions: {}}, search: {shard_count: 1, shards: ['/data/index/00.json'], chunks: '/data/chunks.json', average_token_count: 30}, curated: '/data/curated.json'});
assets.set('/data/chunks.json', chunks);
assets.set('/data/index/00.json', index);
assets.set('/data/curated.json', {answers: [], claims: [], sources: []});
globalThis.fetch = async url => {
  assert.ok(String(url).startsWith(DATA_BASE + '/data/'));
  const asset = assets.get(String(url).slice(DATA_BASE.length));
  return asset ? new Response(JSON.stringify(asset)) : new Response('Not found', {status: 404});
};
async function call(name, args = {}) {
  const response = await worker.fetch(new Request('https://geo.test/api/mcp', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'tools/call', params: {name, arguments: args}})}));
  const result = (await response.json()).result;
  assert.equal(result.isError, false, JSON.stringify(result));
  return result.structuredContent;
}

test('Claude sources excludes domestic keywords and SEO operator passages', async () => {
  const r = await call('ask_geo', {question: 'Claude 信源偏好 引用哪些来源'});
  assert.equal(r.query_intent.kind, 'platform_sources');
  assert.deepEqual(r.query_intent.platforms, ['Claude']);
  assert.ok(r.citations.length);
  assert.ok(r.citations.every(x => x.relevance.direct_platforms.includes('Claude')));
  assert.ok(r.citations.every(x => !/官媒|workflow/i.test(x.title)));
  assert.ok(r.background_citations.some(x => /workflow/i.test(x.title)));
  assert.equal(r.answer_brief.reader_level, 'beginner');
});

test('Grok wishes are background, not source evidence', async () => {
  const r = await call('ask_geo', {question: '我想知道 Grok 他们的信源到底是什么'});
  assert.ok(r.citations.some(x => /tools documentation/.test(x.title)));
  assert.ok(!r.citations.some(x => /建议|notes/.test(x.title)));
  assert.ok(r.background_citations.some(x => /建议/.test(x.title)));
});

test('multi-platform answer balances evidence and marks role per platform', async () => {
  const r = await call('ask_geo', {question: 'Claude 和 Grok 的信源是什么？'});
  assert.deepEqual(r.query_intent.platforms, ['Claude', 'Grok']);
  for (const platform of ['Claude', 'Grok']) {
    assert.ok(r.citations.some(x => x.relevance.direct_platforms.includes(platform)));
    assert.ok(r.platform_coverage.find(x => x.platform === platform).direct_candidates > 0);
  }
  const mixed = r.citations.find(x => /notes/.test(x.title));
  if (mixed) assert.deepEqual(mixed.relevance.direct_platforms, ['Claude']);
  assert.equal(r.answer_brief.user_question, 'Claude 和 Grok 的信源是什么？');
});

test('company aliases select matching product, and missing direct evidence stays explicit', async () => {
  const claude = await call('ask_geo', {question: 'Anthropic sources and citations'});
  assert.deepEqual(claude.query_intent.platforms, ['Claude']);
  assert.ok(claude.citations.some(x => /Claude/.test(x.title)));
  const kimi = await call('ask_geo', {question: 'Kimi 的信源是什么？'});
  assert.equal(kimi.citations.length, 0);
  assert.equal(kimi.status, 'insufficient_evidence');
  assert.ok(kimi.answer_brief.missing_direct_evidence.includes('Kimi'));
  assert.equal(kimi.platform_coverage[0].status, 'background_only');
});

test('source reads clamp requested end to EOF without creating a false continuation', async () => {
  const r = await call('search_geo', {question: 'Claude sources', limit: 2});
  const ref = r.citations[0];
  const read = await call('read_geo_source', {document_id: ref.document_id, source_version: ref.source_version, start_line: 1, end_line: 10000});
  assert.equal(read.line_end, read.line_count);
  assert.equal(read.next_start_line, null);
  assert.equal(read.truncated, false);
  assert.equal(read.source_version, ref.source_version);
});

test('explicit current platform overrides a different engine in previous question', async () => {
  const r = await call('ask_geo', {question: 'Grok 的信源是什么？', context: {question: 'Claude 信源偏好 引用哪些来源'}});
  assert.deepEqual(r.query_intent.platforms, ['Grok']);
  assert.ok(r.citations.every(x => x.relevance.direct_platforms.includes('Grok')));
  assert.equal(r.retrieval_scope.whole_corpus_reviewed, false);
});

test('source metadata and linked tables of contents do not establish a source claim', () => {
  const intent = queryIntent('Claude sources');
  for (const text of ['# Claude web search\n来源：https://example.org/claude-searchbot\n', '- [[#123. Claude-SearchBot|Claude-SearchBot]]']) {
    assert.equal(passageRelevance(intent, 'Claude', text).tier, 'background');
  }
});

test('price and optimization questions retain their task instead of becoming source explanation', () => {
  for (const question of ['Claude web search价格是多少？', '怎么让 Claude 引用我的网站？', 'How to monitor Claude citations?']) assert.equal(queryIntent(question).kind, 'general');
});

test('source percentages require observed evidence, not capability documentation', async () => {
  const r = await call('ask_geo', {question: 'Grok 信源占比是多少？'});
  assert.deepEqual(r.query_intent.source_aspects, ['observed_preferences']);
  assert.equal(r.citations.length, 0);
  assert.equal(r.status, 'insufficient_evidence');
  assert.match(r.answer_brief.focus, /占比|排名/);
});

test('colloquial source preference questions and Chinese product alias keep their intent', () => {
  for (const question of ['Claude 喜欢什么网站？', 'Grok 更喜欢 Reddit 还是官网？', 'Which sources does Claude prefer?', '克劳德偏好哪些网站？']) {
    const intent = queryIntent(question);
    assert.equal(intent.kind, 'platform_sources');
    assert.deepEqual(intent.source_aspects, ['content_sources', 'observed_preferences']);
  }
  assert.deepEqual(queryIntent('克劳德的信源是什么？').platforms, ['Claude']);
});

test('overseas AI source comparison uses a declared illustrative scope and excludes domestic keyword hits', async () => {
  const r = await call('ask_geo', {question: '海外的不同 AI，他们喜欢的信源是什么？'});
  assert.equal(r.query_intent.kind, 'platform_sources');
  assert.equal(r.query_intent.platform_selection, 'illustrative_overseas_scope');
  assert.ok(r.query_intent.platforms.includes('Claude'));
  assert.ok(r.query_intent.platforms.includes('Grok'));
  assert.ok(r.citations.length);
  assert.ok(r.citations.every(x => !/官媒|豆包|元宝/.test(x.title)));
  assert.equal(queryIntent('海外 AI 信源怎么分类？').kind, 'general');
  assert.equal(queryIntent('海外信源怎么分？').kind, 'general');
});
