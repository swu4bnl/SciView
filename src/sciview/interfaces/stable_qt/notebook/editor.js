import 'core-js/actual/array/at';
import { Crepe } from '@milkdown/crepe';
import { editorViewCtx, serializerCtx } from '@milkdown/kit/core';
import { imageSchema } from '@milkdown/kit/preset/commonmark';
import { imageBlockSchema, imageBlockView } from '@milkdown/kit/component/image-block';
import { inlineImageView } from '@milkdown/kit/component/image-inline';
import { listenerCtx } from '@milkdown/kit/plugin/listener';
import { $view, getMarkdown, replaceAll } from '@milkdown/kit/utils';
import { NodeSelection, TextSelection } from '@milkdown/kit/prose/state';
import { Fragment } from '@milkdown/kit/prose/model';
import '@milkdown/crepe/theme/common/style.css';
import '@milkdown/crepe/theme/classic.css';
import 'katex/dist/katex.min.css';
import './editor.css';

let editor, bridge, strings, colormaps = [], scales = [], suppress = false;
let objects = {};
const cards = new Map();
const expandedFigures = new Map();
let settingsFigureId = null;
const settingsPanel = document.getElementById('figure-settings');
const settingsBody = document.getElementById('figure-settings-body');
const outline = document.getElementById('outline');
const outlineRail = document.getElementById('outline-rail');
const svgNamespace = 'http://www.w3.org/2000/svg';
const plotIcon = '<svg viewBox="0 0 24 24"><path d="M3 3v18h18M5 16l5-8 5 5 5-9" fill="none" stroke="currentColor" stroke-width="2"/></svg>';

const objectId = node => /^sciview:([0-9a-f]{32})$/.exec(
  node.attrs.title || node.attrs.caption || '',
)?.[1];

function closeFigureSettings() {
  const previous = cards.get(settingsFigureId);
  settingsFigureId = null;
  settingsPanel.hidden = true;
  settingsBody.replaceChildren();
  settingsPanel.parentElement?.classList.remove('settings-open');
  document.querySelector('.notebook-app').append(settingsPanel);
  previous?.syncTools();
}

function svgElement(name, attributes = {}, text = null) {
  const element = document.createElementNS(svgNamespace, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  if (text !== null) element.textContent = text;
  return element;
}

// Stroke icons in the same 24px outline style as SciView's Qt toolbar assets.
const iconPaths = {
  notebook: ['M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z', 'M8 3v18', 'M11 8h5', 'M11 16l2-2.5 1.5 1.5 1.5-3'],
  file: ['M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M10 13h6', 'M13 10l3 3-3 3'],
  save: ['M3 19V5a2 2 0 0 1 2-2h11.17a2 2 0 0 1 1.42.59l2.83 2.82A2 2 0 0 1 21 7.83V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M8 3v6h8V3', 'M6 21v-8h12v8'],
  expand: ['M9 4H4v5', 'M4 4l6 6', 'M15 20h5v-5', 'M20 20l-6-6'],
  collapse: ['M4 10h6V4', 'M10 10L4 4', 'M20 14h-6v6', 'M14 14l6 6'],
  settings: ['M4 6h9', 'M17 6h3', 'M15 4v4', 'M4 12h3', 'M11 12h9', 'M9 10v4', 'M4 18h11', 'M19 18h1', 'M17 16v4'],
  pan: ['M12 3v18', 'M3 12h18', 'M9 6l3-3 3 3', 'M9 18l3 3 3-3', 'M6 9l-3 3 3 3', 'M18 9l3 3-3 3'],
  zoom: ['M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 1 0 0-13z', 'M15.5 15.5L20 20', 'M10.5 8v5', 'M8 10.5h5'],
  home: ['M4 9V4h5', 'M20 9V4h-5', 'M4 15v5h5', 'M20 15v5h-5', 'M8 15l3-4 2 2 3-4'],
  mark: ['M12 3v4', 'M12 17v4', 'M3 12h4', 'M17 12h4', 'M12 9a3 3 0 1 0 0 6 3 3 0 1 0 0-6z'],
  undo_mark: ['M4.5 8H15s5 0 5 4.7C20 18 15 18 15 18H6.3', 'M7.5 11.5L4 8l3.5-3.5'],
  update: ['M20 12a8 8 0 1 1-2.3-5.6', 'M20 4v4h-4'],
  close: ['M6 6l12 12', 'M18 6L6 18'],
};

function iconElement(name) {
  const icon = svgElement('svg', {
    viewBox: '0 0 24 24', class: 'ui-icon', 'aria-hidden': 'true', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
  });
  for (const d of iconPaths[name]) icon.append(svgElement('path', { d }));
  return icon;
}

function setIcon(control, name, label) {
  control.replaceChildren(iconElement(name));
  control.classList.add('icon-button');
  control.title = label;
  control.setAttribute('aria-label', label);
}
function niceStep(range, target = 5) {
  const raw = range / target;
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const scaled = raw / magnitude;
  return (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10) * magnitude;
}

function superscript(value) {
  const digits = { '-': '⁻', '+': '⁺', 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹' };
  return [...String(value)].map(character => digits[character] || character).join('');
}

function unitText(value) {
  return value.replace(/\^(?:\{([+-]?\d+)\}|([+-]?\d+))/g, (_match, braced, plain) => superscript(braced || plain));
}

function tickValues(range, step) {
  // Multiply from an integer index so ticks land exactly on 0 instead of ±1e-17.
  const ticks = [];
  for (let index = Math.ceil(range[0] / step); index * step <= range[1]; index += 1) {
    ticks.push(Number((index * step).toPrecision(12)));
  }
  return ticks;
}

function tickText(value) {
  if (value === 0) return '0';
  const magnitude = Math.abs(value);
  if (magnitude < 0.001 || magnitude >= 10000) {
    const [coefficient, exponent] = value.toExponential(2).split('e');
    return `${Number(coefficient)}×10${superscript(Number(exponent))}`;
  }
  return Number(value.toPrecision(4)).toString();
}

function extent(values) {
  let low = Infinity;
  let high = -Infinity;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    low = Math.min(low, value);
    high = Math.max(high, value);
  }
  if (!Number.isFinite(low) || !Number.isFinite(high)) return null;
  if (low === high) {
    const pad = Math.abs(low) * 0.05 || 1;
    low -= pad;
    high += pad;
  } else {
    const pad = (high - low) * 0.04;
    low -= pad;
    high += pad;
  }
  return [low, high];
}

function curveDisplayY(curve, position, spacing) {
  return curve.y[position] * curve.gain + curve.index * spacing;
}

function plotRanges(object, visibleCurves) {
  let xLow = Infinity;
  let xHigh = -Infinity;
  let yLow = Infinity;
  let yHigh = -Infinity;
  for (const curve of visibleCurves) {
    for (let position = 0; position < Math.min(curve.x.length, curve.y.length); position += 1) {
      const x = curve.x[position];
      const y = curveDisplayY(curve, position, object.state.spacing);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        xLow = Math.min(xLow, x);
        xHigh = Math.max(xHigh, x);
        yLow = Math.min(yLow, y);
        yHigh = Math.max(yHigh, y);
      }
    }
  }
  const dataX = extent([xLow, xHigh]);
  const dataY = extent([yLow, yHigh]);
  if (!dataX || !dataY) return null;
  const requested = object.state.view_range;
  return requested && requested.length === 2 ? requested : [dataX, dataY];
}

function drawAxes(svg, chart, object, ranges) {
  const [xRange, yRange] = ranges;
  const { width, height, left, right, top, bottom } = chart;
  const xAt = value => left + (value - xRange[0]) / (xRange[1] - xRange[0]) * (width - left - right);
  const yAt = value => top + (yRange[1] - value) / (yRange[1] - yRange[0]) * (height - top - bottom);
  const xStep = niceStep(xRange[1] - xRange[0], Math.max(2, Math.floor((width - left - right) / 90)));
  const yStep = niceStep(yRange[1] - yRange[0], Math.max(2, Math.floor((height - top - bottom) / 55)));

  for (const tick of tickValues(xRange, xStep)) {
    const x = xAt(tick);
    svg.append(svgElement('line', {
      x1: x, x2: x, y1: top, y2: height - bottom,
      stroke: 'var(--border)', 'stroke-opacity': '.45',
    }));
    svg.append(svgElement('text', {
      x, y: height - bottom + 16, fill: 'var(--text)', 'font-size': 11,
      'text-anchor': 'middle',
    }, tickText(tick)));
  }
  for (const tick of tickValues(yRange, yStep)) {
    const y = yAt(tick);
    svg.append(svgElement('line', {
      x1: left, x2: width - right, y1: y, y2: y,
      stroke: 'var(--border)', 'stroke-opacity': '.45',
    }));
    svg.append(svgElement('text', {
      x: left - 7, y: y + 4, fill: 'var(--text)', 'font-size': 11,
      'text-anchor': 'end',
    }, tickText(tick)));
  }
  svg.append(svgElement('path', {
    d: `M${left},${top}V${height - bottom}H${width - right}`,
    fill: 'none', stroke: 'var(--text)', 'stroke-width': 1,
  }));
  svg.append(svgElement('text', {
    x: (left + width - right) / 2, y: height - 4,
    fill: 'var(--text)', 'font-size': 12, 'text-anchor': 'middle',
    'data-figure-label': 'x',
    tabindex: 0, role: 'button', 'aria-label': strings.x_label,
  }, `${object.figure.x_label}${object.figure.x_units ? ` (${unitText(object.figure.x_units)})` : ''}`));
  svg.append(svgElement('text', {
    x: 13, y: (top + height - bottom) / 2,
    fill: 'var(--text)', 'font-size': 12, 'text-anchor': 'middle',
    transform: `rotate(-90 13 ${(top + height - bottom) / 2})`,
    'data-figure-label': 'y',
    tabindex: 0, role: 'button', 'aria-label': strings.y_label,
  }, `${object.figure.y_label}${object.figure.y_units ? ` (${unitText(object.figure.y_units)})` : ''}`));
  for (const label of svg.querySelectorAll('[data-figure-label]')) makeEditable(label, strings.edit_axis_hint);
  return { xAt, yAt, xRange, yRange };
}

