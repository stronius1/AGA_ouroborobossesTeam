import fs from 'node:fs';
import { JSDOM } from 'jsdom';

const drawioPath = process.argv[2];
if (!drawioPath) {
  console.error('Usage: node tests/verify-seaf2drawio-drawio.mjs <file.drawio>');
  process.exit(2);
}

const { window } = new JSDOM('<!doctype html><html></html>');
const doc = new window.DOMParser().parseFromString(fs.readFileSync(drawioPath, 'utf8'), 'application/xml');
const serviceLayerIds = new Set(['101', '102']);
const emptyApplicationLayerId = '103';
const commonPageName = 'Общая схема';

function mxCell(element) {
  if (element?.tagName === 'mxCell') return element;
  return Array.from(element?.children ?? []).find((child) => child.tagName === 'mxCell') ?? null;
}

function elementId(element) {
  const mx = mxCell(element);
  return element?.getAttribute('id') || mx?.getAttribute('id') || '';
}

function isPlainRootLayerCell(element) {
  const mx = mxCell(element);
  if (!mx || mx.getAttribute('parent') !== '0') return false;
  if (mx.getAttribute('vertex') === '1' || mx.getAttribute('edge') === '1') return false;
  return !mx.querySelector('mxGeometry');
}

function layerValue(element) {
  const mx = mxCell(element);
  return String(mx?.getAttribute('value') || element?.getAttribute('label') || '').trim();
}

function isTopLevelVisualContainer(element) {
  const mx = mxCell(element);
  return mx?.getAttribute('parent') === '0'
    && mx.getAttribute('vertex') === '1'
    && Boolean(mx.querySelector('mxGeometry'));
}

function isCommonLayeredVisualContainer(element) {
  const mx = mxCell(element);
  return String(mx?.getAttribute('parent') || '').startsWith('common_layer.visual.')
    && mx.getAttribute('vertex') === '1'
    && Boolean(mx.querySelector('mxGeometry'));
}

function isForegroundLayer(element) {
  if (!isPlainRootLayerCell(element)) return false;
  const id = elementId(element);
  const value = layerValue(element);
  return id === '100'
    || id === '104'
    || serviceLayerIds.has(id)
    || id.startsWith('layer.logical.')
    || id.startsWith('common_layer.logical.')
    || value === 'Connections'
    || value === 'Links';
}

function isTechGroup(element) {
  const id = elementId(element);
  return id.startsWith('tech_group_') || /^common_\d+_tech_group_/.test(id);
}

function isNetworkVertex(element) {
  const mx = mxCell(element);
  return element?.tagName === 'object'
    && element.getAttribute('schema') === 'seaf.company.ta.services.networks'
    && mx?.getAttribute('vertex') === '1';
}

function isNetworkSegmentVertex(element) {
  const mx = mxCell(element);
  return element?.tagName === 'object'
    && element.getAttribute('schema') === 'seaf.company.ta.services.network_segments'
    && mx?.getAttribute('vertex') === '1';
}

function isNetworkEdge(element) {
  const mx = mxCell(element);
  const parent = mx?.getAttribute('parent') || '';
  return mx?.getAttribute('edge') === '1'
    && !element.getAttribute('common_logical_link')
    && (parent === '100' || /^common_\d+_100$/.test(parent) || layerValue(element) === 'Connections');
}

function isNetworkDeviceVertex(element) {
  const mx = mxCell(element);
  return element?.tagName === 'object'
    && element.getAttribute('schema') === 'seaf.company.ta.components.networks'
    && mx?.getAttribute('vertex') === '1';
}

function isInternetFacingProviderNetwork(element) {
  const segment = String(element?.getAttribute('segment') || '').toLowerCase();
  return element?.tagName === 'object'
    && Boolean(element.getAttribute('provider'))
    && (segment.includes('.internet') || segment.endsWith('.inet'));
}

