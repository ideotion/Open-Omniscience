"""Add the cross-language concept fixture on top of STATE C, through the real indexer.

The standing seeder's per-language prose is about a climate TOPIC but does not carry the
ring's surface forms (`Klima`, `مناخ`, `气候` ...), so a walk over it would exercise the
rail against an empty expansion. These nine articles do carry them -- one per language,
plus one deliberately bilingual so the overlap the per-form readout warns about is on
screen rather than only in the caveat.
"""
from datetime import UTC, datetime, timedelta

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.fts import ensure_fts
from src.database.models import Article, Source
from src.database.session import SessionLocal, engine

DOCS = [
    ("en", "Coastal climate assessment", "The regional agency published a climate assessment this week describing how the climate of the harbour district has shifted over ten years. Officials said the climate record now covers four decades of measurements and that the climate committee would review the findings before any flood defence is approved by the assembly."),
    ("en", "Climate funding stalls", "Funding for the largest climate barrier remains unresolved. Engineers studying the climate models said the designs were sound but that the climate budget had not been agreed, and the assembly postponed its decision until the next session."),
    ("fr", "Le climat du port", "Le climat du quartier portuaire a changé de manière mesurable, selon un rapport publié cette semaine. Les chercheurs ont rappelé que le climat régional se réchauffe depuis des décennies et que les relevés de climat couvrent désormais quarante années de mesures continues."),
    ("fr", "Climat et pêche", "Les coopératives de pêche ont accueilli le rapport sur le climat avec prudence. Elles demandent que les communautés exposées soient consultées avant toute décision, car le climat local détermine directement les saisons de pêche."),
    ("de", "Klima im Hafenviertel", "Das Klima im Hafenviertel hat sich messbar verändert. Ein neuer Bericht beschreibt, wie das Klima der Region seit vierzig Jahren erfasst wird und warum das Klima der Küste für die Planung der Deiche entscheidend bleibt."),
    ("es", "El clima costero", "El clima costero ha cambiado de forma medible durante la última década. El informe señala que el registro del clima abarca ya cuarenta años y que el clima de la región determina las decisiones sobre las defensas contra inundaciones."),
    ("ar", "المناخ الساحلي", "أظهر تقرير جديد أن المناخ الساحلي تغير بشكل ملحوظ خلال العقد الماضي. وقال الباحثون إن سجل المناخ يمتد الآن أربعين عاماً وأن المناخ الإقليمي يحدد قرارات الحماية من الفيضانات في المنطقة."),
    ("hi", "तटीय जलवायु", "एक नई रिपोर्ट के अनुसार तटीय जलवायु पिछले दशक में स्पष्ट रूप से बदली है। शोधकर्ताओं ने कहा कि जलवायु का रिकॉर्ड अब चालीस वर्षों का है और क्षेत्रीय जलवायु बाढ़ सुरक्षा के निर्णयों को प्रभावित करती है।"),
    # The overlap document: two forms of one concept in one article, so the per-form
    # figures on screen genuinely do not add up to the total beside them.
    ("en", "Climate and climat, one report", "The joint report is published in two languages: the English edition calls it climate policy and the French edition calls the same thing climat. Readers comparing the two editions will find the climate chapter and the climat chapter identical in substance."),
]

s = SessionLocal()
ex = BaselineExtractor()
srcs = {}
for lg, title, body in DOCS:
    key = f"xl-{lg}"
    if key not in srcs:
        src = s.query(Source).filter(Source.domain == f"{key}.example").first()
        if src is None:
            src = Source(name=f"cross-lang {lg}", rss_url=f"https://{key}.example/feed",
                         domain=f"{key}.example")
            s.add(src); s.flush()
        srcs[key] = src
    u = f"https://{key}.example/{abs(hash(title)) % 10**8}"
    a = Article(title=title, content=body, url=u, canonical_url=u, source_id=srcs[key].id,
                language=lg, published_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=len(srcs)),
                hash=f"xl-{abs(hash(title))}")
    s.add(a); s.flush()
    index_article(s, a, extractor=ex)
s.commit()
ensure_fts(engine, rebuild="always")
print(f"added {len(DOCS)} cross-language fixture articles")
s.close()
