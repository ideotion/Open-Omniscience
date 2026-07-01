<!-- Provenance record for PR #533 (224 live-verified non-English sources).
     Produced by a local Claude Code CLI run of docs/design/SOURCE_DIVERSIFICATION_BRIEF.md
     on 2026-07-01. Verbatim worker output: per-language/region/country added counts +
     the concatenated per-cluster rejection logs. Independently re-validated before merge
     (0 duplicates vs catalog + within batch, taxonomy gate green). -->

# Source diversification report — 2026-07 (language & region equilibrium)

**Total live-verified feeds added: 224**  
Dropped as duplicate of existing catalog (registrable-domain): 7 · Dropped as within-batch cross-cluster duplicate: 6 · Taxonomy problems after validation: 0

Every entry was fetched and parsed this run by a per-cluster verification subagent (HTTP 200 → RSS/Atom parse → ≥3 entries with title+link → ≥1 entry within ~120 days → robots.txt allows). `verified: true` attests to that. Zero US-focused sources. State-media labelled with an ownership tag, never scored. No aggregators, storefronts, or content-farms. Deduped vs `configs/sources.yml` on registrable domain and within the batch.

## Added — by content language

- **French** (`fr`): 32
- **Spanish** (`es`): 26
- **Portuguese** (`pt`): 19
- **English** (`en`): 13
- **Turkish** (`tr`): 12
- **Arabic** (`ar`): 11
- **Ukrainian** (`uk`): 9
- **Chinese** (`zh`): 8
- **Bengali** (`bn`): 7
- **Persian** (`fa`): 6
- **Telugu** (`te`): 5
- **Romanian** (`ro`): 5
- **Hungarian** (`hu`): 5
- **Tamil** (`ta`): 4
- **Korean** (`ko`): 4
- **Russian** (`ru`): 4
- **Polish** (`pl`): 4
- **Greek** (`el`): 4
- **Serbian** (`sr`): 4
- **Croatian** (`hr`): 4
- **Hindi** (`hi`): 3
- **Malayalam** (`ml`): 3
- **Japanese** (`ja`): 3
- **Swahili** (`sw`): 3
- **Urdu** (`ur`): 2
- **Kannada** (`kn`): 2
- **Marathi** (`mr`): 2
- **Malay** (`ms`): 2
- **Vietnamese** (`vi`): 2
- **Thai** (`th`): 2
- **Hausa** (`ha`): 2
- **Amharic** (`am`): 2
- **Czech** (`cs`): 2
- **Slovak** (`sk`): 2
- **Indonesian** (`id`): 1
- **Tagalog** (`tl`): 1
- **Bulgarian** (`bg`): 1
- **Dutch** (`nl`): 1
- **Macedonian** (`mk`): 1
- **Albanian** (`sq`): 1

## Added — by region

- europe: 60
- asia: 57
- africa: 40
- south-america: 27
- middle-east: 26
- north-america: 8
- americas: 6

## Added — by cluster

- Cluster 1 Arabic: 16
- Cluster 10 Persian/Turkish: 18
- Cluster 11 Russian/Ukrainian: 14
- Cluster 12 CEE/Balkans/Greece: 30
- Cluster 13 Francophone beyond FR: 24
- Cluster 14 Fact-checkers: 9
- Cluster 2 South Asia (Hi/Bn/Ur): 18
- Cluster 3 South India (Ta/Te/Mr/Ml/Kn): 16
- Cluster 4 Chinese/Japanese/Korean: 15
- Cluster 5 SE Asia: 8
- Cluster 6 Lusophone: 19
- Cluster 7 Latin American Spanish: 23
- Cluster 8 Sub-Saharan (Sw/Am/Ha/Yo): 7
- Cluster 9 Africa EN/FR: 7

## Added — by country

in:25, tr:12, (none):10, ua:10, br:8, pt:6, bd:5, ir:5, ro:5, hu:5, tn:4, kr:4, mx:4, tz:4, sn:4, pl:4, gr:4, rs:4, hr:4, ca:4, dz:3, ma:3, pk:3, jp:3, cn:3, hk:3, ve:3, pe:3, ec:3, co:3, et:3, ht:3, be:3, ps:2, tw:2, my:2, vn:2, th:2, cv:2, ao:2, gt:2, cl:2, ar:2, bo:2, ng:2, cz:2, sk:2, cd:2, ch:2, qa:1, kw:1, iq:1, sd:1, jo:1, id:1, ph:1, mz:1, uy:1, sv:1, zw:1, cm:1, bg:1, ci:1, cg:1, ml:1, bf:1, tg:1, bj:1, nl:1, mk:1, al:1