function numberAttr(element, name, defaultValue = 0) {
  const value = Number(element?.getAttribute(name));
  return Number.isFinite(value) ? value : defaultValue;
}

function buildPageIndex(root) {
  const cellsById = {};
  for (const element of Array.from(root.children ?? [])) {
    const mx = mxCell(element);
    if (!mx) continue;
    const id = mx.getAttribute('id') || elementId(element);
    if (id) cellsById[id] = mx;
  }
  return { cellsById };
}

function buildElementIdSet(root) {
  const ids = new Set();
  for (const element of Array.from(root?.children ?? [])) {
    const id = elementId(element);
    if (id && !['0', '1'].includes(id)) ids.add(id);
  }
  return ids;
}

function inferCommonPageIndexNames(commonRefs, sourcePageIdsByName) {
  const scoresByPageIndex = {};
  for (const ref of commonRefs) {
    scoresByPageIndex[ref.pageIndex] = scoresByPageIndex[ref.pageIndex] ?? {};
    for (const [pageName, ids] of Object.entries(sourcePageIdsByName)) {
      if (!ids.has(ref.originalId)) continue;
      scoresByPageIndex[ref.pageIndex][pageName] = (scoresByPageIndex[ref.pageIndex][pageName] ?? 0) + 1;
    }
  }

  const pageNamesByIndex = {};
  for (const [pageIndex, scores] of Object.entries(scoresByPageIndex)) {
    const ranked = Object.entries(scores).sort((left, right) => right[1] - left[1]);
    if (ranked.length && ranked[0][1] > 0) pageNamesByIndex[pageIndex] = ranked[0][0];
  }
  return pageNamesByIndex;
}

function buildCommonRefs(commonRoot, sourcePageIdsByName) {
  const refs = [];
  for (const element of Array.from(commonRoot?.children ?? [])) {
    const id = elementId(element);
    const match = id.match(/^common_(\d+)_(.+)$/);
    if (!match) continue;
    refs.push({
      commonId: id,
      pageIndex: Number(match[1]),
      originalId: match[2]
    });
  }

  const pageNamesByIndex = inferCommonPageIndexNames(refs, sourcePageIdsByName);
  const pageIndexes = [...new Set(refs.map((ref) => ref.pageIndex))].sort((left, right) => left - right);
  const refsByOriginal = {};
  const refsByCommonId = {};
  for (const ref of refs) {
    const pageName = pageNamesByIndex[String(ref.pageIndex)] || '';
    const enriched = { ...ref, pageName };
    refsByCommonId[ref.commonId] = enriched;
    refsByOriginal[ref.originalId] = refsByOriginal[ref.originalId] ?? [];
    if (!refsByOriginal[ref.originalId].some((item) => item.commonId === ref.commonId && item.pageName === pageName)) {
      refsByOriginal[ref.originalId].push(enriched);
    }
  }
  return { refsByOriginal, refsByCommonId, pageIndexes, pageNamesByIndex };
}

