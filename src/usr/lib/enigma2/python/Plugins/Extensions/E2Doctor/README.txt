E2 Doctor 2.1 dla Enigma2 Python 3

E2 Doctor jest centrum diagnostyki, objaśniania problemów i bezpiecznej naprawy
dekoderów Enigma2. Wersja 2.1 rozwija działający rdzeń 2.0 o bardziej atrakcyjny
panel graficzny oraz kontekstowe Centrum szybkiej naprawy.

Najważniejsze funkcje:
- pełna diagnostyka systemu, flash, RAM, obciążenia, sieci i czasu,
- kontrola list kanałów, głowic, sygnału, nośników, OPKG, OSCam, EPG i piconów,
- analiza crashlogów z próbą wskazania pliku, linii i podejrzanej wtyczki,
- wynik kondycji tunera w skali 0-100,
- historia skanów i porównywanie zmian,
- Centrum szybkiej naprawy dopasowujące działania do wykrytych problemów,
- naprawa brakujących odwołań do bukietów z kopią bezpieczeństwa,
- bezpieczne czyszczenie flash bez usuwania ustawień, list, wtyczek, EPG i piconów,
- bezpieczne odświeżenie cache RAM bez kończenia procesów,
- restart OSCam, synchronizacja czasu i usuwanie nieaktywnej blokady OPKG,
- rozszerzone testy sieci i diagnostyka nośników,
- tymczasowe wyłączenie podejrzanej wtyczki z możliwością cofnięcia,
- E2 Safe Installer do analizy paczek IPK bez ich instalowania,
- raport techniczny z GUI i raport awaryjny poleceniem e2doctor-report,
- monitor krytycznych problemów działający w tle.

Sterowanie na ekranie rozwiązania:
- czerwony: powrót,
- zielony: główne bezpieczne działanie,
- żółty: dane techniczne,
- niebieski: lista wszystkich działań dla danego problemu,
- INFO lub MENU: zapis instrukcji do pliku.

Bezpieczeństwo:
E2 Doctor nie przywraca ustawień fabrycznych, nie formatuje nośników, nie usuwa
list kanałów i nie zmienia automatycznie konfiguracji głowic ani sieci. Każda
operacja ingerująca w system wymaga potwierdzenia. Naprawy obsługujące rollback
tworzą kopię lub punkt cofania.

Autor: by Paweł Pawełek
Kontakt: aio-iptv@wp.pl

Aktualizacja z GitHub:
- wybierz moduł „Aktualizacja z GitHub” w panelu głównym lub naciśnij klawisz 0,
- E2 Doctor pobierze plik update.json z oficjalnego repozytorium,
- dostępna paczka zostanie pobrana przez HTTPS i sprawdzona sumą SHA-256,
- instalacja uruchomi się dopiero po potwierdzeniu użytkownika,
- po zakończeniu można od razu wykonać restart GUI.

Repozytorium aktualizacji:
https://github.com/OliOli2013/E2-Doctor-Plugin
