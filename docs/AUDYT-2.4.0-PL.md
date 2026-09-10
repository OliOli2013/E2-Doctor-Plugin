# E2 Doctor 2.4.0 — audyt i aktualizacja

Data: 10.09.2026. Build: `20260910-1`.

Przygotowano nowy IPK i źródła do podmiany. Testy lokalne zakończyły się powodzeniem. Nie wykonano instalacji na fizycznym tunerze, testów głowic, restartu OSCam ani renderowania w prawdziwym Enigma2. Wydanie należy najpierw sprawdzić na jednym odbiorniku.

## Materiał wejściowy i zakres

- Repozytorium: https://github.com/OliOli2013/E2-Doctor-Plugin, gałąź `main`, commit `cf94553da06666385b60d6c1fb0b3d44c7393871`.
- Załączony IPK 2.3. Porównanie `plugin.py` z IPK i repozytorium: identyczne bajtowo.
- Przegląd diagnostyki systemu, pamięci, sieci, OPKG, bukietów, głowic, nośników, EPG, piconów, OSCam, crashlogów; historii, kopii, narzędzi, analizatora IPK, aktualizatora i pakowania.
- Zrzuty AIO Panel 16.0.2 jako wzór układu i palety. Nie kopiowano poleceń instalacyjnych z innych wtyczek.

## Najważniejsze ustalenia i poprawki

