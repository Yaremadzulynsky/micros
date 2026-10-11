// Shared by the browser bundle and static SVG exports.
export const palette = {
  ink: '#263449', muted: '#64748b', line: '#e7ebf2',
  base: '#5965df', service: '#009f89', trial: '#9261ce',
  amber: '#b87512', failure: '#c64959',
};
// Avoid quotes in font names: ECharts SSR writes this into an SVG style attribute.
const font = 'system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
const common = { animation: false, textStyle: { fontFamily: font, color: palette.ink } };

// Explicit geometry keeps card labels and connector endpoints aligned in SVG.
function diagram() {
  const graphic = [];
  const label = (x, y, text, size = 12, fill = palette.muted, weight = 400, align = 'center') => ({
    type: 'text', silent: true, style: { x, y, text, font: weight + ' ' + size + 'px ' + font,
      fill, align, verticalAlign: 'middle', lineHeight: size + 5 },
  });
  const box = (x, y, width, height, kind = 'service') => ({
    type: 'rect', silent: true, shape: { x, y, width, height, r: 8 },
    style: { fill: kind === 'kernel' ? '#f4f5ff' : '#fff',
      stroke: kind === 'kernel' ? '#a5acf0' : kind === 'platform' ? '#d6deea' : '#b0d8d0',
      lineWidth: 1.4, shadowBlur: 10, shadowOffsetY: 3, shadowColor: 'rgba(34,51,84,.05)' },
  });
  const link = (x1, y1, x2, y2, vertical = false, directed = true) => {
    graphic.push({ type: 'bezierCurve', silent: true, shape: { x1, y1, x2, y2,
      cpx1: vertical ? x1 : (x1+x2)/2, cpy1: vertical ? (y1+y2)/2 : y1,
      cpx2: vertical ? x2 : (x1+x2)/2, cpy2: vertical ? (y1+y2)/2 : y2 },
      style: { stroke: '#8994da', lineWidth: 1.6, fill: null } });
    if (directed) graphic.push({ type: 'polygon', silent: true, shape: { points: vertical
      ? [[x2,y2],[x2-4,y2-7],[x2+4,y2-7]]
      : [[x2,y2],[x2-7,y2-4],[x2-7,y2+4]] }, style: { fill: '#8994da' } });
  };
  const boundary = (x, y, text, width) => {
    graphic.push({ type: 'rect', silent: true, shape: { x: x-width/2, y:y-13, width, height:26, r:5 },
      style: { fill:'#fff' } }, label(x,y,text,11,palette.base,600));
  };
  return { graphic, label, box, link, boundary };
}

export function systemOption(width, height = width < 680 ? 482 : 420) {
  const d = diagram(), { graphic, label, box, link, boundary } = d;
  const names = ['Climate sensor', 'Fan controller', 'Status display'];
  const targets = ['ESP32 adapter', 'SAMD21 / MKR adapter', 'ESP8266 adapter'];
  if (width < 680) {
    link(width/2,140,width/2,206,true,false);
    link(width/2,292,width/2,370,true,false);
    graphic.push(box(8,8,width-16,132), label(width/2,25,'APPLICATION SERVICES',9,'#168575',600));
    names.forEach((name,i) => {
      graphic.push(label(22,52+i*33,name,13,palette.ink,600,'left'),
        label(width-22,52+i*33,'1 worker',10,palette.muted,400,'right'));
    });
    boundary(width/2,173,'Service ABI · native calls',164);
    graphic.push(box(8,206,width-16,86,'kernel'),
      label(width/2,230,'Micros kernel',18,palette.base,650),
      label(width/2,267,'Lifecycle · resources\nChannels · supervision',12));
    boundary(width/2,330,'Platform interface · one target per build',238);
    graphic.push(box(8,370,width-16,100,'platform'));
    targets.forEach((name,i) => graphic.push(label(width/2,389+i*30,name,12,palette.ink,500)));
  } else {
    const cardWidth = Math.min(236,(width-64)/3), centers = [width/6,width/2,width*5/6];
    centers.forEach(x => { link(x,92,x,164,true,false); link(x,254,x,330,true,false); });
    names.forEach((name,i) => graphic.push(box(centers[i]-cardWidth/2,12,cardWidth,80),
      label(centers[i],40,name,15,palette.ink,650), label(centers[i],67,'One service worker',12)));
    graphic.push(box(8,164,width-16,90,'kernel'), label(width/2,194,'Micros kernel',21,palette.base,650),
      label(width/2,226,'Lifecycle  ·  Resources  ·  Channels  ·  Supervision',13));
    boundary(width/2,127,'Service ABI · native call contract',240);
    boundary(width/2,292,'Platform interface · one adapter per build',300);
    targets.forEach((name,i) => graphic.push(box(centers[i]-cardWidth/2,330,cardWidth,64,'platform'),
      label(centers[i],362,name,13,palette.ink,500)));
  }
  return { ...common, graphic };
}

