import {describe} from '@jest/globals';
import driver from '@global/jsonata/driver.mjs';

import allOfIfThenElse from '../../__fixtures__/jsonata/validator/if-else/allOf-if-then-else.json';
import allOfWithRefIfThenElse from '../../__fixtures__/jsonata/validator/if-else/allOf-with-ref-if-then-else.json';
import anyOfIfThenElse from '../../__fixtures__/jsonata/validator/if-else/anyOf-if-then-else.json';
import anyOfWithRefIfThenElse from '../../__fixtures__/jsonata/validator/if-else/anyOf-with-ref-if-then-else.json';
import ifArrayMaxItemsThenRulesAboutItems from '../../__fixtures__/jsonata/validator/if-else/if-array-maxItems-then-rules-about-items.json';
import ifEmailThenStringMinlengthElseNumber from '../../__fixtures__/jsonata/validator/if-else/if-email-then-string-minLength-else-number.json';
import ifExistsUsingDependenciesThenRequireMoreDeps from '../../__fixtures__/jsonata/validator/if-else/if-exists-using-dependencies-then-require-more-deps.json';
import ifMinimumThenElseEnum from '../../__fixtures__/jsonata/validator/if-else/if-minimum-then-else-enum.json';
import ifNestedValueUsingRequiredThenEnforceDeepStructure from '../../__fixtures__/jsonata/validator/if-else/if-nested-value-using-required-then-enforce-deep-structure.json';
import ifObjectHasPropertyWithMultipleofThenAppliesLimit from '../../__fixtures__/jsonata/validator/if-else/if-object-has-property-with-multipleOf-then-applies-limit.json';
import ifPatternThenTypeElseType from '../../__fixtures__/jsonata/validator/if-else/if-pattern-then-type-else-type.json';
import ifRefInIf from '../../__fixtures__/jsonata/validator/if-else/if-ref-in-if.json';
import jsonataDatasetAllOf from '../../__fixtures__/jsonata/validator/if-else/jsonata-dataset-allOf.json';
import jsonataDatasetIfElse from '../../__fixtures__/jsonata/validator/if-else/jsonata-dataset-if-else.json';
import nestedIfThenElse from '../../__fixtures__/jsonata/validator/if-else/nested-if-then-else.json';
import oneofIfThenElse from '../../__fixtures__/jsonata/validator/if-else/oneOf-if-then-else.json';
import oneofWithRefIfThenElse from '../../__fixtures__/jsonata/validator/if-else/oneOf-with-ref-if-then-else.json';
import simpleIfThenElse from '../../__fixtures__/jsonata/validator/if-else/simple-if-then-else.json';


