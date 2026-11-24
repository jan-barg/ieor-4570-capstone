"""Hand seed for the first outlets.csv (built once, Nov 24). After the build, outlets.csv is the
only source of truth and is edited by hand; this file is kept to show how the first draft was made.

Columns: outlet_id | name | domains | extra x handles | kind | country (point of view) |
AllSides news entry name | Lin domain override | State Media Monitor id | extra opinion folders |
notes | review (why Jan should look at this row; blank = routine)

Countries are ISO 3166-1 alpha-2, plus EU (pan-European outlet) and INT (international body or
aggregator). AllSides ratings, Lin et al. scores, Wikidata ids and the SMM level are joined in by
build_outlets.py from the files in stringer_private/outlet_labels_tests/."""

SEED = r"""
# --- Monitor the Situation's own outlet domains (44) ---
straitstimes|The Straits Times|straitstimes.com|straits_times|news|SG|||SMM-0520|||
aljazeera|Al Jazeera|aljazeera.com;aljazeera.net|AJENews;AJEnglish|news|QA|Al Jazeera||SMM-0236||MtS X account @AJENews|
jpost|The Jerusalem Post|jpost.com|Jerusalem_Post|news|IL|The Jerusalem Post|||||
scmp|South China Morning Post|scmp.com|SCMPNews|news|HK|South China Morning Post||||Owned by Alibaba; Wikidata says CN|country: HK (Hong Kong) or CN?
theguardian|The Guardian|theguardian.com;guardian.co.uk|guardian|news|GB|The Guardian||||Full text comes from the Guardian API|
allafrica|AllAfrica|allafrica.com||news|INT|||||Aggregator that republishes ~100 African outlets; the original outlet is named in the article|country INT (aggregator); rate by original outlet later?
anadolu|Anadolu Agency|aa.com.tr|anadoluagency|wire|TR|Anadolu Agency||SMM-0112|||
dawn|Dawn|dawn.com|dawn_com|news|PK||||||
france24|France 24|france24.com|France24_en|news|FR|France 24||SMM-0009||AllSides page exists but says Not Rated|
kyivindependent|The Kyiv Independent|kyivindependent.com|KyivIndependent|news|UA|The Kyiv Independent||||MtS X account @KyivIndependent|
yonhap|Yonhap News Agency|en.yna.co.kr;yna.co.kr||wire|KR|||SMM-0479||Not in Lin et al.|
abcnews|ABC News|abcnews.go.com;abcnews.com|ABC|news|US|ABC News (Online)|abcnews.go.com|||AllSides lists abcnews.go.com; MtS and Tavily use abcnews.com|
timesofindia|The Times of India|timesofindia.indiatimes.com|timesofindia|news|IN||||||
japantimes|The Japan Times|japantimes.co.jp|japantimes|news|JP|The Japan Times|||||
africanews|Africanews|africanews.com|africanews|news|CG|||||Euronews' African channel, based in Pointe-Noire (Congo)|country CG?
meduza|Meduza|meduza.io|meduzaproject|news|RU|||||Russian exile outlet; legal seat Latvia; country = point of view (Jan, Nov 24)|
upi|United Press International|upi.com|UPI|wire|US|United Press International|||||
bbc|BBC News|bbc.com;bbc.co.uk|BBCWorld;BBCBreaking|news|GB|BBC News|bbc.com|SMM-0028||Lin: bbc.com 0.88, bbc.co.uk 0.72; the file uses bbc.com|
abc_au|ABC News (Australia)|abc.net.au||news|AU|||SMM-0640|||
cna|CNA|channelnewsasia.com|ChannelNewsAsia|news|SG|||SMM-0519||Mediacorp|
dailymaverick|Daily Maverick|dailymaverick.co.za|dailymaverick|news|ZA||||||
moscowtimes|The Moscow Times|themoscowtimes.com|MoscowTimes|news|RU|The Moscow Times||||Exile outlet (Amsterdam); country = point of view|
npr|NPR|npr.org|NPR|news|US|NPR (Online News)||SMM-0637|||
dw|Deutsche Welle|dw.com|DeutscheWelle|news|DE|Deutsche Welle||SMM-0014|||
militarytimes|Military Times|militarytimes.com|MilitaryTimes|news|US|Military Times|||||
un_news|UN News|news.un.org||intergovernmental|INT||||||
breakingdefense|Breaking Defense|breakingdefense.com||news|US||||||
tribune_pk|The Express Tribune|tribune.com.pk|etribune|news|PK||||||
navalnews|Naval News|navalnews.com||news|FR|||||Naval trade site based in France|country FR? kind news?
thediplomat|The Diplomat|thediplomat.com|Diplomat_APAC|news|US|||||Asia-Pacific magazine; legal seat US (Wikidata)|country US?
dominicantoday|Dominican Today|dominicantoday.com||news|DO||||||
batimes|Buenos Aires Times|batimes.com.ar||news|AR||||||
skynews|Sky News|news.sky.com|SkyNews|news|GB|Sky News (UK)||||Tavily returns snippets only|
reliefweb|ReliefWeb|reliefweb.int|reliefweb|intergovernmental|INT|||||UN OCHA service; reposts agency and NGO reports|
twz|The War Zone|twz.com;thewarzone.com||news|US||||||
nosi|nosi.org (naval news)|nosi.org||news|US|||||Naval news site; publisher not identified|who runs nosi.org? country/kind?
defenseone|Defense One|defenseone.com|DefenseOne|news|US|Defense One|||||
longwarjournal|FDD's Long War Journal|longwarjournal.org||research|US|||||Project of the Foundation for Defense of Democracies|
gdacs|GDACS|gdacs.org|gdacs|intergovernmental|INT|||||UN and European Commission disaster alert system|
navylookout|Navy Lookout|navylookout.com||news|GB|||||Independent Royal Navy blog|kind: news or research?
usgs|US Geological Survey|usgs.gov;earthquake.usgs.gov||official|US||||||
noaa|NOAA (incl. National Hurricane Center)|noaa.gov;nhc.noaa.gov||official|US||||||
bellingcat|Bellingcat|bellingcat.com|bellingcat|research|NL||||||
globaltimes|Global Times|globaltimes.cn|globaltimesnews|news|CN|||SMM-0445||People's Daily group|
gulfnews|Gulf News|gulfnews.com|gulf_news|news|AE|||||MtS X account @gulf_news|

# --- US outlets with AllSides ratings ---
cnn|CNN|cnn.com|CNN|news|US|CNN Digital|||||
foxnews|Fox News|foxnews.com|FoxNews|news|US|Fox News Digital|||||
nypost|New York Post|nypost.com|nypost|news|US|New York Post (News)|||||
cnbc|CNBC|cnbc.com|CNBC|news|US|CNBC|||||
cbsnews|CBS News|cbsnews.com|CBSNews|news|US|CBS News (Online)|||||
ap|Associated Press|apnews.com|AP|wire|US|Associated Press||||MtS X account @AP|
nbcnews|NBC News|nbcnews.com|NBCNews|news|US|NBC News Digital|||think||
nytimes|The New York Times|nytimes.com|nytimes|news|US|New York Times (News)|||||
huffpost|HuffPost|huffpost.com|HuffPost|news|US|HuffPost|||||
washingtonpost|The Washington Post|washingtonpost.com|washingtonpost|news|US|The Washington Post|||||
politico|Politico|politico.com|politico;politicomag|news|US|Politico|||||
pbs_newshour|PBS NewsHour|pbs.org/newshour|NewsHour|news|US|PBS NewsHour|pbs.org|SMM-0638||AllSides rating covers pbs.org/newshour only|
pbs|PBS|pbs.org|PBS|news|US||pbs.org|SMM-0638||Other pbs.org pages: no AllSides rating|
time|Time|time.com|TIME|news|US|Time Magazine||||Doesn't mark opinion in its URLs|
newsweek|Newsweek|newsweek.com|Newsweek|news|US|Newsweek||||Doesn't mark opinion in its URLs|
reuters|Reuters|reuters.com|Reuters|wire|GB|Reuters||||Tavily returns snippets only; MtS X account @Reuters; newsroom HQ London|country GB or US?
axios|Axios|axios.com|axios|news|US|Axios|||||
latimes|Los Angeles Times|latimes.com|latimes|news|US|Los Angeles Times|||||
usatoday|USA Today|usatoday.com|USATODAY|news|US|USA TODAY|||||
thehill|The Hill|thehill.com|thehill|news|US|The Hill|||||
foxbusiness|Fox Business|foxbusiness.com|FoxBusiness|news|US|Fox Business|||||
wsj|The Wall Street Journal|wsj.com|WSJ|news|US|Wall Street Journal (News)|||||
breitbart|Breitbart News|breitbart.com|BreitbartNews|news|US|Breitbart News|||||
washingtonexaminer|Washington Examiner|washingtonexaminer.com|dcexaminer|news|US|Washington Examiner|||||
bloomberg|Bloomberg|bloomberg.com|business|news|US|Bloomberg|||||
nationalreview|National Review|nationalreview.com|nro|news|US|National Review (News)|||*;!news|AllSides' news rating covers nationalreview.com/news only; every other page is treated as opinion and takes the opinion rating|
washingtontimes|The Washington Times|washingtontimes.com|WashTimes|news|US|Washington Times|||||
euronews|Euronews|euronews.com|euronews|news|EU|Euronews||||Pan-European, HQ Brussels|country EU?
forbes|Forbes|forbes.com|Forbes|news|US|Forbes||||Contributor posts (/sites/) aren't marked as opinion|
ft|Financial Times|ft.com|FT|news|GB|Financial Times|||||
newsmax|Newsmax|newsmax.com|newsmax|news|US|Newsmax (News)|||||
epochtimes|The Epoch Times|theepochtimes.com|EpochTimes|news|US|The Epoch Times|||||
dailybeast|The Daily Beast|thedailybeast.com|thedailybeast|news|US|Daily Beast|||||
dailywire|The Daily Wire|dailywire.com|realDailyWire|news|US|The Daily Wire|||||
townhall|Townhall|townhall.com|townhallcom|news|US|Townhall|||||
redstate|RedState|redstate.com|RedState|news|US|RedState|||||
dailycaller|The Daily Caller|dailycaller.com|DailyCaller|news|US|The Daily Caller|||||
dailymail|Daily Mail|dailymail.co.uk;dailymail.com|MailOnline|news|GB|Daily Mail|||||
dailysignal|The Daily Signal|dailysignal.com|DailySignal|news|US|The Daily Signal||||Published by the Heritage Foundation|
motherjones|Mother Jones|motherjones.com|MotherJones|news|US|Mother Jones|||||
blaze|Blaze Media|theblaze.com|theblaze|news|US|Blaze Media|||||
semafor|Semafor|semafor.com|semafor|news|US|Semafor|||||
slate|Slate|slate.com|Slate|news|US|Slate|||||
theatlantic|The Atlantic|theatlantic.com|TheAtlantic|news|US|The Atlantic|||||
federalist|The Federalist|thefederalist.com|FDRLST|news|US|The Federalist|||||
vox|Vox|vox.com|voxdotcom|news|US|Vox|||||
csmonitor|The Christian Science Monitor|csmonitor.com|csmonitor|news|US|Christian Science Monitor|||||
economist|The Economist|economist.com|TheEconomist|news|GB|The Economist|||||
freebeacon|Washington Free Beacon|freebeacon.com|FreeBeacon|news|US|Washington Free Beacon|||||
justthenews|Just the News|justthenews.com|JustTheNews|news|US|Just The News|||||
marketwatch|MarketWatch|marketwatch.com|MarketWatch|news|US|MarketWatch|||||
msnow|MS NOW (formerly MSNBC)|ms.now;msnbc.com|MSNBC|news|US|MS NOW|msnbc.com|||Renamed from MSNBC; Lin score is msnbc.com's|
realclearpolitics|RealClearPolitics|realclearpolitics.com|RealClearNews|news|US|RealClearPolitics (Aggregator)||||Mostly links to other outlets|
thefp|The Free Press|thefp.com|TheFP|news|US|The Free Press||||Not in Lin et al.|
rt|RT|rt.com|RT_com|news|RU|RT||SMM-0135|||
tass|TASS|tass.com;tass.ru|tassagency_en|wire|RU|TASS|tass.com|SMM-0137||AllSides page exists but says Not Rated|

# --- Other English-language outlets seen in the Tavily tests ---
politico_eu|Politico Europe|politico.eu|POLITICOEurope|news|EU|||||AllSides' Politico rating is for the US site, so none here|
euractiv|Euractiv|euractiv.com||news|EU||||||
euobserver|EUobserver|euobserver.com|euobs|news|EU||||||
cbc|CBC News|cbc.ca||news|CA|||SMM-0636|||
independent_uk|The Independent|independent.co.uk;the-independent.com||news|GB||||||
thetimes_uk|The Times (UK)|thetimes.com;thetimes.co.uk||news|GB||||||
globeandmail|The Globe and Mail|theglobeandmail.com||news|CA||||||
chicagotribune|Chicago Tribune|chicagotribune.com||news|US||||||
seattletimes|The Seattle Times|seattletimes.com||news|US||||||
houstonchronicle|Houston Chronicle|houstonchronicle.com||news|US||||||
businessinsider|Business Insider|businessinsider.com||news|US||||||
itv|ITV News|itv.com||news|GB||||||
swissinfo|Swissinfo|swissinfo.ch||news|CH|||SMM-0027|||
military_com|Military.com|military.com||news|US||||||
coindesk|CoinDesk|coindesk.com||news|US||||||
theblock|The Block|theblock.co||news|US||||||
afp|AFP|afp.com||wire|FR|||||AFP stories mostly appear on other sites|
kyodo|Kyodo News|english.kyodonews.net;kyodonews.net||wire|JP||||||
nhk|NHK World|nhk.or.jp||news|JP|||SMM-0456|||
mainichi|The Mainichi|mainichi.jp||news|JP||||||
asahi|The Asahi Shimbun|asahi.com||news|JP||||||
nikkei|Nikkei Asia|asia.nikkei.com;nikkei.com||news|JP||||||
trtworld|TRT World|trtworld.com||news|TR|||SMM-0119|||
voa|Voice of America|voanews.com||news|US|||SMM-0639|||
rferl|Radio Free Europe/Radio Liberty|rferl.org||news|US|||SMM-0639|||
premiumtimes|Premium Times|premiumtimesng.com||news|NG||||||
punch|Punch|punchng.com||news|NG||||||
channelstv|Channels Television|channelstv.com||news|NG||||||

# --- Side outlets for the test stories' lenses (answer_sheets_v1) ---
# Ukraine / Russia
ukrinform|Ukrinform|ukrinform.net;ukrinform.ua||wire|UA|||SMM-0196|||
pravda_ua|Ukrainska Pravda|pravda.com.ua|ukrpravda_news|news|UA||||||
kyivpost|Kyiv Post|kyivpost.com|KyivPost|news|UA||||||
unian|UNIAN|unian.info;unian.ua||wire|UA||||||
euromaidan|Euromaidan Press|euromaidanpress.com|euromaidanpress|news|UA||||||
suspilne|Suspilne|suspilne.media||news|UA|||SMM-0194|||
nv_ua|NV (New Voice of Ukraine)|nv.ua|tweetsNV|news|UA||||||
ria|RIA Novosti|ria.ru|rianru|wire|RU|||SMM-0133||Rossiya Segodnya|
sputnik|Sputnik|sputnikglobe.com;sputniknews.com||news|RU|||SMM-0133||Rossiya Segodnya|
rg|Rossiyskaya Gazeta|rg.ru|rgrus|news|RU|||SMM-0134|||
interfax|Interfax|interfax.com;interfax.ru|interfax_news|wire|RU|||||Privately owned; not in the State Media Monitor|
izvestia|Izvestia|iz.ru||news|RU|||SMM-0129||National Media Group|
# Saudi / Gulf vs Houthi / Iran
arabnews|Arab News|arabnews.com|arabnews|news|SA|||SMM-0245||Saudi Research and Media Group|
aawsat|Asharq Al-Awsat|aawsat.com;english.aawsat.com||news|SA|||SMM-0245||Saudi Research and Media Group|
saudigazette|Saudi Gazette|saudigazette.com.sa|Saudi_Gazette|news|SA||||||
spa|Saudi Press Agency|spa.gov.sa|spagov|wire|SA|||SMM-0244|||
alarabiya|Al Arabiya|alarabiya.net;english.alarabiya.net|AlArabiya_Eng|news|SA||alarabiya.net|SMM-0242||MBC group; Lin: alarabiya.net 0.68, english.alarabiya.net 0.37; the file uses alarabiya.net|Lin domain choice
thenational|The National (UAE)|thenationalnews.com||news|AE|||SMM-0254|||
khaleejtimes|Khaleej Times|khaleejtimes.com||news|AE||||||
saba_ye|Saba News Agency (saba.ye)|saba.ye||wire|YE|||||Yemen has two rival SABA agencies (Houthi and UN-recognized government); SMM rates both State-Controlled|which SABA is saba.ye?
saba_net|Saba News Agency (sabanew.net)|sabanew.net||wire|YE|||||See saba.ye|which SABA is sabanew.net?
almasirah|Al Masirah|almasirah.net;english.almasirah.net||news|YE|||||Houthi-run TV; not in the State Media Monitor|
presstv|Press TV|presstv.ir;presstv.com|PressTV|news|IR|||SMM-0202||IRIB; Lin 0.69 is a known oddity (gap-filled)|
tasnim|Tasnim News Agency|tasnimnews.com;tasnimnews.ir|tasnimnews_en|wire|IR|||SMM-0209||Revolutionary Guards media|
irna|IRNA|irna.ir;en.irna.ir|IrnaEnglish|wire|IR|||SMM-0201|||
mehr|Mehr News Agency|mehrnews.com;en.mehrnews.com|MehrnewsCom|wire|IR|||SMM-0211||Islamic Ideology Dissemination Organization|
tehrantimes|Tehran Times|tehrantimes.com||news|IR|||SMM-0211||Islamic Ideology Dissemination Organization|
fars|Fars News Agency|farsnews.ir;en.farsnews.ir||wire|IR|||SMM-0199|||
almanar|Al-Manar|almanar.com.lb;english.almanar.com.lb||news|LB||almanar.com.lb|||Hezbollah's TV; not in the State Media Monitor (a party, not a state); Lin: almanar.com.lb 0.48, english 0.22|Lin domain choice
# Brazil
folha|Folha de S.Paulo|folha.uol.com.br|folha|news|BR||||||
uol|UOL|uol.com.br|UOL|news|BR||||||
g1|G1 (Globo)|g1.globo.com|g1|news|BR||||||
oglobo|O Globo|oglobo.globo.com||news|BR||||||
estadao|O Estado de S. Paulo|estadao.com.br|Estadao|news|BR||||||
cartacapital|CartaCapital|cartacapital.com.br|cartacapital|news|BR||||||
brasildefato|Brasil de Fato|brasildefato.com.br|brasildefato|news|BR||||||
brasil247|Brasil 247|brasil247.com|brasil247|news|BR||||||
revistaforum|Revista Fórum|revistaforum.com.br||news|BR||||||
gazetadopovo|Gazeta do Povo|gazetadopovo.com.br|gazetadopovo|news|BR||||||
revistaoeste|Revista Oeste|revistaoeste.com|revistaoeste|news|BR||||||
jovempan|Jovem Pan|jovempan.com.br||news|BR||||||
plenonews|Pleno.News|pleno.news||news|BR||||||
terrabrasil|Terra Brasil Notícias|terrabrasilnoticias.com||news|BR||||||
# Spain
elpais|El País|elpais.com|el_pais;elpaisinenglish|news|ES||||||
elmundo|El Mundo|elmundo.es|elmundoes|news|ES||||||
abc_es|ABC (Spain)|abc.es|abc_es|news|ES||||||
lavanguardia|La Vanguardia|lavanguardia.com|LaVanguardia|news|ES||||||
20minutos|20 minutos|20minutos.es|20m|news|ES||||||
eldiario|elDiario.es|eldiario.es|eldiarioes|news|ES||||||
elconfidencial|El Confidencial|elconfidencial.com|elconfidencial|news|ES||||||
rtve|RTVE|rtve.es||news|ES|||SMM-0046|||
efe|EFE|efe.com||wire|ES|||SMM-0049|||
# Serbia
informer_rs|Informer|informer.rs||news|RS|||SMM-0097|||
novosti_rs|Večernje novosti|novosti.rs||news|RS|||SMM-0105|||
b92|B92|b92.net||news|RS|||SMM-0098||Kopernikus Corporation|
rts|RTS|rts.rs||news|RS|||SMM-0102|||
politika_rs|Politika|politika.rs||news|RS|||SMM-0101|||
kurir_rs|Kurir|kurir.rs||news|RS|||SMM-0099||Mondo group|
tanjug|Tanjug|tanjug.rs||wire|RS|||SMM-0104|||
n1_rs|N1 Serbia|n1info.rs||news|RS||||||
nova_rs|Nova|nova.rs||news|RS||||||
danas_rs|Danas|danas.rs||news|RS||||||
vreme_rs|Vreme|vreme.com||news|RS||||||
balkaninsight|Balkan Insight (BIRN)|balkaninsight.com||news|RS|||||Regional Balkan network|country RS?
# Israel
haaretz|Haaretz|haaretz.com;haaretz.co.il|haaretzcom|news|IL||||||
timesofisrael|The Times of Israel|timesofisrael.com|TimesofIsrael|news|IL||||||
ynetnews|Ynetnews|ynetnews.com;ynet.co.il|ynetnews|news|IL||||||
israelhayom|Israel Hayom|israelhayom.com;israelhayom.co.il||news|IL||||||
inn|Israel National News (Arutz Sheva)|israelnationalnews.com||news|IL||||||
jns|JNS (Jewish News Syndicate)|jns.org||news|IL|||||US-registered, reports from an Israeli right-of-center view|country IL or US?
mag972|+972 Magazine|972mag.com||news|IL||||||
# France
lemonde|Le Monde|lemonde.fr|lemondefr|news|FR||||||
liberation|Libération|liberation.fr||news|FR||||||
humanite|L'Humanité|humanite.fr||news|FR||||||
mediapart|Mediapart|mediapart.fr||news|FR||||||
lefigaro|Le Figaro|lefigaro.fr||news|FR||||||
cnews|CNews|cnews.fr||news|FR||||||
valeursactuelles|Valeurs actuelles|valeursactuelles.com||news|FR||||||
lejdd|Le Journal du Dimanche|lejdd.fr||news|FR||||||
# Poland
wyborcza|Gazeta Wyborcza|wyborcza.pl||news|PL||||||
tvn24|TVN24|tvn24.pl||news|PL||||||
okopress|OKO.press|oko.press||news|PL||||||
gazeta_pl|Gazeta.pl|gazeta.pl||news|PL||||||
wpolityce|wPolityce|wpolityce.pl||news|PL||||||
dorzeczy|Do Rzeczy|dorzeczy.pl||news|PL||||||
niezalezna|Niezależna (Gazeta Polska)|niezalezna.pl||news|PL||||||
tvrepublika|TV Republika|tvrepublika.pl||news|PL||||||
rp_pl|Rzeczpospolita|rp.pl||news|PL||||||
notesfrompoland|Notes from Poland|notesfrompoland.com||news|PL||||||
tvp|TVP (TVP World, TVP Info)|tvpworld.com;tvp.info||news|PL|||SMM-0089|||
pap|Polish Press Agency|pap.pl||wire|PL|||SMM-0087|||
# China and Russia state media (Shenzhen summit)
xinhua|Xinhua|news.cn;english.news.cn;xinhuanet.com|XHNews|wire|CN||xinhuanet.com|SMM-0451||Lin: news.cn 0.69 but xinhuanet.com 0.31 and english.news.cn 0.33; the file uses xinhuanet.com|Lin domain choice
cgtn|CGTN|cgtn.com|CGTNOfficial|news|CN|||SMM-0438||China Media Group|
chinadaily|China Daily|chinadaily.com.cn||news|CN|||SMM-0436|||
# Myanmar vs The Gambia / Rohingya
gnlm|The Global New Light of Myanmar|gnlm.com.mm||news|MM|||SMM-0511||Junta-run|
mrtv|MRTV|mrtv.gov.mm||news|MM|||SMM-0509||Junta-run|
irrawaddy|The Irrawaddy|irrawaddy.com||news|MM|||||Exile outlet critical of the junta|
mizzima|Mizzima|mizzima.com||news|MM|||||Exile outlet critical of the junta|
myanmarnow|Myanmar Now|myanmar-now.org||news|MM|||||Exile outlet critical of the junta|
thepoint_gm|The Point|thepoint.gm||news|GM||||||
foroyaa|Foroyaa|foroyaa.net||news|GM||||||
standard_gm|The Standard (Gambia)|standard.gm||news|GM||||||
dailystar_bd|The Daily Star (Bangladesh)|thedailystar.net||news|BD|||||Bangladesh hosts the Rohingya camps|
tbsnews|The Business Standard (Bangladesh)|tbsnews.net||news|BD||||||

# --- Research groups, official and intergovernmental sites ---
isw|Institute for the Study of War|understandingwar.org||research|US||||||
cfr|Council on Foreign Relations|cfr.org||research|US||||||
atlanticcouncil|Atlantic Council|atlanticcouncil.org||research|US||||||
brookings|Brookings Institution|brookings.edu||research|US||||||
whitehouse|The White House|whitehouse.gov||official|US||||||
state_dept|US State Department|state.gov||official|US||||||
pentagon|US Department of Defense|defense.gov;war.gov||official|US||||||
cdc|CDC|cdc.gov||official|US||||||
federalreserve|Federal Reserve|federalreserve.gov||official|US||||||
congress|Congress.gov|congress.gov||official|US||||||
kremlin|Kremlin|kremlin.ru||official|RU||||||
mod_ua|Ukraine Ministry of Defence|mod.gov.ua||official|UA||||||
eu|European Union|europa.eu||intergovernmental|EU||||||
un|United Nations|un.org||intergovernmental|INT||||||
who|World Health Organization|who.int||intergovernmental|INT||||||
icj|International Court of Justice|icj-cij.org||intergovernmental|INT||||||

# --- Platforms: never rated (Google redirects, social posts, aggregators) ---
google|Google|google.com;news.google.com||platform|||||||
facebook|Facebook|facebook.com;fb.com||platform|||||||
instagram|Instagram|instagram.com||platform|||||||
youtube|YouTube|youtube.com;youtu.be||platform|||||||
x|X (not a post)|x.com;twitter.com||platform|||||||
reddit|Reddit|reddit.com||platform|||||||
linkedin|LinkedIn|linkedin.com||platform|||||||
tiktok|TikTok|tiktok.com||platform|||||||
yahoo|Yahoo|yahoo.com||platform||||||Copies of wire stories; open question whether to rate by original publisher|
msn|MSN|msn.com||platform||||||Copies of other outlets' stories|
substack|Substack|substack.com||platform|||||||
medium|Medium|medium.com||platform|||||||
telegram|Telegram|t.me;telegram.org||platform|||||||
threads|Threads|threads.net;threads.com||platform|||||||
bluesky|Bluesky|bsky.app||platform|||||||
wikipedia|Wikipedia|wikipedia.org||platform|||||||
tavily|Tavily|tavily.com||platform|||||||
"""


def rows():
    cols = ["outlet_id", "name", "domains", "x_handles", "kind", "country", "allsides",
            "rel_domain", "smm_id", "opinion_paths", "notes", "review"]
    for line in SEED.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != len(cols):
            raise ValueError(f"{len(parts)} fields, want {len(cols)}: {line}")
        yield dict(zip(cols, [p.strip() for p in parts]))
