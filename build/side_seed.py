"""Hand seed for side_lists.csv (built once, Nov 24).

Side lists are the outlet groups the side searches (query plan #3 and #4) search in.
The US lens needs no list here: code derives US left / US right / right tail from outlets.csv
(country US and the AllSides lean), so it follows the file when ratings change.

Which lens and sides each test story uses is fixture data, so it lives only in
stringer_private/fixtures/fixture_lenses_v1.csv (edited by hand there), not in this repo."""

SIDES = r"""
ukraine|Pro-Ukraine (Ukrainian outlets)|kyivindependent;ukrinform;pravda_ua;kyivpost;unian;euromaidan;suspilne;nv_ua
russia|Pro-Russia (Russian state and Russian outlets)|tass;rt;ria;sputnik;rg;interfax;izvestia
saudi_gulf|Saudi- and Gulf-aligned outlets|arabnews;aawsat;saudigazette;spa;alarabiya;thenational;gulfnews;khaleejtimes
houthi_iran|Houthi- and Iran-aligned outlets|saba_ye;saba_net;almasirah;presstv;tasnim;irna;mehr;tehrantimes;fars;almanar
iran|Iran-aligned outlets|presstv;tasnim;irna;mehr;tehrantimes;fars
us_gulf|US- and Gulf-aligned outlets|arabnews;aawsat;alarabiya;thenational;gulfnews;ap;cnn;foxnews;nytimes;wsj
br_pro_lula|Pro-Lula (left) Brazilian outlets|cartacapital;brasildefato;brasil247;revistaforum
br_pro_bolsonaro|Pro-Bolsonaro (right) Brazilian outlets|gazetadopovo;revistaoeste;jovempan;plenonews;terrabrasil
serbia_gov|Government-aligned (pro-Vucic) Serbian outlets|informer_rs;novosti_rs;b92;rts;politika_rs;kurir_rs;tanjug
serbia_indep|Independent and opposition Serbian outlets|n1_rs;nova_rs;danas_rs;vreme_rs;balkaninsight
israel_pro_netanyahu|Pro-Netanyahu outlets|israelhayom;inn;jns
israel_anti_netanyahu|Anti-Netanyahu outlets|haaretz;ynetnews;mag972
france_protest|Outlets sympathetic to the protesters|liberation;humanite;mediapart
france_order|Government and law-and-order outlets|lefigaro;cnews;valeursactuelles;lejdd
poland_liberal|Liberal Polish outlets|wyborcza;tvn24;okopress;gazeta_pl
poland_conservative|Conservative Polish outlets|wpolityce;dorzeczy;niezalezna;tvrepublika
china_russia_state|Chinese and Russian state outlets|xinhua;globaltimes;cgtn;chinadaily;tass;rt;ria;sputnik
western|Western outlets|bbc;theguardian;dw;france24;ft;economist;ap;nytimes;wsj;cnn;foxnews
myanmar_gov|Myanmar's government (junta) outlets|gnlm;mrtv
gambia_rohingya|The Gambia and Rohingya advocates|thepoint_gm;foroyaa;standard_gm;dailystar_bd;tbsnews;irrawaddy;mizzima;myanmarnow
trump_call|Backing Trump's call (US right and Russian outlets)|foxnews;nypost;washingtonexaminer;breitbart;dailywire;newsmax;federalist;tass;rt;ria
zelensky|Backing Zelensky (Ukrainian and European outlets)|kyivindependent;ukrinform;pravda_ua;kyivpost;bbc;theguardian;dw;politico_eu
"""

# event short id | lens | side_a | side_b | answer sheet number or chain parent



def _rows(text, cols):
    for line in text.strip().splitlines():
        if line.strip() and not line.startswith("#"):
            parts = [p.strip() for p in line.split("|")]
            assert len(parts) == len(cols), line
            yield dict(zip(cols, parts))


def sides():
    return list(_rows(SIDES, ["side_id", "label", "outlet_ids"]))
