import test from 'node:test';
import assert from 'node:assert/strict';
import { assertSupportedJsonSchema, assertObjectJsonSchema, jsonSchemaToTs, jsonSchemaToPy,
  renderToolsSdk, renderToolsSdkPy, validateJsonSchemaValue } from '@deepseek-ai/dsh-tools';
import { QUERY_SCHEMA, OPERATE_SCHEMA, operationArgv, tools } from '../src/host-tools.mjs';

test('actual wire schemas are supported object-root inputs with typed action literals', () => {
  for (const schema of [QUERY_SCHEMA, OPERATE_SCHEMA]) {
    assert.doesNotThrow(() => assertSupportedJsonSchema(schema));
    assert.doesNotThrow(() => assertObjectJsonSchema(schema));
    assert.equal(schema.type, 'object'); assert.equal(schema.oneOf, undefined);
    assert.equal(schema.properties.action.type, 'string');
    assert(!jsonSchemaToTs(schema.properties.action).includes('unknown'));
    assert(!jsonSchemaToPy(schema.properties.action).includes('Any'));
    for (const action of schema.properties.action.enum) {
      assert(jsonSchemaToTs(schema).includes(JSON.stringify(action)));
      assert(jsonSchemaToPy(schema.properties.action).includes(action));
    }
    assert(validateJsonSchemaValue(schema, { action: 'shell' }).length > 0);
    assert(validateJsonSchemaValue(schema, { action: schema.properties.action.enum[0], confirmed: true }).length > 0);
  }
});

test('native TypeScript and Python SDK projections retain action, baseline and project fields', () => {
  const schemas = tools({}, {}).map(({ name, description, parameters, output }) => ({ name, description, parameters, output: output.schema }));
  for (const rendered of [renderToolsSdk(schemas), renderToolsSdkPy(schemas)]) {
    for (const token of ['dsh_dev_query', 'dsh_dev_operate', 'release-resume', 'commit-plan', 'baseline', 'project', 'runId']) assert(rendered.includes(token), token);
    assert(!/action\??:\s*(?:unknown|Any)\b/.test(rendered));
  }
});

test('flat wire input does not weaken action-specific required or forbidden fields', async () => {
  assert.throws(() => operationArgv({ action: 'commit', project: 'dsh-test' }), /Missing argument/);
  assert.throws(() => operationArgv({ action: 'validate', project: 'dsh-test', baseline: 'a'.repeat(64) }), /Unexpected argument/);
  assert.throws(() => operationArgv({ action: 'sync', project: 'dsh-test', baseline: 'a'.repeat(64), remote: '' }), /Invalid argument/);
  assert.equal(operationArgv({ action: 'sync', project: 'dsh-test', baseline: 'a'.repeat(64), remote: 'empty' })[3], 'empty');
  await assert.rejects(tools({}, {})[0].execute({ action: 'projects', project: 'dsh-test' }, {}), /Unexpected argument/);
});
