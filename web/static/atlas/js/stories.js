// The shared made-up content (../_shared/content.js) given places on the map. Everything here is invented.
// Events in content.js have no coordinates, so each one gets a place near its country's real location (the
// videos already have lat/lng). Chain parts get their own places, so a follow-up draws a route.
(function () {
  'use strict';
  const D = window.STRINGER_DEMO;

  // Where each story sits. region: a province the fly-to lights up (built by tools/build_geo.py).
  // frame: what the camera fits when it flies there [west, south, east, north].
  const PLACES = {
    'e-beni-airlift':    {place: 'Trinidad, Beni', short: 'Trinidad', lat: -14.83, lng: -64.90, region: 'beni', frame: [-69.5, -18.2, -61.5, -9.6]},
    'e-nairobi-highway': {place: 'Voi, on the Mombasa road', short: 'Voi', lat: -3.39, lng: 38.56, region: 'coast', frame: [35.2, -5.6, 41.0, 0.6]},
    'e-us-cr':           {place: 'Washington, D.C.', short: 'Washington', lat: 38.89, lng: -77.01, region: 'washington', frame: [-80.6, 36.6, -73.4, 41.2]},
    'e-eu-steel':        {place: 'Brussels', short: 'Brussels', lat: 50.85, lng: 4.35, region: 'brussels', frame: [1.6, 49.4, 7.0, 52.4]},
    'e-gorkha-slide':    {place: 'Gorkha, Nepal', short: 'Gorkha', lat: 28.0, lng: 84.63, region: 'gandaki', frame: [81.5, 26.0, 87.8, 30.4]},
    'e-belgorod-depot':  {place: 'Belgorod region', short: 'Belgorod', lat: 50.6, lng: 36.6, region: 'belgorod', frame: [35.0, 49.4, 39.6, 51.9]},
    'e-kasai-cholera':   {place: 'Tshikapa, Kasai', short: 'Tshikapa', lat: -6.42, lng: 20.8, region: 'kasai', frame: [17.5, -9.0, 25.0, -2.0]},
    'e-muscat-talks':    {place: 'Muscat', short: 'Muscat', lat: 23.59, lng: 58.41, region: 'muscat', frame: [55.0, 20.6, 61.4, 26.4]},
    'e-basra-fire':      {place: 'Basra', short: 'Basra', lat: 30.51, lng: 47.81, region: 'basra', frame: [44.6, 28.4, 50.8, 32.6]},
    'e-malawi-count':    {place: 'Lilongwe', short: 'Lilongwe', lat: -13.96, lng: 33.79, region: 'lilongwe', frame: [30.6, -17.4, 37.2, -9.2]},
    'v-brazil-rates':    {place: 'Brasília', short: 'Brasília', region: 'df', frame: [-51.5, -18.6, -44.2, -13.0]},
    'v-antwerp':         {place: 'Antwerp', short: 'Antwerp', region: 'antwerp', frame: [2.4, 50.2, 6.8, 52.3]},
    'v-kenya-levy':      {place: 'Nairobi', short: 'Nairobi', region: 'nairobi', frame: [35.2, -5.6, 41.0, 0.6]},
    'v-hokkaido':        {place: 'Kushiro, Hokkaido', short: 'Kushiro', region: 'hokkaido', frame: [139.4, 41.2, 146.4, 45.6]},
    'v-valparaiso':      {place: 'Viña del Mar', short: 'Viña del Mar', region: 'valparaiso', frame: [-73.6, -35.0, -68.8, -31.0]},
  };

  // Chain parts with their own places and days (route nodes on the map).
  const CHAIN_PLACES = {
    'v-beni-1': {short: 'Riberalta', lat: -11.01, lng: -66.07, day: '24 Nov'},
    'v-beni-2': {short: 'Santa Ana', lat: -13.74, lng: -65.43, day: '25 Nov'},
    'v-beni-3': {short: 'Trinidad', lat: -14.83, lng: -64.90, day: '27 Nov'},
    'v-belgorod-1': {short: 'Belgorod region', lat: 50.88, lng: 37.28, day: '25 Nov'},
    'v-belgorod-2': {short: 'Fuel depot', lat: 50.6, lng: 36.6, day: '26 Nov'},
    'v-kenya-levy': {short: 'Nairobi', lat: -1.29, lng: 36.82, day: '26 Nov'},
    'e-nairobi-highway': {short: 'Voi', lat: -3.39, lng: 38.56, day: 'Today'},
  };

  // Hot score for an event with no video yet, from the system map's draft formula (size, momentum, freshness,
  // a small severity bump). Only used to size pins.
  function eventHot(e) {
    const ago = /(\d+)\s*min/.test(e.lastReport) ? +RegExp.$1 / 60 : /(\d+)\s*h/.test(e.lastReport) ? +RegExp.$1 : 0;
    const momentum = Math.round(e.reports * 0.3);
    return (Math.log2(1 + e.reports) + Math.log2(1 + momentum)) * (1 + 0.25 * (e.severity - 2)) * Math.pow(0.5, ago / 8) * 0.95;
  }

  // Clips 1 and 2 show real politicians (cut-out portraits). The stories here are invented, so each one gets a
  // clip with no real person in it; a few clips are shared. clip-08 is a rates story, clip-07 is about Japan.
  const CLIPS = {'v-beni-3': 3, 'v-stopgap': 4, 'v-belgorod-2': 6, 'v-brazil-rates': 8, 'v-antwerp': 5, 'v-kenya-levy': 5, 'v-hokkaido': 7, 'v-valparaiso': 3};
  const videos = D.videos.map((v) => ({...v, clip: CLIPS[v.id] || v.clip}));
  const videosById = Object.fromEntries(videos.map((v) => [v.id, v]));
  const items = [];
  const byId = {};
  const add = (it) => { items.push(it); byId[it.id] = it; };

  D.events.forEach((e, i) => {
    const p = PLACES[e.id];
    const v = e.video ? videosById[e.video] : null;
    const state = e.state === 'has_video' ? 'done' : e.state;
    add({
      id: e.id, rank: i + 1, event: e, video: state === 'done' ? v : null, state,
      title: v && state === 'done' ? v.headline : e.title, wire: e.title,
      place: p.place, short: p.short, lat: p.lat, lng: p.lng, region: p.region, frame: p.frame,
      country: e.country, category: e.category, subtype: e.subtype, regionName: e.region,
      chain: e.chain || (v && v.chain) || null,
      hot: v ? v.hot : eventHot(e),
      progress: e.progress ? {...e.progress} : null,
      reason: e.reason || null,
    });
  });
  // Finished videos whose event has left the top 10 still stand on the map.
  videos.forEach((v) => {
    if (items.some((it) => it.video && it.video.id === v.id)) return;
    const p = PLACES[v.id];
    add({
      id: v.id, rank: null, event: null, video: v, state: v.hidden ? 'hidden' : 'done',
      title: v.headline, wire: null, place: p.place, short: p.short, lat: v.lat, lng: v.lng, region: p.region, frame: p.frame,
      country: v.country, category: v.category, subtype: v.subtype, regionName: v.region,
      chain: v.chain && D.chains[v.chain] ? v.chain : null, hot: v.hot, progress: null, reason: null,
    });
  });
  // The hidden Basra video is only known from the reports
  const basra = byId['e-basra-fire'];
  basra.hiddenHeadline = 'Fire at Basra hospital kills eleven';

  // Chains, in time order, with places.
  const chains = {};
  for (const [key, parts] of Object.entries(D.chains)) {
    chains[key] = parts.map((p, i) => ({...p, ...(CHAIN_PLACES[p.id] || {}), part: i + 1, of: parts.length,
      making: /being made/.test(p.headline), headline: p.headline.replace(/^\(being made\)\s*/, '')}));
  }

  // Hot right now: finished videos that are not hidden, by hot score.
  function hotList() {
    return items.filter((it) => it.state === 'done' && it.video).sort((a, b) => b.hot - a.hot);
  }

  const WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const TODAY_WD = WEEK.indexOf(new Date(D.now).toLocaleDateString('en-US', {timeZone: 'America/New_York', weekday: 'short'}));   // Friday 27 November
  const fmtTime = (iso) => {
    const d = new Date(iso);
    const now = new Date(D.now);
    const day = (x) => x.toLocaleDateString('en-US', {timeZone: 'America/New_York', year: 'numeric', month: 'numeric', day: 'numeric'});
    const hm = d.toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit'}).replace(' AM', ' am').replace(' PM', ' pm');
    const ymd = (x) => { const [m, dd, yy] = day(x).split('/').map(Number); return Date.UTC(yy, m - 1, dd); };
    const diff = Math.round((ymd(now) - ymd(d)) / 86400000);
    if (diff === 0) return `Today, ${hm}`;
    if (diff === 1) return `Yesterday, ${hm}`;
    // weekday names counted back from the shared content's today
    const wd = WEEK[((TODAY_WD - diff) % 7 + 7) % 7];
    return `${wd} ${d.toLocaleDateString('en-GB', {timeZone: 'America/New_York', day: 'numeric', month: 'short'})}, ${hm}`;
  };

  // Tags, from category, subtype, country, region and the story's sides (content.js fields).
  function tagsOf(it) {
    const v = it.video;
    const t = [it.category, it.subtype, it.country, it.regionName].filter(Boolean);
    let sides = null;
    if (v && v.sides) sides = v.sides.kind === 'no real divide' ? {none: true} : {A: v.sides.A.label, B: v.sides.B.label};
    return {plain: t, sides};
  }

  window.Stories = {D, items, byId, chains, hotList, fmtTime, tagsOf, videosById, CHAIN_PLACES, WEEK, TODAY_WD};
})();
