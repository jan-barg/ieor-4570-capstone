// The landing page's scripted story (module 9; from the designs' _shared/content.js, Nov 27, 2026).
// Everything here is MADE UP: every headline, event, outlet, id and number. None of it comes from Monitor the
// Situation. The landing page plays the invented Antwerp dock strike on the map to show how a video is made;
// its real figures (the daily limit, the cost) come from /api/site (landing-live.js).
window.STRINGER_DEMO = {
 "now": "2026-11-27T09:43:00-05:00",
 "credit": "Events by Monitor the Situation",
 "site": {
  "open": true,
  "videosToday": 3,
  "videosPerDay": 10,
  "beingMade": 2,
  "atOnce": 3,
  "youThisHour": 1,
  "perPersonPerHour": 3,
  "searchCreditsLeft": 46,
  "searchCreditsMonth": 1000,
  "searchCreditsPauseAt": 30,
  "spentToday": 0.94,
  "estimatePerVideo": 0.66,
  "capPerVideo": 5,
  "minutesPerVideo": "4–5"
 },
 "steps": [
  {
   "key": "sides",
   "label": "Finding the two sides",
   "share": 0.06
  },
  {
   "key": "search",
   "label": "Searching the news",
   "share": 0.16
  },
  {
   "key": "read",
   "label": "Reading the articles",
   "share": 0.22
  },
  {
   "key": "check",
   "label": "Checking every claim",
   "share": 0.2
  },
  {
   "key": "script",
   "label": "Writing the script",
   "share": 0.18
  },
  {
   "key": "voice",
   "label": "Recording the voice",
   "share": 0.06
  },
  {
   "key": "draw",
   "label": "Drawing the video",
   "share": 0.12
  }
 ],
 "videos": [
  {
   "id": "v-beni-3",
   "chain": "beni-floods",
   "part": 3,
   "of": 3,
   "headline": "Army airlifts food to flooded Beni towns",
   "dek": "Helicopters reach three towns that roads can no longer reach, a week into the floods.",
   "category": "disaster",
   "subtype": "flood",
   "country": "Bolivia",
   "region": "South America",
   "place": "Trinidad, Beni",
   "lat": -14.83,
   "lng": -64.9,
   "sides": {
    "kind": "no real divide",
    "reason": "A flood relief story: outlets agree on what happened and differ only on detail."
   },
   "articles": 11,
   "outlets": 9,
   "claims": 34,
   "claimsBacked": 31,
   "made": "2026-11-27T09:12:00-05:00",
   "minutes": 4.5,
   "cost": 0.71,
   "hot": 9.4,
   "momentum": "+14 reports in 6 h",
   "clip": 1,
   "duration": "1:04",
   "reported": false
  },
  {
   "id": "v-stopgap",
   "chain": "us-budget",
   "part": 1,
   "of": 1,
   "headline": "Stopgap bill passes hours before shutdown",
   "dek": "The Senate funds the government to 30 January; the fight over the full budget moves to the new year.",
   "category": "political",
   "subtype": "legislation",
   "country": "United States",
   "region": "North America",
   "place": "Washington, D.C.",
   "lat": 38.89,
   "lng": -77.01,
   "sides": {
    "kind": "two sides",
    "A": {
     "label": "US left-leaning outlets",
     "articles": 6,
     "outlets": [
      "Meridian Daily",
      "Lantern Post",
      "Capitol Signal"
     ]
    },
    "B": {
     "label": "US right-leaning outlets",
     "articles": 5,
     "outlets": [
      "Plains Register",
      "Northbridge News",
      "Ridgeway Times"
     ]
    },
    "howA": "Led with the averted shutdown and federal workers who will be paid on time.",
    "howB": "Led with the spending level and the conservatives who voted no.",
    "words": [
     {
      "a": "averted a shutdown",
      "b": "kicked the can"
     },
     {
      "a": "federal workers",
      "b": "taxpayers"
     }
    ]
   },
   "articles": 14,
   "outlets": 10,
   "claims": 41,
   "claimsBacked": 38,
   "made": "2026-11-27T04:10:00-05:00",
   "minutes": 4.2,
   "cost": 0.68,
   "hot": 8.1,
   "momentum": "+9 reports in 6 h",
   "clip": 2,
   "duration": "1:08",
   "reported": false,
   "keptUp": true
  },
  {
   "id": "v-belgorod-2",
   "chain": "belgorod-depot",
   "part": 2,
   "of": 2,
   "headline": "Fuel depot burns after drone strike near Belgorod",
   "dek": "Ukraine says it hit a depot that supplies the front; Russia says air defences stopped most drones.",
   "category": "conflict",
   "subtype": "drone strike",
   "country": "Russia",
   "region": "Europe",
   "place": "Belgorod region",
   "lat": 50.6,
   "lng": 36.6,
   "sides": {
    "kind": "two sides",
    "A": {
     "label": "Pro-Ukraine outlets",
     "articles": 4,
     "outlets": [
      "Eastern Dispatch",
      "Harbor Courier"
     ]
    },
    "B": {
     "label": "Pro-Russia outlets",
     "articles": 3,
     "outlets": [
      "Steppe Herald",
      "Atlas Wire"
     ]
    },
    "howA": "Called it a precise hit on fuel for the front line, with satellite pictures of the fire.",
    "howB": "Said 22 drones were shot down and debris caused a fire at a storage site.",
    "words": [
     {
      "a": "military fuel depot",
      "b": "storage site"
     },
     {
      "a": "hit",
      "b": "debris fell"
     }
    ]
   },
   "articles": 9,
   "outlets": 7,
   "claims": 29,
   "claimsBacked": 22,
   "made": "2026-11-26T22:40:00-05:00",
   "minutes": 4.8,
   "cost": 0.62,
   "hot": 7.6,
   "momentum": "+6 reports in 6 h",
   "clip": 3,
   "duration": "1:01",
   "reported": false
  },
  {
   "id": "v-brazil-rates",
   "chain": "brazil-rates",
   "part": 1,
   "of": 1,
   "headline": "Brazil's central bank raises rates to 12.75%",
   "dek": "A half-point rise, the third this year, as food prices keep climbing.",
   "category": "economic",
   "subtype": "interest rates",
   "country": "Brazil",
   "region": "South America",
   "place": "Brasília",
   "lat": -15.79,
   "lng": -47.88,
   "sides": {
    "kind": "two sides",
    "A": {
     "label": "Outlets close to the government",
     "articles": 3,
     "outlets": [
      "Planalto Today"
     ]
    },
    "B": {
     "label": "Market and business press",
     "articles": 5,
     "outlets": [
      "Market Ledger",
      "Atlas Wire"
     ]
    },
    "howA": "Stressed the cost to borrowers and quoted ministers who wanted a smaller rise.",
    "howB": "Called the rise overdue and focused on inflation expectations.",
    "words": [
     {
      "a": "squeezes families",
      "b": "anchors inflation"
     }
    ]
   },
   "articles": 8,
   "outlets": 6,
   "claims": 26,
   "claimsBacked": 25,
   "made": "2026-11-26T18:05:00-05:00",
   "minutes": 4.1,
   "cost": 0.59,
   "hot": 6.2,
   "momentum": "+3 reports in 6 h",
   "clip": 4,
   "duration": "0:58",
   "reported": false
  },
  {
   "id": "v-antwerp",
   "chain": "antwerp-strike",
   "part": 1,
   "of": 1,
   "headline": "Dock workers' strike shuts Antwerp for a third day",
   "dek": "More than 80 ships wait offshore as unions and port operators argue over night shifts.",
   "category": "economic",
   "subtype": "labour strike",
   "country": "Belgium",
   "region": "Europe",
   "place": "Antwerp",
   "lat": 51.26,
   "lng": 4.4,
   "sides": {
    "kind": "two sides",
    "A": {
     "label": "Union-friendly outlets",
     "articles": 4,
     "outlets": [
      "Union Voice",
      "Lantern Post"
     ]
    },
    "B": {
     "label": "Business press",
     "articles": 4,
     "outlets": [
      "Market Ledger",
      "Harbor Courier"
     ]
    },
    "howA": "Centred on safety on night shifts and quoted dock workers.",
    "howB": "Centred on the cost to shippers, put at €40 million a day.",
    "words": [
     {
      "a": "walkout",
      "b": "blockade"
     }
    ]
   },
   "articles": 10,
   "outlets": 8,
   "claims": 31,
   "claimsBacked": 29,
   "made": "2026-11-26T15:30:00-05:00",
   "minutes": 4.6,
   "cost": 0.66,
   "hot": 5.5,
   "momentum": "+2 reports in 6 h",
   "clip": 5,
   "duration": "1:06",
   "reported": true,
   "restoredBy": "Jan",
   "restoredAt": "2026-11-26T20:02:00-05:00"
  },
  {
   "id": "v-kenya-levy",
   "chain": "kenya-fuel",
   "part": 1,
   "of": 2,
   "headline": "Court halts Kenya's new fuel levy",
   "dek": "The High Court suspends the tax until a full hearing; the treasury says it will appeal.",
   "category": "political",
   "subtype": "court ruling",
   "country": "Kenya",
   "region": "Africa",
   "place": "Nairobi",
   "lat": -1.29,
   "lng": 36.82,
   "sides": {
    "kind": "two sides",
    "A": {
     "label": "Government-friendly outlets",
     "articles": 3,
     "outlets": [
      "Capital Wire"
     ]
    },
    "B": {
     "label": "Opposition-leaning outlets",
     "articles": 4,
     "outlets": [
      "Meridian Daily",
      "Coastline Times"
     ]
    },
    "howA": "Focused on the budget gap the levy was meant to close.",
    "howB": "Focused on pump prices and called the ruling a win for drivers.",
    "words": [
     {
      "a": "revenue measure",
      "b": "fuel tax"
     }
    ]
   },
   "articles": 9,
   "outlets": 7,
   "claims": 27,
   "claimsBacked": 26,
   "made": "2026-11-26T11:20:00-05:00",
   "minutes": 4.3,
   "cost": 0.64,
   "hot": 4.9,
   "momentum": "+1 report in 6 h",
   "clip": 6,
   "duration": "1:05",
   "reported": false
  },
  {
   "id": "v-hokkaido",
   "chain": "hokkaido-quake",
   "part": 1,
   "of": 1,
   "headline": "Hokkaido quake: no tsunami, 90,000 homes without power",
   "dek": "A magnitude 6.1 quake off the east coast; trains stopped for safety checks.",
   "category": "disaster",
   "subtype": "earthquake",
   "country": "Japan",
   "region": "Asia",
   "place": "Kushiro, Hokkaido",
   "lat": 42.98,
   "lng": 144.38,
   "sides": {
    "kind": "no real divide",
    "reason": "Outlets agree on the facts; there is no political divide in the coverage."
   },
   "articles": 12,
   "outlets": 10,
   "claims": 30,
   "claimsBacked": 30,
   "made": "2026-11-25T21:15:00-05:00",
   "minutes": 4,
   "cost": 0.57,
   "hot": 3.8,
   "momentum": "0 reports in 6 h",
   "clip": 7,
   "duration": "1:00",
   "reported": false,
   "remakeOrdered": true
  },
  {
   "id": "v-valparaiso",
   "chain": "valparaiso-fire",
   "part": 1,
   "of": 1,
   "headline": "Wildfire forces 4,000 from homes near Valparaíso",
   "dek": "Strong winds push the fire toward the hills above Viña del Mar.",
   "category": "disaster",
   "subtype": "wildfire",
   "country": "Chile",
   "region": "South America",
   "place": "Viña del Mar",
   "lat": -33.02,
   "lng": -71.55,
   "sides": {
    "kind": "no real divide",
    "reason": "Outlets agree on what happened."
   },
   "articles": 10,
   "outlets": 8,
   "claims": 24,
   "claimsBacked": 23,
   "made": "2026-11-26T08:45:00-05:00",
   "minutes": 4.4,
   "cost": 0.61,
   "hot": 4.4,
   "momentum": "+2 reports in 6 h",
   "clip": 8,
   "duration": "0:59",
   "reported": true,
   "hidden": true
  }
 ],
 "chains": {
  "beni-floods": [
   {
    "id": "v-beni-1",
    "headline": "Heavy rain swells rivers across Beni",
    "made": "2026-11-24T16:00:00-05:00",
    "clip": 1
   },
   {
    "id": "v-beni-2",
    "headline": "Three towns cut off as Beni floods spread",
    "made": "2026-11-25T19:30:00-05:00",
    "clip": 1
   },
   {
    "id": "v-beni-3",
    "headline": "Army airlifts food to flooded Beni towns",
    "made": "2026-11-27T09:12:00-05:00",
    "clip": 1
   }
  ],
  "belgorod-depot": [
   {
    "id": "v-belgorod-1",
    "headline": "Drone attacks reported across Belgorod region",
    "made": "2026-11-25T23:50:00-05:00",
    "clip": 3
   },
   {
    "id": "v-belgorod-2",
    "headline": "Fuel depot burns after drone strike near Belgorod",
    "made": "2026-11-26T22:40:00-05:00",
    "clip": 3
   }
  ],
  "kenya-fuel": [
   {
    "id": "v-kenya-levy",
    "headline": "Court halts Kenya's new fuel levy",
    "made": "2026-11-26T11:20:00-05:00",
    "clip": 6
   },
   {
    "id": "e-nairobi-highway",
    "headline": "(being made) Protesters block the Nairobi–Mombasa highway",
    "made": null
   }
  ]
 },
 "events": [
  {
   "id": "e-beni-airlift",
   "title": "Bolivian army begins airlift to flood-isolated towns in Beni",
   "category": "disaster",
   "subtype": "flood",
   "country": "Bolivia",
   "region": "South America",
   "severity": 3,
   "confidence": "Verified",
   "reports": 38,
   "lastReport": "6 min ago",
   "state": "has_video",
   "video": "v-beni-3",
   "chain": "beni-floods"
  },
  {
   "id": "e-nairobi-highway",
   "title": "Protesters block Nairobi–Mombasa highway over fuel prices",
   "category": "political",
   "subtype": "protest",
   "country": "Kenya",
   "region": "Africa",
   "severity": 3,
   "confidence": "Developing",
   "reports": 21,
   "lastReport": "3 min ago",
   "state": "making",
   "progress": {
    "step": "check",
    "pct": 58,
    "startedAgo": "2 min 40 s",
    "by": "another student"
   },
   "chain": "kenya-fuel",
   "followUpOf": "v-kenya-levy"
  },
  {
   "id": "e-us-cr",
   "title": "US Senate passes continuing resolution ahead of funding deadline",
   "category": "political",
   "subtype": "legislation",
   "country": "United States",
   "region": "North America",
   "severity": 2,
   "confidence": "Verified",
   "reports": 44,
   "lastReport": "18 min ago",
   "state": "has_video",
   "video": "v-stopgap"
  },
  {
   "id": "e-eu-steel",
   "title": "EU ministers agree new tariffs on steel imports",
   "category": "economic",
   "subtype": "trade",
   "country": "Belgium",
   "region": "Europe",
   "severity": 2,
   "confidence": "Verified",
   "reports": 17,
   "lastReport": "11 min ago",
   "state": "making",
   "progress": {
    "step": "search",
    "pct": 14,
    "startedAgo": "40 s",
    "by": "you"
   }
  },
  {
   "id": "e-gorkha-slide",
   "title": "Landslide blocks main highway in Nepal's Gorkha district",
   "category": "disaster",
   "subtype": "landslide",
   "country": "Nepal",
   "region": "Asia",
   "severity": 3,
   "confidence": "Developing",
   "reports": 12,
   "lastReport": "24 min ago",
   "state": "ready",
   "estimate": 0.66
  },
  {
   "id": "e-belgorod-depot",
   "title": "Drone strike sparks large fire at fuel depot in Belgorod region",
   "category": "conflict",
   "subtype": "drone strike",
   "country": "Russia",
   "region": "Europe",
   "severity": 4,
   "confidence": "Developing",
   "reports": 29,
   "lastReport": "41 min ago",
   "state": "has_video",
   "video": "v-belgorod-2",
   "chain": "belgorod-depot"
  },
  {
   "id": "e-kasai-cholera",
   "title": "Cholera cases rise in Kasai province as clinics run short of fluids",
   "category": "humanitarian",
   "subtype": "outbreak",
   "country": "DR Congo",
   "region": "Africa",
   "severity": 3,
   "confidence": "Developing",
   "reports": 9,
   "lastReport": "1 h ago",
   "state": "ready",
   "estimate": 0.66
  },
  {
   "id": "e-muscat-talks",
   "title": "Talks on Red Sea shipping corridor resume in Muscat",
   "category": "political",
   "subtype": "diplomacy",
   "country": "Oman",
   "region": "Middle East",
   "severity": 2,
   "confidence": "Developing",
   "reports": 14,
   "lastReport": "2 h ago",
   "state": "no_video",
   "reason": "The fact check couldn't back the opening line."
  },
  {
   "id": "e-basra-fire",
   "title": "Fire at Basra hospital kills at least nine",
   "category": "disaster",
   "subtype": "fire",
   "country": "Iraq",
   "region": "Middle East",
   "severity": 4,
   "confidence": "Verified",
   "reports": 26,
   "lastReport": "2 h ago",
   "state": "hidden",
   "video": "v-basra",
   "hiddenNote": "Hidden while we check a report."
  },
  {
   "id": "e-malawi-count",
   "title": "Electoral commission delays count in Malawi local elections",
   "category": "political",
   "subtype": "election",
   "country": "Malawi",
   "region": "Africa",
   "severity": 2,
   "confidence": "Verified",
   "reports": 8,
   "lastReport": "3 h ago",
   "state": "ready",
   "estimate": 0.66
  }
 ]
};
