import { describe, expect, it } from 'vitest';
import { parseStartParam, startParamToPath } from './startParam';

describe('parseStartParam', () => {
  it('разбирает известный вид приглашения', () => {
    expect(parseStartParam('inv_abc123')).toEqual({ kind: 'inv', value: 'abc123' });
  });

  it('разбирает заявку и экран', () => {
    expect(parseStartParam('req_req_42')).toEqual({ kind: 'req', value: 'req_42' });
    expect(parseStartParam('scr_equipment')).toEqual({ kind: 'scr', value: 'equipment' });
  });

  it('возвращает null для пустого или некорректного значения', () => {
    expect(parseStartParam(null)).toBeNull();
    expect(parseStartParam(undefined)).toBeNull();
    expect(parseStartParam('')).toBeNull();
    expect(parseStartParam('noSeparatorHere')).toBeNull();
    expect(parseStartParam('_novalue')).toBeNull();
    expect(parseStartParam('inv_')).toBeNull();
  });

  it('отклоняет неизвестный вид параметра', () => {
    expect(parseStartParam('xyz_something')).toBeNull();
  });
});

describe('startParamToPath', () => {
  it('строит путь приглашения с токеном в query', () => {
    expect(startParamToPath({ kind: 'inv', value: 'tok123' })).toBe(
      '/invitations/accept?token=tok123',
    );
  });

  it('строит путь заявки', () => {
    expect(startParamToPath({ kind: 'req', value: 'req_1' })).toBe('/requests/req_1');
  });

  it('строит путь приглашения на привязку сервиса', () => {
    expect(startParamToPath({ kind: 'sb', value: 'tok456' })).toBe('/bindings/accept?token=tok456');
  });

  it('строит путь известного экрана и null для неизвестного', () => {
    expect(startParamToPath({ kind: 'scr', value: 'equipment' })).toBe('/equipment');
    expect(startParamToPath({ kind: 'scr', value: 'unknown' })).toBeNull();
  });

  it('строит путь карточки биржи и экранов бота', () => {
    expect(startParamToPath(parseStartParam('mkt_req_7'))).toBe('/provider/available/req_7');
    expect(startParamToPath(parseStartParam('scr_inbox'))).toBe('/provider/incoming');
    expect(startParamToPath(parseStartParam('scr_integration'))).toBe('/integration');
  });

  it('возвращает null при отсутствии параметра', () => {
    expect(startParamToPath(null)).toBeNull();
  });
});

describe('parseStartParam: идентификатор объекта', () => {
  it('пропускает UUID и обычный id заявки', () => {
    expect(parseStartParam('req_3f2b8c1e-0d4a-4b7e-9a51-2c6d8e9f0a1b')).toEqual({
      kind: 'req',
      value: '3f2b8c1e-0d4a-4b7e-9a51-2c6d8e9f0a1b',
    });
    expect(parseStartParam('mkt_req_7')).toEqual({ kind: 'mkt', value: 'req_7' });
  });

  it('отклоняет обход пути и спецсимволы в id', () => {
    expect(parseStartParam('req_..%2F..%2Fadmin')).toBeNull();
    expect(parseStartParam('req_../../x')).toBeNull();
    expect(parseStartParam('mkt_a?b=1')).toBeNull();
    expect(parseStartParam('req_a.b')).toBeNull();
  });

  it('токены приглашений не ограничиваются алфавитом id', () => {
    expect(parseStartParam('inv_a.b~c')).toEqual({ kind: 'inv', value: 'a.b~c' });
  });
});