## Rejection logs (concatenated, per cluster)

_These are the candidates each worker fetched and dropped, with reasons (dead / not-XML / robots / duplicate / stale / country-unknown / 404-no-feed / blocked-403)._

### Cluster 1 — Arabic — rejection log
Duplicates (already in existing_domains.txt): aljazeera.net, aawsat.com, alquds.co.uk, almasryalyoum.com, shorouknews.com, youm7.com, madamasr.com, hespress.com, tsa-algerie.com, sana.sy, annahar.com, al-akhbar.com, okaz.com.sa, alriyadh.com, spa.gov.sa, albayan.ae, alanba.com.kw, alraimedia.com, qna.org.qa, addustour.com, jordantimes.com, elwatan-dz.com, mapnews.ma, le360.ma, businessnews.com.tn, nawaat.org, skynewsarabia.com, aa.com.tr, middleeasteye.net, independentarabia.com, gate.ahram.org.eg, egypttoday.com, dailynewsegypt.com, naharnet.com, lorientlejour.com, shafaq.com; PLUS daraj.media (caught at orchestrator global-dedup).
Blocked (403/429 to OO UA): alarabiya.net, enabbaladi.net, gulftoday.ae, alyaum.com, alayam.com, alwatannews.net, alghad.com, maannews.net, palestinechronicle.com(429), almayadeen.net, raialyoum.com, dostor.org, filgoal.com, syriahr.com, ina.iq, alrakoba.net, paltoday.ps, cairo24.com, palestine-studies.org.
404/no feed: emaratalyoum.com, alqabas.com, raya.com, omandaily.om, atheer.om, shabiba.com, wafa.ps, khaberni.com, alwatanvoice.com, aps.dz, lematin.ma, al-jazirah.com, aleqt.com, elwatannews.com, muscatdaily.com, ammonnews.net, almahriah.net, qudsn.co, safa.ps, libyaobserver.ly, libyaherald.com, megaphone.news, bna.bh(405).
Not-XML: aletihad.ae, sabq.org, eldorar.com, alsumaria.tv, sarayanews.com.
Stale/unusable: masrawy.com(no pubDate), almasdaronline.com(no dates), sudanakhbar.com(1 entry).
Dead: kuna.net.kw, almirbad.net, jfranews.com.jo, tap.info.tn, almassae.press, saba.ye/sabanew.net(500), alsouria.net(521), nasnews.com(hijacked redirect).

### Cluster 2 — South Asia (Hindi/Bengali/Urdu + EN IN/PK/BD) — rejection log
Duplicate: dainikbhaskar.com(->bhaskar.com).
Stale: navbharattimes.indiatimes.com, arabnews.pk(no dates), thekashmirwalla.com, urdunews.com.
Dead: dailypakistan.com.pk, samakal.com, livehindustan.com.
Not-XML/0-entries: patrika.com, eisamay.com(410), samaa.tv, dunyanews.tv, dailynayadiganta.com, urdu.geo.tv, dailyaaj.com.pk, urdu.dunyanews.tv.
404/no-feed: bartamanpatrika.com, jansatta.com, punjabkesari.in, unb.com.bd, profit.pakistantoday.com.pk, uniindia.com, millenniumpost.in, swarajyamag.com, hamariweb.com, inquilab.com, etemaaddaily.com.
Robots/403: newagebd.net, daily-sun.com, observerbd.com, bolnews.com, news18.com(+hindi/bengali), zeenews.india.com, dailyexcelsior.com, propakistani.pk, bd-pratidin.com, deshrupantor.com.