function curvePath(curve, scales, spacing) {
  let commands = '';
  let penDown = false;
  const count = Math.min(curve.x.length, curve.y.length);
  for (let position = 0; position < count; position += 1) {
    const x = curve.x[position];
    const y = curveDisplayY(curve, position, spacing);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      penDown = false;
      continue;
    }
    commands += `${penDown ? 'L' : 'M'}${scales.xAt(x).toFixed(2)},${scales.yAt(y).toFixed(2)}`;
    penDown = true;
  }
  return commands;
}

function nearestSample(curve, clientX, clientY, svg, chart, scales, spacing) {
  const bounds = svg.getBoundingClientRect();
  const xScale = chart.width / bounds.width;
  const yScale = chart.height / bounds.height;
  const pointerX = (clientX - bounds.left) * xScale;
  const pointerY = (clientY - bounds.top) * yScale;
  let nearest = -1;
  let distance = Infinity;
  const count = Math.min(curve.x.length, curve.y.length);
  for (let position = 0; position < count; position += 1) {
    const x = curve.x[position];
    const y = curveDisplayY(curve, position, spacing);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const dx = scales.xAt(x) - pointerX;
    const dy = scales.yAt(y) - pointerY;
    const candidate = dx * dx + dy * dy;
    if (candidate < distance) {
      distance = candidate;
      nearest = position;
    }
  }
  return nearest;
}

function nearestCurve(card, event) {
  if (!card.chart) return null;
  const object = objects[card.id];
  const hidden = new Set(object.state.hidden_sources);
  const bounds = card.svg.getBoundingClientRect();
  const { chart, scales } = card.chart;
  const x = (event.clientX - bounds.left) * chart.width / bounds.width;
  const y = (event.clientY - bounds.top) * chart.height / bounds.height;
  let closest = null;
  let distance = 14 ** 2;
  for (const curve of object.curves) {
    if (hidden.has(curve.source)) continue;
    let previous = null;
    for (let point = 0; point < Math.min(curve.x.length, curve.y.length); point += 1) {
      const sampleX = scales.xAt(curve.x[point]);
      const sampleY = scales.yAt(curveDisplayY(curve, point, object.state.spacing));
      if (!Number.isFinite(sampleX) || !Number.isFinite(sampleY)) {
        previous = null;
        continue;
      }
      const startX = previous?.x ?? sampleX;
      const startY = previous?.y ?? sampleY;
      const dx = sampleX - startX;
      const dy = sampleY - startY;
      const length = dx * dx + dy * dy;
      const along = length ? Math.max(0, Math.min(1, ((x - startX) * dx + (y - startY) * dy) / length)) : 0;
      const candidate = (startX + along * dx - x) ** 2 + (startY + along * dy - y) ** 2;
      if (candidate < distance) {
        distance = candidate;
        closest = { index: curve.index, point: previous && along < .5 ? point - 1 : point };
      }
      previous = { x: sampleX, y: sampleY };
    }
  }
  return closest;
}

function chartClip(svg, card, chart) {
  const clipId = `plot-clip-${card.id}`;
  const definitions = svgElement('defs');
  const clip = svgElement('clipPath', { id: clipId });
  clip.append(svgElement('rect', {
    x: chart.left, y: chart.top,
    width: chart.width - chart.left - chart.right,
    height: chart.height - chart.top - chart.bottom,
  }));
  definitions.append(clip);
  svg.prepend(definitions);
  return { clipId, definitions };
}

function imageValues(card, object) {
  if (card.imageValues?.data === object.image.data) return card.imageValues.values;
  const bytes = Uint8Array.from(atob(object.image.data), character => character.charCodeAt(0));
  const values = new Float32Array(bytes.buffer, 0, object.image.width * object.image.height);
  card.imageValues = { data: object.image.data, values };
  return values;
}

function intensityPosition(value, object) {
  const [low, high] = object.limits;
  if (!Number.isFinite(value)) return null;
  if (object.state.scale === 'log') {
    const floor = Math.log10(low);
    return (Math.log10(Math.max(value, low)) - floor) / (Math.log10(high) - floor);
  }
  return (value - low) / (high - low);
}

function imageDataUrl(card, object) {
  const key = `${object.state.colormap}|${object.state.scale}|${object.limits.join(',')}|${object.lut.join('')}`;
  if (card.imageBitmap?.key === key && card.imageBitmap.data === object.image.data) return card.imageBitmap.url;
  const { width, height } = object.image;
  const values = imageValues(card, object);
  const lut = object.lut.map(color => [1, 3, 5].map(offset => parseInt(color.slice(offset, offset + 2), 16)));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  const pixels = context.createImageData(width, height);
  for (let row = 0; row < height; row += 1) {
    // Row 0 of the scientific map lies at the bottom of the axes.
    const target = (height - 1 - row) * width;
    for (let column = 0; column < width; column += 1) {
      const position = intensityPosition(values[row * width + column], object);
      const offset = (target + column) * 4;
      if (position === null) continue;
      const [red, green, blue] = lut[Math.max(0, Math.min(255, Math.round(position * 255)))];
      pixels.data[offset] = red;
      pixels.data[offset + 1] = green;
      pixels.data[offset + 2] = blue;
      pixels.data[offset + 3] = 255;
    }
  }
  context.putImageData(pixels, 0, 0);
  card.imageBitmap = { key, data: object.image.data, url: canvas.toDataURL('image/png') };
  return card.imageBitmap.url;
}

function drawColorbar(svg, chart, object, cardId) {
  const gradientId = `colorbar-${cardId}`;
  const gradient = svgElement('linearGradient', { id: gradientId, x1: 0, y1: 1, x2: 0, y2: 0 });
  for (let stop = 0; stop <= 16; stop += 1) {
    gradient.append(svgElement('stop', {
      offset: `${(stop / 16) * 100}%`, 'stop-color': object.lut[Math.round((stop / 16) * 255)],
    }));
  }
  svg.querySelector('defs').append(gradient);
  const x = chart.width - chart.right + 14;
  const top = chart.top;
  const bottom = chart.height - chart.bottom;
  svg.append(svgElement('rect', {
    x, y: top, width: 12, height: bottom - top, fill: `url(#${gradientId})`,
    stroke: 'var(--text)', 'stroke-width': .5, class: 'image-colorbar',
  }));
  const [low, high] = object.limits;
  const ticks = 5;
  for (let tick = 0; tick <= ticks; tick += 1) {
    const fraction = tick / ticks;
    const value = object.state.scale === 'log'
      ? 10 ** (Math.log10(low) + fraction * (Math.log10(high) - Math.log10(low)))
      : low + fraction * (high - low);
    const y = bottom - fraction * (bottom - top);
    svg.append(svgElement('line', { x1: x + 12, x2: x + 15, y1: y, y2: y, stroke: 'var(--text)' }));
    svg.append(svgElement('text', {
      x: x + 18, y: y + 4, fill: 'var(--text)', 'font-size': 10,
    }, tickText(Number(value.toPrecision(3)))));
  }
}

function imageSample(card, object, x, y) {
  const [[x0, x1], [y0, y1]] = object.image.extent;
  const column = Math.floor((x - x0) / (x1 - x0) * object.image.width);
  const row = Math.floor((y - y0) / (y1 - y0) * object.image.height);
  if (column < 0 || row < 0 || column >= object.image.width || row >= object.image.height) return null;
  return imageValues(card, object)[row * object.image.width + column];
}

function renderImage(card) {
  const object = objects[card.id];
  const bounds = card.surface.getBoundingClientRect();
  const width = Math.max(1, Math.round(bounds.width || 640));
  const height = Math.max(160, Math.round(bounds.height || object.height));
  const svg = card.svg;
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.replaceChildren();
  card.chart = null;
  const extent = object.image.extent;
  const requested = object.state.view_range;
  const ranges = requested && requested.length === 2 ? requested : extent.map(range => range.slice());
  const chart = { width, height, left: 64, right: 92, top: 16, bottom: 42 };
  const scales = drawAxes(svg, chart, object, ranges);
  card.chart = { chart, scales };
  const { clipId } = chartClip(svg, card, chart);
  const xs = [scales.xAt(extent[0][0]), scales.xAt(extent[0][1])];
  const ys = [scales.yAt(extent[1][0]), scales.yAt(extent[1][1])];
  const group = svgElement('g', { 'clip-path': `url(#${clipId})` });
  const image = svgElement('image', {
    href: imageDataUrl(card, object),
    x: Math.min(...xs), y: Math.min(...ys),
    width: Math.abs(xs[1] - xs[0]), height: Math.abs(ys[1] - ys[0]),
    preserveAspectRatio: 'none', 'data-image-map': '',
  });
  image.style.imageRendering = 'pixelated';
  group.append(image);
  svg.append(group);
  drawColorbar(svg, chart, object, card.id);
  card.readout.textContent = strings.hover_map;
}

