/*
 * Тесты cost-structure.js — из чего сложился расход: чтение кэша, запись,
 * выход, и что было бы при другом promptCacheTtl.
 */
const { test } = require('node:test');
const assert = require('node:assert');

const { bucketOf, writeCost, ttlAlternative, BUCKETS } = require('./cost-structure');

test('ход попадает в корзину по размеру прочитанного контекста', () => {
  assert.strictEqual(bucketOf(0), '0–20k');
  assert.strictEqual(bucketOf(19999), '0–20k');
  assert.strictEqual(bucketOf(20000), '20–40k');
  assert.strictEqual(bucketOf(99999), '80–100k');
  assert.strictEqual(bucketOf(250000), '100k+');
});

test('корзины перечислены по возрастанию и покрывают любое число', () => {
  assert.strictEqual(BUCKETS[0], '0–20k');
  assert.strictEqual(BUCKETS[BUCKETS.length - 1], '100k+');
  for (const n of [0, 1, 40000, 1e9]) assert.ok(BUCKETS.includes(bucketOf(n)));
});

test('запись кэша считается по TTL: часовая вдвое дороже входа, пятиминутная в 1.25', () => {
  // opus 5: вход 5 $/MTok.
  const u = { cache_creation: { ephemeral_5m_input_tokens: 1e6, ephemeral_1h_input_tokens: 1e6 } };
  assert.strictEqual(writeCost('claude-opus-5', u), 5 * 1.25 + 5 * 2);
});

test('без разбивки по TTL вся запись считается пятиминутной', () => {
  assert.strictEqual(writeCost('claude-opus-5', { cache_creation_input_tokens: 1e6 }), 5 * 1.25);
});

test('при пятиминутном TTL неистёкший ход платит ту же запись дешевле', () => {
  const u = { cache_creation: { ephemeral_1h_input_tokens: 1e6 }, cache_read_input_tokens: 5e5 };
  assert.strictEqual(ttlAlternative('claude-opus-5', u, false), 5 * 1.25);
});

test('истёкший кэш заставляет переписать весь префикс заново', () => {
  // Разрыв длиннее пяти минут: префикс, который сейчас читается из кэша,
  // при TTL 5m пришлось бы записать снова.
  const u = { cache_creation: { ephemeral_1h_input_tokens: 1e6 }, cache_read_input_tokens: 1e6 };
  assert.strictEqual(ttlAlternative('claude-opus-5', u, true), 5 * 1.25 + 5 * 1.25);
});

test('незнакомая модель не роняет счёт', () => {
  assert.strictEqual(writeCost('claude-unknown', { cache_creation_input_tokens: 1e6 }), 0);
  assert.strictEqual(ttlAlternative('claude-unknown', { cache_read_input_tokens: 1e6 }, true), 0);
});
