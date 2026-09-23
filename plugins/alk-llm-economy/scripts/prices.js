/*
 * prices.js — прайс API и правила пересчёта токенов в деньги.
 *
 * Один источник для `session-cost.js` и `cache-split.js`: раньше таблица
 * лежала в обоих и при смене цен пришлось бы править два файла.
 *
 * Цены в $/MTok: вход / чтение кэша / выход. Запись кэша считается от входа:
 * ×1.25 при TTL 5 минут, ×2 при TTL 1 час.
 * Источник — справочник claude-api, кэш 2026-06-24 (Opus 5.5 сверен 2026-09-23).
 * Обновлять при смене цен.
 */
const PRICE = {
  'claude-fable-5-1': { in: 10, cr: 0.25, out: 50 },
  'claude-fable-5':   { in: 10, cr: 1.0,  out: 50 },
  'claude-opus-5-5':  { in: 4,  cr: 0.2,  out: 20 },
  'claude-opus-5':    { in: 5,  cr: 0.5,  out: 25 },
  'claude-opus-4-8':  { in: 5,  cr: 0.5,  out: 25 },
  'claude-opus-4-7':  { in: 5,  cr: 0.5,  out: 25 },
  'claude-opus-4-6':  { in: 5,  cr: 0.5,  out: 25 },
  'claude-sonnet-5':  { in: 2,  cr: 0.2,  out: 10 },
  'claude-sonnet-4-6':{ in: 3,  cr: 0.3,  out: 15 },
  'claude-haiku-4-5': { in: 1,  cr: 0.1,  out: 5 },
};

// В транскриптах модель бывает с датой сборки: claude-haiku-4-5-20251001.
const normModel = m => String(m).replace(/-[0-9]{8}$/, '');

// Коэффициенты записи кэша от цены входа.
const CACHE_WRITE = { '5m': 1.25, '1h': 2 };

module.exports = { PRICE, normModel, CACHE_WRITE };