function renderPlot(card) {
  const object = objects[card.id];
  if (!object) return;
  if (object.kind === 'image') {
    renderImage(card);
    return;
  }
  const bounds = card.surface.getBoundingClientRect();
  const width = Math.max(1, Math.round(bounds.width || 640));
  const height = Math.max(160, Math.round(bounds.height || object.height));
  const svg = card.svg;
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.replaceChildren();
  card.chart = null;

  const hidden = new Set(object.state.hidden_sources || []);
  const visible = object.curves.filter(curve =>
    curve.x.length && curve.y.length && !hidden.has(curve.source));
  const ranges = plotRanges(object, visible);
  if (!ranges) {
    card.readout.textContent = strings.hover_empty;
    return;
  }
  const chart = { width, height, left: 64, right: 18, top: 16, bottom: 42 };
  const scales = drawAxes(svg, chart, object, ranges);
  card.chart = { chart, scales };
  const { clipId } = chartClip(svg, card, chart);

  for (const curve of visible) {
    const d = curvePath(curve, scales, object.state.spacing);
    if (!d) continue;
    const selected = object.state.selected_index === curve.index;
    const hovered = card.hoveredIndex === curve.index;
    const group = svgElement('g', {
      'data-curve-index': curve.index,
      'clip-path': `url(#${clipId})`,
    });
    const dash = {
      solid: '',
      dash: '7 4',
      dot: '2 4',
      dash_dot: '7 3 2 3',
    }[curve.line_style] || '';
    group.append(svgElement('path', {
      d, fill: 'none', stroke: curve.color,
      'stroke-width': Math.max(0.75, curve.line_width * (selected || hovered ? 1.7 : 1)),
      'stroke-dasharray': dash,
      'stroke-opacity': curve.opacity,
      'vector-effect': 'non-scaling-stroke',
      'pointer-events': 'none',
    }));
    const hit = svgElement('path', {
      d, fill: 'none', stroke: 'transparent', 'stroke-width': 14,
      'pointer-events': 'stroke', 'data-curve-index': curve.index,
      tabindex: 0, role: 'button',
      'aria-label': curve.source.split(/[\\/]/).at(-1),
    });
    group.append(hit);
    svg.append(group);
  }

  const curvesByIndex = new Map(object.curves.map(curve => [curve.index, curve]));
  for (const [index, point] of object.state.marks || []) {
    const curve = curvesByIndex.get(index);
    if (!curve || hidden.has(curve.source) || !Number.isInteger(point)) continue;
    if (point < 0 || point >= curve.x.length || !Number.isFinite(curve.x[point])) continue;
    const x = scales.xAt(curve.x[point]);
    const y = scales.yAt(curveDisplayY(curve, point, object.state.spacing));
    if (x < chart.left || x > width - chart.right || y < chart.top || y > height - chart.bottom) continue;
    svg.append(svgElement('circle', {
      cx: x,
      cy: y,
      r: 4, fill: 'var(--accent)', stroke: 'var(--text)', 'stroke-width': 1,
      'pointer-events': 'none',
    }));
    svg.append(svgElement('text', {
      x: Math.min(width - chart.right - 4, Math.max(chart.left + 4, x)),
      y: Math.max(chart.top + 12, y - 10),
      fill: 'var(--text)', 'font-size': 11,
      'text-anchor': x > width / 2 ? 'end' : 'start',
      'pointer-events': 'none',
    }, `${object.figure.x_label}=${tickText(curve.x[point])} ${unitText(object.figure.x_units)}, ${object.figure.y_label}=${tickText(curve.y[point])}`));
  }
  card.readout.textContent = strings.hover_empty;
}

function makeEditable(element, hint) {
  element.classList.add('figure-editable');
  if (!(element instanceof SVGElement)) element.title = hint;
}

function addFigureTool(parent, labelText, control, output = null) {
  const row = document.createElement('label');
  row.className = 'figure-tool';
  const label = document.createElement('span');
  label.textContent = labelText;
  row.append(label, control);
  if (output) row.append(output);
  parent.append(row);
  return row;
}

function toolGroup(parent, label) {
  const section = document.createElement('section');
  section.className = 'figure-tool-group';
  section.setAttribute('aria-label', label);
  parent.append(section);
  return section;
}

function spacingText(object, value) {
  const unit = object.figure.y_units;
  return `${tickText(value)}${unit ? ` ${unitText(unit)}` : ''}`;
}