### Cluster 3 — South Indian languages (Tamil/Telugu/Marathi/Malayalam/Kannada) — rejection log
Duplicates(existing): eenadu.net, lokmat.com, bhaskar.com(divya marathi), mathrubhumi.com, manoramaonline.com, prajavani.net.
404/no-feed: dinamalar.com, dinamani.com, dinakaran.com, maalaimalar.com, andhrajyothy.com, loksatta.com, maharashtratimes.com, esakal.com, madhyamam.com, deshabhimani.com, mangalam.com, asianetnews.com, reporterlive.com, vijaykarnataka.com, kannadaprabha.com, vijayavani.net.
403/blocked: news18.com(all langs), saamana.com, zeenews.india.com(zee24taas).
Redirect-loop/no-feed: news18marathi.com, lokshahi.com, udayavani.com.
Dead(000): prajasakti.com, mediaonetv.in.
0-entries/empty: abplive.com(marathi).
Stale: oneindia.com(marathi/tamil/etc 2026-01), keralakaumudi.com, suprabhaatham.com.
Aggregator/domain-collision: oneindia.com editions (single registrable domain).

### Cluster 4 — Chinese/Japanese/Korean — rejection log
Duplicates: scmp.com, nhk.or.jp, asahi.com, mainichi.jp, yomiuri.co.jp, japantimes.co.jp, jiji.com, kyodonews.net, yna.co.kr, koreaherald.com, koreatimes.co.kr, donga.com, udn.com, ltn.com.tw, taipeitimes.com, thepaper.cn, xinhuanet.com, sixthtone.com, hk01.com, mingpao.com, hongkongfp.com, globaltimes.cn, hket.com, nippon.com.
Stale: people.com.cn(2025-06), chinadaily.com.cn(2017), hani.co.kr(no dates).
Robots: mediatoday.co.kr(Disallow /rss/).
404/no-feed: cna.com.tw(only FeedBurner), chinatimes.com, sankei.com, storm.mg, yicai.com, gmw.cn, newtalk.tw, hankookilbo.com, jiemian.com, cls.cn, cnr.cn, ftv.com.tw, taiwannews.com.tw, pts.org.tw.
Not-XML/0-entries: nocutnews.co.kr, guancha.cn.
Dead: cts.com.tw(410), huxiu.com(timeout).
Aggregator: tw.news.yahoo.com, ettoday.net(FeedBurner only).

### Cluster 5 — SE Asia — rejection log
Duplicates (already in catalog): kompas.com, detik.com, thairath.co.th, rappler.com, bernama.com, malaysiakini.com, cnnindonesia.com, antaranews.com, republika.co.id, tribunnews.com, katadata.co.id, bharian.com.my, freemalaysiatoday.com, dantri.com.vn, vietnamnet.vn, matichon.co.th, prachatai.com, bangkokpost.com, inquirer.net (newsinfo/bandera), philstar.com, bworldonline.com.
404/no-feed: liputan6.com, suara.com, thejakartapost.com, jakartaglobe.id, vov.vn, baochinhphu.vn, mgronline.com, bangkokbiznews.com, thaipbs.or.th, astroawani.com, mstar.com.my, manilatimes.net, philstar.com(pilipino-star).
Not-XML/0-entries: merdeka.com, tirto.id, laodong.vn, tienphong.vn, nhandan.vn, vietnamplus.vn, dailynews.co.th, thansettakij.com, nationthailand.com, sinarharian.com.my, abante.com.ph.
Blocked(403): mb.com.ph.
Dead(000): baotintuc.vn.

### Cluster 6 — Lusophone — rejection log
Duplicates: folha.uol.com.br, oglobo.globo.com, estadao.com.br, g1.globo.com, uol.com.br, agenciabrasil.ebc.com.br, cartacapital.com.br, nexojornal.com.br, apublica.org, poder360.com.br, metropoles.com, valor.globo.com, aosfatos.org, jota.info, publico.pt, observador.pt, expresso.pt, dn.pt, rtp.pt, jornaldeangola.ao, opais.co.mz, cartamz.com, asemana.publ.cv, dinheirovivo.pt(->dn.pt).
Robots: noticiasaominuto.com.
Dead/timeout: sicnoticias.pt(403), rr.pt, angop.ao, jornaldenoticias.co.mz, inforpress.cv(500), club-k.net(500).
404/no-feed: tsf.pt, novojornal.co.ao, savana.co.mz, mediafax.co.mz, opovo.com.br, brasildefato.com.br.
Stale: redeangola.info(2017).
Not-XML: verangola.net, valoreconomico.co.ao, opais.ao.
Out-of-scope: sol.iol.pt(brand ambiguity), tecmundo.com.br(content-farm-adjacent).

