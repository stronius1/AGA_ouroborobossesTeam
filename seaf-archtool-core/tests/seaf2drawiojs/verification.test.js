/**
 * @jest-environment jsdom
 */

import { afterEach, describe, expect, it, jest } from '@jest/globals';

import { SCHEMAS } from '../../plugins/seaf2drawiojs/lib/constants';
import { getSchemaData } from '../../plugins/seaf2drawiojs/lib/utils';
import {
  analyzeGeneratedXml,
  collectExpectedPatternObjects,
  createVerificationState,
  excludeCommonOnlyLogicalLinksFromVerification,
  logPendingMissingLinks,
  logVerificationReport
} from '../../plugins/seaf2drawiojs/lib/verification';

import crossPageLogicalLink from './fixtures/negative/cross-page-logical-link.json';
import missingLinkEndpoint from './fixtures/negative/missing-link-endpoint.json';
import missingParent from './fixtures/negative/missing-parent.json';
import unknownTopology from './fixtures/negative/unknown-topology.json';
import successMinimal from './fixtures/success/minimal.json';

function createLogger() {
  const calls = [];
  const logger = {};
  for (const level of ['debug', 'info', 'warn', 'error']) {
    logger[level] = (messageFactory, error) => {
      calls.push({
        level,
        value: typeof messageFactory === 'function' ? messageFactory() : messageFactory,
        error
      });
    };
  }
  return {
    logger,
    calls,
    text: () => JSON.stringify(calls)
  };
}

function drawioXml(pageName, objects) {
  return `<mxfile><diagram name="${pageName}"><mxGraphModel><root>${objects.join('')}</root></mxGraphModel></diagram></mxfile>`;
}

function objectXml(id, schema) {
  return `<object id="${id}" schema="${schema}" label="${id}"><mxCell vertex="1" parent="1" /></object>`;
}

describe('seaf2drawiojs verification logging', () => {
  afterEach(() => {
    delete global.DocHub;
    jest.resetModules();
  });

  it('reports missing pattern object with parent diagnostics', () => {
    const { logger, text } = createLogger();
    const state = createVerificationState();
    const objectData = getSchemaData(missingParent, SCHEMAS.COMPONENT_NETWORK);

    collectExpectedPatternObjects(
      state,
      'network_switch',
      { schema: SCHEMAS.COMPONENT_NETWORK, parent_id: 'segment', type: 'type:switch' },
      objectData
    );

    const report = analyzeGeneratedXml(
      drawioXml('Office', [objectXml('segment.office', SCHEMAS.NETWORK_SEGMENT)]),
      state
    );
    logVerificationReport(report, logger);

    expect(report.allMatch).toBe(false);
    expect(report.summary).toContainEqual({
      schema: SCHEMAS.COMPONENT_NETWORK,
      expected: 1,
      drawn_unique: 0,
      drawn_total: 0,
      status: 'MISMATCH'
    });
    expect(text()).toContain('device.missing.parent');
    expect(text()).toContain("parent 'segment' not present on pages");
  });

  it('warns about a skipped link only when an endpoint is absent globally', () => {
    const { logger, text } = createLogger();
    const link = getSchemaData(missingLinkEndpoint, SCHEMAS.LOGICAL_LINK)['link.missing'];

    const result = logPendingMissingLinks([
      {
        type: 'logical',
        pageName: 'Office',
        linkOid: 'link.missing',
        sourceId: link.source,
        targetId: link.target,
        topology: link.topology,
        reason: 'endpoint_missing_on_page'
      }
    ], { Office: ['segment.office', 'device.source'] }, logger);

    expect(result.missing).toHaveLength(1);
    expect(result.deferred).toHaveLength(0);
    expect(text()).toContain('skipped 1 links because endpoints are missing on all pages');
    expect(text()).toContain('link.missing');
    expect(text()).toContain('device.absent');
  });

  it('logs cross-page logical links as common-page processing without false warn', () => {
    const { logger, calls, text } = createLogger();
    const state = createVerificationState();
    const logicalLinks = getSchemaData(crossPageLogicalLink, SCHEMAS.LOGICAL_LINK);
    const diagramIds = {
      Office: ['segment.office', 'device.office'],
      DC: ['segment.dc', 'device.dc']
    };

    collectExpectedPatternObjects(
      state,
      'logical_links_1',
      { schema: SCHEMAS.LOGICAL_LINK, targets: 'target' },
      logicalLinks
    );

    const commonOnly = excludeCommonOnlyLogicalLinksFromVerification(state, crossPageLogicalLink, diagramIds, logger);
    const pendingResult = logPendingMissingLinks([
      {
        type: 'logical',
        pageName: 'Office',
        linkOid: 'link.cross',
        sourceId: 'device.office',
        targetId: 'device.dc',
        topology: 'star',
        reason: 'endpoint_missing_on_page'
      }
    ], diagramIds, logger);

    expect(commonOnly).toEqual(['link.cross']);
    expect(state.expectedCounts[SCHEMAS.LOGICAL_LINK].has('link.cross')).toBe(false);
    expect(pendingResult.missing).toHaveLength(0);
    expect(pendingResult.deferred).toHaveLength(1);
    expect(calls.some((call) => call.level === 'warn')).toBe(false);
    expect(text()).toContain('common page only');
    expect(text()).toContain('deferred to the common page');
  });

  it('warns about unknown logical link topology and falls back to star', async () => {
    const { logger, calls } = createLogger();
    global.DocHub = {
      documents: {
        getLoggerWithTag: jest.fn(() => logger)
      }
    };
    const { Seaf2Drawio } = await import('../../plugins/seaf2drawiojs/lib/seaf-drawio');
    const drawio = new Seaf2Drawio({}, {});
    const linkData = { ...getSchemaData(unknownTopology, SCHEMAS.LOGICAL_LINK)['link.unknown'] };

    const steps = drawio.logicalLinkSteps('link.unknown', linkData, { targets: 'target' }, 'Office');

    expect(steps).toHaveLength(1);
    expect(linkData.topology).toBe('star');
    expect(calls).toContainEqual(expect.objectContaining({
      level: 'warn',
      value: expect.stringContaining('unknown topology "mesh", using star')
    }));
  });

  it('logs OK summary for a successful minimal dataset without missing warnings', () => {
    const { logger, calls, text } = createLogger();
    const state = createVerificationState();
    const objectData = getSchemaData(successMinimal, SCHEMAS.NETWORK_SEGMENT);

    collectExpectedPatternObjects(
      state,
      'segment_int_net',
      { schema: SCHEMAS.NETWORK_SEGMENT, parent_id: 'location', type: 'zone:INT-NET' },
      objectData
    );

    const report = analyzeGeneratedXml(
      drawioXml('Office', [objectXml('segment.office', SCHEMAS.NETWORK_SEGMENT)]),
      state
    );
    logVerificationReport(report, logger);

    expect(report.allMatch).toBe(true);
    expect(report.summary).toContainEqual({
      schema: SCHEMAS.NETWORK_SEGMENT,
      expected: 1,
      drawn_unique: 1,
      drawn_total: 1,
      status: 'OK'
    });
    expect(calls.some((call) => call.level === 'warn')).toBe(false);
    expect(text()).toContain('GENERATION MATCHES YAML (by schema)');
  });
});