function plotNodeView(node, view, getPos) {
  const id = objectId(node);
  const kind = objects[id]?.kind || 'curves';
  const dom = document.createElement('div');
  dom.className = 'plot-card';
  dom.contentEditable = 'false';
  dom.dataset.objectId = id;
  dom.tabIndex = 0;
  dom.setAttribute('role', 'group');
  dom.setAttribute('aria-label', objects[id]?.title || id);
  const editHint = document.createElement('div');
  editHint.className = 'figure-edit-hint';
  editHint.hidden = true;
  editHint.setAttribute('aria-hidden', 'true');
  dom.append(editHint);
  function showEditHint(element) {
    if (!element || element === document.activeElement || element.closest('.axis-label-editor')) {
      editHint.hidden = true;
      return;
    }
    const bounds = element.getBoundingClientRect();
    const cardBounds = dom.getBoundingClientRect();
    editHint.style.left = `${bounds.left - cardBounds.left - 3}px`;
    editHint.style.top = `${bounds.top - cardBounds.top - 2}px`;
    editHint.style.width = `${bounds.width + 6}px`;
    editHint.style.height = `${bounds.height + 4}px`;
    editHint.hidden = false;
  }
  dom.addEventListener('pointerover', event => showEditHint(event.target.closest?.('.figure-editable')));
  dom.addEventListener('pointerout', event => {
    const editable = event.target.closest?.('.figure-editable');
    if (editable && !editable.contains(event.relatedTarget)) editHint.hidden = true;
  });
  dom.addEventListener('focusin', () => { editHint.hidden = true; });
  dom.addEventListener('mousedown', event => {
    if (event.target.closest('input, select, button, summary, .figure-settings, .figure-context-tools, .figure-editable, .legend-entry, .plot-resize')) return;
    if (event.target.closest('.plot-surface')) return;
    selectFigure();
    hideElementTools();
  });
  dom.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target === dom) {
      event.preventDefault();
      selectFigure();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      setNavigationMode('pan');
      continueWriting();
    } else if (kind !== 'image' && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z'
      && !event.target.closest('input, select')) {
      event.preventDefault();
      bridge.setPlotControl(id, 'undo_mark', '');
    }
  });
  function selectFigure(focus = true) {
    const position = getPos();
    if (typeof position === 'number') {
      view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc, position)));
      if (focus) view.focus();
    }
  }
  function continueWriting() {
    const position = getPos();
    if (typeof position !== 'number') return;
    const after = position + view.state.doc.nodeAt(position).nodeSize;
    let transaction = view.state.tr;
    if (after === transaction.doc.content.size) {
      transaction = transaction.insert(after, view.state.schema.nodes.paragraph.create());
    }
    transaction.setSelection(TextSelection.near(transaction.doc.resolve(after), 1));
    view.dispatch(transaction.scrollIntoView());
    view.focus();
  }

  const header = document.createElement('div');
  header.className = 'plot-header';
  const title = document.createElement('input');
  title.type = 'text';
  title.maxLength = 256;
  title.className = 'plot-title';
  title.dataset.figureField = 'title';
  title.setAttribute('aria-label', strings.figure_title);
  title.setAttribute('role', 'textbox');
  makeEditable(title, strings.edit_title_hint);
  title.addEventListener('mousedown', () => selectFigure(false));
  title.addEventListener('focus', () => {
    hideElementTools('title');
  });
  title.addEventListener('change', () => bridge.setFigureText(id, 'title', title.value));
  title.addEventListener('keydown', event => {
    event.stopPropagation();
    if (event.key === 'Enter' || event.key === 'Escape') {
      event.preventDefault();
      if (event.key === 'Escape') title.value = objects[id].title;
      title.blur();
    }
  });
  const count = document.createElement('span');
  count.className = 'plot-count';
  header.append(title);
  header.append(count);
  const update = document.createElement('button');
  update.type = 'button';
  update.className = 'plot-update';
  update.dataset.plotAction = 'update';
  update.hidden = true;
  update.title = strings.update_stale_hint;
  update.append(iconElement('update'), document.createTextNode(strings.update_stale));
  update.addEventListener('mousedown', event => event.preventDefault());
  update.addEventListener('click', () => bridge.updateFigure(id));
  header.append(update);
  const tools = document.createElement('div');
  tools.className = 'plot-tools';
  function tool(name, label, action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.plotAction = name;
    setIcon(button, name, label);
    button.addEventListener('mousedown', event => event.preventDefault());
    button.addEventListener('click', () => {
      selectFigure();
      action();
    });
    tools.append(button);
    return button;
  }
  const expand = tool('expand', strings.expand, () => {
    if (card.expanded) {
      const previous = expandedFigures.get(id);
      expandedFigures.delete(id);
      bridge.resizePlot(id, previous.width, previous.height);
    } else {
      const object = objects[id];
      expandedFigures.set(id, { width: object.width, height: object.height });
      bridge.resizePlot(id, 100, Math.max(object.height, Math.min(760, Math.round(
        document.getElementById('editor').clientHeight * .65,
      ))));
    }
    dom.classList.toggle('expanded', card.expanded);
    document.querySelector('.milkdown').classList.toggle(
      'has-expanded-figure', [...cards.values()].some(item => item.expanded),
    );
    setIcon(expand, card.expanded ? 'collapse' : 'expand', card.expanded ? strings.collapse : strings.expand);
    expand.setAttribute('aria-expanded', String(card.expanded));
    cards.get(id)?.refresh();
  });
  expand.setAttribute('aria-expanded', 'false');
  const settings = tool('settings', strings.figure_controls, () => {
    if (settingsFigureId === id) closeFigureSettings();
    else card.openSettings(true);
  });
  settings.setAttribute('aria-controls', 'figure-settings');
  settings.setAttribute('aria-expanded', 'false');
  header.append(tools);

  const plotBody = document.createElement('div');
  plotBody.className = 'plot-body';
  const idleReadout = kind === 'image' ? strings.hover_map : strings.hover_empty;
  const readout = document.createElement('div');
  readout.className = 'plot-readout';
  readout.textContent = idleReadout;
  const surface = document.createElement('div');
  surface.className = 'plot-surface';
  const svg = svgElement('svg', {
    role: 'img',
    'aria-label': objects[id]?.title || id,
  });
  surface.append(svg);

  const contextTools = document.createElement('div');
  contextTools.className = 'figure-context-tools';
  contextTools.hidden = true;
  contextTools.setAttribute('role', 'toolbar');
  const figureSection = document.createElement('div');
  figureSection.className = 'figure-settings-controls';
  function settingsSection(name, label) {
    const section = document.createElement('section');
    section.className = 'figure-settings-section';
    section.dataset.settingsSection = name;
    section.setAttribute('aria-label', label);
    const heading = document.createElement('div');
    heading.className = 'figure-settings-section-heading';
    heading.textContent = label;
    section.append(heading);
    figureSection.append(section);
    return section;
  }
  function selectControl(options, label) {
    const select = document.createElement('select');
    for (const [value, text] of options) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      select.append(option);
    }
    select.setAttribute('aria-label', label);
    return select;
  }
  const lineStyleOptions = [
    ['solid', strings.solid], ['dash', strings.dash],
    ['dot', strings.dot], ['dash_dot', strings.dash_dot],
  ];
  function buildCurveSettings() {
    const globalSection = settingsSection('figure', strings.figure_section);
    const curvesSection = settingsSection('curves', strings.curves_section);
    const collectionSection = settingsSection('waterfall', strings.waterfall_section);
    const showLegend = document.createElement('input');
    showLegend.type = 'checkbox';
    showLegend.setAttribute('aria-label', strings.legend);
    addFigureTool(globalSection, strings.legend, showLegend).classList.add('figure-tool-toggle');
    showLegend.addEventListener('change', () => bridge.setPlotControl(id, 'show_legend', String(showLegend.checked)));
    const spacing = document.createElement('input');
    spacing.type = 'range';
    spacing.min = '0';
    spacing.max = '300';
    spacing.step = '1';
    spacing.setAttribute('aria-label', strings.separation);
    const spacingValue = document.createElement('input');
    spacingValue.type = 'number';
    spacingValue.min = '0';
    spacingValue.step = 'any';
    spacingValue.setAttribute('aria-label', strings.separation);
    addFigureTool(collectionSection, strings.separation, spacing, spacingValue).classList.add('figure-tool-range');
    spacingValue.addEventListener('change', () => {
      if (spacingValue.reportValidity()) bridge.setPlotControl(id, 'spacing', spacingValue.value);
    });
    spacing.addEventListener('input', () => {
      const object = objects[id];
      const percent = Number(spacing.value);
      const value = object.spacing_reference * percent / 100;
      spacingValue.value = String(value);
      bridge.setPlotControl(id, 'spacing', String(value));
    });
    const palette = selectControl(['viridis', 'plasma', 'cividis', 'turbo'].map(value => [value, value]), strings.palette);
    addFigureTool(collectionSection, strings.palette, palette);
    palette.addEventListener('change', () => bridge.setPlotControl(id, 'palette', palette.value));
    const defaultAppearance = document.createElement('details');
    defaultAppearance.className = 'default-curve-appearance';
    const defaultSummary = document.createElement('summary');
    defaultSummary.textContent = strings.default_appearance;
    defaultAppearance.append(defaultSummary);
    const defaultLineStyle = selectControl(lineStyleOptions, strings.default_line_style);
    const defaultLineRow = document.createElement('div');
    defaultLineRow.className = 'default-line-row';
    defaultAppearance.append(defaultLineRow);
    addFigureTool(defaultLineRow, strings.style, defaultLineStyle);
    defaultLineStyle.addEventListener('change', () => bridge.setPlotControl(id, 'default_line_style', defaultLineStyle.value));
    const defaultLineWidth = document.createElement('input');
    defaultLineWidth.type = 'number';
    defaultLineWidth.min = '1';
    defaultLineWidth.max = '8';
    defaultLineWidth.step = 'any';
    defaultLineWidth.setAttribute('aria-label', strings.default_line_width);
    addFigureTool(defaultLineRow, strings.width, defaultLineWidth);
    defaultLineWidth.addEventListener('input', () => {
      if (defaultLineWidth.validity.valid && defaultLineWidth.value !== '') {
        bridge.setPlotControl(id, 'default_line_width', defaultLineWidth.value);
      }
    });
    const measurements = document.createElement('section');
    measurements.className = 'figure-measurements';
    measurements.setAttribute('aria-label', strings.measurements);
    const measurementHeading = document.createElement('div');
    measurementHeading.className = 'visible-curve-count';
    const measurementList = document.createElement('div');
    measurementList.className = 'figure-measurement-list';
    measurements.append(measurementHeading, measurementList);
    curvesSection.append(measurements, defaultAppearance);
    return {
      focusTarget: showLegend, showLegend, spacing, spacingValue, palette,
      defaultLineStyle, defaultLineWidth, measurementHeading, measurementList,
    };
  }
  function buildImageSettings() {
    const imageSection = settingsSection('image', strings.image_section);
    const colormap = selectControl(colormaps.map(value => [value, value]), strings.colormap);
    addFigureTool(imageSection, strings.colormap, colormap);
    colormap.addEventListener('change', () => bridge.setPlotControl(id, 'colormap', colormap.value));
    const scale = selectControl(scales.map(value => [value, strings[value] || value]), strings.intensity_scale);
    addFigureTool(imageSection, strings.intensity_scale, scale);
    scale.addEventListener('change', () => bridge.setPlotControl(id, 'scale', scale.value));
    const autoLimits = document.createElement('input');
    autoLimits.type = 'checkbox';
    autoLimits.setAttribute('aria-label', strings.auto_intensity);
    addFigureTool(imageSection, strings.auto_intensity, autoLimits).classList.add('figure-tool-toggle');
    const limitInputs = ['intensity_min', 'intensity_max'].map(name => {
      const input = document.createElement('input');
      input.type = 'number';
      input.step = 'any';
      input.setAttribute('aria-label', strings[name]);
      addFigureTool(imageSection, strings[name], input);
      return input;
    });
    const sendLimits = () => {
      if (!limitInputs.every(input => input.validity.valid && input.value !== '')) return;
      bridge.setPlotControl(id, 'limits', JSON.stringify(limitInputs.map(input => Number(input.value))));
    };
    autoLimits.addEventListener('change', () => {
      if (autoLimits.checked) bridge.setPlotControl(id, 'limits', 'auto');
      else sendLimits();
    });
    for (const input of limitInputs) input.addEventListener('change', sendLimits);
    return { focusTarget: colormap, colormap, scale, autoLimits, limitInputs };
  }
  const curveSettings = kind === 'image' ? null : buildCurveSettings();
  const imageSettings = kind === 'image' ? buildImageSettings() : null;

  const styleSection = toolGroup(contextTools, strings.curve_controls);
  styleSection.hidden = true;
  const selectedSource = document.createElement('div');
  selectedSource.className = 'selected-source';
  styleSection.append(selectedSource);
  const lineControls = document.createElement('div');
  lineControls.className = 'curve-line-row';
  lineControls.setAttribute('role', 'group');
  lineControls.setAttribute('aria-label', strings.line);
  const lineHeading = document.createElement('span');
  lineHeading.className = 'curve-line-heading';
  lineHeading.textContent = strings.line;
  lineControls.append(lineHeading);
  styleSection.append(lineControls);
  const color = document.createElement('input');
  color.type = 'color';
  color.setAttribute('aria-label', strings.color);
  addFigureTool(lineControls, strings.color, color);
  color.addEventListener('input', () => bridge.setPlotControl(id, 'curve_color', color.value));

  const lineStyle = selectControl(lineStyleOptions, strings.line_style);
  addFigureTool(lineControls, strings.style, lineStyle);
  lineStyle.addEventListener('change', () => bridge.setPlotControl(id, 'line_style', lineStyle.value));
  const lineWidth = document.createElement('input');
  lineWidth.type = 'range';
  lineWidth.min = '1';
  lineWidth.max = '8';
  lineWidth.step = '0.5';
  lineWidth.setAttribute('aria-label', strings.line_width);
  const lineWidthValue = document.createElement('input');
  lineWidthValue.type = 'number';
  lineWidthValue.min = '1';
  lineWidthValue.max = '8';
  lineWidthValue.step = 'any';
  lineWidthValue.setAttribute('aria-label', strings.line_width);
  addFigureTool(lineControls, strings.width, lineWidth, lineWidthValue);
  lineWidth.addEventListener('input', () => {
    lineWidthValue.value = lineWidth.value;
    bridge.setPlotControl(id, 'line_width', lineWidth.value);
  });
  lineWidthValue.addEventListener('input', () => {
    if (lineWidthValue.validity.valid && lineWidthValue.value !== '') bridge.setPlotControl(id, 'line_width', lineWidthValue.value);
  });
  const gain = document.createElement('input');
  gain.type = 'range';
  gain.min = '0';
  gain.max = '3';
  gain.step = '0.05';
  gain.setAttribute('aria-label', strings.display_gain);
  const gainValue = document.createElement('input');
  gainValue.type = 'number';
  gainValue.min = '0';
  gainValue.step = 'any';
  gainValue.setAttribute('aria-label', strings.display_gain);
  const scalingRow = addFigureTool(styleSection, strings.display_gain, gain, gainValue);
  scalingRow.classList.add('curve-scaling-row');
  gain.title = strings.scaling_hint;
  gainValue.title = strings.scaling_hint;
  gain.addEventListener('input', () => {
    gainValue.value = gain.value;
    bridge.setPlotControl(id, 'gain', gain.value);
  });
  gainValue.addEventListener('input', () => {
    if (gainValue.validity.valid && gainValue.value !== '') bridge.setPlotControl(id, 'gain', gainValue.value);
  });
  const opacity = document.createElement('input');
  opacity.type = 'range';
  opacity.min = '0';
  opacity.max = '1';
  opacity.step = '.05';
  opacity.setAttribute('aria-label', strings.opacity);
  const opacityValue = document.createElement('input');
  opacityValue.type = 'number';
  opacityValue.min = '0';
  opacityValue.max = '1';
  opacityValue.step = 'any';
  opacityValue.setAttribute('aria-label', strings.opacity);
  addFigureTool(lineControls, strings.opacity, opacity, opacityValue);
  opacity.addEventListener('input', () => {
    opacityValue.value = opacity.value;
    bridge.setPlotControl(id, 'opacity', opacity.value);
  });
  opacityValue.addEventListener('input', () => {
    if (opacityValue.validity.valid && opacityValue.value !== '') bridge.setPlotControl(id, 'opacity', opacityValue.value);
  });
  contextTools.addEventListener('keydown', event => {
    event.stopPropagation();
    if (event.key === 'Escape') {
      event.preventDefault();
      hideElementTools();
      dom.focus();
    }
  });
  function hideElementTools(element = null) {
    card.element = element;
    contextTools.hidden = true;
  }
  function showElementTools(element, event) {
    surface.querySelector('.axis-label-editor')?.remove();
    card.element = element;
    const bounds = surface.getBoundingClientRect();
    card.toolAnchor = event?.detail
      ? { x: (event.clientX - bounds.left) / bounds.width, y: (event.clientY - bounds.top) / bounds.height }
      : { x: .5, y: .15 };
    card.syncTools();
    positionElementTools();
  }
  function positionElementTools() {
    if (contextTools.hidden) return;
    const bounds = surface.getBoundingClientRect();
    const cardBounds = dom.getBoundingClientRect();
    const anchor = card.toolAnchor || { x: .5, y: .15 };
    const x = bounds.left - cardBounds.left + bounds.width * anchor.x;
    const y = bounds.top - cardBounds.top + bounds.height * anchor.y;
    contextTools.style.left = `${Math.max(8, Math.min(x - contextTools.offsetWidth / 2,
      cardBounds.width - contextTools.offsetWidth - 8))}px`;
    const below = y + 18;
    contextTools.style.top = `${Math.max(bounds.top - cardBounds.top,
      below + contextTools.offsetHeight > bounds.bottom - cardBounds.top
        ? y - contextTools.offsetHeight - 18 : below)}px`;
  }

  const navigation = document.createElement('div');
  navigation.className = 'plot-navigation';
  const modeButtons = [];
  function setNavigationMode(name) {
    card.mode = name;
    for (const button of modeButtons) {
      button.setAttribute('aria-pressed', String(button.dataset.plotAction === name));
    }
    surface.dataset.mode = name;
  }
  const navigationActions = kind === 'image' ? ['pan', 'zoom', 'home'] : ['pan', 'zoom', 'home', 'mark', 'undo_mark'];
  for (const name of navigationActions) {
    const button = document.createElement('button');
    button.type = 'button';
    setIcon(button, name, strings[name]);
    button.dataset.plotAction = name;
    button.addEventListener('mousedown', event => event.preventDefault());
    button.addEventListener('click', () => {
      selectFigure();
      hideElementTools();
      if (name === 'home') {
        bridge.setPlotControl(id, 'view_range', 'auto');
      } else if (name === 'undo_mark') {
        bridge.setPlotControl(id, 'undo_mark', '');
      } else {
        setNavigationMode(name);
      }
    });
    if (['pan', 'zoom', 'mark'].includes(name)) {
      button.setAttribute('aria-pressed', String(name === 'pan'));
      modeButtons.push(button);
    }
    navigation.append(button);
  }

  const resize = document.createElement('span');
  resize.className = 'plot-resize';
  resize.tabIndex = 0;
  resize.setAttribute('role', 'slider');
  resize.setAttribute('aria-label', strings.resize);
  resize.title = strings.resize;
  let sizeFrame = 0;
  const resizeObserver = new ResizeObserver(() => {
    if (sizeFrame) return;
    sizeFrame = requestAnimationFrame(() => {
      sizeFrame = 0;
      dom.classList.toggle('wide', dom.getBoundingClientRect().width >= 720);
      const bounds = surface.getBoundingClientRect();
      if (bounds.width <= 0 || bounds.height <= 0) return;
      renderPlot(card);
      positionElementTools();
      positionAxisEditor();
      const ratio = window.devicePixelRatio || 1;
      bridge.previewSize(id, Math.round(bounds.width * ratio), Math.round(bounds.height * ratio));
    });
  });
  resizeObserver.observe(surface);
  resizeObserver.observe(dom);
  resize.setAttribute('aria-valuemin', '50');
  resize.setAttribute('aria-valuemax', '100');
  resize.addEventListener('pointerdown', event => {
    event.preventDefault();
    event.stopPropagation();
    hideElementTools();
    selectFigure();
    card.resizing = true;
    const start = dom.getBoundingClientRect();
    const startHeight = surface.getBoundingClientRect().height;
    const containerWidth = start.width / (objects[id].width / 100);
    let dimensions = { width: objects[id].width, height: objects[id].height };
    const move = next => {
      const width = start.width + 2 * (next.clientX - event.clientX);
      dimensions = {
        width: Math.max(50, Math.min(100, Math.round(width / containerWidth * 100))),
        height: Math.round(Math.max(160, Math.min(1200, startHeight + next.clientY - event.clientY))),
      };
      dom.style.width = `${dimensions.width}%`;
      surface.style.height = `${dimensions.height}px`;
    };
    const finish = next => {
      move(next);
      resize.removeEventListener('pointermove', move);
      resize.removeEventListener('pointerup', finish);
      resize.removeEventListener('pointercancel', cancel);
      card.resizing = false;
      bridge.resizePlot(id, dimensions.width, dimensions.height);
    };
    const cancel = () => {
      resize.removeEventListener('pointermove', move);
      resize.removeEventListener('pointerup', finish);
      resize.removeEventListener('pointercancel', cancel);
      card.resizing = false;
      card.refresh();
    };
    resize.setPointerCapture(event.pointerId);
    resize.addEventListener('pointermove', move);
    resize.addEventListener('pointerup', finish);
    resize.addEventListener('pointercancel', cancel);
  });
  resize.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    selectFigure();
    bridge.resizePlot(
      id,
      event.key === 'ArrowLeft' ? 50 : event.key === 'ArrowRight' ? 100 : objects[id].width,
      Math.max(160, Math.min(1200, objects[id].height + (event.key === 'ArrowDown' ? 20 : event.key === 'ArrowUp' ? -20 : 0))),
    );
  });

  let gesture = null;
  surface.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('.plot-resize, input, .figure-editable') || !card.chart || card.mode === 'mark') return;
    selectFigure();
    hideElementTools();
    const { chart, scales } = card.chart;
    const bounds = svg.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * chart.width / bounds.width;
    const y = (event.clientY - bounds.top) * chart.height / bounds.height;
    if (x < chart.left || x > chart.width - chart.right || y < chart.top || y > chart.height - chart.bottom) return;
    gesture = { x, y, ranges: [scales.xRange.slice(), scales.yRange.slice()], moved: false };
    event.preventDefault();
  });
  surface.addEventListener('pointermove', event => {
    if (!gesture || !card.chart) return;
    const { chart } = card.chart;
    const bounds = svg.getBoundingClientRect();
    const x = Math.max(chart.left, Math.min(chart.width - chart.right,
      (event.clientX - bounds.left) * chart.width / bounds.width));
    const y = Math.max(chart.top, Math.min(chart.height - chart.bottom,
      (event.clientY - bounds.top) * chart.height / bounds.height));
    gesture.end = { x, y };
    if (Math.hypot(x - gesture.x, y - gesture.y) < 4) return;
    if (!gesture.moved) surface.setPointerCapture(event.pointerId);
    gesture.moved = true;
    if (card.mode === 'pan') {
      const dx = (gesture.x - x) / (chart.width - chart.left - chart.right);
      const dy = (y - gesture.y) / (chart.height - chart.top - chart.bottom);
      objects[id].state.view_range = gesture.ranges.map((range, index) => {
        const shift = (index === 0 ? dx : dy) * (range[1] - range[0]);
        return range.map(value => value + shift);
      });
      renderPlot(card);
    } else {
      let box = svg.querySelector('.zoom-box');
      if (!box) {
        box = svgElement('rect', {
          class: 'zoom-box', fill: 'var(--accent)', 'fill-opacity': '.1',
          stroke: 'var(--accent)', 'pointer-events': 'none',
        });
        svg.append(box);
      }
      for (const [key, value] of Object.entries({
        x: Math.min(x, gesture.x), y: Math.min(y, gesture.y),
        width: Math.abs(x - gesture.x), height: Math.abs(y - gesture.y),
      })) box.setAttribute(key, value);
    }
  });
  function finishGesture(cancelled) {
    if (!gesture) return;
    const current = gesture;
    gesture = null;
    if (cancelled || !current.moved) {
      if (cancelled) {
        objects[id].state.view_range = current.ranges;
        renderPlot(card);
      }
      return;
    }
    card.ignoreClick = true;
    setTimeout(() => { card.ignoreClick = false; }, 0);
    if (card.mode === 'zoom' && card.chart && current.end) {
      const { chart } = card.chart;
      const xValue = pixel => current.ranges[0][0] + (pixel - chart.left)
        / (chart.width - chart.left - chart.right) * (current.ranges[0][1] - current.ranges[0][0]);
      const yValue = pixel => current.ranges[1][1] - (pixel - chart.top)
        / (chart.height - chart.top - chart.bottom) * (current.ranges[1][1] - current.ranges[1][0]);
      if (Math.abs(current.end.x - current.x) < 4 || Math.abs(current.end.y - current.y) < 4) {
        renderPlot(card);
        return;
      }
      objects[id].state.view_range = [
        [xValue(current.x), xValue(current.end.x)].sort((a, b) => a - b),
        [yValue(current.y), yValue(current.end.y)].sort((a, b) => a - b),
      ];
    }
    bridge.setPlotControl(id, 'view_range', JSON.stringify(objects[id].state.view_range));
    renderPlot(card);
  }
  surface.addEventListener('pointerup', () => finishGesture(false));
  surface.addEventListener('pointercancel', () => finishGesture(true));
  surface.addEventListener('wheel', event => {
    if (!dom.classList.contains('selected') || !(event.ctrlKey || event.metaKey) || !card.chart) return;
    event.preventDefault();
    const factor = Math.exp(Math.max(-1, Math.min(1, event.deltaY * .002)));
    const ranges = [card.chart.scales.xRange, card.chart.scales.yRange].map(range => {
      const middle = (range[0] + range[1]) / 2;
      return range.map(value => middle + (value - middle) * factor);
    });
    objects[id].state.view_range = ranges;
    bridge.setPlotControl(id, 'view_range', JSON.stringify(ranges));
    renderPlot(card);
  }, { passive: false });

  let lastHover = '';
  let lastBridgeHover = 0;
  let pendingPointer = null;
  let pointerFrame = 0;
  svg.addEventListener('pointermove', event => {
    if (kind !== 'image' || !card.chart || gesture) return;
    const object = objects[id];
    const { chart, scales } = card.chart;
    const bounds = svg.getBoundingClientRect();
    const px = (event.clientX - bounds.left) * chart.width / bounds.width;
    const py = (event.clientY - bounds.top) * chart.height / bounds.height;
    const x = scales.xRange[0] + (px - chart.left) / (chart.width - chart.left - chart.right) * (scales.xRange[1] - scales.xRange[0]);
    const y = scales.yRange[1] - (py - chart.top) / (chart.height - chart.top - chart.bottom) * (scales.yRange[1] - scales.yRange[0]);
    const value = imageSample(card, object, x, y);
    if (value === null || value === undefined) {
      readout.textContent = idleReadout;
      return;
    }
    const figure = object.figure;
    readout.textContent = `${figure.x_label}=${tickText(Number(x.toPrecision(5)))} ${unitText(figure.x_units)} · `
      + `${figure.y_label}=${tickText(Number(y.toPrecision(5)))} ${unitText(figure.y_units)} · `
      + `${strings.intensity} ${Number.isFinite(value) ? tickText(Number(value.toPrecision(5))) : '—'}`;
  });
  svg.addEventListener('pointermove', event => {
    const hit = event.target.closest('[data-curve-index]');
    if (!hit || !card.chart) return;
    pendingPointer = event;
    if (pointerFrame) return;
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      if (!pendingPointer || gesture || !card.chart) return;
      const current = pendingPointer;
      pendingPointer = null;
      const object = objects[id];
      const nearest = nearestCurve(card, current);
      if (!nearest) return;
      const curve = object.curves.find(item => item.index === nearest.index);
      if (!curve) return;
      const point = nearest.point;
      if (point < 0) return;
      setCurveHighlight(card, nearest.index);
      const filename = curve.source.split(/[\\/]/).at(-1);
      const figure = object.figure;
      readout.textContent = `${filename} · ${figure.x_label}=${tickText(curve.x[point])} ${unitText(figure.x_units)} · ${figure.y_label}=${tickText(curve.y[point])} ${unitText(figure.y_units)}`;
      svg.setAttribute('aria-label', readout.textContent);
      const token = `${nearest.index}:${point}`;
      const now = performance.now();
      const curveChanged = lastHover.split(':', 1)[0] !== String(nearest.index);
      if (curveChanged || (lastHover !== token && now - lastBridgeHover >= 40)) {
        bridge.curveHovered(id, nearest.index, point);
        lastBridgeHover = now;
      }
      lastHover = token;
    });
  });
  svg.addEventListener('pointerleave', () => {
    setCurveHighlight(card, -1);
    readout.textContent = idleReadout;
    if (lastHover) bridge.curveHovered(id, -1, -1);
    lastHover = '';
  });
  svg.addEventListener('click', event => {
    if (card.ignoreClick) {
      card.ignoreClick = false;
      return;
    }
    const axis = event.target.closest('[data-figure-label]');
    if (axis) {
      event.preventDefault();
      event.stopPropagation();
      selectFigure();
      hideElementTools('axis');
      bridge.curveSelected(id, -1);
      const direction = axis.dataset.figureLabel;
      const editor = document.createElement('div');
      editor.className = 'axis-label-editor';
      editor.dataset.axis = direction;
      for (const part of ['label', 'units']) {
        const field = `${direction}_${part}`;
        const input = document.createElement('input');
        input.type = 'text';
        input.maxLength = 256;
        input.setAttribute('aria-label', strings[field]);
        input.dataset.figureField = field;
        input.value = objects[id].figure[field];
        input.addEventListener('change', () => bridge.setFigureText(id, field, input.value));
        input.addEventListener('keydown', key => {
          key.stopPropagation();
          if (key.key === 'Enter') {
            key.preventDefault();
            input.blur();
            editor.remove();
          } else if (key.key === 'Escape') {
            key.preventDefault();
            input.value = objects[id].figure[field];
            editor.remove();
          }
        });
        editor.append(input);
      }
      surface.querySelector('.axis-label-editor')?.remove();
      surface.append(editor);
      positionAxisEditor();
      editor.addEventListener('focusout', () => {
        requestAnimationFrame(() => {
          if (!editor.contains(document.activeElement)) editor.remove();
        });
      });
      editor.firstChild.focus();
      editor.firstChild.select();
      return;
    }
    const hit = event.target.closest('[data-curve-index]');
    if (!hit) {
      selectFigure();
      hideElementTools();
      bridge.curveSelected(id, -1);
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const nearest = event.detail === 0 ? { index: Number(hit.dataset.curveIndex) }
      : nearestCurve(card, event);
    if (!nearest) return;
    const index = nearest.index;
    selectFigure();
    if (card.mode !== 'mark') showElementTools('curve', event);
    bridge.curveSelected(id, index);
    if (card.mode === 'mark' && card.chart) {
      const curve = objects[id].curves.find(item => item.index === index);
      const point = nearestSample(curve, event.clientX, event.clientY, svg,
        card.chart.chart, card.chart.scales, objects[id].state.spacing);
      if (point >= 0) bridge.setPlotControl(id, 'mark', JSON.stringify([index, point]));
    }
  });
  svg.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    if (event.target.closest('[data-figure-label]')) {
      event.preventDefault();
      event.stopPropagation();
      event.target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return;
    }
    const hit = event.target.closest('[data-curve-index]');
    if (!hit) return;
    event.preventDefault();
    event.stopPropagation();
    const index = Number(hit.dataset.curveIndex);
    showElementTools('curve');
    view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc, getPos())));
    bridge.curveSelected(id, index);
  });

  const footer = document.createElement('div');
  footer.className = 'plot-footer';
  footer.append(navigation, readout);
  plotBody.append(surface, resize);
  const legend = document.createElement('div');
  legend.className = 'plot-legend';
  legend.setAttribute('aria-label', strings.legend);
  dom.append(header, plotBody, legend, footer, contextTools);
  function positionAxisEditor() {
    const axisEditor = surface.querySelector('.axis-label-editor');
    if (!axisEditor) return;
    const axis = svg.querySelector(`[data-figure-label="${axisEditor.dataset.axis}"]`);
    if (!axis) return;
    const bounds = axis.getBoundingClientRect();
    const surfaceBounds = surface.getBoundingClientRect();
    axisEditor.style.left = `${bounds.left + bounds.width / 2 - surfaceBounds.left}px`;
    axisEditor.style.top = `${bounds.top + bounds.height / 2 - surfaceBounds.top}px`;
    axisEditor.style.width = `${Math.min(axisEditor.dataset.axis === 'y' ? surfaceBounds.height - 40
      : surfaceBounds.width - 20, Math.max(200, axisEditor.dataset.axis === 'y' ? bounds.height + 40 : bounds.width + 40))}px`;
  }
  const card = {
    id,
    hoveredIndex: -1,
    chart: null,
    surface,
    svg,
    readout,
    contextTools,
    get expanded() { return expandedFigures.has(id); },
    resizing: false,
    mode: 'pan',
    element: null,
    continueWriting() {
      setNavigationMode('pan');
      continueWriting();
    },
    focusSettings() {
      settings.focus();
    },
    openSettings(focus = false) {
      hideElementTools();
      settingsPanel.parentElement?.classList.remove('settings-open');
      settingsFigureId = id;
      settingsBody.replaceChildren(figureSection);
      dom.append(settingsPanel);
      settingsPanel.hidden = false;
      dom.classList.add('settings-open');
      card.syncTools();
      if (focus) (curveSettings || imageSettings).focusTarget.focus();
    },
    syncTools() {
      const object = objects[id];
      if (!object) return;
      const state = object.state;
      settings.setAttribute('aria-expanded', String(settingsFigureId === id));
      if (settingsFigureId === id) settingsPanel.dataset.objectId = id;
      if (imageSettings) {
        imageSettings.colormap.value = state.colormap;
        imageSettings.scale.value = state.scale;
        imageSettings.autoLimits.checked = state.auto;
        const shownLimits = state.auto ? object.limits : [state.vmin, state.vmax];
        imageSettings.limitInputs.forEach((input, position) => {
          input.disabled = state.auto;
          if (document.activeElement !== input) input.value = String(shownLimits[position]);
        });
        styleSection.hidden = true;
        contextTools.hidden = true;
        card.selectedIndex = null;
        return;
      }
      const {
        spacing, spacingValue, palette, defaultLineStyle, defaultLineWidth, showLegend,
        measurementHeading, measurementList,
      } = curveSettings;
      const reference = object.spacing_reference || 1;
      const spacingPercent = Math.max(0, Math.min(300, Math.round(state.spacing / reference * 100)));
      spacing.value = String(spacingPercent);
      if (document.activeElement !== spacingValue) spacingValue.value = String(state.spacing);
      spacingValue.title = spacingText(object, state.spacing);
      palette.value = state.palette;
      defaultLineStyle.value = state.default_line_style;
      if (document.activeElement !== defaultLineWidth) defaultLineWidth.value = String(state.default_line_width);
      showLegend.checked = object.figure.show_legend;
      const hidden = new Set(state.hidden_sources || []);
      measurementHeading.textContent = strings.visible_curves.replace(
        '{count}', String(object.curves.filter(curve => curve.x.length && !hidden.has(curve.source)).length),
      );
      const indices = [...measurementList.children].map(entry => Number(entry.dataset.curveIndex));
      if (indices.join(',') !== object.curves.map(curve => curve.index).join(',')) {
        measurementList.replaceChildren();
        for (const curve of object.curves) {
          const entry = document.createElement('label');
          entry.className = 'measurement-visibility';
          entry.dataset.curveIndex = String(curve.index);
          const checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.addEventListener('change', () => bridge.setPlotControl(id, 'visibility', String(curve.index)));
          const name = document.createElement('span');
          entry.append(checkbox, name);
          measurementList.append(entry);
        }
      }
      for (const entry of measurementList.children) {
        const curve = object.curves.find(item => item.index === Number(entry.dataset.curveIndex));
        entry.firstChild.checked = !hidden.has(curve.source);
        entry.lastChild.textContent = object.figure.legend_names[curve.index] || curve.source.split(/[\\/]/).at(-1);
        entry.title = curve.source;
      }
      const selectedCurve = object.curves.find(item => item.index === state.selected_index);
      styleSection.hidden = !selectedCurve || card.element !== 'curve';
      contextTools.hidden = !dom.classList.contains('selected') || styleSection.hidden;
      contextTools.setAttribute('aria-label', strings.curve_controls);
      if (!selectedCurve) {
        card.selectedIndex = null;
        return;
      }
      card.selectedIndex = state.selected_index;
      selectedSource.textContent = object.figure.legend_names[selectedCurve.index] || selectedCurve.source.split(/[\\/]/).at(-1);
      selectedSource.title = selectedCurve.source;
      color.value = selectedCurve.color;
      lineStyle.value = selectedCurve.line_style;
      lineWidth.value = String(selectedCurve.line_width);
      if (document.activeElement !== lineWidthValue) lineWidthValue.value = String(selectedCurve.line_width);
      gain.value = String(selectedCurve.gain);
      if (document.activeElement !== gainValue) gainValue.value = String(selectedCurve.gain);
      opacity.value = String(selectedCurve.opacity);
      if (document.activeElement !== opacityValue) opacityValue.value = String(selectedCurve.opacity);
    },
    refresh() {
      const object = objects[id];
      if (!object) return;
      if (document.activeElement !== title) title.value = object.title;
      count.textContent = object.summary;
      update.hidden = !object.stale;
      dom.classList.toggle('expanded', card.expanded);
      setIcon(expand, card.expanded ? 'collapse' : 'expand', card.expanded ? strings.collapse : strings.expand);
      expand.setAttribute('aria-expanded', String(card.expanded));
      resize.setAttribute('aria-valuenow', String(object.width));
      if (!card.resizing) {
        dom.style.width = `${object.width}%`;
        surface.style.height = `${object.height}px`;
      }
      legend.hidden = kind === 'image' || !object.figure.show_legend;
      if (kind !== 'image' && document.activeElement?.closest('.plot-legend') !== legend) {
        legend.replaceChildren();
        for (const curve of object.curves) {
          const entry = document.createElement('div');
          entry.className = 'legend-entry';
          entry.dataset.curveIndex = String(curve.index);
          entry.classList.toggle('muted', object.state.hidden_sources.includes(curve.source));
          entry.classList.toggle('active', object.state.selected_index === curve.index);
          const swatch = document.createElement('button');
          swatch.type = 'button';
          swatch.className = 'curve-swatch';
          swatch.style.backgroundColor = curve.color;
          swatch.setAttribute('aria-label', strings.curve_controls);
          swatch.title = strings.curve_controls;
          swatch.addEventListener('mousedown', event => event.preventDefault());
          swatch.addEventListener('click', event => {
            selectFigure();
            showElementTools('curve', event);
            bridge.curveSelected(id, curve.index);
          });
          const name = document.createElement('input');
          name.type = 'text';
          name.maxLength = 256;
          name.setAttribute('role', 'textbox');
          name.setAttribute('aria-label', strings.legend_name);
          name.dataset.figureField = `legend:${curve.index}`;
          name.value = object.figure.legend_names[curve.index] || curve.source.split(/[\\/]/).at(-1);
          makeEditable(name, `${strings.edit_legend_hint}\n${curve.source}`);
          name.addEventListener('mousedown', () => selectFigure(false));
          name.addEventListener('focus', () => {
            hideElementTools('legend');
            bridge.curveSelected(id, curve.index);
          });
          name.addEventListener('change', () => bridge.setFigureText(id, `legend:${curve.index}`, name.value));
          name.addEventListener('keydown', event => {
            event.stopPropagation();
            if (event.key === 'Enter' || event.key === 'Escape') {
              event.preventDefault();
              if (event.key === 'Escape') name.value = object.figure.legend_names[curve.index] || curve.source.split(/[\\/]/).at(-1);
              name.blur();
            }
          });
          entry.addEventListener('pointerenter', () => setCurveHighlight(card, curve.index));
          entry.addEventListener('pointerleave', () => setCurveHighlight(card, -1));
          entry.append(swatch, name);
          legend.append(entry);
        }
      }
      card.syncTools();
      renderPlot(card);
      positionElementTools();
      positionAxisEditor();
    },
  };
  card.refresh();
  cards.set(id, card);
  if (settingsFigureId === id) card.openSettings();
  return {
    dom,
    stopEvent: event => !['dragover', 'drop'].includes(event.type),
    ignoreMutation: () => true,
    selectNode() {
      dom.classList.add('selected');
      bridge.selectPlot(id);
      card.syncTools();
    },
    deselectNode() {
      dom.classList.remove('selected');
      bridge.selectPlot('');
      hideElementTools();
      if (settingsFigureId === id && cards.get(id) === card) closeFigureSettings();
      surface.querySelector('.axis-label-editor')?.remove();
    },
    update(next) { return objectId(next) === id; },
    destroy() {
      resizeObserver.disconnect();
      cancelAnimationFrame(sizeFrame);
      cancelAnimationFrame(pointerFrame);
      if (cards.get(id) === card) cards.delete(id);
      requestAnimationFrame(() => {
        if (settingsFigureId === id && !cards.has(id)) closeFigureSettings();
      });
      document.querySelector('.milkdown')?.classList.toggle(
        'has-expanded-figure', [...cards.values()].some(item => item.expanded),
      );
    },
  };
}

