import time, simplemma
from simplemma import Lemmatizer
from simplemma.strategies import DefaultStrategy, DefaultDictionaryFactory

LANGS = ["it","pt","de","fr","ru","id","nl","en","es"]          # nine -- the app's set
WORDS = [f"coronavirus{i}" for i in range(40)]

def bench(label, fn, langs):
    for w in WORDS[:3]:                                          # warm the dictionaries
        for lg in langs: fn(w, lg)
    t0 = time.perf_counter()
    for w in WORDS:
        for lg in langs: fn(w, lg)
    dt = time.perf_counter() - t0
    n = len(WORDS) * len(langs)
    print(f"{label:<52} {dt*1000:9.1f} ms for {n} calls -> {dt/n*1000:6.2f} ms/call", flush=True)

bench("shipped: simplemma.lemmatize, 9 langs (cache 8)", lambda w, lg: simplemma.lemmatize(w, lg), LANGS)
bench("shipped: simplemma.lemmatize, 8 langs (cache 8)", lambda w, lg: simplemma.lemmatize(w, lg), LANGS[:8])
lz = Lemmatizer(lemmatization_strategy=DefaultStrategy(
    dictionary_factory=DefaultDictionaryFactory(cache_max_size=len(LANGS))))
bench("fixed: one Lemmatizer, factory cache = 9", lambda w, lg: lz.lemmatize(w, lg), LANGS)