| Obszar | Problem w 2.3 | Zmiana w 2.4.0 |
|---|---|---|
| Responsywność | Pełny skan i pobieranie manifestu wykonywane w wątku GUI | Wątek roboczy, kolejka wyników i eTimer; odczyt aktywnej głowicy pozostaje w wątku GUI |
| Postęp | Komunikat o rozpoczęciu mógł nie zdążyć się wyświetlić | Widoczny etap skanu; osobny ekran postępu dla dłuższych narzędzi |
| Analiza IPK/Python | Skanowanie plików i analiza blokowały obsługę ekranu | Praca w tle, wynik przekazywany do GUI |
| Sieć | Połączenie TCP z portem 443 nazywano poprawnym HTTPS | Rzeczywisty handshake TLS i weryfikacja certyfikatu GitHub; brak twierdzenia o wszystkich usługach internetu |
| DNS i procesy | DNS mógł przekroczyć deklarowany timeout; po timeout zabijano tylko proces powłoki | Test sieci w osobnym procesie z limitem; zakończenie grupy procesów i zebranie procesu potomnego |
| OPKG | Każdy stan inny niż `install ok installed` uznawano za uszkodzenie | Prawidłowa obsługa `hold`, pozostałych plików konfiguracyjnych po usunięciu i stanów częściowej instalacji |
| Baza OPKG | Tylko `/var/lib/opkg/status` | Dodatkowo `/usr/lib/opkg/status` |
| Blokady OPKG | Usuwanie pliku mogło umożliwić równoległe operacje pakietowe | Sprawdzenie procesu i blokady jądra bez usuwania inode; pozostawiony plik nie jest sam w sobie błędem |
| Bukiety | Brak `lamedb` zgłaszał błąd także przy `lamedb5` | Rozpoznawanie obu nazw bazy |
| Kopie bukietów | Możliwa kolizja katalogów w tej samej sekundzie; zapis operacji dopiero po zmianie | Unikalny katalog kopii; rejestracja kopii przed edycją; cofanie najpierw odczytuje wszystkie kopie |
| Wyłączanie wtyczek | Katalog z nową nazwą pozostawał pod `Extensions` i nadal był skanowany | Przeniesienie do `/usr/lib/enigma2/python/e2doctor-disabled`, poza drzewo `Plugins`; cofnięcie przeniesienia przy błędzie zapisu historii |
| Crashlogi | Zwykłe logi debug mogły maskować awarię i trafiać do czyszczenia | Wyszukiwanie plików `*crash*.log`; pomijanie dowiązań |
| Analiza traceback | Pierwszy wzorzec błędu mógł zostać połączony z kontekstem innego traceback | Analiza ostatniego traceback z jego kontekstem; nadal jest to wskazówka, nie dowód winy wtyczki |
| Czytanie logów | Pozycjonowanie UTF-8 mogło trafić w środek znaku | Odczyt końcówki w trybie binarnym, następnie dekodowanie z zastępowaniem niepełnych znaków |
| Czyszczenie | Pliki OPKG/core uznawano za zbędne na podstawie nazwy | Automatyczne czyszczenie wyłącznie starych crashlogów z głównego systemu plików; wiek >24 h i zachowanie trzech najnowszych |
| Zmiana pliku po podglądzie | Przed usunięciem nie sprawdzano, czy plik się zmienił | Ponowna kwalifikacja oraz porównanie urządzenia, inode, rozmiaru i czasu modyfikacji |
| Raporty | Fragment błędu mógł zawierać hasło, mimo deklaracji braku haseł | Maskowanie rozpoznanych pól i danych logowania w URL; prywatny zapis atomowy; uczciwa informacja o ograniczeniach maskowania |
| Raport awaryjny | Skrypt powłoki wypisywał także argumenty procesów i miał niespójny numer wersji | Samodzielny skrypt Python bez importowania GUI, ograniczone odczyty, nazwy procesów bez pełnych argumentów i maskowanie danych |
| Aktualizator | Stała ścieżka w `/tmp`, pobieranie wget bez ogólnego limitu, brak kontroli tożsamości pakietu | Prywatny katalog, limit pobrania 32 MiB i 60 s, SHA-256, nazwa pakietu, wersja i architektura `all` |
| Przekierowania | Dozwolony host sprawdzano tylko w początkowym URL | HTTPS i dozwolona domena również przy przekierowaniach; odrzucenie userinfo i niestandardowego portu |
| Instalacja aktualizacji | Sam kod zakończenia OPKG mógł dać fałszywy sukces | Weryfikacja faktycznie zapisanej wersji i build w `__init__.py`; blokada zmiany manifestu w czasie potwierdzenia |
| Porównanie wersji | `2.4` i `2.4.0` traktowano jako różne | Normalizacja końcowych zer; nadal obsługiwany nowszy build tej samej wersji |
| Analizator archiwum | Brak kontroli ujemnych rozmiarów i obciętych elementów ar; nieograniczona analiza tar | Limity 32 MiB IPK, 128 MiB danych tar, 10 tys. wpisów; odrzucenie traversal, zewnętrznych linków i plików specjalnych |
| Zależności IPK | Sprawdzano tylko pierwszą alternatywę i uznawano usunięte pakiety za obecne | Uwzględnianie alternatyw i `Provides` z faktycznie zainstalowanych pakietów; brak wersjonowanego solvera zależności |
| OSCam | Wysłanie HUP mogło być opisane jako restart | Usunięcie HUP z listy metod restartu; informacja o powodzeniu polecenia usługi |
| Monitor | Wielokrotne wywołanie startu mogło tworzyć kolejne timery | Jedna instancja i zatrzymanie przy końcu sesji |
| Kod | Wiele definicji było bezwarunkowo przesłanianych | Usunięcie 43 nieużywanych definicji, wydzielenie dashboard.py, runtime.py i jobs.py |
| Pakowanie | Składnię sprawdzano po utworzeniu paczki, niepełne Depends | Kontrola składni przed budową, jawne pakiety biblioteki standardowej, zgodne wersje, md5sums i SHA256SUMS; powtarzalna budowa |

## Interfejs

Nowy główny ekran: ciemne, nieprzezroczyste tło, turkusowy akcent, menu kategorii po lewej, wyniki pośrodku, opis i orientacyjny wynik kontroli po prawej. Widoczne przyciski kolorowe i podpis autora. Przegląd tunera otwiera się jako pierwsza kategoria.