function setCurveHighlight(card, index) {
  card.hoveredIndex = index;
  for (const entry of card.svg.closest('.plot-card').querySelectorAll('.legend-entry')) {
    entry.classList.toggle('hovered', Number(entry.dataset.curveIndex) === index);
  }
  for (const group of card.svg.querySelectorAll('g[data-curve-index]')) {
    const curveIndex = Number(group.dataset.curveIndex);
    const object = objects[card.id];
    const selected = object?.state.selected_index === curveIndex;
    const hovered = curveIndex === index;
    const line = group.querySelector('path:not([data-curve-index])');
    const curve = object?.curves.find(item => item.index === curveIndex);
    if (line && curve) {
      line.setAttribute('stroke-width', String(
        Math.max(0.75, curve.line_width * (selected || hovered ? 1.7 : 1)),
      ));
    }
  }
}

const plotViews = [
  [imageSchema.node, inlineImageView],
  [imageBlockSchema.node, imageBlockView],
].map(([schema, nativeView]) => $view(schema, () => (node, view, getPos, ...rest) => {
  if (objectId(node)) return plotNodeView(node, view, getPos);
  const rendered = nativeView.view(node, view, getPos, ...rest);
  const update = rendered.update;
  rendered.update = (next, ...args) => !objectId(next) && (update ? update.call(rendered, next, ...args) : false);
  return rendered;
}));

