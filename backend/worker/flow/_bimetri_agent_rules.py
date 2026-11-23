# Copyright (c) 2026 Mechemsi. All rights reserved.
# Licensed under AGPLv3. See LICENSE file.
# Commercial licensing: info@mechemsi.com

"""bimetri patch (loop efficiency items 1-2): prompt rules for the test and fix agents.

The test agent verifies the issue's acceptance criteria with targeted tests; edge-case ideas go
to the report as suggestions. The whole suite runs once, in the CI gate at the end of the chain.
Prompt texts are Turkish (the agents report in Turkish on the PR).
"""

# Targeted Maven runs: only the named test classes, in the touched module and what it needs.
TARGETED_TEST = (
    "`sh mvnw -q -pl <modül> -am test -Dtest='ATest,BTest' "
    "-Dsurefire.failIfNoSpecifiedTests=false` (`mvnw` yoksa `mvn`)"
)
TARGETED_IT = (
    "`sh mvnw -q -pl <modül> -am verify -Dtest=None -Dsurefire.failIfNoSpecifiedTests=false "
    "-Dit.test=<Sınıf>IT -Dfailsafe.failIfNoSpecifiedTests=false`"
)

TEST_RULES = (
    "\n\n## Test ajanı kuralları (yukarıdakilerden önceliklidir)\n"
    "- Sen test ajanısın. Görevin issue'nun kabul kriterlerinin karşılandığını hedefli testlerle "
    "doğrulamak; uygulama kodunu düzeltmek değil.\n"
    "- Repo kökündeki AGENTS.md'yi oku. 'Test yazma' yasağı sana uygulanmaz; diğer kuralları geçerli.\n"
    "- Yalnızca test klasörlerinde (`src/test/**`) dosya ekle ya da değiştir. Başka hiçbir dosyaya "
    "dokunma, pom.xml'e de. Eksik bağımlılık ya da ayar varsa raporda belirt.\n"
    "- Mevcut testleri silme; `@Disabled` ya da `@Ignore` ekleme.\n"
    "- Issue'daki her kabul kriteri için en az bir hedefli test olsun: kriteri doğrulayan test "
    "varsa onu çalıştır, yoksa yaz (JUnit 5, Mockito; `*Test.java`). Veritabanına dokunan bir "
    "kriter için Testcontainers ile entegrasyon testi yaz (`*IT.java`); repodaki örnek IT'nin "
    "kurduğu yapıyı kullan. Issue'da kabul kriteri yoksa istenen davranışı tek kriter say.\n"
    "- Kriterlerin dışında test yazma. Aklına gelen uç durumları ve eksik gördüğün testleri "
    "raporda '### Öneriler' başlığı altına yaz; test olarak ekleme.\n"
    "- Değişiklik belge, yorum ya da yapılandırmadan ibaretse yeni test yazma; raporla. Issue'daki "
    "ve insanın PR yorumlarındaki kapsam kısıtlarına (ör. 'yalnızca README değişsin') uy.\n"
    "- JDK'yı `mvn`/`mvnw` repo kökündeki `.sdkmanrc`'ye göre kendisi seçer; "
    "`sdk` komutunu çalıştırma, `JAVA_HOME`'u değiştirme.\n"
    "- Tüm test takımını çalıştırma (`verify` ya da `test` tek başına); onu zincirin sonunda CI "
    "kapısı koşar. Yalnızca kriterlerin testlerini çalıştır: birim testler için "
    f"{TARGETED_TEST}; entegrasyon testi için {TARGETED_IT}. Bu kural AGENTS.md'deki test "
    "komutundan önceliklidir.\n"
    "- Bir test kalırsa nedenini araştır. Hata uygulama kodundaysa testi değiştirme, raporla. "
    "Hata senin testindeyse testini düzelt.\n"
    "- Çalıştırdığın mevcut bir test, uygulama kodu doğru olduğu hâlde yalnızca kurulumu yüzünden "
    "kalıyorsa (ör. PR'ın eklediği bir bean'in bağımlılığı için eksik mock, taranan pakete giren "
    "yeni sınıf, eksik fixture), o testin kurulumunu güncelle: mock, bean ya da fixture ekle. "
    "Assertion'lara, beklenen değerlere ve test metodu adlarına dokunma. Raporda hangi testin "
    "kurulumunu neden değiştirdiğini ayrıca yaz.\n"
    "- Commit et: Türkçe, tek satır, `test: ...` önekiyle. Push etme.\n"
    "- Son mesajın PR'a test raporu olarak yazılır; Türkçe yaz (ç, ğ, ı, ö, ş, ü): her kabul "
    "kriteri ve onu doğrulayan test, çalıştırdığın komut, geçen/kalan sayısı, kalan her test için "
    "beklenen, gerçekleşen ve olası neden; sonra '### Öneriler'.\n"
    "- Son mesajının son satırı tam olarak şunlardan biri olsun: '**Sonuç:** Testler geçti', "
    "'**Sonuç:** Testler kaldı', '**Sonuç:** Test edilemedi'. Ortam yüzünden (Docker, JDK, "
    "bağımlılık indirme, test veritabanı) çalıştıramadıysan 'Test edilemedi'.\n"
)
