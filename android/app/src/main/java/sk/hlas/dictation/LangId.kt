package sk.hlas.dictation

/** Port of desktop/hlas/langid.py (keep in sync). */
object LangId {
    private fun words(s: String) = s.split(Regex("\\s+")).filter { it.isNotBlank() }.toSet()

    private val EN = words("""the a an and or but of to in on at for with from by is are was were be been being it this that
these those i you he she we they me him her us them my your our their not no yes do does did have has had
will would can could should just so if then than what when where who why how there here about as up out
all very really okay ok please thanks thank because also into over get got go going know think want need
like make sure let's i'm it's don't that's""")
    private val DE = words("""der die das den dem des ein eine einen einem einer und oder aber nicht ist sind war waren bin bist
sein ich du er sie es wir ihr mich mir dich dir uns euch mein dein sein unser mit von zu im in am auf an
für bei aus nach über unter auch noch schon nur so wie was wer wo wann warum wenn dass weil ja nein doch
hat habe haben hatte wird werden kann können muss müssen soll will möchte bitte danke gut heute morgen
jetzt hier da dann mal sehr gerne kein keine nichts etwas alles man""")
    private val SK = words("""a aj ale alebo že sa si som sme ste sú je bol bola bolo by na v vo z zo do od pre pri po o k ku s so
ja ty on ona ono my vy oni mi ti mu jej nám vám ich ma ťa ho môj tvoj náš váš tak ako čo kto kde kedy prečo
áno nie no už ešte len iba veľmi dobre teraz dnes zajtra včera tu tam toto tento táto ten to tie tí
mám máš má máme máte majú môžem môžeš môže potrebujem chcem chceš prosím ďakujem
w jest się nie czy jak mnie mi ten ta to tylko bardzo proszę dzień jutro dzisiaj mam masz ma
jsem jsi jsme jste není ještě také když protože abych proto jenom hodně děkuji prosím""")
    private val SLAVIC = Regex("[čďľĺňŕšťžôřůěłąęśźżńćщъыэюя]")
    private val GERMAN = Regex("[ßöü]")
    private val WORD = Regex("[\\p{L}]+(?:'[\\p{L}]+)?")

    data class Scores(val en: Double, val de: Double, val sk: Double, val n: Int)

    fun scores(text: String): Scores {
        val w = WORD.findAll(text).map { it.value.lowercase() }.toList()
        val n = w.size
        if (n == 0) return Scores(0.0, 0.0, 0.0, 0)
        val low = text.lowercase()
        val en = w.count { it in EN }.toDouble() / n
        var de = w.count { it in DE }.toDouble() / n
        var sk = w.count { it in SK }.toDouble() / n
        sk += minOf(0.3, SLAVIC.findAll(low).count().toDouble() / n * 0.5)
        de += minOf(0.2, GERMAN.findAll(low).count().toDouble() / n * 0.5)
        return Scores(en, de, sk, n)
    }

    /** "en", "de", "sk" (Slovak or a Slavic look-alike), or "" if unclear. */
    fun guess(text: String): String {
        val s = scores(text)
        if (s.n == 0) return ""
        val best = listOf("en" to s.en, "de" to s.de, "sk" to s.sk).maxByOrNull { it.second }!!
        if (best.second < 0.12) return if (SLAVIC.containsMatchIn(text.lowercase())) "sk" else ""
        return best.first
    }

    /** Which model's output reads like real text: "base" or "sk". */
    fun pick(baseText: String, skText: String): String {
        val b = scores(baseText)
        val k = scores(skText)
        var baseConf = maxOf(b.en, b.de)
        var skConf = k.sk
        if ("<unk>" in baseText) baseConf -= 0.2
        if ("<unk>" in skText) skConf -= 0.2
        if (b.sk > baseConf) return "sk"
        return if (skConf > baseConf) "sk" else "base"
    }
}