function renderOutline(entries) {
  outline.replaceChildren();
  outline.setAttribute('aria-label', strings.outline);
  if (!entries.length) {
    const hint = document.createElement('p');
    hint.className = 'outline-empty';
    hint.textContent = strings.outline_empty;
    outline.append(hint);
  }
  for (const entry of entries) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `outline-entry outline-level-${Math.min(6, Math.max(1, entry.level))}`;
    button.textContent = entry.label || strings.untitled_heading;
    button.addEventListener('mousedown', event => event.preventDefault());
    if (entry.objectId) button.dataset.objectId = entry.objectId;
    button.addEventListener('click', () => navigate(entry.position));
    outline.append(button);
  }
}

function updateOutline() {
  const view = editor.action(ctx => ctx.get(editorViewCtx));
  const entries = [];
  view.state.doc.descendants((node, position) => {
    if (node.type.name === 'heading') {
      entries.push({ position, level: node.attrs.level, label: node.textContent });
    } else {
      const id = objectId(node);
      if (id) entries.push({
        position,
        level: 1,
        label: objects[id]?.title || id,
        objectId: id,
      });
    }
  });
  renderOutline(entries);
}

function navigate(position) {
  const view = editor.action(ctx => ctx.get(editorViewCtx));
  const dom = view.nodeDOM(position);
  if (dom instanceof HTMLElement) {
    dom.scrollIntoView({
      block: 'start',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    });
  }
}

