# Apex DNS Changer

Popüler DNS sunucularını gecikme testleriyle karşılaştırıp tek tıkla değiştiren
DNS yöneticisi ve ağ teşhis aracı. DoH ve IPv6 testi, teşhis raporu ve
PyInstaller ile üretilen Windows `.exe` sürümü içerir.

## Özellikler

- Koyu temalı, tek ekranlı arayüz; gecikme testi sonucunda en hızlı DNS önerilir.
- **DoH (DNS over HTTPS)** testi: RFC 8484 (POST ve GET) ve JSON API uçları.
- **IPv6 testi**: yığın varlığı, genel adres, AAAA çözümleme ve ICMPv6 gecikmesi.
- Çoklu bağlantı üzerinde toplu DNS değişikliği ve DHCP'ye sıfırlama.
- Konsol teşhis raporu: DNS süreleri, DoH, IPv6, bağlantılar, paket kaybı, bant
  genişliği ve en çok ağ kullanan işlemler.
- JSON çıktı (`diagnostics-json`) ile otomasyona uygun çıktı.

## Kurulum

```bash
python -m pip install -r requirements.txt
```

Python 3.10+ gerekir. `httpx[http2]` olmadan da çalışır; yalnızca HTTP/2
zorunlu DoH uçları (Quad9) hata döndürür.

## Kullanım

```bash
python main.py                      # arayüzü başlatır (gerekirse yöneticiye yükseltir)
python main.py diagnostics          # konsol teşhis raporu
python main.py diagnostics --quick  # yavaş ölçümleri atlar
python main.py diagnostics-json     # makine tarafından okunabilir rapor
python main.py doh                  # DoH ve IPv6 testi
python main.py adapters              # ağ bağlantılarını listeler
python main.py ping 1.1.1.1         # gecikme ve paket kaybı
python main.py speed                 # bant genişliği
python main.py providers             # DNS sağlayıcı listesi
```

`dns_changer.py` geriye dönük uyum için korunmuş bir başlatıcıdır ve
`main.py` dosyasına yönlendirir.

## Yapı

```
main.py              komut satırı giriş noktası
core/                iş mantığı (GUI bağımsız)
  system.py          platform tespiti, gizli alt süreç, ping ayrıştırma
  providers.py       DNS sağlayıcı kataloğu (tek doğru kaynak)
  resolver.py        UDP DNS, DoH ve IPv6 probları (yalnızca standart kütüphane)
  dns_service.py     bağlantı keşfi ve DNS okuma/yazma, platform arka uçları
  elevation.py       yönetici tespiti ve UAC akışı
ui/                  tkinter katmanı
  theme.py           renkler, yazı tipleri, ttk stilleri
  widgets.py         DnsCard, ProviderList, AdapterBar, CustomDnsForm, StatusFooter
  app.py             pencere denetleyicisi
diagnostics/         konsol teşhisi
  speedtest.py       bant genişliği, ping, işlem başına ağ kullanımı
  netusage.py        ağ kullanımı örneklemesi
  report.py          metin ve JSON rapor üretimi
packaging/           PyInstaller spec, UAC manifesti, ikon, build betiği
tools/               ikon üretimi ve manifest doğrulama
tests/               birim testleri (çapraz platform)
```

`core` katmanı hiçbir GUI veya Windows'a özgü içe aktarma barındırmaz; bu
sayede Linux ve macOS üzerinde de içe aktarılabilir ve test edilebilir.

## Platform desteği

| İşlem | Windows | Linux | macOS |
| --- | --- | --- | --- |
| Bağlantı listeleme | PowerShell (`Get-NetAdapter`) | `nmcli` | `resolv.conf` |
| DNS okuma | ✅ | ✅ | ✅ (salt okunur) |
| DNS yazma / sıfırlama | ✅ | ✅ | ❌ desteklenmiyor |

macOS ve BSD'de çözümleyici yapılandırması sistem geneli bir ağ tercihidir;
uygulama yazma işlemini açıkça reddeder. DNS testleri her yerde çalışır.

## Windows .exe üretimi

```powershell
pwsh -File packaging/build.ps1        # ilk çalıştırmada .venv-build oluşturulur
pwsh -File packaging/build.ps1 -Clean # sıfırdan derleme
```

İki yürütülebilir üretilir:

- `ApexDNSChanger.exe` — pencere uygulaması, gömülü `requireAdministrator`
  manifesti sayesinde UAC istemiyle DNS değiştirebilir.
- `ApexDNSDiagnostics.exe` — konsol uygulaması, `asInvoker`; teşhis raporu
  yönetici istemi tetiklemez.

UAC seviyesini doğrulamak için:

```bash
python tools/check_manifest.py dist/ApexDNSChanger.exe dist/ApexDNSDiagnostics.exe
```

Kaynak kodla çalışırken UAC yükseltmesi `core/elevation.py` tarafından yapılır;
`--no-elevation` ile atlanabilir.

## Testler

```bash
python -m unittest discover -s tests -t .
python -m ruff check .
```

Testler ağ bağlantısı gerektirmez; tüm platformlarda çalışır.

## Proje durumu

- [CHANGELOG.md](CHANGELOG.md) — sürüm 2.0.0'daki tüm değişiklikler
- [ROADMAP.md](ROADMAP.md) — planlanan çalışmalar
- [LICENSE](LICENSE) — MIT

## Lisans

Bu proje [MIT Lisansı](LICENSE) altında lisanslanmıştır.
