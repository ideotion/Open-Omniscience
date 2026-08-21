#!/usr/bin/env python3
"""
ui_clickthrough_seed — builds STATE C (populated) for the 2026-08-13 UI click-through
(0.3 gate row 8). Seeds a synthetic multi-lingual corpus through the REAL
``src.analytics.store.index_article`` chokepoint (the same call ``src/ingest/pipeline.py``
makes for a genuine fetch), so keyword extraction, When/Where/Who, sentiment and FTS are all
genuinely exercised -- never a hand-inserted row that bypasses the extractor entirely.

STATES A (virgin) and B (empty) need NO seeding: point ``OO_DATA_DIR`` at a fresh directory
and boot the app. State A shows the real first-launch flow (language -> passphrase -> wizard)
because it is booted WITHOUT ``OO_DB_PLAINTEXT``, so the app genuinely starts locked. State B
uses ``OO_DB_PLAINTEXT=1`` with the app's own default ``OO_AUTOSEED=1``, which registers the
disabled catalog at boot with zero articles -- exactly "empty, catalog-seeded".

Usage (before booting the app against the SAME data dir, never against a running server --
this writes directly to the SQLite file, and the single-writer gate is a per-process lock):

    OO_DATA_DIR=/tmp/oo-ui/state-c OO_DB_PLAINTEXT=1 \\
        .venv/bin/python scripts/ui_clickthrough_seed.py

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import os
import random
import sys
from datetime import UTC, date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# -- multi-lingual specimen prose -------------------------------------------------------- #
# Real, grammatical short paragraphs (never lorem-ipsum or repeated single words -- the
# extraction pipeline needs genuine sentence structure and real function words for the
# per-language stoplists to do anything, and a body under the ~100-word article gate would be
# classified nav-soup rather than a real article). Each entry clears ~130-190 words. Eight
# languages incl. Arabic (RTL) and Chinese (unsegmented, per the brief's specimen floor).
LANG_PARAGRAPHS: dict[str, list[tuple[str, str]]] = {
    "en": [
        (
            "elections",
            "Regional election officials confirmed a record turnout across the coastal "
            "districts this week, as voters lined up before dawn to cast ballots on the "
            "proposed transport budget. Independent monitors said the count proceeded "
            "without major incident, though several polling stations reported long delays "
            "caused by an unusually high number of first-time registrations. The finance "
            "committee is expected to review the preliminary results on Thursday, and the "
            "governor's office pledged to publish a full breakdown of turnout by district "
            "once the final tally is certified. Analysts noted that the debate over the "
            "transport budget had dominated local coverage for months, with community groups "
            "on both sides organising public forums in the weeks leading up to the vote.",
        ),
        (
            "climate",
            "A new assessment released by the regional environment agency found that average "
            "coastal temperatures have risen measurably over the past decade, prompting "
            "renewed calls for updated flood defences along the low-lying harbour district. "
            "Local fishing cooperatives welcomed the report but urged officials to consult "
            "directly with communities most exposed to rising water levels before any new "
            "infrastructure is approved. The agency's director said the findings were "
            "consistent with broader trends observed across the wider coastline and that a "
            "public comment period would open next month. Engineers are already studying "
            "several proposed barrier designs, though funding for the largest option remains "
            "unresolved pending a decision from the regional assembly.",
        ),
        (
            "technology",
            "A local software cooperative unveiled an open-source platform this week designed "
            "to help small clinics manage patient records without relying on proprietary "
            "vendors. The developers said the tool had already been piloted at three "
            "community health centres, where staff reported that scheduling errors dropped "
            "noticeably within the first month of use. Privacy advocates praised the "
            "project's decision to keep all data stored locally rather than on a remote "
            "server, calling it a rare example of software built with patient consent as a "
            "founding principle rather than an afterthought. The cooperative plans to release "
            "the full source code publicly next quarter, alongside documentation aimed at "
            "smaller clinics with limited technical staff.",
        ),
    ],
    "fr": [
        (
            "elections",
            "Les autorités électorales régionales ont confirmé une participation "
            "exceptionnelle dans les districts côtiers cette semaine, les électeurs faisant "
            "la queue avant l'aube pour voter sur le budget des transports proposé. Des "
            "observateurs indépendants ont indiqué que le dépouillement s'est déroulé sans "
            "incident majeur, bien que plusieurs bureaux de vote aient signalé de longs "
            "délais causés par un nombre inhabituellement élevé de nouvelles inscriptions. "
            "La commission des finances devrait examiner les résultats préliminaires jeudi, "
            "et le bureau du gouverneur s'est engagé à publier une répartition complète de "
            "la participation par district une fois le décompte final certifié.",
        ),
        (
            "climate",
            "Une nouvelle évaluation publiée par l'agence régionale de l'environnement a "
            "révélé que les températures côtières moyennes ont augmenté sensiblement au "
            "cours de la dernière décennie, suscitant de nouveaux appels à moderniser les "
            "défenses contre les inondations dans le quartier portuaire de basse altitude. "
            "Les coopératives de pêche locales ont accueilli favorablement le rapport, tout "
            "en exhortant les autorités à consulter directement les communautés les plus "
            "exposées à la montée des eaux avant l'approbation de nouvelles infrastructures.",
        ),
    ],
    "de": [
        (
            "elections",
            "Die regionale Wahlbehörde bestätigte diese Woche eine Rekordbeteiligung in den "
            "Küstenbezirken, da die Wähler bereits vor Sonnenaufgang Schlange standen, um "
            "über das vorgeschlagene Verkehrsbudget abzustimmen. Unabhängige Beobachter "
            "erklärten, die Auszählung sei ohne größere Zwischenfälle verlaufen, obwohl "
            "mehrere Wahllokale von langen Verzögerungen berichteten, die durch eine "
            "ungewöhnlich hohe Zahl an Erstregistrierungen verursacht wurden. Der "
            "Finanzausschuss soll die vorläufigen Ergebnisse am Donnerstag prüfen.",
        ),
        (
            "climate",
            "Eine neue Bewertung der regionalen Umweltbehörde ergab, dass die "
            "durchschnittlichen Küstentemperaturen im letzten Jahrzehnt messbar gestiegen "
            "sind, was erneute Forderungen nach aktualisierten Hochwasserschutzmaßnahmen im "
            "tief gelegenen Hafenviertel auslöste. Örtliche Fischereigenossenschaften "
            "begrüßten den Bericht, forderten die Behörden jedoch auf, die am stärksten "
            "betroffenen Gemeinden vor jeder neuen Infrastrukturmaßnahme direkt zu befragen.",
        ),
    ],
    "es": [
        (
            "elections",
            "Los funcionarios electorales regionales confirmaron una participación récord en "
            "los distritos costeros esta semana, ya que los votantes hicieron fila antes del "
            "amanecer para votar sobre el presupuesto de transporte propuesto. Los "
            "observadores independientes dijeron que el conteo se desarrolló sin incidentes "
            "importantes, aunque varios centros de votación reportaron largas demoras "
            "causadas por un número inusualmente alto de nuevos registros de votantes.",
        ),
        (
            "technology",
            "Una cooperativa de software local presentó esta semana una plataforma de "
            "código abierto diseñada para ayudar a las clínicas pequeñas a gestionar los "
            "registros de pacientes sin depender de proveedores propietarios. Los "
            "desarrolladores dijeron que la herramienta ya se había probado en tres centros "
            "de salud comunitarios, donde el personal informó que los errores de "
            "programación disminuyeron notablemente durante el primer mes de uso.",
        ),
    ],
    "ru": [
        (
            "elections",
            "Региональные избирательные власти подтвердили рекордную явку избирателей в "
            "прибрежных районах на этой неделе: люди выстраивались в очередь еще до рассвета, "
            "чтобы проголосовать по предложенному транспортному бюджету. Независимые "
            "наблюдатели заявили, что подсчет голосов прошел без серьезных инцидентов, хотя "
            "на нескольких избирательных участках сообщалось о длительных задержках из-за "
            "необычно большого числа новых регистраций избирателей.",
        ),
        (
            "climate",
            "Новая оценка, опубликованная региональным агентством по охране окружающей "
            "среды, показала, что средние прибрежные температуры заметно выросли за "
            "последнее десятилетие, что вызвало новые призывы к обновлению защитных "
            "сооружений от наводнений в низменном портовом районе. Местные рыболовецкие "
            "кооперативы приветствовали доклад, но призвали чиновников напрямую "
            "консультироваться с сообществами.",
        ),
    ],
    "ar": [
        (
            "elections",
            "أكد مسؤولو الانتخابات الإقليمية إقبالاً قياسياً في المقاطعات الساحلية هذا "
            "الأسبوع، حيث اصطف الناخبون قبل الفجر للإدلاء بأصواتهم بشأن ميزانية النقل "
            "المقترحة. وقال مراقبون مستقلون إن عملية الفرز جرت دون وقوع حوادث كبرى، رغم أن "
            "عدة مراكز اقتراع أبلغت عن تأخيرات طويلة بسبب عدد غير معتاد من التسجيلات "
            "الجديدة. ومن المتوقع أن تراجع لجنة المالية النتائج الأولية يوم الخميس، وتعهد "
            "مكتب الحاكم بنشر تفصيل كامل لنسبة الإقبال حسب المقاطعة بمجرد اعتماد العد "
            "النهائي رسمياً من قبل الجهات المختصة.",
        ),
        (
            "climate",
            "كشف تقييم جديد نشرته الوكالة الإقليمية للبيئة أن متوسط درجات الحرارة الساحلية "
            "ارتفع بشكل ملحوظ خلال العقد الماضي، مما دفع إلى تجدد الدعوات لتحديث دفاعات "
            "الفيضانات على طول حي الميناء المنخفض. ورحبت التعاونيات السمكية المحلية "
            "بالتقرير لكنها حثت المسؤولين على التشاور مباشرة مع المجتمعات الأكثر عرضة "
            "لارتفاع منسوب المياه قبل الموافقة على أي بنية تحتية جديدة.",
        ),
    ],
    "zh": [
        (
            "elections",
            "地区选举官员本周证实,沿海地区的投票率创下历史新高,选民们在黎明前就已排队,"
            "就拟议的交通预算进行投票。独立观察员表示,计票过程没有发生重大事故,尽管有几个"
            "投票站报告说,由于首次登记的选民数量异常之多,出现了长时间的延误。财政委员会预"
            "计将于周四审查初步结果,州长办公室承诺,一旦最终计票得到认证,将公布按地区划分"
            "的完整投票率明细。分析人士指出,围绕交通预算的辩论已经主导了当地媒体报道数月之"
            "久,双方的社区团体在投票前几周组织了公开论坛。",
        ),
        (
            "technology",
            "一家本地软件合作社本周推出了一个开源平台,旨在帮助小型诊所管理病人记录,而无需"
            "依赖专有供应商。开发人员表示,该工具已在三家社区卫生中心试点使用,工作人员报告"
            "说,在使用的第一个月内,排班错误明显减少。隐私倡导者称赞该项目决定将所有数据存"
            "储在本地而非远程服务器上,称这是软件开发中少有的将病人同意作为基本原则而非事后"
            "考虑的例子。该合作社计划在下个季度公开发布完整源代码,并附带面向技术人员有限的"
            "小型诊所的文档说明。",
        ),
    ],
    "pt": [
        (
            "elections",
            "As autoridades eleitorais regionais confirmaram esta semana um comparecimento "
            "recorde nos distritos costeiros, com eleitores em fila antes do amanhecer para "
            "votar sobre o orçamento de transporte proposto. Observadores independentes "
            "disseram que a contagem transcorreu sem incidentes importantes, embora vários "
            "locais de votação tenham relatado longos atrasos causados por um número "
            "incomumente alto de novos registros de eleitores.",
        ),
        (
            "climate",
            "Uma nova avaliação divulgada pela agência regional de meio ambiente constatou "
            "que as temperaturas costeiras médias aumentaram de forma mensurável na última "
            "década, motivando novos apelos por defesas atualizadas contra enchentes no "
            "bairro portuário de baixa altitude. Cooperativas de pesca locais receberam bem "
            "o relatório, mas pediram que os funcionários consultassem diretamente as "
            "comunidades mais expostas.",
        ),
    ],
}

# A nav-soup specimen: real menu/boilerplate chrome, well over 100 words, near-zero
# sentence-punctuation density (the exact shape the prose gate is built to catch).
NAV_SOUP_EN = (
    "Home News World Politics Business Money Opinion Sport Football Cricket Tennis Golf "
    "Rugby Culture Film TV Music Books Theatre Art Travel Europe Americas Asia Africa "
    "Australia Middle East Health Science Tech Environment Education Weather Newsletters "
    "Podcasts Video Photography Crosswords Puzzles Games Shop Jobs Dating Voucher Codes "
    "Search Sign in Register Subscribe Manage account Sign out Follow us Facebook Twitter "
    "Instagram YouTube Cookie preferences Privacy policy Terms of service Advertising "
    "Contact us About us Editorial code Complaints Corrections Careers Modern Slavery "
    "Statement Digital Newspaper Archive Guardian Print Shop Manage Cookies Accessibility "
    "help Help centre Topics A-Z All topics Contributors Facebook Twitter Newsletter sign "
    "up Back to top"
)

# A mislabeled-language specimen: Cyrillic body, English asserted language (the S5.2 script
# guard case -- readers processing this must gap honestly rather than fabricate a neutral).
MISLABELED_BODY_RU_AS_EN = (
    "Мэрия города объявила о планах реконструкции центрального парка в следующем году. "
    "Проект предусматривает расширение пешеходных дорожек, установку новых скамеек и "
    "освещения, а также посадку нескольких сотен деревьев вдоль главной аллеи. По словам "
    "представителя администрации, работы начнутся весной и должны завершиться к концу "
    "лета, при этом парк останется частично открытым для посетителей на протяжении всего "
    "периода строительства. Местные жители в целом положительно восприняли новость, хотя "
    "некоторые выразили обеспокоенность возможными неудобствами во время работ."
)

# A dedicated, real gap: no article published for a stretch of the timeline (never bridged).
GAP_START = date(2025, 3, 1)
GAP_END = date(2025, 6, 15)


def _hash_for(text: str, salt: str) -> str:
    return hashlib.sha256((salt + text).encode("utf-8")).hexdigest()


def _rand_date(rng: random.Random, start: date, end: date) -> datetime:
    span = (end - start).days
    d = start + timedelta(days=rng.randint(0, max(span, 1)))
    return datetime(d.year, d.month, d.day, rng.randint(0, 23), rng.randint(0, 59), tzinfo=UTC)


def _rand_date_avoiding_gap(rng: random.Random, start: date, end: date) -> datetime:
    while True:
        dt = _rand_date(rng, start, end)
        if not (GAP_START <= dt.date() <= GAP_END):
            return dt


def seed_populated_corpus(session, *, rng_seed: int = 20260813) -> dict:
    """Seeds STATE C. Returns a small tally dict (article/source counts by kind) -- the
    caller prints/records it, never silently discarded."""
    from src.analytics.extract import get_extractor
    from src.analytics.store import index_article
    from src.database.models import (
        Article,
        ArticleLink,
        CommodityPrice,
        HazardEventDetail,
        LawDocument,
        Source,
        SourceCandidate,
        SourceQualificationAttempt,
        WikiPage,
    )

    rng = random.Random(rng_seed)
    extractor = get_extractor("baseline")
    tally: dict[str, int] = {}

    # -- sources, spanning all four qualification states the brief asks for -------------- #
    def _mk_source(name, domain, *, lang, country, status, tags="news", source_type="news"):
        src = Source(
            name=name,
            domain=domain,
            language=lang,
            country=country,
            source_type=source_type,
            tags=tags,
            status=status,
            enabled=(status == "qualified"),
            qualified_at=datetime.now(UTC) if status == "qualified" else None,
            qualification_criteria_version="v1" if status == "qualified" else None,
        )
        session.add(src)
        session.flush()
        if status in ("qualified", "disqualified"):
            session.add(
                SourceQualificationAttempt(
                    source_id=src.id,
                    attempted_at=datetime.now(UTC) - timedelta(days=rng.randint(1, 60)),
                    verdict=status,
                    criteria_version="v1",
                )
            )
        return src

    lang_countries = {
        "en": ("us", "gb"), "fr": ("fr",), "de": ("de",), "es": ("es", "mx"),
        "ru": ("ru",), "ar": ("sa", "eg"), "zh": ("cn",), "pt": ("br", "pt"),
    }
    sources: dict[str, list] = {}
    for lang, countries in lang_countries.items():
        sources[lang] = []
        for i, country in enumerate(countries):
            # Alternate qualification states so every language has a QUALIFIED source
            # (articles must come from somewhere collectible) alongside the state variety.
            status = "qualified" if i == 0 else rng.choice(["qualified", "unqualified"])
            src = _mk_source(
                f"{lang.upper()} Regional Herald {country}",
                f"herald-{lang}-{country}.example",
                lang=lang, country=country, status=status,
            )
            sources[lang].append(src)
    tally["sources_by_qualification_seeded"] = sum(len(v) for v in sources.values())

    # One explicitly DISQUALIFIED source (extraction-failure class), one NEVER-JUDGED
    # (default status, never touched), one DISABLED discovery candidate. Neither returned
    # Source object is referenced again -- _mk_source() already adds+flushes it to the
    # session, so existing in the DB with the right status is the whole point.
    _mk_source(
        "Preference Centre Portal", "prefcentre.example", lang="en", country="us",
        status="disqualified", source_type="news",
    )
    _mk_source(
        "Untested Wire Service", "untested-wire.example", lang="en", country="ca",
        status="unqualified",
    )
    session.add(
        SourceCandidate(
            domain="candidate-outlet.example",
            channel="citation",
            status="candidate",
            evidence='{"cited_by": 3}',
        )
    )
    session.flush()

    # -- the bulk of the corpus: multi-lingual articles across a multi-year spread -------- #
    n_articles = 0
    start, end = date(2023, 1, 1), date(2026, 8, 1)
    for lang, paragraphs in LANG_PARAGRAPHS.items():
        src_pool = sources[lang]
        per_lang = 55  # ~55 * 8 languages = ~440, clears the >=400 floor comfortably
        for i in range(per_lang):
            topic, body = paragraphs[i % len(paragraphs)]
            src = src_pool[i % len(src_pool)]
            variant = f" (edition {i // len(paragraphs) + 1})"
            title = f"{topic.capitalize()} coverage {variant.strip()} — {lang}"
            content = body + f" [{lang}-{topic}-{i}]"
            published = None if (i % 23 == 0) else _rand_date_avoiding_gap(rng, start, end)
            created = published or datetime.now(UTC) - timedelta(days=rng.randint(0, 30))
            article = Article(
                url=f"https://{src.domain}/{topic}-{i}",
                canonical_url=f"https://{src.domain}/{topic}-{i}",
                source_id=src.id,
                title=title,
                content=content,
                published_at=published,
                language=lang,
                hash=_hash_for(content, f"{lang}-{i}"),
                author=f"Staff Writer {i % 5}",
                word_count=len(content.split()),
                created_at=created,
                updated_at=created,
            )
            session.add(article)
            session.commit()
            index_article(session, article, extractor=extractor, country=src.country)
            n_articles += 1
    tally["articles_lang_pool"] = n_articles

    # -- a 3-source near-duplicate cluster sharing one outbound link ---------------------- #
    dup_src_a, dup_src_b, dup_src_c = sources["en"][0], sources["fr"][0], sources["de"][0]
    dup_body = (
        "The central committee approved a new port-expansion agreement on Tuesday after "
        "months of negotiation between the shipping consortium and the regional transport "
        "authority. Officials described the deal as the largest infrastructure investment "
        "in the harbour district in over a decade, with construction expected to begin "
        "early next year and create hundreds of temporary jobs. Environmental groups "
        "raised concerns about dredging impacts on nearby wetlands, and a public hearing "
        "has been scheduled for the coming weeks to address those objections before any "
        "permits are finalised by the coastal planning board."
    )
    dup_ids = []
    for j, (src, tag) in enumerate([(dup_src_a, "A"), (dup_src_b, "B"), (dup_src_c, "C")]):
        content = dup_body + f" [source {tag}]"
        a = Article(
            url=f"https://{src.domain}/port-expansion-{tag}",
            canonical_url=f"https://{src.domain}/port-expansion-{tag}",
            source_id=src.id, title=f"Port expansion approved ({tag})", content=content,
            published_at=datetime(2026, 2, 10 + j, tzinfo=UTC), language="en",
            hash=_hash_for(content, f"dup-{tag}"), word_count=len(content.split()),
            created_at=datetime(2026, 2, 10 + j, tzinfo=UTC),
        )
        session.add(a)
        session.commit()
        index_article(session, a, extractor=extractor, country=src.country)
        dup_ids.append(a.id)
        session.add(
            ArticleLink(
                article_id=a.id, url="https://wire-agency.example/port-deal-original",
                normalized_url="wire-agency.example/port-deal-original",
                link_type="external", classification="reference",
            )
        )
    session.commit()
    tally["near_dup_cluster"] = len(dup_ids)

    # -- the nav-soup / mislabeled-language / empty-body specimens ------------------------ #
    navsoup_src = sources["en"][1]
    navsoup = Article(
        url=f"https://{navsoup_src.domain}/newsletter-preference-centre",
        canonical_url=f"https://{navsoup_src.domain}/newsletter-preference-centre",
        source_id=navsoup_src.id, title="Preference Centre", content=NAV_SOUP_EN,
        published_at=datetime(2026, 7, 4, tzinfo=UTC), language="en",
        hash=_hash_for(NAV_SOUP_EN, "navsoup"), word_count=len(NAV_SOUP_EN.split()),
        created_at=datetime(2026, 7, 4, tzinfo=UTC),
    )
    session.add(navsoup)
    session.commit()
    index_article(session, navsoup, extractor=extractor, country=navsoup_src.country)

    mislabel_src = sources["ru"][0]
    mislabel = Article(
        url=f"https://{mislabel_src.domain}/park-renovation",
        canonical_url=f"https://{mislabel_src.domain}/park-renovation",
        source_id=mislabel_src.id, title="Park renovation announced",
        content=MISLABELED_BODY_RU_AS_EN,
        published_at=datetime(2026, 4, 12, tzinfo=UTC),
        language="en",  # DELIBERATELY wrong -- the body is Russian (the S5.2 mislabel case)
        hash=_hash_for(MISLABELED_BODY_RU_AS_EN, "mislabel"),
        word_count=len(MISLABELED_BODY_RU_AS_EN.split()),
        created_at=datetime(2026, 4, 12, tzinfo=UTC),
    )
    session.add(mislabel)
    session.commit()
    index_article(session, mislabel, extractor=extractor, country=mislabel_src.country)

    empty_src = sources["en"][0]
    empty = Article(
        url=f"https://{empty_src.domain}/empty-body-specimen",
        canonical_url=f"https://{empty_src.domain}/empty-body-specimen",
        source_id=empty_src.id, title="Empty body specimen", content="",
        published_at=datetime(2026, 5, 1, tzinfo=UTC), language="en",
        hash=_hash_for("", "empty-body"), word_count=0,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    session.add(empty)
    session.commit()
    index_article(session, empty, extractor=extractor, country=empty_src.country)
    tally["specimens"] = 3

    # -- dense (>=60pt), sparse (<10pt), and gapped commodity price series ---------------- #
    dense_start = date(2026, 1, 1)
    for d in range(70):
        session.add(
            CommodityPrice(
                symbol="Nd", market="china_spot",
                observed_on=dense_start + timedelta(days=d),
                price=55.0 + rng.uniform(-3, 3), currency="USD", unit="kg",
                source="ui-clickthrough-seed",
            )
        )
    for m in range(7):  # sparse: 7 monthly points, well under 10
        session.add(
            CommodityPrice(
                symbol="Dy", market="china_spot",
                observed_on=date(2025, 1, 1) + timedelta(days=30 * m),
                price=280.0 + rng.uniform(-10, 10), currency="USD", unit="kg",
                source="ui-clickthrough-seed",
            )
        )
    # gapped: real points before AND after a real multi-month hole -- never bridged.
    for d in range(20):
        session.add(
            CommodityPrice(
                symbol="Pr", market="china_spot", observed_on=date(2024, 10, 1) + timedelta(days=d),
                price=68.0 + rng.uniform(-2, 2), currency="USD", unit="kg",
                source="ui-clickthrough-seed",
            )
        )
    for d in range(20):
        session.add(
            CommodityPrice(
                symbol="Pr", market="china_spot", observed_on=date(2025, 8, 1) + timedelta(days=d),
                price=71.0 + rng.uniform(-2, 2), currency="USD", unit="kg",
                source="ui-clickthrough-seed",
            )
        )
    session.commit()
    tally["commodity_series"] = 3

    # -- law / wiki / newsletter / hazard provenance samples ------------------------------ #
    law_src = _mk_source(
        "Sample Consolidated Statutes", "law.gb.local", lang="en", country="gb",
        status="qualified", tags="legal", source_type="legal",
    )
    law_body = (
        "This consolidated statute governs the registration and oversight of coastal "
        "infrastructure permits within the jurisdiction. Section one establishes the "
        "regulatory authority; section two sets out the application procedure; section "
        "three defines penalties for non-compliance and the appeals process available to "
        "an affected party. The text below reflects the version in force as of the most "
        "recent amendment, consolidated for reference and cross-checked against the "
        "official gazette publication of record."
    )
    law_article = Article(
        url="https://law.gb.local/statute-42", canonical_url="https://law.gb.local/statute-42",
        source_id=law_src.id, title="Coastal Infrastructure Act (consolidated)",
        content=law_body, published_at=datetime(2026, 1, 15, tzinfo=UTC), language="en",
        hash=_hash_for(law_body, "law"), word_count=len(law_body.split()),
        created_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    session.add(law_article)
    session.commit()
    index_article(session, law_article, extractor=extractor, country="gb")
    session.add(
        LawDocument(
            jurisdiction="gb", title="Coastal Infrastructure Act", url="https://law.gb.local/statute-42",
            official_url="https://legislation.gov.example/coastal-infra-act",
            category="legislation", consolidated=True, watched=True,
            baseline_text=law_body, language="en", country="gb",
            last_status="ok", last_checked_at=datetime.now(UTC),
        )
    )

    wiki_src = _mk_source(
        "Wikipedia (en)", "en.wikipedia.org", lang="en", country=None, status="qualified",
        tags="wiki", source_type="wiki",
    )
    wiki_body = (
        "The Coastal Infrastructure Act is a piece of regional legislation establishing "
        "oversight of harbour development permits. It was first enacted in the previous "
        "decade and has been amended several times since, most recently to expand the "
        "environmental review requirement for large-scale dredging projects near "
        "protected wetlands."
    )
    wiki_article = Article(
        url="https://en.wikipedia.org/wiki/Coastal_Infrastructure_Act",
        canonical_url="https://en.wikipedia.org/wiki/Coastal_Infrastructure_Act",
        source_id=wiki_src.id, title="Coastal Infrastructure Act", content=wiki_body,
        published_at=datetime(2025, 11, 1, tzinfo=UTC), language="en",
        hash=_hash_for(wiki_body, "wiki"), word_count=len(wiki_body.split()),
        created_at=datetime(2025, 11, 1, tzinfo=UTC),
    )
    session.add(wiki_article)
    session.commit()
    index_article(session, wiki_article, extractor=extractor, country=None)
    session.add(
        WikiPage(
            wiki="en", title="Coastal Infrastructure Act", pageid=987654, watched=True,
            baseline_text=wiki_body, latest_text=wiki_body, last_checked_at=datetime.now(UTC),
        )
    )

    newsletter_src = _mk_source(
        "Weekly Coastal Digest", "newsletters.import.local", lang="en", country=None,
        status="qualified", tags="newsletter", source_type="newsletter",
    )
    nl_body = (
        "This week's roundup: the port expansion agreement, the coastal temperature "
        "assessment, and a preview of Thursday's finance committee review of the election "
        "turnout figures. As always, thank you for reading and forwarding to a friend who "
        "might enjoy the local news roundup we publish every Friday morning."
    )
    nl_article = Article(
        url="https://newsletters.import.local/digest-2026-07-10",
        canonical_url="https://newsletters.import.local/digest-2026-07-10",
        source_id=newsletter_src.id, title="Weekly Coastal Digest — July 10",
        content=nl_body, published_at=datetime(2026, 7, 10, tzinfo=UTC), language="en",
        hash=_hash_for(nl_body, "newsletter"), word_count=len(nl_body.split()),
        created_at=datetime(2026, 7, 10, tzinfo=UTC),
    )
    session.add(nl_article)
    session.commit()
    index_article(session, nl_article, extractor=extractor, country=None)

    hazard_src = _mk_source(
        "USGS Earthquake Feed", "earthquake.usgs.gov", lang="en", country="us",
        status="qualified", tags="hazard", source_type="hazard",
    )
    hazard_body = (
        "A magnitude 6.1 earthquake struck offshore near the coastal district early this "
        "morning, the United States Geological Survey reported, with no immediate reports "
        "of major damage. Local authorities advised residents in low-lying areas to remain "
        "alert for aftershocks over the coming days."
    )
    hazard_article = Article(
        url="https://earthquake.usgs.gov/event/us7000abcd",
        canonical_url="https://earthquake.usgs.gov/event/us7000abcd",
        source_id=hazard_src.id, title="M6.1 earthquake offshore", content=hazard_body,
        published_at=datetime(2026, 6, 20, 8, 15, tzinfo=UTC), language="en",
        hash=_hash_for(hazard_body, "hazard"), word_count=len(hazard_body.split()),
        created_at=datetime(2026, 6, 20, 8, 15, tzinfo=UTC),
    )
    session.add(hazard_article)
    session.commit()
    index_article(session, hazard_article, extractor=extractor, country="us")
    session.add(
        HazardEventDetail(
            article_id=hazard_article.id, provider="usgs", event_id="us7000abcd",
            event_type="earthquake", severity="orange", magnitude=6.1,
            lat=34.05, lon=-118.25, place="offshore, coastal district",
            event_time=datetime(2026, 6, 20, 8, 12, tzinfo=UTC),
            source_url="https://earthquake.usgs.gov/event/us7000abcd",
        )
    )
    session.commit()
    tally["provenance_samples"] = 4  # law, wiki, newsletter, hazard

    # -- a DEDUCED-future-event specimen (2026-08-20, the T5 agenda drill) ---------------- #
    # The agenda's deduced layer (timemap/datestore.upcoming_deduced) surfaces a FUTURE date
    # mentioned by >= 2 distinct articles within 120 days. Without a specimen the drill can
    # only report "blocked: no deduced event in the corpus" -- an untested path is not a
    # pass, so the specimen is seeded THROUGH the real extractor (index_article stores the
    # mentioned date with snippet provenance; nothing is hand-inserted into
    # article_mentioned_dates). Three articles, two sources, one explicit future date.
    fut_bodies = [
        (
            sources["en"][0],
            "The regional planning board confirmed that the public hearing on the harbour "
            "dredging permits will be held on 12 October 2026 at the civic centre. "
            "Residents of the low-lying districts are encouraged to register in advance, "
            "officials said, as seating for the session is limited and demand is expected "
            "to be high given the months of debate over the port expansion. The hearing "
            "will take written submissions as well, and the board pledged to publish every "
            "submission it receives alongside the minutes of the session itself, so that "
            "the record of the decision remains open to public scrutiny afterwards.",
        ),
        (
            sources["en"][1],
            "Campaign groups on both sides of the port expansion argument said they would "
            "attend the hearing scheduled for 12 October 2026, with the fishing "
            "cooperative planning to present its own survey of wetland impacts. The "
            "cooperative's chair said the survey covered three seasons of observations "
            "along the affected shoreline and would be released publicly a week before "
            "the session. A spokesperson for the shipping consortium said the company "
            "welcomed the scrutiny and would answer every question the panel put to it "
            "during the session, however long that took.",
        ),
        (
            sources["en"][0],
            "A procedural note published by the clerk's office confirmed the 12 October "
            "2026 date for the dredging hearing and set out how members of the public can "
            "submit evidence. Submissions close one week before the session, the note "
            "said, and any material received after the deadline will be carried over to a "
            "follow-up session if one is required. The clerk also confirmed that the "
            "session will be recorded and that the recording will be published unedited "
            "within three working days, in line with the board's open-proceedings policy "
            "adopted earlier this year after criticism of closed-door planning decisions.",
        ),
    ]
    for k, (src, body) in enumerate(fut_bodies):
        a = Article(
            url=f"https://{src.domain}/hearing-note-{k}",
            canonical_url=f"https://{src.domain}/hearing-note-{k}",
            source_id=src.id, title=f"Dredging hearing note {k + 1}", content=body,
            published_at=datetime(2026, 7, 20 + k, tzinfo=UTC), language="en",
            hash=_hash_for(body, f"future-event-{k}"), word_count=len(body.split()),
            created_at=datetime(2026, 7, 20 + k, tzinfo=UTC),
        )
        session.add(a)
        session.commit()
        index_article(session, a, extractor=extractor, country=src.country)
    session.commit()
    tally["deduced_future_event_articles"] = len(fut_bodies)

    return tally


def seed_mini_corpus(session, *, rng_seed: int = 20260820) -> dict:
    """A SMALL corpus (the import-fixture SOURCE, T2 of the 2026-08-20 matrix session):
    ~24 articles across 4 languages, seeded through the SAME ``index_article`` chokepoint as
    the full state-C corpus. This corpus is backed up with the app's own volume-backup
    engine and then imported into a FRESH instance through the real Import dialog, so the
    post-import screen renders a REAL run's summary — never a fabricated fixture payload.
    Small on purpose: the import drill's subject is the post-import SCREEN, not scale
    (scale is P0-validation territory, already measured elsewhere)."""
    from src.analytics.extract import get_extractor
    from src.analytics.store import index_article
    from src.database.models import Article, Source

    rng = random.Random(rng_seed)
    extractor = get_extractor("baseline")
    tally: dict[str, int] = {}
    n = 0
    for lang in ("en", "fr", "de", "zh"):
        src = Source(
            name=f"Mini {lang.upper()} Wire", domain=f"mini-{lang}.example",
            language=lang, country={"en": "us", "fr": "fr", "de": "de", "zh": "cn"}[lang],
            source_type="news", tags="news", status="qualified", enabled=True,
            qualified_at=datetime.now(UTC), qualification_criteria_version="v1",
        )
        session.add(src)
        session.flush()
        paragraphs = LANG_PARAGRAPHS[lang]
        for i in range(6):
            topic, body = paragraphs[i % len(paragraphs)]
            content = body + f" [mini-{lang}-{topic}-{i}]"
            published = _rand_date(rng, date(2025, 1, 1), date(2026, 7, 1))
            a = Article(
                url=f"https://{src.domain}/{topic}-{i}",
                canonical_url=f"https://{src.domain}/{topic}-{i}",
                source_id=src.id, title=f"Mini {topic} {i} — {lang}", content=content,
                published_at=published, language=lang,
                hash=_hash_for(content, f"mini-{lang}-{i}"),
                word_count=len(content.split()), created_at=published, updated_at=published,
            )
            session.add(a)
            session.commit()
            index_article(session, a, extractor=extractor, country=src.country)
            n += 1
    tally["mini_articles"] = n
    return tally


def main() -> None:
    import argparse

    from src.database.session import SessionLocal, init_db

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mini", action="store_true",
        help="seed the SMALL import-fixture source corpus instead of the full state C",
    )
    args = ap.parse_args()

    init_db()
    session = SessionLocal()
    try:
        tally = seed_mini_corpus(session) if args.mini else seed_populated_corpus(session)
        session.commit()
    finally:
        session.close()
    print(f"ui_clickthrough_seed: {'MINI import-source' if args.mini else 'STATE C'} seeded.")
    for k, v in tally.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