function insertPlotAtSelection(id) {
  const object = objects[id];
  if (!object) throw new Error(strings.preview_failed);
  editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    const image = imageBlockSchema.type(ctx).create({
      src: `sciview-object:${id}`,
      caption: `sciview:${id}`,
    });
    const paragraph = view.state.schema.nodes.paragraph;
    let transaction = view.state.tr;
    let position;
    if (view.state.selection instanceof NodeSelection) {
      position = view.state.selection.to;
      transaction.insert(position, Fragment.fromArray([image, paragraph.create()]));
    } else {
      transaction.deleteSelection();
      position = transaction.selection.from;
      try {
        transaction.split(position);
        transaction.insert(position, image);
      } catch {
        transaction = view.state.tr.deleteSelection();
        const resolved = transaction.doc.resolve(transaction.selection.from);
        position = resolved.depth ? resolved.after(1) : resolved.pos;
        transaction.insert(position, Fragment.fromArray([image, paragraph.create()]));
      }
    }
    const cursor = Math.min(position + image.nodeSize + 1, transaction.doc.content.size);
    transaction.setSelection(TextSelection.near(transaction.doc.resolve(cursor), 1));
    view.dispatch(transaction.scrollIntoView());
    view.focus();
  });
}

function flush() {
  return editor.action(getMarkdown());
}