Przyciski: czerwony — skan; zielony/OK — wejście lub szczegóły; żółty — zapis raportu; niebieski/EXIT — wyjście; lewo/prawo — kolumna; MENU — ustawienia; 0 — aktualizacja. Wyniki z błędami i ostrzeżeniami są na górze.

Skalowanie głównego panelu i aktualizatora dostosowuje układ do framebuffer. Dotychczasowe ekrany pomocnicze zachowują układy HD/FHD z ujednoliconą paletą. Załączony PNG to render projektu z przykładowymi danymi, nie zdjęcie pracującego tunera.

## Sprawdzenia lokalne

20 testów unittest: stany OPKG, Provides, atomowy zapis i uprawnienia, UTF-8, timeout procesu, URL i wersje, maskowanie danych, traceback, uszkodzone ar, niebezpieczne ścieżki tar, ochrona zmienionego pliku przed usunięciem, granice XML, kolejka/wyjście z ekranu, izolowanie błędów modułu, cykl życia aktualizatora, checksumy i zawartość IPK, brak fałszywego sukcesu aktualizacji, asynchroniczny manifest, konstrukcja ekranów pomocniczych i lamedb5.

Dodatkowo: składnia wszystkich plików wykonywalnych Python z gramatyką 3.5, składnia powłoki, kontrola integralności ar/tar, właściciele i tryby plików, brak pyc, zgodność manifestu z IPK, kontrola odtwarzalności budowy. Testy wykonano na Pythonie 3.12 z atrapami API Enigma2; sprawdzenie gramatyki nie jest uruchomieniem na Pythonie 3.5.

## Granice i dalsza weryfikacja na tunerze

- Cel: obrazy Enigma2 z Pythonem 3 i OPKG. Nie jest to wydanie dla Python 2 ani paczka DEB dla DreamOS.
- Potrzebny test na OpenATV i OpenPLi: instalacja 2.3 → 2.4.0, restart GUI, pilot, przewijanie, PL/EN, HD/FHD, pełny skan, raport, cofanie kopii, aktualizacja z opublikowanego manifestu.
- TLS wymaga poprawnej daty i działających certyfikatów systemowych. Nie wyłączono sprawdzania certyfikatów.
- Obsługa restartu OSCam nadal zależy od skryptu/usługi dostępnej w danym obrazie. Nie sprawdzano odtwarzania kanałów po restarcie.
- Score /100 to heurystyka, a nie pomiar niezawodności. Progi temperatur i pamięci pozostają orientacyjne.
- Brak crashlogu w obsługiwanych lokalizacjach nie dowodzi braku awarii. Logi o niestandardowych nazwach wymagają ręcznej analizy.
- Analizator IPK niczego nie instaluje; odrzuca także część legalnych paczek z zewnętrznymi linkami lub przekraczających limity. Nie rozstrzyga wersji zależności i nie uruchamia skryptów pakietu.
- Maskowanie raportów nie gwarantuje rozpoznania każdego niestandardowego sekretu. Przed publikacją przejrzyj raport.
- Pozostawiono część historycznych adapterów ekranów i tłumaczeń używanych przez aktualną implementację. Diagnostyka PL/EN w części opisów korzysta z dotychczasowych reguł tłumaczenia; nie jest pełnym nowym katalogiem gettext.
- Wyjście w czasie skanu anuluje kolejne moduły. Bieżący odczyt systemowego/nośnikowego I/O może zakończyć się później; nie odwołuje się wtedy do zamkniętego GUI.

## Źródła techniczne

Kod bazowy: [E2 Doctor](https://github.com/OliOli2013/E2-Doctor-Plugin/tree/cf94553da06666385b60d6c1fb0b3d44c7393871).
Zasady skanowania katalogów wtyczek sprawdzono w [PluginComponent OpenATV](https://github.com/openatv/enigma2/blob/master/lib/python/Components/PluginComponent.py).
Nazwy pakietów standardowej biblioteki Python potwierdzono w [manifeście OpenEmbedded](https://github.com/openembedded/openembedded-core/blob/master/meta/recipes-devtools/python/python3/python3-manifest.json).