function dedupeCommonRefPairs(refPairs) {
  const result = [];
  const seen = new Set();
  for (const [sourceRef, targetRef] of refPairs) {
    if (!sourceRef?.commonId || !targetRef?.commonId) continue;
    if (sourceRef.commonId === targetRef.commonId) continue;
    const key = `${sourceRef.commonId}\u0000${targetRef.commonId}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push([sourceRef, targetRef]);
  }
  return result;
}

function selectCommonRefPairs(sourceRefs, targetRefs) {
  const samePagePairs = [];
  for (const sourceRef of sourceRefs) {
    for (const targetRef of targetRefs) {
      if (sourceRef.pageName && sourceRef.pageName === targetRef.pageName) samePagePairs.push([sourceRef, targetRef]);
    }
  }
  if (samePagePairs.length) return dedupeCommonRefPairs(samePagePairs);

  const sourceCommonIds = new Set(sourceRefs.map((ref) => ref.commonId));
  const targetCommonIds = new Set(targetRefs.map((ref) => ref.commonId));
  if (sourceCommonIds.size === 1) {
    return dedupeCommonRefPairs(targetRefs.map((targetRef) => [sourceRefs[0], targetRef]));
  }
  if (targetCommonIds.size === 1) {
    return dedupeCommonRefPairs(sourceRefs.map((sourceRef) => [sourceRef, targetRefs[0]]));
  }

  const sourceRef = [...sourceRefs].sort((left, right) => left.pageIndex - right.pageIndex)[0];
  const targetRef = [...targetRefs].sort((left, right) => left.pageIndex - right.pageIndex)[0];
  return dedupeCommonRefPairs([[sourceRef, targetRef]]);
}

function pairKey(sourceCommonId, targetCommonId) {
  return `${sourceCommonId}\u0000${targetCommonId}`;
}

function logicalGroupKey(edge) {
  return [
    edge.logicalLinkId,
    edge.stepIndex,
    edge.sourceOid,
    edge.targetOid,
    edge.parent
  ].join('\u0000');
}

function boxesOverlap(left, right, padding = 2) {
  return left.x + padding < right.x + right.width - padding
    && left.x + left.width - padding > right.x + padding
    && left.y + padding < right.y + right.height - padding
    && left.y + left.height - padding > right.y + padding;
}

function roundedLaneX(box) {
  return Math.round(box.x / 5) * 5;
}

function rotationDegrees(style) {
  const value = String(style || '').match(/(?:^|;)rotation=([^;]+)/)?.[1];
  const rotation = Number(value);
  return Number.isFinite(rotation) ? rotation : 0;
}

function visualGeometry(geometry) {
  const normalizedRotation = ((rotationDegrees(geometry.style) % 360) + 360) % 360;
  if (normalizedRotation !== 90 && normalizedRotation !== 270) return geometry;

  const centerX = geometry.x + geometry.width / 2;
  const centerY = geometry.y + geometry.height / 2;
  return {
    ...geometry,
    x: centerX - geometry.height / 2,
    y: centerY - geometry.width / 2,
    width: geometry.height,
    height: geometry.width
  };
}

function absoluteGeometry(cellId, index, seen = new Set()) {
  if (!cellId || seen.has(cellId)) return null;
  seen.add(cellId);
  const cell = index.cellsById[cellId];
  if (!cell || cell.getAttribute('vertex') !== '1') return null;
  const geometry = cell.querySelector('mxGeometry');
  if (!geometry) return null;

  let x = numberAttr(geometry, 'x');
  let y = numberAttr(geometry, 'y');
  const width = numberAttr(geometry, 'width');
  const height = numberAttr(geometry, 'height');
  const parent = cell.getAttribute('parent');
  if (parent && !['0', '1'].includes(parent)) {
    const parentGeometry = absoluteGeometry(parent, index, seen);
    if (parentGeometry) {
      x += parentGeometry.x;
      y += parentGeometry.y;
    }
  }
  return { x, y, width, height, style: cell.getAttribute('style') || '' };
}

const failures = [];
const stats = {
  pages: [],
  layerOrder: {},
  serviceGroups: { total: 0, security: 0, tech: 0, invalid: 0 },
  parent103: [],
  networkEdgesByPage: {},
  networkDeviceOverlaps: [],
  networkDeviceNetworkOverlaps: [],
  networkDeviceLaneSpans: [],
  segmentStackAlignment: [],
  commonLogicalLinks: {
    total: 0,
    groups: 0,
    multiEndpointGroups: 0,
    multiEndpointEdges: 0,
    samePageResolvedEdges: 0,
    invalidEndpointPairs: 0,
    parentLayers: {},
    pageNamesByIndex: {}
  },
  commonProviders: {
    sourceInternetProviderNetworks: 0,
    commonProviderNodes: 0,
    copiedInternetProviderNetworks: 0,
    edgesToCommonProviders: 0,
    placement: null
  },
  commonRootLayers: {
    invalidRootVisuals: [],
    duplicateLabels: {}
  }
};

const diagrams = Array.from(doc.getElementsByTagName('diagram'));
const sourcePageIdsByName = {};
for (const page of diagrams) {
  const pageName = page.getAttribute('name') || '';
  if (!pageName || pageName === commonPageName || pageName === 'Main Schema') continue;
  const root = page.getElementsByTagName('root')[0];
  sourcePageIdsByName[pageName] = buildElementIdSet(root);
}

for (const page of diagrams) {
  const pageName = page.getAttribute('name') || '';
  stats.pages.push(pageName);
  const root = page.getElementsByTagName('root')[0];
  if (!root) {
    failures.push(`${pageName}: missing root`);
    continue;
  }

  const children = Array.from(root.children ?? []);
  const pageIndex = buildPageIndex(root);
  const rootLayerIds = new Set(
    children
      .filter((element) => isPlainRootLayerCell(element))
      .map((element) => elementId(element))
  );
  for (const layerId of ['101', '102', '103']) {
    if (!rootLayerIds.has(layerId)) failures.push(`${pageName}: missing root layer ${layerId}`);
  }

  if (pageName === commonPageName) {
    const commonRootLayerLabels = {};
    for (const element of children) {
      const mx = mxCell(element);
      if (!mx || mx.getAttribute('parent') !== '0') continue;
      const id = elementId(element);
      if (id === '1') continue;
      const value = layerValue(element);
      if (isPlainRootLayerCell(element)) {
        if (value) commonRootLayerLabels[value] = (commonRootLayerLabels[value] ?? 0) + 1;
        continue;
      }
      stats.commonRootLayers.invalidRootVisuals.push({
        id,
        value,
        vertex: mx.getAttribute('vertex') || '',
        edge: mx.getAttribute('edge') || '',
        hasGeometry: Boolean(mx.querySelector('mxGeometry'))
      });
    }
    stats.commonRootLayers.duplicateLabels = Object.fromEntries(
      Object.entries(commonRootLayerLabels).filter(([, count]) => count > 1)
    );
    if (stats.commonRootLayers.invalidRootVisuals.length) {
      failures.push(`${pageName}: root contains visual/non-layer cells in layer panel: ${
        stats.commonRootLayers.invalidRootVisuals.slice(0, 10).map((item) => `${item.id}:${item.value}`).join(', ')
      }`);
    }
    for (const [label, count] of Object.entries(stats.commonRootLayers.duplicateLabels)) {
      failures.push(`${pageName}: root layer label "${label}" is duplicated ${count} times`);
    }
  }

  const topLevelContainerIndexes = children
    .map((element, index) => ({ element, index }))
    .filter(({ element }) => isTopLevelVisualContainer(element))
    .map(({ index }) => index);
  const foregroundLayerIndexes = children
    .map((element, index) => ({ element, index }))
    .filter(({ element }) => isForegroundLayer(element))
    .map(({ element, index }) => ({ id: elementId(element), value: layerValue(element), index }));
  const maxTopLevelContainerIndex = topLevelContainerIndexes.length ? Math.max(...topLevelContainerIndexes) : -1;
  stats.layerOrder[pageName] = {
    maxTopLevelContainerIndex,
    foregroundLayerIndexes
  };
  for (const layer of foregroundLayerIndexes) {
    if (layer.index <= maxTopLevelContainerIndex) {
      failures.push(`${pageName}: foreground layer ${layer.id || layer.value} is below top-level visual containers`);
    }
  }

  const cells = Array.from(root.getElementsByTagName('mxCell'));
  for (const cell of cells) {
    if (cell.getAttribute('parent') === emptyApplicationLayerId) {
      stats.parent103.push({ pageName, id: cell.getAttribute('id') || cell.parentElement?.getAttribute('id') || '' });
    }
  }

  let networkVertices = 0;
  let networkEdges = 0;
  const networkSegmentBoxes = [];
  const networkBoxes = [];
  const networkDeviceBoxes = [];
  const commonProviderBoxes = [];
  const commonContentBoxes = [];
  const commonLogicalGroups = {};
  const commonLogicalContext = pageName === commonPageName
    ? buildCommonRefs(root, sourcePageIdsByName)
    : null;
  if (commonLogicalContext) {
    stats.commonLogicalLinks.pageNamesByIndex = commonLogicalContext.pageNamesByIndex;
  }
  for (const element of children) {
    const mx = mxCell(element);
    if (!['Main Schema', 'Общая схема'].includes(pageName) && isInternetFacingProviderNetwork(element)) {
      stats.commonProviders.sourceInternetProviderNetworks += 1;
    }
    if (pageName === commonPageName && element.getAttribute('common_provider') === 'true') {
      stats.commonProviders.commonProviderNodes += 1;
    }
    if (pageName === commonPageName && isInternetFacingProviderNetwork(element)) {
      stats.commonProviders.copiedInternetProviderNetworks += 1;
      failures.push(`${pageName}: copied Internet-facing provider network ${elementId(element)} was not deduplicated`);
    }
    if (pageName === commonPageName && mx?.getAttribute('edge') === '1') {
      const source = mx.getAttribute('source') || '';
      const target = mx.getAttribute('target') || '';
      if (source.startsWith('common_provider_') || target.startsWith('common_provider_')) {
        stats.commonProviders.edgesToCommonProviders += 1;
      }
    }
    if (pageName === commonPageName && mx?.getAttribute('vertex') === '1') {
      const geometry = absoluteGeometry(mx.getAttribute('id') || elementId(element), pageIndex);
      if (geometry) {
        if (element.getAttribute('common_provider') === 'true') {
          commonProviderBoxes.push(geometry);
        } else if (isTopLevelVisualContainer(element) || isCommonLayeredVisualContainer(element)) {
          commonContentBoxes.push(geometry);
        }
      }
    }
    if (isTechGroup(element) && mx?.getAttribute('vertex') === '1') {
      stats.serviceGroups.total += 1;
      const parent = mx.getAttribute('parent');
      if (parent === '101') stats.serviceGroups.security += 1;
      else if (parent === '102') stats.serviceGroups.tech += 1;
      else {
        stats.serviceGroups.invalid += 1;
        failures.push(`${pageName}: service group ${elementId(element)} has parent ${parent}`);
      }
    }
    if (isNetworkVertex(element)) {
      networkVertices += 1;
      if (!['Main Schema', commonPageName].includes(pageName)) {
        const geometry = absoluteGeometry(mx.getAttribute('id') || elementId(element), pageIndex);
        if (geometry) {
          networkBoxes.push({
            id: elementId(element),
            parent: mx.getAttribute('parent') || '',
            label: element.getAttribute('label') || '',
            ...visualGeometry(geometry)
          });
        }
      }
    }
    if (isNetworkEdge(element)) networkEdges += 1;
    if (!['Main Schema', commonPageName].includes(pageName) && isNetworkSegmentVertex(element)) {
      const geometry = absoluteGeometry(mx.getAttribute('id') || elementId(element), pageIndex);
      if (geometry) {
        networkSegmentBoxes.push({
          id: elementId(element),
          label: element.getAttribute('label') || '',
          ...geometry
        });
      }
    }
    if (!['Main Schema', commonPageName].includes(pageName) && isNetworkDeviceVertex(element)) {
      const geometry = absoluteGeometry(mx.getAttribute('id') || elementId(element), pageIndex);
      if (geometry) {
        networkDeviceBoxes.push({
          id: elementId(element),
          parent: mx.getAttribute('parent') || '',
          label: element.getAttribute('label') || '',
          ...geometry
        });
      }
    }

    if (commonLogicalContext && element.getAttribute('common_logical_link') === 'true') {
      const parent = mx?.getAttribute('parent') || '';
      const edge = {
        id: elementId(element),
        logicalLinkId: element.getAttribute('logical_link_id') || '',
        sourceOid: element.getAttribute('source_oid') || '',
        targetOid: element.getAttribute('target_oid') || '',
        sourcePage: element.getAttribute('source_page') || '',
        targetPage: element.getAttribute('target_page') || '',
        stepIndex: element.getAttribute('step_index') || '',
        parent,
        source: mx?.getAttribute('source') || '',
        target: mx?.getAttribute('target') || ''
      };
      stats.commonLogicalLinks.total += 1;
      stats.commonLogicalLinks.parentLayers[parent] = (stats.commonLogicalLinks.parentLayers[parent] ?? 0) + 1;

      if (!pageIndex.cellsById[edge.source]) failures.push(`${pageName}: common logical link ${edge.id} has missing source cell ${edge.source}`);
      if (!pageIndex.cellsById[edge.target]) failures.push(`${pageName}: common logical link ${edge.id} has missing target cell ${edge.target}`);
      if (edge.source === edge.target) failures.push(`${pageName}: common logical link ${edge.id} connects ${edge.source} to itself`);
      const parentCell = pageIndex.cellsById[parent];
      if (!parentCell) failures.push(`${pageName}: common logical link ${edge.id} has missing parent layer ${parent}`);
      if (parent.startsWith('common_layer.logical.') && parentCell?.getAttribute('visible') !== '0') {
        failures.push(`${pageName}: common logical link ${edge.id} parent layer ${parent} is not hidden`);
      }
      if (parent === 'layer.logical.visible' && parentCell?.getAttribute('visible') === '0') {
        failures.push(`${pageName}: common logical link ${edge.id} uses hidden visible logical layer`);
      }

      commonLogicalGroups[logicalGroupKey(edge)] = commonLogicalGroups[logicalGroupKey(edge)] ?? [];
      commonLogicalGroups[logicalGroupKey(edge)].push(edge);
    }
  }
  stats.networkEdgesByPage[pageName] = { networkVertices, networkEdges };
  if (!['Main Schema', 'Общая схема'].includes(pageName) && networkVertices > 1 && networkEdges === 0) {
    failures.push(`${pageName}: page has ${networkVertices} network vertices but no network edge cells`);
  }
  if (pageName.includes('DC')) {
    const dmzSegments = networkSegmentBoxes.filter((segment) => /\bDMZ\b/.test(segment.label));
    const intWanSegments = networkSegmentBoxes.filter((segment) => /INT\s+WAN-EDGE/.test(segment.label));
    for (const dmz of dmzSegments) {
      const intWan = intWanSegments.find((segment) => segment.y >= dmz.y + dmz.height - 1);
      if (!intWan) continue;
      const alignment = {
        pageName,
        dmz: dmz.id,
        intWan: intWan.id,
        dmzBox: { x: dmz.x, y: dmz.y, width: dmz.width, height: dmz.height },
        intWanBox: { x: intWan.x, y: intWan.y, width: intWan.width, height: intWan.height }
      };
      stats.segmentStackAlignment.push(alignment);
      if (Math.abs(dmz.x - intWan.x) > 1) {
        failures.push(`${pageName}: ${intWan.id} x=${intWan.x} is not aligned with ${dmz.id} x=${dmz.x}`);
      }
      if (intWan.width + 1 < dmz.width) {
        failures.push(`${pageName}: ${intWan.id} width=${intWan.width} is narrower than ${dmz.id} width=${dmz.width}`);
      }
      if (intWan.y + 1 < dmz.y + dmz.height) {
        failures.push(`${pageName}: ${intWan.id} is not below ${dmz.id}`);
      }
    }
  }
  const edgeSegmentsById = Object.fromEntries(
    networkSegmentBoxes
      .filter((segment) => /EDGE/i.test(segment.label))
      .map((segment) => [segment.id, segment])
  );
  const devicesByEdgeSegmentId = {};
  for (const device of networkDeviceBoxes) {
    if (!edgeSegmentsById[device.parent]) continue;
    devicesByEdgeSegmentId[device.parent] = devicesByEdgeSegmentId[device.parent] ?? [];
    devicesByEdgeSegmentId[device.parent].push(device);
  }
  for (const [segmentId, devices] of Object.entries(devicesByEdgeSegmentId)) {
    if (devices.length < 4) continue;
    const xValues = [...new Set(devices.map(roundedLaneX))].sort((left, right) => left - right);
    const span = Math.max(...xValues) - Math.min(...xValues);
    const laneSpan = {
      pageName,
      parent: segmentId,
      segmentLabel: edgeSegmentsById[segmentId].label,
      deviceCount: devices.length,
      xValues,
      span
    };
    stats.networkDeviceLaneSpans.push(laneSpan);
    if (xValues.length < 2 || span < 80) {
      failures.push(`${pageName}: edge segment ${segmentId} has ${devices.length} network devices collapsed into x lanes ${xValues.join(', ')}`);
    }
  }
  for (let leftIndex = 0; leftIndex < networkDeviceBoxes.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < networkDeviceBoxes.length; rightIndex++) {
      const left = networkDeviceBoxes[leftIndex];
      const right = networkDeviceBoxes[rightIndex];
      if (left.parent !== right.parent || !boxesOverlap(left, right)) continue;
      const overlap = {
        pageName,
        parent: left.parent,
        left: left.id,
        right: right.id,
        leftBox: { x: left.x, y: left.y, width: left.width, height: left.height },
        rightBox: { x: right.x, y: right.y, width: right.width, height: right.height }
      };
      stats.networkDeviceOverlaps.push(overlap);
      failures.push(`${pageName}: network devices overlap in ${left.parent}: ${left.id} and ${right.id}`);
    }
  }
  for (const network of networkBoxes) {
    for (const device of networkDeviceBoxes) {
      if (network.parent !== device.parent || !boxesOverlap(network, device)) continue;
      const overlap = {
        pageName,
        parent: network.parent,
        network: network.id,
        device: device.id,
        networkBox: { x: network.x, y: network.y, width: network.width, height: network.height },
        deviceBox: { x: device.x, y: device.y, width: device.width, height: device.height }
      };
      stats.networkDeviceNetworkOverlaps.push(overlap);
      failures.push(`${pageName}: network ${network.id} overlaps network device ${device.id} in ${network.parent}`);
    }
  }
  if (pageName === commonPageName && commonProviderBoxes.length && commonContentBoxes.length) {
    const providerRight = Math.max(...commonProviderBoxes.map((box) => box.x + box.width));
    const contentLeft = Math.min(...commonContentBoxes.map((box) => box.x));
    stats.commonProviders.placement = {
      providerRight,
      contentLeft,
      gap: contentLeft - providerRight
    };
    if (providerRight >= contentLeft) {
      failures.push(`Общая схема: common_provider nodes are not placed left of content (providerRight=${providerRight}, contentLeft=${contentLeft})`);
    }
  }

  for (const element of children) {
    if (element.getAttribute('common_logical_link') !== 'true') continue;
    const parent = mxCell(element)?.getAttribute('parent') || '';
    if (parent === '1') failures.push(`${pageName}: common logical link ${elementId(element)} is on base layer 1`);
  }

  if (commonLogicalContext) {
    const { refsByOriginal, refsByCommonId, pageIndexes, pageNamesByIndex } = commonLogicalContext;
    for (const pageIndexKey of pageIndexes) {
      if (!pageNamesByIndex[String(pageIndexKey)]) {
        failures.push(`${pageName}: cannot infer source page for common_${pageIndexKey}_* refs`);
      }
    }

    const groups = Object.values(commonLogicalGroups);
    stats.commonLogicalLinks.groups = groups.length;
    for (const edges of groups) {
      const first = edges[0];
      const sourceRefs = refsByOriginal[first.sourceOid] ?? [];
      const targetRefs = refsByOriginal[first.targetOid] ?? [];
      if (!sourceRefs.length || !targetRefs.length) {
        stats.commonLogicalLinks.invalidEndpointPairs += edges.length;
        failures.push(`${pageName}: common logical group ${first.logicalLinkId} step=${first.stepIndex} has unresolved refs ${first.sourceOid} -> ${first.targetOid}`);
        continue;
      }

      const expectedPairs = selectCommonRefPairs(sourceRefs, targetRefs);
      const expectedPairKeys = new Set(expectedPairs.map(([sourceRef, targetRef]) => pairKey(sourceRef.commonId, targetRef.commonId)));
      const actualPairKeys = new Set(edges.map((edge) => pairKey(edge.source, edge.target)));

      if (sourceRefs.length > 1 || targetRefs.length > 1) {
        stats.commonLogicalLinks.multiEndpointGroups += 1;
        stats.commonLogicalLinks.multiEndpointEdges += edges.length;
      }

      for (const edge of edges) {
        const sourceRef = refsByCommonId[edge.source];
        const targetRef = refsByCommonId[edge.target];
        if (sourceRef?.pageName && edge.sourcePage !== sourceRef.pageName) {
          failures.push(`${pageName}: common logical link ${edge.id} source_page=${edge.sourcePage} does not match ${edge.source}`);
        }
        if (targetRef?.pageName && edge.targetPage !== targetRef.pageName) {
          failures.push(`${pageName}: common logical link ${edge.id} target_page=${edge.targetPage} does not match ${edge.target}`);
        }
        if (sourceRef?.pageName && targetRef?.pageName && sourceRef.pageName === targetRef.pageName) {
          stats.commonLogicalLinks.samePageResolvedEdges += 1;
        }
      }

      for (const expectedPair of expectedPairKeys) {
        if (actualPairKeys.has(expectedPair)) continue;
        const [sourceCommonId, targetCommonId] = expectedPair.split('\u0000');
        stats.commonLogicalLinks.invalidEndpointPairs += 1;
        failures.push(`${pageName}: common logical group ${first.logicalLinkId} step=${first.stepIndex} parent=${first.parent} is missing expected pair ${sourceCommonId} -> ${targetCommonId}`);
      }
      for (const actualPair of actualPairKeys) {
        if (expectedPairKeys.has(actualPair)) continue;
        const [sourceCommonId, targetCommonId] = actualPair.split('\u0000');
        stats.commonLogicalLinks.invalidEndpointPairs += 1;
        failures.push(`${pageName}: common logical group ${first.logicalLinkId} step=${first.stepIndex} parent=${first.parent} has unexpected pair ${sourceCommonId} -> ${targetCommonId}`);
      }
      if (actualPairKeys.size !== edges.length) {
        failures.push(`${pageName}: common logical group ${first.logicalLinkId} step=${first.stepIndex} parent=${first.parent} has duplicate endpoint pairs`);
      }
    }
  }
}

if (stats.parent103.length) {
  failures.push(`layer 103 is not empty: ${stats.parent103.slice(0, 20).map((item) => `${item.pageName}:${item.id}`).join(', ')}`);
}

if (stats.commonProviders.sourceInternetProviderNetworks > 0) {
  if (stats.commonProviders.commonProviderNodes === 0) {
    failures.push('Общая схема: missing common_provider nodes for Internet-facing provider networks');
  }
  if (stats.commonProviders.edgesToCommonProviders === 0) {
    failures.push('Общая схема: no edges are reconnected to common_provider nodes');
  }
}

const report = { file: drawioPath, failures, stats };
console.log(JSON.stringify(report, null, 2));
if (failures.length) process.exit(1);