window.sciview = {
  flush,
  setDocumentTitle(name, dirty) {
    document.getElementById('document-name').textContent = name;
    document.getElementById('save-state').textContent = dirty ? strings.unsaved : strings.saved_state;
  },
  setLatestAvailable(available) {
    const button = document.getElementById('insert-result');
    button.hidden = !available;
  },
  setStale(id, stale) {
    const object = objects[id];
    if (!object) return;
    object.stale = stale;
    cards.get(id)?.refresh();
  },
  setDocument(markdown, values) {
    closeFigureSettings();
    objects = values;
    expandedFigures.clear();
    suppress = true;
    editor.action(replaceAll(markdown, true));
    suppress = false;
    updateOutline();
    editor.action(ctx => ctx.get(editorViewCtx).focus());
  },
  updateObjects(values) {
    objects = values;
    for (const card of cards.values()) card.refresh();
    updateOutline();
  },
  updatePlotState(id, presentation) {
    const object = objects[id];
    if (!object) {
      bridge.failed(strings.missing_object);
      return;
    }
    for (const key of ['width', 'height', 'state', 'title', 'figure', 'display_note', 'limits', 'lut']) {
      if (key in presentation) object[key] = presentation[key];
    }
    object.spacing_reference = presentation.spacing_reference || object.spacing_reference;
    if (presentation.curves) {
      const curves = new Map(presentation.curves.map(curve => [curve.index, curve]));
      for (const curve of object.curves) {
        const style = curves.get(curve.index);
        if (style) Object.assign(curve, style);
      }
    }
    const card = cards.get(id);
    if (card) {
      card.refresh();
    }
    updateOutline();
  },
  addPlot(id) {
    try {
      insertPlotAtSelection(id);
    } catch (error) {
      bridge.failed(String(error));
    }
  },
  navigate,
  toggleOutline(visible) {
    outlineRail.classList.toggle('collapsed', !visible);
    document.getElementById('work-area').classList.toggle('outline-visible', visible);
    const toggle = document.getElementById('outline-toggle');
    toggle.setAttribute('aria-expanded', String(visible));
    toggle.title = visible ? strings.outline_hide : strings.outline_show;
    toggle.setAttribute('aria-label', toggle.title);
  },
  highlightCurve(id, index) {
    const card = cards.get(id);
    if (!card || card.hoveredIndex === index) return;
    setCurveHighlight(card, index);
  },
  clearSelection() {
    const view = editor.action(ctx => ctx.get(editorViewCtx));
    view.dispatch(view.state.tr.setSelection(TextSelection.atEnd(view.state.doc)));
  },
};

function configureShell() {
  document.getElementById('figure-settings-heading').textContent = strings.figure_controls;
  const closeSettings = document.getElementById('close-figure-settings');
  closeSettings.title = strings.close_inspector;
  closeSettings.setAttribute('aria-label', strings.close_inspector);
  closeSettings.addEventListener('click', () => {
    const card = cards.get(settingsFigureId);
    closeFigureSettings();
    card?.focusSettings();
  });
  settingsPanel.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    const card = cards.get(settingsFigureId);
    closeFigureSettings();
    card?.focusSettings();
  });
  document.getElementById('app-name').textContent = strings.app_name;
  document.getElementById('outline-heading').textContent = strings.outline_heading;
  document.getElementById('insert-result').textContent = strings.insert_result;
  setIcon(document.getElementById('file-menu-label'), 'file', strings.file_menu);
  document.querySelector('[data-action="new"]').textContent = strings.new;
  document.querySelector('[data-action="open"]').textContent = strings.open;
  document.querySelector('[data-action="save-as"]').textContent = strings.save_as;
  setIcon(document.getElementById('save-button'), 'save', strings.save);
  setIcon(closeSettings, 'close', strings.close_inspector);
  document.querySelector('.brand-mark').replaceChildren(iconElement('notebook'));
  const outlineToggle = document.getElementById('outline-toggle');
  outlineToggle.addEventListener('mousedown', event => event.preventDefault());
  window.sciview.toggleOutline(false);
  outlineToggle.addEventListener('click', () => {
    const visible = outlineToggle.getAttribute('aria-expanded') !== 'true';
    window.sciview.toggleOutline(visible);
  });
  document.getElementById('insert-result').addEventListener('click', () => bridge.latest());
  document.getElementById('save-button').addEventListener('click', () => bridge.saveDocument());
  document.querySelector('[data-action="new"]').addEventListener('click', () => bridge.newDocument());
  document.querySelector('[data-action="open"]').addEventListener('click', () => bridge.openDocument());
  document.querySelector('[data-action="save-as"]').addEventListener('click', () => bridge.saveAs());
  document.querySelectorAll('.file-menu-items button').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelector('.file-menu').open = false;
    });
  });
}

window.addEventListener('error', event => {
  if (bridge) bridge.failed(event.message);
});
window.addEventListener('unhandledrejection', event => {
  const message = String(event.reason?.stack || event.reason);
  if (bridge) bridge.failed(message);
});

document.addEventListener('click', event => {
  const link = event.target.closest('a[href]');
  if (!link || !(link.closest('.milkdown-link-preview') || event.ctrlKey || event.metaKey)) return;
  event.preventDefault();
  event.stopPropagation();
  bridge.openLink(link.getAttribute('href'));
}, true);

// Figures move only through Crepe's block handle (its draggable container is the drag target);
// gestures on the figure itself never start a drag.
document.addEventListener('dragstart', event => {
  if (event.target.closest?.('.plot-card')) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

document.getElementById('editor').addEventListener('pointerdown', event => {
  if (event.target.closest('.plot-card, .ProseMirror, .milkdown-top-bar, .milkdown-toolbar, .milkdown-slash-menu')) return;
  const view = editor.action(ctx => ctx.get(editorViewCtx));
  if (view.state.selection instanceof NodeSelection && objectId(view.state.selection.node)) {
    cards.get(objectId(view.state.selection.node))?.continueWriting();
  }
});

document.getElementById('editor').addEventListener('keydown', event => {
  if (event.key !== 'Escape' || event.defaultPrevented) return;
  const view = editor.action(ctx => ctx.get(editorViewCtx));
  if (event.target !== view.dom) return;
  if (!(view.state.selection instanceof NodeSelection)) return;
  const card = cards.get(objectId(view.state.selection.node));
  if (!card) return;
  event.preventDefault();
  event.stopPropagation();
  card.continueWriting();
}, true);

new QWebChannel(qt.webChannelTransport, async channel => {
  bridge = channel.objects.notebook;
  const config = JSON.parse(await new Promise(resolve => bridge.configuration(resolve)));
  strings = config.strings;
  colormaps = config.colormaps;
  scales = config.scales;
  configureShell();
  const crepe = new Crepe({
    root: document.getElementById('editor'),
    features: { [Crepe.Feature.TopBar]: true },
    featureConfigs: {
      [Crepe.Feature.TopBar]: {
        buildTopBar: builder => {
          builder.addGroup('sciview', 'SciView').addItem('waterfall', {
            icon: plotIcon,
            active: () => false,
            onRun: () => bridge.latest(),
          });
          for (const group of builder.build()) {
            for (const item of group.items) {
              if (item.icon) {
                const label = item.key === 'waterfall' ? strings.insert_result
                  : item.key.replaceAll('-', ' ').replace(/^./, character => character.toUpperCase());
                item.icon = `<span data-format-command="${item.key}" role="img" title="${label}" aria-label="${label}">${item.icon}</span>`;
              }
            }
          }
        },
      },
      [Crepe.Feature.Placeholder]: { text: strings.placeholder },
      [Crepe.Feature.ImageBlock]: {
        onUpload: file => new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(new Error(strings.image_failed));
          reader.readAsDataURL(file);
        }),
        onImageLoadError: () => bridge.failed(strings.image_failed),
      },
      [Crepe.Feature.BlockEdit]: {
        buildMenu: builder => builder.addGroup('sciview', 'SciView').addItem('plot', {
          label: strings.plot_block,
          icon: plotIcon,
          onRun: () => bridge.latest(),
        }),
      },
    },
  });
  editor = crepe.editor;
  // Serializing and shipping the whole document on every keystroke is the main typing cost;
  // coalesce it. Saves and snapshots read the editor directly through flush().
  let syncTimer = 0;
  editor.config(ctx => {
    ctx.get(listenerCtx).updated((ctx, doc) => {
      if (suppress) {
        updateOutline();
        return;
      }
      clearTimeout(syncTimer);
      syncTimer = setTimeout(() => {
        bridge.changed(ctx.get(serializerCtx)(doc));
        updateOutline();
      }, 250);
    });
  }).use(plotViews);
  await crepe.create();
  const toolbar = document.querySelector('.milkdown-top-bar');
  toolbar.setAttribute('role', 'toolbar');
  toolbar.setAttribute('aria-label', strings.formatting);
  bridge.ready();
});
