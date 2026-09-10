# E2 Doctor 2.4.1

Centrum diagnostyki i narzędzi Enigma2. Python 3, pakiet OPKG/IPK. Autor: Paweł Pawełek.

Przywrócony wygląd wersji 2.3: duże logo, ocena kondycji tunera, kolorowe liczniki i lista modułów z ikonami, PL/EN. Diagnostyka i pobieranie aktualizacji działają poza wątkiem GUI. Szczegóły zmian, testów i ograniczeń: [audyt funkcji 2.4.0](docs/AUDYT-2.4.0-PL.md) oraz [zmiany 2.4.1](docs/ZMIANY-2.4.1-PL.md).

## Instalacja

Pobierz `releases/enigma2-plugin-extensions-e2doctor_2.4.1_all.ipk`, skopiuj do `/tmp`, a następnie:

```sh
opkg install /tmp/enigma2-plugin-extensions-e2doctor_2.4.1_all.ipk
```

Po poprawnej instalacji wykonaj restart GUI z menu tunera. Ustawienia i historia są w `/etc/enigma2/e2doctor`; paczka ich nie zastępuje. Jeżeli OPKG zgłosi brak zależności, sprawdź feedy właściwe dla swojego obrazu. Nie używaj `--force-depends`.

Istniejący aktualizator 2.3 może pobrać wydanie po publikacji nowego `update.json` oraz IPK pod podanym w nim adresem. Dla tej pierwszej aktualizacji można też użyć instalacji ręcznej.

## Publikacja plików na GitHubie

1. Wgraj zawartość paczki do katalogu głównego repozytorium, zachowując `src/`, `packaging/`, `scripts/`, `tests/`, `docs/` i `releases/`.
2. Nie twórz dodatkowego katalogu nadrzędnego w repozytorium. Wgraj cały katalog źródeł — `plugin.py` korzysta z nowych modułów.
3. Zatwierdź IPK i `update.json` w jednym commicie. Jeżeli publikujesz oddzielnie, najpierw IPK, a manifest na końcu.
4. Nie zmieniaj nazwy IPK bez zmiany `download_url` i nie podmieniaj bajtów IPK bez przeliczenia `sha256`.
5. Starsze pliki w `releases/` mogą pozostać. Nowy manifest wskazuje tylko wersję 2.4.1.

## Pilot

Czerwony: skan. Zielony/OK: otwórz wynik/działanie. Żółty: raport. Niebieski/EXIT: wyjście. Góra/dół: wybór modułu. MENU: ustawienia. 0: aktualizacja.

## Budowanie i testy

Na komputerze z Pythonem 3.12+:

```sh
sh build_ipk.sh
python3 -m unittest discover -s tests -v
```

Budowa aktualizuje manifest i sumy kontrolne. Raport awaryjny na tunerze: `e2doctor-report`.

Przed szeroką publikacją sprawdź IPK na jednym odbiorniku. Testy lokalne używają atrap API Enigma2; nie zastępują testu obrazu, pilota, głowic i usług. Python 2 oraz DreamOS/DEB nie są obsługiwane.

## English

E2 Doctor 2.4.1 restores the original 2.3 dashboard while retaining background scans, update validation, safer cleanup and other 2.4.0 fixes. Intended for Python 3 Enigma2 images using OPKG. Local tests passed; physical receiver validation is still required. Install the IPK, then restart the GUI. Publish the complete source tree and matching IPK/manifest together.
