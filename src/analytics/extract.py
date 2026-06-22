"""
Pluggable keyword & entity extraction (offset-aware).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Turns an article body into ``ExtractedTerm``s carrying their occurrence count and
the char offset of their first occurrence (so the surrounding sentence can be
shown later, sliced from the stored article text). Two honest backends:

  * **BaselineExtractor** (core, no deps): topical n-gram *terms* (stopword-filtered,
    lowercased) PLUS *entities* detected as stand-alone ALL-CAPS **acronyms** only
    (WHO, NATO, USA). Title-Case was dropped as an entity signal — it is anglocentric
    and wrong for a multilingual corpus (German capitalises every noun; Romance
    languages capitalise sentence starts; Arabic/CJK have no case). A person/org/
    location ``kind`` comes only from a supplied gazetteer / spaCy; an unvouched
    acronym gets the honest generic kind ``entity``. Best for space-delimited scripts;
    it does not pretend to segment CJK/Arabic.
  * **SpacyExtractor** (opt-in ``[nlp]`` extra): real PERSON/ORG/GPE/LOC entities
    from a local spaCy model, reusing the baseline for topical terms. Constructed
    only if spaCy + a model are installed; callers fall back to baseline otherwise.

Every term records which extractor produced it; an entity ``kind`` is a
"labelled-by-X" assertion, never asserted as ground truth.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from html import unescape

from src.services.stopwords import stopwords_manager

# A word token: starts with a (unicode) letter, may contain letters, marks,
# apostrophes and hyphens. Digits-only / punctuation tokens are ignored.
# Indic combining marks (Unicode category Mn/Mc): dependent vowel signs (matras),
# the virama, anusvara/visarga/candrabindu, nukta. Python's stdlib `\w` does NOT
# match these (they're Marks, not alphanumerics), so "सरकार" used to split at the ा
# matra into "सरक"+"र" — Hindi/Bengali keywords were mangled, not merely unstoplisted
# (field test 2026-06-22). Allowing them ONLY as word CONTINUATIONS is additive: no
# Latin/Cyrillic/Greek/Arabic token uses these codepoints, so those scripts are
# byte-unchanged. (Other Indic/Thai scripts have the same need but are out of scope —
# zh/ja stay unsegmented regardless.)
_DEVANAGARI_MARKS = "ऀ-ःऺ-ॏ॑-ॗॢॣ"
_BENGALI_MARKS = "ঁ-ঃ়া-্ৗৢৣ"
_WORD_RE = re.compile(
    rf"[^\W\d_][\w'’\-{_DEVANAGARI_MARKS}{_BENGALI_MARKS}]*", re.UNICODE
)

_DEFAULT_MAX_TERMS = 80
_DEFAULT_MAX_ENTITIES = 80
_MIN_TERM_LEN = 3

# --------------------------------------------------------------------------- #
# Markup strip at the extraction chokepoint (field diagnostics 2026-06-21)
# --------------------------------------------------------------------------- #
# When a stored article body still carries raw HTML/CSS — a pre-2026-06-20 .eml
# import, or any fetch path that kept markup — the word tokenizer mints `div`,
# `span`, `max-width`, `font-size` … as "keywords" (the live log showed a 36.5k
# unknown-language junk bucket dominated by exactly these). The web scrape path
# is clean (trafilatura), but we defend at the ONE place every path passes
# through — keyword extraction — so a re-index cleans existing rows regardless of
# which path stored the markup, and any future leak is caught by construction.
#
# A real tag is `<`/`</` immediately followed by a tag-name letter, ending in a
# whitespace/`/`/`>`-bounded close: this matches `<div>`, `<div class="x">`,
# `<br/>`, `</p>` but NOT an angle-bracketed URL `<https://x>` or prose like
# "x < y > z", so clean text is left byte-for-byte identical (keyword offsets
# into the stored body stay exact).
_MARKUP_STYLE_SCRIPT_RE = re.compile(
    r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_MARKUP_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKUP_TAG_RE = re.compile(r"</?[a-zA-Z][\w-]*(\s[^<>]*?)?/?>", re.DOTALL)
_MARKUP_ENTITY_RE = re.compile(r"&[#a-zA-Z][#a-zA-Z0-9]*;")


def _has_markup(text: str) -> bool:
    """Cheap, precise gate: True only when an actual strip would change ``text``."""
    return bool(
        _MARKUP_TAG_RE.search(text)
        or _MARKUP_STYLE_SCRIPT_RE.search(text)
        or _MARKUP_COMMENT_RE.search(text)
        or _MARKUP_ENTITY_RE.search(text)
    )


def strip_markup(text: str) -> str:
    """Drop HTML/CSS markup from ``text``; return it unchanged when there is none.

    Order matters (the email ``_strip_html`` lesson): <style>/<script> BLOCKS go
    first (their CSS/JS must never survive as body text), then HTML comments
    (incl. MSO conditional comments containing '>'), then every remaining tag,
    then HTML entities are decoded (so `&nbsp;`/`&copy;` don't become `nbsp`/
    `copy` keywords). Clean text is returned byte-identical so a term's recorded
    first-offset still points at the right place in the stored article body.
    """
    if not _has_markup(text):
        return text
    out = _MARKUP_STYLE_SCRIPT_RE.sub(" ", text)
    out = _MARKUP_COMMENT_RE.sub(" ", out)
    out = _MARKUP_TAG_RE.sub(" ", out)
    return unescape(out)

# All-caps tokens that are NOT entities (emphasis / chrome / titles), so the
# acronym detector doesn't mistake them for organisations. Kept deliberately small
# and evidence-driven — the keyword-diagnostics logs surface new ones to add.
_ACRONYM_STOP: frozenset[str] = frozenset(
    {
        "ok", "vs", "am", "pm", "aka", "faq", "ceo", "cfo", "cto", "vip", "rip",
        "diy", "asap", "fyi", "no", "so", "yes", "etc", "via", "na",
    }
)


def _is_caps_run_word(w: str) -> bool:
    """True for an all-caps token of length >= 2 with at least one letter.

    Covers plain acronyms (WHO) and digit/hyphen-bearing ones (G7, COVID-19); used
    both to spot an acronym candidate and to detect an all-caps headline/shout run.
    """
    return len(w) >= 2 and w.isupper() and any(c.isalpha() for c in w)


# Curated extra stoplist: very common function words / fillers that the per-language
# sets miss, plus number-words, across the major Latin-script languages. Combined
# with the per-language sets into global_stopwords(). The user can add more from
# the Settings tab (keyword filter).
_EXTRA_STOPWORD_TEXT = (
    # English fillers the base set lacks
    "not no nor one two three four five six seven eight nine ten "
    "get got gets getting make made makes making take takes took taking "
    "go goes going gone come comes coming came see sees seen saw "
    "know knows knew known think thinks thought want wants wanted need needs "
    "like likes liked use used uses using way ways thing things lot lots "
    "new old good bad big small great little much many even still back "
    "people person time times part parts case cases number numbers group "
    "well around across along yet ever never always often sometimes maybe perhaps "
    "really quite rather pretty almost enough across upon onto unto whatever whoever "
    "into within without toward towards among amongst per via "
    "this that these those here there what which whose "
    # Relative time + news-attribution fillers users flagged as noise
    "since last next first second third ago today yesterday tomorrow soon "
    "early late later recent recently latest current currently meanwhile amid "
    "said says say told tells according reportedly however therefore thus hence "
    "indeed instead although though whereas whilst despite "
    # Contractions (ASCII; curly-apostrophe variants are added programmatically below)
    "it's don't doesn't didn't won't can't cannot isn't aren't wasn't weren't "
    "hasn't haven't hadn't couldn't wouldn't shouldn't i'm you're we're they're "
    "i've you've we've they've i'll you'll that's there's what's let's he's she's "
    "dont doesnt didnt wont cant isnt arent wasnt werent hasnt havent hadnt "
    "couldnt wouldnt shouldnt youre theyre ive youve weve theyve thats theres whats lets "
    # Spanish
    "el la los las un una unos unas de del y o pero que como para por con sin "
    "es son fue era ser estar su sus lo le les nos se mas muy "
    # German
    "der die das den dem ein eine einer und oder aber auch ist sind war "
    "nicht mit von zu im am ich du wir sie es auf für "
    # Italian
    "il lo la gli le un uno una di del della che chi non con per tra fra "
    "sono era essere ho hai abbiamo questo quello "
    # Portuguese
    "o a os as um uma uns umas de do da dos das que nao com para por "
    "sou somos foi ser este esse isso "
    # Dutch
    "de het een en of maar ook is zijn was niet met van te ik je wij zij "
    # French (was MISSING entirely — the 2026-06-11 field log leaked dans/plus/
    # pas/aux/ont/ses… as top "entities"; added with elision combos + fillers)
    "le la les un une des du de au aux et ou mais donc or ni car que qui quoi "
    "dont où dans sur sous avec sans pour par entre vers chez pas plus moins "
    "très tout tous toute toutes même aussi ainsi alors comme encore déjà "
    "depuis pendant avant après être avoir fait faire été ont sont est était "
    "avait avaient seront sera leur leurs ses son sa ce cet cette ces celui "
    "celle ceux celles il elle ils elles nous vous je tu on lui y en se soi "
    "notre votre nos vos mon ma mes ton ta tes deux trois quatre cinq six "
    "sept huit neuf dix plusieurs quelques chaque autre autres certains "
    "certaines désormais également notamment toutefois cependant pourtant "
    "c'est n'est d'un d'une qu'il qu'elle qu'ils s'est j'ai l'on jusqu'à "
    "aujourd'hui hier demain lundi mardi mercredi jeudi vendredi samedi dimanche "
    # Month names leak as entities ("June" en:317, "Juin" fr:68 in the field log)
    "january february march april may june july august september october november december "
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre "
    # English generics observed leaking as entities in the field log
    "including found help work million billion millions billions "
    # ----------------------------------------------------------------------- #
    # Field log #2 (2026-06-12, 63,672-keyword export): the de-US-centred
    # catalog brought 22 source languages, 16 of them WITHOUT stoplists —
    # function words sat in TOP analytics slots (nl "dat"×1599, de "sich"×982,
    # es "más"×1001, sv "som"×795, ru "что"×531…). Maintainer ruling: NO cap on
    # keyword counts; instead a clear exception policy for pronouns,
    # conjunctions & co. in ALL the app's corpus languages. Every block below
    # is evidence-backed by that export; global_stopwords() applies these
    # retroactively at query time, so stored junk disappears from analytics
    # without touching data.
    # English (the 3 residual leaks)
    "another further yes "
    # Spanish (extends the thin block above; 48 leaked words, 5,754 mentions)
    "al en sobre entre desde hasta yo tú él ella ellos ellas nosotros usted "
    "ustedes mi tu nuestro este esta estos estas ese esa esos esas aquel quien "
    "cual cuyo donde cuando fueron hay también ya si sólo solo así pues porque "
    "aunque mientras cada todo toda todos todas otro otra otros otras mismo misma qué "
    # German (48 leaked, 8,194 mentions: sich/bei/wie/aus/über/nach/einem/einen…)
    "des einem einen eines kein keine ja nein bei aus nach über unter vor "
    "hinter zwischen durch gegen ohne um er ihr sich mein dein sein unser euer "
    "dieser diese dieses jener welche welcher was wer wie wo wann warum waren "
    "haben hat hatte werden wird wurde noch schon nur sehr mehr als wenn weil "
    "dass damit sowie sowohl beide jeder jede jedes alle "
    # Italian (42 leaked, 3,230 mentions: alla/dei/nel/più/delle/anche…)
    "i dei delle a al alla in nel nella con da dal su sul senza io tu lui lei "
    "noi voi loro mio tuo suo nostro questa questi queste quella cui dove "
    "quando perché è erano avere ha hanno fu furono anche molto più meno già "
    "sì così poiché mentre ogni tutto tutta tutti tutte altro altra "
    # Portuguese (20 leaked: não/ele/também/até/foram/seu/ela…)
    "no na nos nas em sem sobre entre desde até eu tu ele ela eles elas nós "
    "você vocês meu teu seu nosso estes estas essa aquele quem qual cujo onde "
    "quando porque é são era eram estar foram há também muito mais menos já "
    "não sim só assim pois embora enquanto cada todo toda todos todas outro outra "
    # Dutch (34 leaked, 10,257 mentions — the worst: dat/voor/hij/uit/bij/naar…)
    "dat voor naar in op bij uit door over onder tussen tegen zonder om jij "
    "hij wie zich mijn jouw zijn haar ons hun deze die dit welke wat waar "
    "wanneer hoe waarom waren worden wordt werd hebben heeft had nog al alleen "
    "zeer meer als toen omdat zodat beide elke alle "
    # Russian (54 leaked, 2,658 mentions: что/для/как/его/также/это/при/более…)
    "и в во не на я он она оно они мы вы ты что это эта этот эти как так но "
    "или а же бы был была были быть есть от до из у за под над при с со для "
    "по о об к ко его её их наш ваш мой твой свой кто где когда почему зачем "
    "тоже также уже ещё еще только очень более менее всех весь вся всё все "
    "другой другая каждый если потому пока между через без "
    # Swedish (30 leaked, 3,752 mentions: som/har/det/och/för…)
    "och eller men av till i på vid med för från ut genom över under mellan "
    "mot utan om jag du han hon vi ni de sig min din sin vår er denna detta "
    "dessa den det som vem vad var när hur varför är varit bli blir blev ha "
    "har hade också än redan bara mycket mer mest alla varje annan "
    # Norwegian bokmål (30 leaked: til/jeg/seg/ble/også/hadde/ved/når…)
    "og av til ved fra gjennom mellom mot uten jeg han hun dere seg din sin "
    "deres denne dette disse hvem hva hvor når hvordan hvorfor vært ble enn "
    "hver annen "
    # Danish (9 leaked; same family as nb/sv — completes the Scandinavian set)
    "ud mod hvis bliver blive meget havde vores hvad gennem uden anden "
    # Polish (42 leaked, 2,789 mentions: się/jest/jak/przez/czy/dla…)
    "i w we na nie z ze do od po za pod nad przy o u dla przez bez się to ta "
    "ten te tej tego tych jak tak ale lub albo czy że by był była było były "
    "być jest są ma mają mój twój swój nasz wasz kto co gdzie kiedy dlaczego "
    "też także już jeszcze tylko bardzo więcej mniej każdy wszystko wszyscy "
    "inny inna jeśli bo między "
    # Hungarian (32 leaked: hogy/nem/egy/már/volt/vagy/még/több…)
    "a az és vagy de hogy nem igen egy ez ezek azok aki ami amely ahol amikor "
    "miért hogyan én te ő mi ti ők enyém tied övé miénk van volt lesz lenni "
    "már még csak nagyon több kevesebb minden mindenki más ha mert között "
    "nélkül ellen alatt felett által "
    # Arabic (22 leaked, 1,417 mentions: على/إلى/هذا/التي/هذه/كما/ذلك…)
    "في من إلى على عن مع هذا هذه ذلك تلك التي الذي الذين ما لا لم لن إن أن "
    "كان كانت يكون هو هي هم هن نحن أنت أنا أو ثم بل لكن حتى إذا كما قد كل "
    "بعض غير بين عند منذ أي "
    # Serbian/Croatian/Bosnian latin (30 leaked: kako/još/sve/više/biti/kada…)
    "u za od do po pri sa bez kroz preko ispod iznad između protiv ovaj ova "
    "ovo taj ona oni ko šta gde gdje kada kako zašto je su bio bila bilo biti "
    "ima imaju takođe također već još samo veoma više manje svaki sve drugi "
    "druga ako jer moj tvoj svoj naš vaš "
    # Turkish (26 leaked: için/olarak/daha/çok/veya/ancak/gibi/değil…)
    "ve veya ama fakat ancak ki bu şu bir için ile gibi kadar sonra önce "
    "üzere göre eğer çünkü her hem ya ne hangi kim nerede zaman nasıl niçin "
    "neden ben sen biz siz onlar benim senin onun bizim sizin değil var yok "
    "daha çok az en idi olan olarak "
    # Indonesian (33 leaked: untuk/ini/dengan/itu/adalah/pada/juga…)
    "dan atau tetapi tapi dari ke di pada dengan untuk tanpa atas bawah "
    "antara terhadap ini itu yang siapa apa mana kapan bagaimana mengapa saya "
    "kamu dia kami kita mereka aku adalah ialah ada sudah telah akan juga "
    "masih hanya sangat lebih kurang semua setiap lain jika karena "
    # Finnish (16 leaked: että/olla/hän/myös…)
    "ja tai mutta että ei kyllä se tämä nämä nuo joka mikä kuka missä milloin "
    "miksi miten minä sinä hän me te he on oli ollut olla olen myös jo vain "
    "hyvin enemmän vähemmän kaikki jokainen muu jos koska välillä ilman "
    # Hindi (1 leaked — अगर; the conjunction/pronoun core completes the policy)
    "और या लेकिन कि नहीं हाँ यह वह ये वे जो क्या कौन कहाँ कब कैसे क्यों मैं तुम आप हम "
    "का की के को से में पर है हैं था थे थी होना भी अभी केवल बहुत अधिक कम सब हर "
    "अन्य अगर क्योंकि बीच बिना "
    # Second evidence pass (same export, post-policy survivors): inflected
    # function words, modals, attribution verbs and date-generics that the
    # core sets miss — plus month names beyond en/fr (es "junio"×257 and
    # ru "июня"×133 leaked exactly like the en/fr months above).
    "aan geen wel veel zegt zei jaar jaren niet maar werd onder meer "  # nl
    "att ett kommer skriver sade säger mån månader dag dagar år procent "  # sv
    "está según durante contra años año donde fueron sido siendo estado "  # es
    "zum zur kann muss soll andere anderen ihre ihren seinen seiner jahr jahren "  # de
    "anni anno dopo prima contro essere stato stata fatto detto "  # it
    "года году год лет годы после этом этой этого того тем том тех ней нем них ему ей им "  # ru
    "etter siden også året år dager "  # nb
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre "
    "januar februar märz april mai juni juli august september oktober november dezember "
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre "
    "januari februari maart april mei juni juli augustus oktober "
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря "
    "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь "
    # ----------------------------------------------------------------------- #
    # Field log (2026-06-14 keyword-diagnostics export, 1,201-article corpus;
    # surfaced via scripts/analyze_keyword_log.py). The de-US-centred corpus kept
    # leaking per-language FUNCTION words the earlier passes missed, plus WEEKDAY
    # names (the month blocks above never covered weekdays: "Sunday"/"sábado"/
    # "lørdag" sat among the top keywords) and comment-widget/paywall BOILERPLATE.
    # Net-new vs the blocks above; applied retroactively by global_stopwords().
    # Names, places and content words the analyzer flagged stay OUT (its 'review'
    # bucket); cross-language collisions (sea/tom/fin/laut…) deliberately omitted
    # because this set is unioned across ALL languages.
    # Weekday names across the corpus languages (fr weekdays already covered above)
    "monday tuesday wednesday thursday friday saturday sunday "
    "lunes martes miércoles miercoles jueves viernes sábado sabado domingo "
    "montag dienstag mittwoch donnerstag freitag samstag sonntag "
    "lunedì lunedi martedì martedi mercoledì mercoledi giovedì giovedi venerdì venerdi sabato domenica "
    "segunda terça terca quarta quinta sexta "
    "maandag dinsdag woensdag donderdag vrijdag zaterdag zondag "
    "mandag tirsdag onsdag torsdag fredag lørdag lordag søndag sondag "
    "poniedziałek poniedzialek wtorek środa sroda czwartek piątek piatek sobota niedziela "
    "hétfő hetfo kedd szerda csütörtök csutortok péntek pentek szombat vasárnap vasarnap "
    "ponedeljak utorak sreda četvrtak cetvrtak petak subota nedelja nedjelja "
    "ponedeljek torek četrtek cetrtek petek "
    "senin selasa rabu kamis jumat sabtu minggu "
    "понедельник вторник среда четверг пятница суббота воскресенье "
    "الاثنين الإثنين الثلاثاء الأربعاء الخميس الجمعة السبت الأحد "
    # French function words still leaking (afin/lire la suite/doit/soit/à travers)
    "afin lire doit soit travers a-t-il n'a "
    # Spanish function words + number/temporal generics
    "vez tres gran días después bien "
    # German modals / conjunctions / adverbs
    "können sondern solche dazu sollte oft selbst deshalb bereits dadurch keinen "
    # Italian auxiliaries / prepositions / adverbs
    "poi sarà dalla nei nelle sotto sarebbe oggi tempo "
    # Portuguese function words
    "ainda pelo pelas num numa deste apesar "
    # Russian conjunctions / pronouns / adverbs / aux
    "чтобы которые около там было даже время стать можете знать однако сейчас ранее прямо "
    # Danish function words + paywall/comment boilerplate (læs/adgang/dagens)
    "kun ikke godt ingen vil hele efter første læs adgang dagens "
    # Polish function words + temporal
    "które tym oraz może jej można aby również jednak jego nich roku "
    # Hungarian function words + temporal/number generics
    "meg azt pedig majd szerint ezt így után olyan kell arra első fel lehet "
    "mondta egyik ahogy volna miatt akkor két perc "
    # Serbian/Croatian function words + comment-widget boilerplate
    "ili ovoj temi vaše nije što kao koja godine tako nakon "
    "pročitajte komentare diskusiji oglas mišljenje "
    # Slovenian function words
    "tudi kot zelo vse tem ter bodo bolj jih kar naj nekaj veliko sicer saj "
    "potem tega res kjer zaradi lahko "
    # Arabic prepositions / conjunctions
    "خلال قبل ضمن بعد وفي ومن حول بشكل داخل وهو أجل حيث بما "
    # Indonesian function words
    "dalam oleh bisa bagi menjadi sebagai satu dapat hari secara agar tidak "
    "maupun melalui merupakan "
    # Field log (2026-06-17 keyword-diagnostics export, 2,324-article corpus). The
    # per-source concentration suspects surfaced LOGIN/SUBSCRIBE widget chrome that
    # appears in ~every article of a source (share_of_source ≈ 1.0) — pure UI, not
    # content. ONLY unambiguous chrome + pure function words are added; dual-use
    # platform NAMES (facebook/twitter/telegram…) and content-capable words
    # (comments/follow/correo/electrónico) are deliberately left OUT (a story may be
    # ABOUT them), staying visible in the diagnostics for a maintainer ruling.
    # French account-wall chrome (Le Nouvelliste: connectez-vous/inscrivez-vous in
    # 27/27 of its articles) + leaked function words (selon/lors/avez):
    "connectez-vous inscrivez-vous gratuitement selon lors avez "
    # English subscribe button:
    "subscribe "
    # Round-2 of the same 2026-06-17 export: PURE function words still leaking in
    # the higher-volume non-English corpora (analyzer "high-confidence" bucket,
    # hand-filtered). Deliberately CONSERVATIVE because global_stopwords() is
    # unioned across ALL languages: every word here is either accented (so it
    # can't be a content token in another corpus language) or unambiguous grammar
    # that is not an English/name homograph. Cross-language homographs were
    # EXCLUDED on purpose — mint/nun/sei/seine (de), ska/nye/nyt/ole (Nordic/fi
    # collide with ska-genre / Bill Nye / NYT / the name Ole), dana/nagy/srbije
    # (names/places), kroner/ritzau (currency / the Ritzau agency name).
    "doch vom seit wieder immer dabei viele viel dann habe gibt heute "  # German
    "úgy arról hanem azért bár előtt óta "  # Hungarian
    "može zbog prema tokom "  # Serbian
    "två här inte nya "  # Swedish
    "være prosent sier "  # Norwegian
    "været blevet fået siger skal andet lyder blandt "  # Danish
    "sitä olisi mukaan sanoo ovat kuin teki "  # Finnish
    "görə "  # Azerbaijani postposition (Meydan TV per-source concentration)
    # Universal WEB-MARKUP / URL junk (2026-06-18 field log: a source whose page
    # chrome leaked into the indexed content turned 'https', 'www', 'img',
    # 'margin-left', … into top keywords). These are never meaningful content in
    # ANY language, so the global union is safe. NB: the real fix is stripping
    # HTML/CSS/URLs from article content BEFORE extraction (a content-extraction
    # issue, flagged separately) — this only stops the markup that still leaks
    # from polluting keywords. Dual-use words (table/body/icon/html/css) are
    # deliberately left OUT (a story may be about them).
    "https http www href img colspan rowspan tbody thead nbsp margin-left margin-right px utf "
    # 2026-06-18 keyword-log: the highest-volume no_stoplist languages (el 4992,
    # uk 3684, bg 3090 keywords) leaked their grammar into the index. These are
    # GREEK and CYRILLIC scripts, so the global union can never collide with a Latin
    # corpus language; cross-Cyrillic overlap (bg/uk/ru/sr) is fine — a shared
    # function word is a stopword in each. Hand-filtered to PURE grammar (articles,
    # prepositions, pronouns, conjunctions, common auxiliaries); content/entities/
    # months were excluded on purpose (el: ηπα/ιράν/τραμπ/πηγές; bg: българия/юни/
    # евро/софия/директор; uk: україни/нато/завод/червня + the ru-mislabelled forms).
    # el promotes to MANAGED (src/analytics/managed.py); uk stays gated (its sample
    # mixed ru-spelled tokens, so the language signal is not yet trustworthy).
    "και του της την για από που στο τον των στην τις ότι δεν τους στη στις είναι "  # Greek
    "μια στα έχει ένα στον αλλά κατά ενώ όπως μας αυτό οποία ήταν εδώ μέσα μετά είχε "  # Greek
    "αυτή καθώς προς σας έχουν πως πρέπει πιο μεταξύ μόνο όλα όταν πριν οποίο μία ένας έναν "  # Greek
    "това като които има може през към ако много няма само който след той всички този "  # Bulgarian
    "във която което защото със срещу така една както още дали трябва бъде беше пред "  # Bulgarian
    "вече също кой бил чрез тези тази един "  # Bulgarian
    "про він під також після які який від але вже його вони має мають лише коли цього всі "  # Ukrainian
    # 2026-06-21 keyword-log (29k-article corpus): more CSS/markup leaked into the
    # unknown-language ('?') bucket (table/width/div/block-1/max-width/font-size) — the
    # root fix is HTML/CSS stripping before extraction (flagged), this stops the markup
    # that still leaks. Only UNAMBIGUOUS CSS/HTML tokens (never natural content in any
    # language); dual-use (table/width/body/icon) deliberately left OUT.
    "div span max-width font-size font-family "
    # de dialectal weekday the month/weekday pass missed (Saturday).
    "sonnabend "
    # Pure grammar still leaking in the higher-volume corpora (analyzer high-confidence,
    # hand-filtered per the standing rule: accented OR unambiguous grammar, no English/
    # name homograph, no cross-language content collision).
    "tras ante sino eso hoy ahora esto además cómo "   # Spanish
    "degli sulla sua sia "                                # Italian
    "pela aos pode "                                      # Portuguese
    "jako który gdy "                                     # Polish
    "več prav danes "                                     # Slovenian
    "får läs "                                            # Swedish
    "flere opp "                                          # Norwegian
    "aynı karşı "                                         # Turkish (accented; promotes toward managed)
    # 2026-06-22 (field test, engine report): hi + bn are UI languages but were
    # no_stoplist, leaking grammar into the index ("give them stoplists … hi/bn no
    # longer no_stoplist"). DEVANAGARI + BENGALI scripts, so the global union can
    # NEVER collide with a Latin/Cyrillic/Greek corpus language. Hand-filtered to
    # PURE grammar (postpositions, pronouns, conjunctions, common auxiliaries);
    # content nouns, names and months were excluded on purpose. Both promote to
    # MANAGED (src/analytics/managed.py).
    "का की के को में से पर ने और या भी है हैं था थे थी कि जो नहीं तो ही लिए तक साथ बाद पहले हुआ हुई हुए "  # Hindi
    "एक इस उस अपने अपनी कर करने किया रहा रही रहे गया गई गए "  # Hindi
    "এর এবং ও কে থেকে যে এই সেই করে করা হয় হয়েছে ছিল না কি যা তার জন্য কিন্তু বা আর হবে হয়ে নিয়ে "  # Bengali
    "একটি দিয়ে সঙ্গে পরে আগে করেন করেছে "  # Bengali
)
_EXTRA_STOPWORDS: frozenset[str] = frozenset(_EXTRA_STOPWORD_TEXT.split())
# News text often uses a curly apostrophe (’) — match those spellings of any
# contraction too, so "don't" and "don’t" are both filtered without listing each twice.
_EXTRA_STOPWORDS = _EXTRA_STOPWORDS | frozenset(
    w.replace("'", "’") for w in _EXTRA_STOPWORDS if "'" in w
)


@lru_cache(maxsize=1)
def global_stopwords() -> frozenset[str]:
    """Union of all built-in per-language stoplists + the curated extra set.

    Language-agnostic: a word that is a stopword in any supported language (or in
    the curated extra list) is treated as one. Used both at extraction time and at
    query time (so leaky terms already in the store are hidden retroactively).
    """
    s: set[str] = set(_EXTRA_STOPWORDS)
    s |= set(stopwords_manager.default_stopwords)
    for lang in getattr(stopwords_manager, "language_stopwords", {}):
        s |= set(stopwords_manager.get_stopwords(lang))
    return frozenset(s)


def _stopset(language: str) -> frozenset[str]:
    return frozenset(stopwords_manager.get_stopwords(language)) | global_stopwords()


@dataclass
class ExtractedTerm:
    term: str  # display form (entities keep case; terms are lowercased)
    normalized: str  # dedup key (casefold)
    kind: str  # term | person | org | location | entity
    count: int
    first_offset: int | None


_ELISION = re.compile(r"\b([dlncjmst]|qu)['’](?=\w)", re.IGNORECASE)


def _deelide(word: str) -> str:
    """Strip a leading Romance elision from a single token: l'assemblée -> assemblée,
    d'euros -> euros, qu'il -> il, c'est -> est. The elided article/pronoun is
    tokenization noise, not meaning (French/Italian/Catalan/Occitan…). Cheap guard:
    only touch tokens that actually carry an apostrophe."""
    if "'" in word or "’" in word:
        return _ELISION.sub("", word)
    return word


def _normalize(s: str) -> str:
    # French elisions are tokenization noise, not meaning: "d'euros" is about
    # euros, "l'ia" about ia. Strip the elided article before keying (field
    # log 2026-06-11). Contraction STOPWORDS like c'est stay listed verbatim
    # (they're filtered before this matters).
    s = _ELISION.sub("", s)
    return " ".join(s.split()).casefold()


class BaselineExtractor:
    """Dependency-free n-gram terms + Title-Case entity detection."""

    name = "baseline"

    def __init__(
        self,
        *,
        gazetteer: dict[str, str] | None = None,
        max_terms: int = _DEFAULT_MAX_TERMS,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
    ):
        # gazetteer maps normalized name -> kind ("person"|"org"|"location").
        self.gazetteer = gazetteer or {}
        self.max_terms = max_terms
        self.max_entities = max_entities

    # -- entities ---------------------------------------------------------- #

    def _entities(self, text: str) -> list[ExtractedTerm]:
        """Detect entities as stand-alone ALL-CAPS acronyms only.

        Title-Case ("World", German "Behauptung") was DROPPED as an entity signal:
        it is anglocentric and wrong for a multilingual corpus — German capitalises
        every noun, Romance languages capitalise sentence starts / months /
        nationalities, and Arabic/CJK have no case at all (2026-06-16 keyword-log
        finding: ~60–75% of case "entities" per language were common words, and the
        flag carried no person/org/location semantics anyway). The ONE reliable,
        language-independent case signal is an all-caps ACRONYM standing out in
        mixed-case text (WHO, NATO, USA).

        The normalized form is kept UPPERCASE so an acronym stays distinct from a
        lowercase homograph (WHO != who, US != us) and survives the stopword filter —
        the answer to the WHO/Who problem. Real person/org/place entities come from
        the gazetteer / spaCy (language-aware), applied here and in extract().
        """
        tokens = list(_WORD_RE.finditer(text))
        n = len(tokens)
        agg: dict[str, dict] = {}
        for i, tok in enumerate(tokens):
            surface = tok.group(0)
            if not _is_caps_run_word(surface):
                continue
            if surface.casefold() in _ACRONYM_STOP:
                continue
            # A real acronym stands out against mixed-case neighbours; an all-caps
            # token ADJACENT to another all-caps word is part of a HEADLINE/shout run
            # (catches the first & last word of the run, not just the middle).
            prev = tokens[i - 1].group(0) if i > 0 else ""
            nxt = tokens[i + 1].group(0) if i + 1 < n else ""
            if _is_caps_run_word(prev) or _is_caps_run_word(nxt):
                continue
            norm = surface  # PRESERVE case: WHO != who, US != us
            a = agg.get(norm)
            if a is None:
                a = {"count": 0, "first": tok.start(), "surface": surface}
                agg[norm] = a
            a["count"] += 1

        entities = [
            ExtractedTerm(
                term=a["surface"],
                normalized=norm,
                kind=self.gazetteer.get(norm.casefold(), "entity"),
                count=a["count"],
                first_offset=a["first"],
            )
            for norm, a in agg.items()
        ]
        entities.sort(key=lambda e: (-e.count, e.first_offset or 0))
        return entities[: self.max_entities]

    # -- topical terms ----------------------------------------------------- #

    def _terms(self, text: str, language: str) -> list[ExtractedTerm]:
        stop = _stopset(language)
        # De-elide each token: the contracted article (l'/d'/qu'/c'…) is noise, so
        # "l'assemblée" is the keyword "assemblée" and "qu'il" reduces to the stopword
        # "il". Without this the whole "l'assemblée" form was kept as a keyword.
        toks = [(_deelide(m.group(0).lower()), m.start()) for m in _WORD_RE.finditer(text)]
        counts: Counter[str] = Counter()
        first_at: dict[str, int] = {}

        def _record(term: str, offset: int) -> None:
            counts[term] += 1
            first_at.setdefault(term, offset)

        # Unigrams (content words only).
        for word, off in toks:
            if len(word) >= _MIN_TERM_LEN and word not in stop and not word.isdigit():
                _record(word, off)
        # Bigrams / trigrams over the raw token stream, dropping ones bounded by
        # stopwords so phrases stay meaningful ("prime minister", not "of the").
        for size in (2, 3):
            for k in range(len(toks) - size + 1):
                window = toks[k : k + size]
                words = [w for w, _ in window]
                # Drop a phrase if ANY token is a stopword or too short/numeric, so
                # fillers don't leak inside n-grams ("not one bit", "economy is not").
                if any(w in stop or len(w) < _MIN_TERM_LEN or w.isdigit() for w in words):
                    continue
                phrase = " ".join(words)
                _record(phrase, window[0][1])

        terms = [
            ExtractedTerm(term=t, normalized=t, kind="term", count=c, first_offset=first_at.get(t))
            for t, c in counts.items()
            if c >= 1
        ]
        terms.sort(key=lambda e: (-e.count, len(e.term)))
        return terms[: self.max_terms]

    def extract(self, text: str, *, title: str = "", language: str = "en") -> list[ExtractedTerm]:
        if not text or not text.strip():
            return []
        text = strip_markup(text)  # never mint div/span/max-width/font-size keywords
        entities = self._entities(text)
        ent_norms = {e.normalized for e in entities}
        # Topical terms. A term whose normalized form is in the gazetteer is promoted
        # to its real person/org/location kind — with Title-Case dropped, NAMED
        # entities now come from the gazetteer / spaCy (language-aware), not from
        # capitalisation. Terms duplicating a detected acronym are skipped.
        terms: list[ExtractedTerm] = []
        for t in self._terms(text, language):
            if t.normalized in ent_norms:
                continue
            kind = self.gazetteer.get(t.normalized)
            if kind:
                terms.append(
                    ExtractedTerm(
                        term=t.term,
                        normalized=t.normalized,
                        kind=kind,
                        count=t.count,
                        first_offset=t.first_offset,
                    )
                )
            else:
                terms.append(t)
        return entities + terms


class SpacyExtractor:
    """Opt-in real NER (PERSON/ORG/GPE/LOC) + baseline topical terms."""

    name = "spacy"
    _LABELS = {
        "PERSON": "person",
        "PER": "person",
        "ORG": "org",
        "GPE": "location",
        "LOC": "location",
        "FAC": "location",
        "NORP": "org",
    }

    def __init__(
        self,
        model: str = "en_core_web_sm",
        *,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
        baseline: BaselineExtractor | None = None,
    ):
        import spacy  # raises ImportError if the [nlp] extra is absent

        self._nlp = spacy.load(model, disable=["lemmatizer", "tagger"])
        self.model = model
        self.max_entities = max_entities
        self._baseline = baseline or BaselineExtractor()

    def extract(self, text: str, *, title: str = "", language: str = "en") -> list[ExtractedTerm]:
        if not text or not text.strip():
            return []
        text = strip_markup(text)  # never mint div/span/max-width/font-size keywords
        doc = self._nlp(text[:1_000_000])  # spaCy default max length guard
        ents: dict[str, ExtractedTerm] = {}
        for ent in doc.ents:
            kind = self._LABELS.get(ent.label_)
            if kind is None:
                continue
            norm = _normalize(ent.text)
            if norm in ents:
                ents[norm].count += 1
            else:
                ents[norm] = ExtractedTerm(ent.text, norm, kind, 1, ent.start_char)
        entities = sorted(ents.values(), key=lambda e: (-e.count, e.first_offset or 0))[
            : self.max_entities
        ]
        # Topical terms from the baseline (entities here are model-labelled), minus
        # any that duplicate a detected entity.
        ent_norms = {e.normalized for e in entities}
        terms = [t for t in self._baseline._terms(text, language) if t.normalized not in ent_norms]
        return entities + terms


def get_extractor(name: str = "baseline", *, gazetteer: dict[str, str] | None = None, **kw):
    """Factory. ``name='spacy'`` falls back to baseline if the extra is missing."""
    if name == "spacy":
        try:
            return SpacyExtractor(baseline=BaselineExtractor(gazetteer=gazetteer), **kw)
        except Exception:  # noqa: BLE001 - spaCy/model absent -> honest fallback
            return BaselineExtractor(gazetteer=gazetteer)
    return BaselineExtractor(gazetteer=gazetteer)
