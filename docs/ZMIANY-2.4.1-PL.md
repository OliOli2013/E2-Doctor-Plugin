# E2 Doctor 2.4.1 — poprzedni wygląd, poprawione funkcje

Przywrócono wygląd z dołączonej wersji 2.3: duże logo, ocenę kondycji, cztery kolorowe liczniki i listę modułów z ikonami. Wróciła też paleta ekranów pomocniczych. W aktualizatorze zachowano poprzedni układ, powiększając wariant HD, aby status nie nachodził na przyciski.

Poprawki funkcji z 2.4.0 pozostają. Stary panel otrzymał adapter do skanowania w tle, kolejki wyników i bezpiecznego zamykania. Raport lub moduł naprawy wybrany przed pierwszym skanem czeka na jego zakończenie. Odświeżanie zachowuje pozycję na liście. Skorygowano odstępy tekstu w pozycjach listy.

Wersja pakietu: 2.4.1. Build: 20260910-2. Instalacja możliwa z 2.3 i 2.4.0; po instalacji restart GUI. Wgraj cały ZIP do katalogu głównego repozytorium. IPK i update.json opublikuj razem. Źródła wymagają również nowego pliku classic.py.

Weryfikacja: 22 testy lokalne, składnia Python, integralność IPK, manifest i sumy kontrolne. Ekrany sprawdzono z atrapami API Enigma2; podgląd PNG jest ilustracyjnym renderem, nie zrzutem fizycznego tunera. Nie wykonano testu na odbiorniku.

Audyt 2.4.0 pozostaje dokumentem historycznym: opis jego trzykolumnowego interfejsu nie dotyczy wersji 2.4.1.