### Cluster 7 — Latin American Spanish — rejection log
Pre-filtered duplicates(existing): clarin.com, infobae.com, milenio.com, eltiempo.com, latercera.com, elfaro.net, confidencial.digital, andina.pe, armando.info, chequeado.com (+~50 more matched existing_domains.txt).
Stale: tiempoar.com.ar(2025-07), elsalvador.com(2025-04), hoy.com.py(2023).
Blocked(403/429): peru21.pe, lapatilla.com, wambra.ec.
Not-XML/challenge: desinformemonos.org, lasillarota.com, soy502.com, nomada.gt, resumen.cl, lajornadamaya.mx, noticiasfides.com.
404/no-feed: tn.com.ar, df.cl, bluradio.com, portafolio.co, vistazo.com, minutouno.com, lanacion.com.py, laprensa.hn, elheraldo.hn, eldinamo.cl, adnradio.cl, busqueda.com.uy, laestrella.com.pa, eleconomista.com.mx, letrap.com.ar, eldestapeweb.com, opinion.com.bo, cambiocolombia.com, correodelsur.com, listindiario.com.
Redirect-non-feed: rcnradio.com.
Unreachable(000): 4pelagatos.com, brujuladigital.io, erbol.com.bo, sudestada.com.uy, elcolombiano.com, cooperativa.cl, elheraldo.co.

### Cluster 8 — Sub-Saharan Africa (Swahili/Amharic/Hausa/Yoruba) — rejection log
Duplicates: bbc.com, dw.com, rfi.fr, aa.com.tr, dailytrust.com, legit.ng, leadership.ng, mwananchi.co.tz, nation.africa, globalvoices.org, premiumtimesng.com, alwihdainfo.com, addisstandard.com, voanews.com.
Within-batch dup domain: trtafrika.com (Swahili section dropped; Hausa kept).
Stale (VOA/USAGM suspended 2025 + others): voaswahili.com, amharic.voanews.com, voahausa.com(0 entries), rariya.com.ng, addismaleda.com.
No-feed/maintenance/parking: millardayo.com, alaroye.org, alaroye.com, iwe-iroyin.com, yoruba.com.ng.
Not-XML/blocked/0-entries: mtanzania.co.tz, raiamwema.co.tz, mwanahalisionline.com, waltainfo.com, ippmedia.com, clouds.co.tz, blueprint.ng.
Dead/DNS: uhuru.co.tz.
404/no-feed: borkena.com, addisadmassnews.com, press.et, ena.et.
NOTE: Yoruba yielded no live feed this run (all candidates parked/stale/dead) — honestly omitted.