export function communicationOption(width, height = width < 680 ? 540 : 430) {
  const { graphic, label, box, link } = diagram();
  const mobile = width < 680;
  const card = (x,y,w,h,name,note,channel = false) => {
    graphic.push(box(x,y,w,h,channel ? 'kernel' : 'service'),
      label(x+w/2,y+15,channel ? 'LATEST CHANNEL' : 'SERVICE',9,channel ? palette.base : '#168575',600),
      label(x+w/2,y+(name.includes('\n') ? 45 : 36),name,mobile ? 12 : 15,channel ? palette.base : palette.ink,650),
      label(x+w/2,y+h-23,note,mobile ? 10.5 : 12));
  };
  if (mobile) {
    const wide = Math.min(218,width-16), serviceWidth = Math.min(204,width-16);
    const readerWidth = (width-34)/2, rightX = width-8-readerWidth;
    link(width/2,100,width/2,144,true);
    link(width/2,228,8+readerWidth/2,286,true);
    link(width/2,228,rightX+readerWidth/2,435,true);
    link(8+readerWidth/2,392,8+readerWidth/2,446,true);
    link(8+readerWidth,485,rightX,485);
    card((width-serviceWidth)/2,8,serviceWidth,92,'Climate sensor','Temperature + humidity');
    card((width-wide)/2,144,wide,84,'climate.reading','Current conditions',true);
    card(8,286,readerWidth,106,'Fan\ncontroller','Applies the\nfan policy');
    card(8,446,readerWidth,78,'fan.status','Current fan state',true);
    card(rightX,435,readerWidth,100,'Status\ndisplay','Shows both\nmessages');
  } else {
    const serviceWidth = Math.min(194,width*.23), channelWidth = Math.min(234,width*.29);
    const channelX = (width-channelWidth)/2, rightX = width-8-serviceWidth;
    link(8+serviceWidth,204,channelX,204);
    link(channelX+channelWidth,204,rightX,64);
    link(channelX+channelWidth,204,rightX,364);
    link(rightX+serviceWidth/2,112,rightX+serviceWidth/2,166,true);
    link(rightX+serviceWidth/2,244,rightX+serviceWidth/2,312,true);
    card(8,152,serviceWidth,104,'Climate sensor','Temperature + humidity');
    card(channelX,152,channelWidth,104,'climate.reading','Current conditions',true);
    card(rightX,16,serviceWidth,96,'Fan controller','Applies the fan policy');
    card(rightX,166,serviceWidth,78,'fan.status','Current fan state',true);
    card(rightX,312,serviceWidth,104,'Status display','Shows both messages');
  }
  return { ...common, graphic };
}

export function updateOption(width, failure = false) {
  const mobile = width < 560;
  const left = mobile ? 85 : 158, right = mobile ? 8 : 20;
  const steps = ['Check', 'Stage', 'Trial', failure ? 'Fallback' : 'Confirm'];
  const block = (lane, start, end, text, fill, color) => ({ value: [start, end, lane], text, fill, color });
  const rows = [
    ...(!failure ? [block(0, 0, 4, 'Management available throughout', '#eef0ff', palette.base)] : [
      block(0, 0, 2, 'Available', '#eef0ff', palette.base),
      block(0, 2, 3, 'Reset /\nreconnect', '#f5f2fb', '#765b95'),
      block(0, 3, 4, 'Available', '#eef0ff', palette.base),
    ]),
    block(1, 0, 1, 'Old app', '#e5f5f0', '#087d6d'),
    block(1, 1, 2, 'Paused', '#fff3dd', '#97641b'),
    block(1, 2, 3, failure ? 'Failed\ntrials' : 'Candidate', failure ? '#fdecef' : '#f2ebfb', failure ? palette.failure : '#7d52ac'),
    block(1, 3, 4, failure ? 'Old app' : 'New app', '#e5f5f0', '#087d6d'),
    ...(failure ? [block(2, 0, 4, 'Prior good remains recorded', '#f0f3f8', '#596a82')] : [
      block(2, 0, 3, 'Prior good retained', '#f0f3f8', '#596a82'),
      block(2, 3, 4, 'New good', '#e5f5f0', '#087d6d'),
    ]),
  ];
  return {
    ...common,
    grid: { left, right, top: 48, bottom: 12 },
    xAxis: { type: 'value', min: 0, max: 4, interval: 1, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false }, splitLine: { lineStyle: { color: palette.line, type: 'dashed' } } },
    yAxis: { type: 'category', inverse: true,
      data: mobile ? ['Resident\nmanagement', 'Application\nworkers', 'Recorded\ngood graph'] : ['Resident management', 'Application workers', 'Recorded good graph'],
      axisLabel: { color: palette.muted, fontSize: mobile ? 10 : 12, lineHeight: 17, margin: 13 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    graphic: steps.map((text, i) => ({ type: 'text', x: left + (width - left - right) * (i + .5) / 4, y: 17,
      style: { text, font: `600 ${mobile ? 10 : 12}px ${font}`, fill: palette.muted, align: 'center' }, silent: true })),
    series: [{ type: 'custom', silent: true, data: rows, encode: { x: [0, 1], y: 2 },
      renderItem(params, api) {
        const row = rows[params.dataIndex];
        const start = api.coord([api.value(0), api.value(2)]), end = api.coord([api.value(1), api.value(2)]);
        const x = start[0] + 3, y = start[1] - 24, w = end[0] - start[0] - 6;
        let text = row.text;
        if (mobile && text === 'Reset /\nreconnect') text = 'Reset\nrejoin';
        if (mobile && row.value[1] - row.value[0] === 1) text = text.replace(' ', '\n');
        if (mobile && text === 'Candidate') text = 'On trial';
        if (mobile && text === 'Available') text = 'Online';
        if (mobile && text === 'Management available throughout') text = 'Management available';
        return { type: 'group', children: [
          { type: 'rect', shape: { x, y, width: w, height: 48, r: 7 }, style: { fill: row.fill } },
          { type: 'text', style: { x: x + w / 2, y: y + 24, text, align: 'center', verticalAlign: 'middle',
            font: `600 ${mobile ? 10 : 12}px ${font}`, lineHeight: 14, fill: row.color } },
        ] };
      },
    }],
  };
}
