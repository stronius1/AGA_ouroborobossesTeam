import {describe} from '@jest/globals';
import driver from '@global/jsonata/driver.mjs';
import allOfSchema from '../../__fixtures__/jsonata/validator/inheritance/singlelevel/allOf/schema.json';
import allOfData from '../../__fixtures__/jsonata/validator/inheritance/singlelevel/allOf/data.json';
import anyOfSchema from '../../__fixtures__/jsonata/validator/inheritance/singlelevel/anyOf/schema.json';
import anyOfData from '../../__fixtures__/jsonata/validator/inheritance/singlelevel/anyOf/data.json';
import oneOfSchema from '../../__fixtures__/jsonata/validator/inheritance/singlelevel/oneOf/schema.json';
import oneOfData from '../../__fixtures__/jsonata/validator/inheritance/singlelevel/oneOf/data.json';

describe.skip('Проверка атрибутов в ответе валидатора jsonata - наследование 1 уровень', () => {

  test('allOf', async() => {
    const expression = `(
    $validator := $jsonschema($params.schema);
    $validator($params.data);
  )`;
    const evaluator = driver.expression(expression, null, {
      schema: allOfSchema,
      data: allOfData
    });
    const validationResult = await evaluator.evaluate({});
    expect(validationResult).not.toBe(true);
    expect(validationResult).toHaveLength(1);
    expect(validationResult[0].attrInfo.title).toBe('Группа систем');
    expect(validationResult[0].attrInfo.type).toBe('string');
  });


  test('anyOf', async() => {
    const expression = `(
    $validator := $jsonschema($params.schema);
    $validator($params.data);
  )`;
    const evaluator = driver.expression(expression, null, {
      schema: anyOfSchema,
      data: anyOfData
    });
    const validationResult = await evaluator.evaluate({});
    // В схеме anyOfData добавлены атрибуты required т.к. без него ошибок не происходит и проверять нечего
    // Если не required, то не важно какие атрибуты передавать, даже если в одном из вариантов они обязательные,
    // валидация пройдет без ошибок если хоть в одном из вариантов anyOf есть объект без required
    // Поэтому тут проверим наличие 3 ошибок: anyOf + ошибка enum + ошибку required второго вариант anyOf
    expect(validationResult).not.toBe(true);
    expect(validationResult).toHaveLength(3);

    const enumError = validationResult.find((el) => el.keyword === 'enum');
    expect(enumError.attrInfo.title).toBe('Группа систем');
    expect(enumError.attrInfo.type).toBe('string');

    const requiredError = validationResult.find((el) => el.keyword === 'required');
    expect(requiredError.attrInfo.title).toBe('Описание изменений');
    expect(requiredError.attrInfo.type).toBe('string');

    const anyOfError = validationResult.find((el) => el.keyword === 'anyOf');
    expect(anyOfError.attrInfo.title).toBeUndefined();
    expect(anyOfError.attrInfo.type).toBe('object');
  });

  test('oneOf', async() => {
    const expression = `(
    $validator := $jsonschema($params.schema);
    $validator($params.data);
  )`;
    const evaluator = driver.expression(expression, null, {
      schema: oneOfSchema,
      data: oneOfData
    });
    const validationResult = await evaluator.evaluate({});
    expect(validationResult).not.toBe(true);
    expect(validationResult).toHaveLength(3);

    // В схеме oneOfData добавлены атрибуты required т.к. без него ошибок не происходит и проверять нечего
    // Если не required, то не важно какие атрибуты передавать, даже если в одном из вариантов они обязательные,
    // валидация пройдет без ошибок если хоть в одном из вариантов anyOf есть объект без required
    // Поэтому тут проверим наличие 3 ошибок: anyOf + ошибка enum + ошибку required второго вариант anyOf
    const enumError = validationResult.find((el) => el.keyword === 'enum');
    expect(enumError.attrInfo.title).toBe('Группа систем');
    expect(enumError.attrInfo.type).toBe('string');

    const requiredError = validationResult.find((el) => el.keyword === 'required');
    expect(requiredError.attrInfo.title).toBe('Описание изменений');
    expect(requiredError.attrInfo.type).toBe('string');

    const anyOfError = validationResult.find((el) => el.keyword === 'oneOf');
    expect(anyOfError.attrInfo.title).toBeUndefined();
    expect(anyOfError.attrInfo.type).toBe('object');
  });
});