### Cluster 9 — Africa English/French outlets — rejection log
Duplicates(existing): thecitizen.co.tz, dailymaverick.co.za, mg.co.za, standardmedia.co.ke, businessdailyafrica.com, graphic.com.gh, myjoyonline.com, actualite.cd, newtimes.co.rw, monitor.co.ug, herald.co.zw, addisstandard.com, thecable.ng, guardian.ng, ewn.co.za, newvision.co.ug, punchng.com, vanguardngr.com, dailytrust.com, nairametrics.com, iol.co.za, citizen.co.za, timeslive.co.za, sowetanlive.co.za, the-star.co.ke, nation.africa, capitalfm.co.ke, citinewsroom.com, 3news.com, theeastafrican.co.ke, seneweb.com, radiookapi.net, observer.ug, ktpress.rw, lusakatimes.com, diggers.news, newsday.co.zw, journalducameroun.com, thereporterethiopia.com, zimlive.com, leadership.ng, businessday.ng, dailypost.ng, saharareporters.com, groundup.org.za, news24.com, dakaractu.com.
Robots/ambiguous: jeuneafrique.com(Disallow /*/feed + France-based).
404/no-feed/not-XML: nilepost.co.ug, fratmat.info, businessincameroon.com, enca.com, mediacongo.net, 7sur7.cd.
Dead/DNS: actualite7sur7.cd.
Dropped (shared infra dup): chronicle.co.zw(->herald infra).

### Cluster 10 — Persian + Turkish — rejection log
Duplicates: mehrnews.com, presstv.ir, isna.ir, radiofarda.com, iranintl.com, radiozamaneh.com, iranwire.com, bbc.com, dw.com, aa.com.tr, birgun.net, t24.com.tr, bianet.org, diken.com.tr, evrensel.net, sozcu.com.tr, milliyet.com.tr, duvarenglish.com.
Dead/DNS/timeout: tasnimnews.com, farsnews.ir, shargdaily.com, akhbar-rooz.com, gercekgundem.com(TLS), haber.sol.org.tr(TLS).
404/no-feed: etemadonline.com, mardomsalari.ir, independentpersian.com, news.gooya.com, trtworld.com, dokuz8haber.net, independentturkish.com.
Robots/403: tavaana.org, parstoday.ir, gazeteduvar.com.tr.
Not-XML/0-entries: donya-e-eqtesad.com, hamshahrionline.ir.
Not-retried: peykeiran.com.

### Cluster 11 — Russian + Ukrainian — rejection log
Duplicates: meduza.io, novayagazeta.eu, istories.media, theins.ru, holod.media, agents.media, verstka.media, tass.ru, tass.com, ria.ru, rt.com, rg.ru, lenta.ru, sputnikglobe.com, pravda.com.ua, kyivindependent.com, kyivpost.com, ukrinform.net, hromadske.ua, nv.ua, tsn.ua, themoscowtimes.com, currenttime.tv.
Dead(000): republic.ru, bumaga.media/paperpaper.ru.
404/no-feed: novayagazeta.ru, doxa.team, 7x7-journal.ru, kavkaz-uzel.eu, interfax.com.ua, texty.org.ua, glavcom.ua, ukranews.com.
Robots/403: censor.net, day.kyiv.ua.
Not-XML/0-entries/stale: severreal.org, svoboda.org, zaborona.com, dt.ua/zn.ua.
NOTE (orchestrator): The Bell originally carried a "russia" tag (country name) — stripped to pass the taxonomy gate.

### Cluster 12 — CEE/Balkans/Greece — rejection log
Duplicates(existing): wyborcza.pl, rp.pl, tvn24.pl, oko.press, pap.pl, notesfrompoland.com, digi24.ro, hotnews.ro, g4media.ro, recorder.ro, n1info.rs, danas.rs, vreme.com, krik.rs, tovima.gr, naftemporiki.gr, protothema.gr, efsyn.gr, amna.gr, iefimerida.gr, telex.hu, hvg.hu, atlatszo.hu, direkt36.hu, 444.hu, 24.hu, jutarnji.hr, index.hr, telegram.hr, dnevnik.bg, novinite.com, mediapool.bg, idnes.cz, irozhlas.cz, denikn.cz, aktualne.cz, seznamzpravy.cz, dennikn.sk, aktuality.sk.
404/no-feed: forsal.pl, gazetaprawna.pl, polityka.pl, cnn.gr, b92.net, origo.hu, vijesti.hrt.hr, dnes.bg, fakti.bg, bta.bg, pravda.sk.
410-Gone: kathimerini.gr.
403/blocked: news247.gr, lifo.gr.
Robots: lidovky.cz(Disallow rss.aspx).
Not-XML/empty: novosti.rs, bnr.bg, respekt.cz.
Trimmed-for-cap(verified-live): telegraf.rs(tabloid), 24sata.hr(tabloid), mandiner.hu(redundant).
UNVERIFIED (sandbox-timeout, not retried, honestly NOT retained): niezalezna.pl, wpolityce.pl, adevarul.ro, libertatea.ro, agerpres.ro, spotmedia.ro.

### Cluster 13 — Francophone beyond France — rejection log
Duplicates(existing): tsa-algerie.com, le360.ma, telquel.ma, hespress.com, tunisienumerique.com, businessnews.com.tn, nawaat.org, seneweb.com, dakaractu.com, journalducameroun.com, radiookapi.net, actualite.cd, maliweb.net, lefaso.net, burkina24.com, actuniger.com, gabonreview.com, inkyfada.com, agenceecofin.com, financialafrik.com, 24haubenin.info, ledevoir.com, lapresse.ca, lesoir.be, rtbf.be, letemps.ch, 24heures.ch, tdg.ch, swissinfo.ch, watson.ch, lenouvelliste.com(ht), alterpresse.org.
Cross-batch dups (kept in cluster 1): medias24.com, lapresse.tn, kapitalis.com.
Dead/not-XML/no-feed: elwatan.com, maghrebemergent.info, yabiladi.com(fr non-resolving), webdo.tn(410), fratmat.info, koaci.com, 7sur7.cd, observalgerie.com, lopinion.ma, h24info.ma(403), sikafinance.com, linfodrome.com(0), cameroon-info.net(522), mediacongo.net, info241.com(SSL), imatin.net, aniamey.com, lebabi.net, gabonmediatime.com(0), lenational.org, ayibopost.com(0), laliberte.ch, arcinfo.ch, lacote.ch, lenouvelliste.ch, heidi.news, gauchebdo.ch, bilan.ch, blick.ch/fr(403), lecho.be(403).
Trimmed-after-pass (verified live but redundant for balance): algerie360.com, sudquotidien.sn, journaldequebec.com, ledroit.com, lequotidien.com, lavenir.net, sahelien.com.

### Cluster 14 — Worldwide fact-checkers — rejection log
Duplicates (already in catalog): newtral.es, chequeado.com, lessurligneurs.eu, teyit.org, vishvasnews.com, observador.pt, demagog.org.pl, faktograf.hr, ellinikahoaxes.gr, cotejo.info, stopfake.org, voxukraine.org, maldita.es, knack.be, dubawa.org, aosfatos.org, fastcheck.cl, efe.com(verifica), newschecker.in, thequint.com.
Cross-batch duplicate: agencialupa.org (also returned by cluster 6 — kept once via global dedup).
Robots: verificat.cat(Disallow */feed/).
Out-of-cluster (English/Anglophone): stopfake.org/en, fullfact.org.
Blocked(403): factuel.afp.com/factual/checamos, fatabyyano.net, faktabaari.fi, pesacheck.org, istinomer.rs.
Dead(000): correctiv.org, saheehmasr.com, kallkritikbyra.se, malaespina.cl, verificado.uy, benditointernet.com, factcrescendo.com, hindi.newschecker.in.
404/410/no-feed: misbar.com, demagog.cz, ojo-publico.com, poligrafo.sapo.pt, facta.news, dogrulukpayi.com, chequeabolivia.bo, saludconlupa.com, animalpolitico.com, faktisk.no, liputan6.com, kompas.com, 211check.org, verify-sy.com, matsda2sh.com, mythdetector.ge(410).
Not-XML: colombiacheck.com, pagellapolitica.it, demagog.sk, verafiles.org, cekfakta.tempo.co, medcom.id, raskrinkavanje.ba.
0-entries: boomlive.in, namibiafactcheck.org.na, dogrula.org.
Stale: convoca.pe, elsurti.com, tsek.ph.
No-dates/liveness-unverifiable: tjekdet.dk, delfi.lt, turnbackhoax.id.
Not-factcheck-specific: lasillavacia.com, efectococuyo.com.
Compromised/spam: dabegad.com.


## Orchestrator global-dedup (caught after workers returned)

Registrable-domain duplicates of an outlet already in the catalog (catalog holds another-language subdomain of the same outlet):
- `royanews.tv` (en.royanews.tv exists), `arynews.tv` (ARY News Urdu; arynews.tv exists), `chosun.com` (english.chosun.com), `tempo.co` (en.tempo.co), `vnexpress.net` (e.vnexpress.net), `irna.ir` (en.irna.ir), `zona.media` (en.zona.media) — plus `daraj.media` (already present).

Within-batch cross-cluster duplicates (kept once, first cluster wins):
- `fanamc.com` (c8 Amharic kept, c9 English dropped), `medias24.com`/`lapresse.tn`/`kapitalis.com` (c1 kept, c13 dropped), `aps.sn`/`actucameroun.com` (c9 kept, c13 dropped), `trtafrika.com` (c8 Hausa kept, Swahili section dropped), `agencialupa.org` (c6 kept, c14 dropped).