describe.skip('Проверка атрибутов в ответе валидатора jsonata - if-else', () => {

     test.each([
        [allOfIfThenElse.name, 'then' , allOfIfThenElse]
        ,[allOfIfThenElse.name, 'else' , allOfIfThenElse]
        ,[allOfWithRefIfThenElse.name, 'then' , allOfWithRefIfThenElse]
        ,[allOfWithRefIfThenElse.name, 'else' , allOfWithRefIfThenElse]
        ,[anyOfIfThenElse.name, 'then' , anyOfIfThenElse]
        ,[anyOfIfThenElse.name, 'else' , anyOfIfThenElse]
        ,[anyOfWithRefIfThenElse.name, 'then' , anyOfWithRefIfThenElse]
        ,[anyOfWithRefIfThenElse.name, 'else' , anyOfWithRefIfThenElse]
        ,[ifArrayMaxItemsThenRulesAboutItems.name, 'then' , ifArrayMaxItemsThenRulesAboutItems]
        ,[ifArrayMaxItemsThenRulesAboutItems.name, 'else' , ifArrayMaxItemsThenRulesAboutItems]
        ,[ifEmailThenStringMinlengthElseNumber.name, 'then' , ifEmailThenStringMinlengthElseNumber]
        ,[ifEmailThenStringMinlengthElseNumber.name, 'else' , ifEmailThenStringMinlengthElseNumber]
        ,[ifExistsUsingDependenciesThenRequireMoreDeps.name, 'then' , ifExistsUsingDependenciesThenRequireMoreDeps]
        ,[ifExistsUsingDependenciesThenRequireMoreDeps.name, 'else' , ifExistsUsingDependenciesThenRequireMoreDeps]
        ,[ifMinimumThenElseEnum.name, 'then' , ifMinimumThenElseEnum]
        ,[ifMinimumThenElseEnum.name, 'else' , ifMinimumThenElseEnum]
        ,[ifNestedValueUsingRequiredThenEnforceDeepStructure.name, 'then' , ifNestedValueUsingRequiredThenEnforceDeepStructure]
        ,[ifNestedValueUsingRequiredThenEnforceDeepStructure.name, 'else' , ifNestedValueUsingRequiredThenEnforceDeepStructure]
        ,[ifObjectHasPropertyWithMultipleofThenAppliesLimit.name, 'then' , ifObjectHasPropertyWithMultipleofThenAppliesLimit]
        ,[ifObjectHasPropertyWithMultipleofThenAppliesLimit.name, 'else' , ifObjectHasPropertyWithMultipleofThenAppliesLimit]
        ,[ifPatternThenTypeElseType.name, 'then' , ifPatternThenTypeElseType]
        ,[ifPatternThenTypeElseType.name, 'else' , ifPatternThenTypeElseType]
        ,[ifRefInIf.name, 'then' , ifRefInIf]
        ,[ifRefInIf.name, 'else' , ifRefInIf]
        ,[jsonataDatasetAllOf.name, 'invalidDataset' , jsonataDatasetAllOf]
        ,[jsonataDatasetAllOf.name, 'invalidJsonata' , jsonataDatasetAllOf]
        ,[jsonataDatasetIfElse.name, 'invalidDataset' , jsonataDatasetIfElse]
        ,[jsonataDatasetIfElse.name, 'invalidJsonata' , jsonataDatasetIfElse]
        ,[nestedIfThenElse.name, 'then' , nestedIfThenElse]
        ,[nestedIfThenElse.name, 'else' , nestedIfThenElse]
        ,[oneofIfThenElse.name, 'then' , oneofIfThenElse]
        ,[oneofIfThenElse.name, 'else' , oneofIfThenElse]
        ,[oneofWithRefIfThenElse.name, 'then' , oneofWithRefIfThenElse]
        ,[oneofWithRefIfThenElse.name, 'else' , oneofWithRefIfThenElse]
        ,[simpleIfThenElse.name, 'then' , simpleIfThenElse]
        ,[simpleIfThenElse.name, 'else' , simpleIfThenElse]
    ])('Ошибки в if-else: %s: %s', async(name, scenario, testData) => {
        const expression = `(
            $validator := $jsonschema($params.schema);
            $validator($params.data);
        )`;
        let scenarioData = testData[scenario];
        const evaluator = driver.expression(expression, null, {
            schema: testData.schema,
            data: scenarioData.data
        });
        const validationResult = await evaluator.evaluate({});
        expect(validationResult).not.toBe(true);
        const actual = validationResult.find((el) => el.attrInfo.name === scenarioData.expectedInfo.name);
        try{
            expect(actual.attrInfo).toBeDefined();
        } catch (e) {
            throw new Error('attrInfo must be defined');
        }
        try{
            expect(actual.attrInfo.title).toBe(scenarioData.expectedInfo.title);
        } catch (e) {
            throw new Error(`attrInfo title check, actual: [${actual.attrInfo.title}] (type: ${typeof actual.attrInfo.title}), expected: [${scenarioData.expectedInfo.title}] (type: ${typeof scenarioData.expectedInfo.title})`);
        }
        try{
            expect(actual.attrInfo.type).toBe(scenarioData.expectedInfo.type);
        } catch (e) {
            throw new Error(`attrInfo type check, actual: [${actual.attrInfo.type}] (type: ${typeof actual.attrInfo.type}), expected: [${scenarioData.expectedInfo.type}] (type: ${typeof scenarioData.expectedInfo.type})`);
        }
        try{
            if (typeof scenarioData.expectedInfo.currentValue === 'object') {
                expect(actual.attrInfo.currentValue).toStrictEqual(scenarioData.expectedInfo.currentValue);
            } else {
                expect(actual.attrInfo.currentValue).toBe(scenarioData.expectedInfo.currentValue);
            }
        } catch (e) {
            throw new Error(`attrInfo currentValue check, actual: [${actual.attrInfo.currentValue}] (type: ${typeof actual.attrInfo.currentValue}), expected: [${scenarioData.expectedInfo.currentValue}] (type: ${typeof scenarioData.expectedInfo.currentValue})`);
        }
    });
});
